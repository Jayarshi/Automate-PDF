"""Bounded PDF rasterization and a capability-checked ScanTailor CLI wrapper."""

import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from .config import Config

log = logging.getLogger(__name__)
REQUIRED_OPTIONS = ("layout", "layout-direction", "deskew", "content-detection",
                    "margins", "dpi", "output-dpi", "color-mode", "white-margins",
                    "normalize-illumination", "despeckle", "dewarping",
                    "start-filter", "end-filter")


def _environment():
    # AppImages can run on hosts without FUSE (including containers).
    return {**os.environ, "QT_QPA_PLATFORM": "offscreen", "APPIMAGE_EXTRACT_AND_RUN": "1"}


def _help(binary: str) -> str:
    result = subprocess.run([binary, "--help"], capture_output=True, text=True,
                            errors="replace", timeout=60, env=_environment())
    return result.stdout + result.stderr


def cli_kind(binary: str) -> str:
    help_text = _help(binary)
    if "Headless ScanTailor" in help_text and all(word in help_text for word in ("create", "options", "run", "export")):
        return "project"
    missing = [flag for flag in REQUIRED_OPTIONS
               if not re.search(r"--" + re.escape(flag) + r"(?=[=\s<]|$)", help_text)]
    if missing:
        raise RuntimeError(f"Incompatible ScanTailor CLI {binary}: missing {missing}")
    return "legacy"


def check_scantailor(binary: str) -> Path:
    executable = shutil.which(binary)
    if not executable:
        raise RuntimeError(
            f"ScanTailor CLI not found: {binary!r}. Advanced upstream lacks a CLI; "
            "install a compatible CLI build and pass --scantailor /path/to/binary."
        )
    cli_kind(executable)
    path = Path(executable)
    # Preserve an explicit symlink basename: the self-contained pyScanTailor
    # AppImage selects its headless entry point when invoked as
    # ``scantailor-cli``.  Canonicalize ordinary binaries.
    return path.absolute() if path.is_symlink() else path.resolve()


def command(config: Config, source: Path, target: Path) -> list[str]:
    return [config.scantailor, f"--layout={config.layout}",
            f"--layout-direction={config.direction}", "--deskew=auto",
            "--content-detection=normal", "--margins=0",
            f"--dpi={config.dpi}", f"--output-dpi={config.dpi}",
            "--color-mode=black_and_white", "--white-margins",
            "--normalize-illumination", "--despeckle=cautious", "--dewarping=auto",
            "--start-filter=1", "--end-filter=6", str(source), str(target)]


def natural_key(path: Path):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", path.name)]


def rectify(pdf: Path, workspace: Path, config: Config) -> list[Path]:
    import pymupdf
    from PIL import Image

    executable = str(check_scantailor(config.scantailor))
    kind = cli_kind(executable)
    rectified = workspace / "rectified"
    rectified.mkdir(parents=True)
    result_pages = []
    raster_dir = workspace / "raster"
    raster_dir.mkdir()
    with pymupdf.open(pdf) as document:
        if document.needs_pass:
            raise RuntimeError("Encrypted PDF requires a decrypted input copy")
        if not 0 < len(document) <= config.max_pages:
            raise RuntimeError(f"PDF page count is outside 1..{config.max_pages}")
        for number, page in enumerate(document, 1):
            width = math.ceil(page.rect.width * config.dpi / 72)
            height = math.ceil(page.rect.height * config.dpi / 72)
            if width * height > config.max_pixels:
                raise RuntimeError(f"Page {number} exceeds --max-pixels at {config.dpi} DPI")
            log.info("Stage 1: %s page %d/%d", pdf.name, number, len(document))
            raster = raster_dir / f"page-{number:06d}.png"
            pixmap = page.get_pixmap(dpi=config.dpi, colorspace=pymupdf.csRGB, alpha=False)
            pixmap.save(raster)
            del pixmap
    if kind == "project":
        project = workspace / "scantailor-project.json"
        target = workspace / "scantailor-output"
        exported = workspace / "scantailor-export"
        target.mkdir()
        exported.mkdir()
        logfile = workspace / "scantailor.log"

        def invoke(arguments):
            with logfile.open("ab") as stream:
                try:
                    proc = subprocess.run([executable, *arguments], stdout=stream,
                                          stderr=subprocess.STDOUT, timeout=config.scan_timeout,
                                          env=_environment())
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(f"ScanTailor timed out; see {logfile}") from exc
            if proc.returncode:
                raise RuntimeError(f"ScanTailor exited {proc.returncode}; see {logfile}")

        invoke(["create", "--dpi", str(config.dpi), "--layout-direction",
                {"lr": "LTR", "rl": "RTL"}[config.direction],
                "--output-dir", str(target), "--force",
                str(raster_dir), str(project)])
        if config.layout != "0":
            layout = {"1": "single-page", "1.5": "cut", "2": "two-page"}[config.layout]
            invoke(["options", "set", str(project), "page_split_layout_type", layout])
        invoke(["options", "set", str(project), "output_dpi",
                f'{{"horizontal":{config.dpi},"vertical":{config.dpi}}}'])
        invoke(["options", "set", str(project), "output_color_mode", "bw"])
        invoke(["options", "set", str(project), "output_despeckle_level", "cautious"])
        invoke(["run", "--workers", "1", str(project)])
        invoke(["export", "tiff", str(project), str(exported)])
        outputs = sorted((p for p in exported.rglob("*")
                          if p.suffix.lower() in {".tif", ".tiff", ".png"}), key=natural_key)
        if not outputs:
            raise RuntimeError(f"ScanTailor produced no rectified pages; see {logfile}")
        if len(outputs) > config.max_pages * 2:
            raise RuntimeError("ScanTailor produced more than two output pages per input page")
        for index, output in enumerate(outputs, 1):
            destination = rectified / f"page-{index:06d}.png"
            with Image.open(output) as image:
                if image.width * image.height > config.max_pixels:
                    raise RuntimeError(f"Rectified page exceeds --max-pixels: {output}")
                image.convert("RGB").save(destination, dpi=(config.dpi, config.dpi))
            result_pages.append(destination)
        if not config.keep_temp:
            shutil.rmtree(raster_dir)
        return result_pages

    # Historical C++ CLI: process one input image at a time.
    for number, raster in enumerate(sorted(raster_dir.iterdir(), key=natural_key), 1):
            scratch = workspace / f"scan-{number:06d}"
            source, target = scratch / "input", scratch / "output"
            source.mkdir(parents=True)
            target.mkdir()
            shutil.copyfile(raster, source / raster.name)
            logfile = workspace / f"scantailor-{number:06d}.log"
            with logfile.open("wb") as stream:
                try:
                    proc = subprocess.run(command(config, source, target), stdout=stream,
                                          stderr=subprocess.STDOUT, timeout=config.scan_timeout,
                                          env=_environment())
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(f"ScanTailor timed out on page {number}; {logfile}") from exc
            if proc.returncode:
                raise RuntimeError(f"ScanTailor exited {proc.returncode}; see {logfile}")
            outputs = sorted((p for p in target.iterdir()
                              if p.suffix.lower() in {".tif", ".tiff", ".png"}), key=natural_key)
            if not 1 <= len(outputs) <= 2:
                raise RuntimeError(f"Expected 1 or 2 rectified pages, found {len(outputs)}; {logfile}")
            # ScanTailor names halves physically left/right; order them for RTL books.
            if config.direction == "rl":
                outputs.reverse()
            for half, output in enumerate(outputs, 1):
                destination = rectified / f"page-{number:06d}-{half}.png"
                with Image.open(output) as image:
                    if image.width * image.height > config.max_pixels:
                        raise RuntimeError(f"Rectified page exceeds --max-pixels: {output}")
                    if getattr(image, "n_frames", 1) != 1:
                        raise RuntimeError("Unexpected multi-frame ScanTailor output")
                    image.convert("RGB").save(destination, dpi=(config.dpi, config.dpi))
                result_pages.append(destination)
            if not config.keep_temp:
                shutil.rmtree(scratch)
    return result_pages
