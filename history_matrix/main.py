"""Command-line entrypoint for the historical consensus pipeline."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from src.aligner import align_sources
from src.config import Settings, connect_db, initialize_database, load_sources, sync_manifest
from src.deduplicator import deduplicate_facts
from src.exporter import export_ledger
from src.extractor import extract_facts
from src.parser import parse_books, resolve_tessdata_path
from src.scorer import score_facts


app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Build a source-weighted, quote-grounded historical fact consensus ledger.",
)
console = Console()


def _settings(project_dir: Path) -> Settings:
    settings = Settings.load(project_dir)
    initialize_database(settings)
    return settings


def _print_stats(stage: str, value: object) -> None:
    console.print(f"[bold green]{stage} complete[/bold green]")
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    console.print_json(json.dumps(payload, default=str))


@app.command("init")
def init_project(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
) -> None:
    """Create/upgrade the SQLite schema and verify sources.md syntax."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    with connect_db(settings) as conn:
        sync_manifest(conn, manifest)
        conn.commit()
    console.print(
        f"[green]Initialized[/green] {settings.db_path} with {len(manifest.sources)} sources."
    )


@app.command()
def parse(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Reparse every configured PDF."),
) -> None:
    """Extract page text and page-bounded chunks from configured PDFs."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    with connect_db(settings) as conn:
        _print_stats("parse", parse_books(conn, settings, manifest, force=force))


@app.command()
def extract(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Discard and recreate all raw facts."),
) -> None:
    """Extract atomic, verbatim-quote-grounded facts from pending chunks."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    with connect_db(settings) as conn:
        sync_manifest(conn, manifest)
        conn.commit()
        _print_stats("extract", extract_facts(conn, settings, force=force))


@app.command()
def deduplicate(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Rebuild every canonical fact family."),
) -> None:
    """Cluster assertions and synthesize canonical disputed fact families."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    with connect_db(settings) as conn:
        sync_manifest(conn, manifest)
        conn.commit()
        _print_stats("deduplicate", deduplicate_facts(conn, settings, force=force))


@app.command()
def align(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Re-adjudicate every book/fact pair."),
) -> None:
    """Classify each book as supporting, contradicting, mixed, or silent."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    with connect_db(settings) as conn:
        sync_manifest(conn, manifest)
        conn.commit()
        _print_stats("align", align_sources(conn, settings, manifest, force=force))


@app.command()
def score(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Recompute all deterministic scores."),
) -> None:
    """Compute the independence-aware evidence index and confidence tier."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    with connect_db(settings) as conn:
        sync_manifest(conn, manifest)
        conn.commit()
        _print_stats("score", score_facts(conn, manifest, force=force))


@app.command()
def export(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
) -> None:
    """Write complete Excel, CSV, and Markdown factual reports."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    with connect_db(settings) as conn:
        sync_manifest(conn, manifest)
        conn.commit()
        _print_stats(
            "export",
            export_ledger(
                conn, settings.output_dir, project_title=manifest.project.title
            ),
        )


@app.command("run")
def run_all(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    from_stage: Literal["parse", "extract", "deduplicate", "align", "score", "export"] =
        typer.Option("parse", help="Resume from this stage; earlier products are retained."),
    force: bool = typer.Option(False, help="Rebuild the selected stage and its dependents."),
) -> None:
    """Run all remaining stages in order, with resumable checkpoints."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    stages = ["parse", "extract", "deduplicate", "align", "score", "export"]
    start = stages.index(from_stage)
    if start <= stages.index("align"):
        settings.require_api_key()
    with connect_db(settings) as conn:
        sync_manifest(conn, manifest)
        conn.commit()
        for index, stage_name in enumerate(stages[start:], start=start):
            stage_force = force and index == start
            if stage_name == "parse":
                result = parse_books(conn, settings, manifest, force=stage_force)
            elif stage_name == "extract":
                result = extract_facts(conn, settings, force=stage_force)
            elif stage_name == "deduplicate":
                result = deduplicate_facts(conn, settings, force=stage_force)
            elif stage_name == "align":
                result = align_sources(conn, settings, manifest, force=stage_force)
            elif stage_name == "score":
                result = score_facts(conn, manifest, force=stage_force)
            else:
                result = export_ledger(
                    conn, settings.output_dir, project_title=manifest.project.title
                )
            _print_stats(stage_name, result)


@app.command()
def status(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
) -> None:
    """Show durable pipeline counts and incomplete LLM work."""
    settings = _settings(project_dir)
    queries = {
        "Sources": "SELECT COUNT(*) FROM sources",
        "Pages": "SELECT COUNT(*) FROM pages",
        "OCR pages": "SELECT COUNT(*) FROM pages WHERE used_ocr=1",
        "Chunks": "SELECT COUNT(*) FROM chunks",
        "Pending extraction": "SELECT COUNT(*) FROM chunks WHERE extracted_at IS NULL",
        "Extraction errors": "SELECT COUNT(*) FROM chunks WHERE extraction_error IS NOT NULL",
        "Raw facts": "SELECT COUNT(*) FROM raw_facts",
        "Canonical facts": "SELECT COUNT(*) FROM canonical_facts",
        "Stance decisions": "SELECT COUNT(*) FROM stances",
        "Pending alignment": """
            SELECT MAX(0,
                (SELECT COUNT(*) FROM canonical_facts) *
                (SELECT COUNT(*) FROM sources) -
                (SELECT COUNT(*) FROM stances)
            )
        """,
        "Scores": "SELECT COUNT(*) FROM scores",
        "Pending scoring": """
            SELECT MAX(0,
                (SELECT COUNT(*) FROM canonical_facts) -
                (SELECT COUNT(*) FROM scores)
            )
        """,
    }
    table = Table(title="History Matrix status")
    table.add_column("Artifact")
    table.add_column("Count", justify="right")
    with connect_db(settings) as conn:
        for label, query in queries.items():
            table.add_row(label, str(conn.execute(query).fetchone()[0]))
    console.print(table)


@app.command()
def doctor(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
) -> None:
    """Check configuration, PDFs, OCR, API access, and SQLite integrity."""
    settings = _settings(project_dir)
    manifest = load_sources(settings.sources_path)
    configured = {source.filename.casefold(): source.filename for source in manifest.sources}
    present = {path.name.casefold(): path.name for path in settings.books_dir.glob("*.pdf")}
    missing = sorted(configured[key] for key in configured.keys() - present.keys())
    unexpected = sorted(present[key] for key in present.keys() - configured.keys())
    tesseract = shutil.which("tesseract")
    if not tesseract:
        environment_tesseract = Path(sys.executable).with_name("tesseract")
        if environment_tesseract.is_file():
            tesseract = str(environment_tesseract)
    tessdata = resolve_tessdata_path(settings)

    checks: list[tuple[str, str, bool]] = [
        ("sources.md policy", f"valid ({len(manifest.sources)} sources)", True),
        (
            "Configured PDFs",
            f"{len(configured) - len(missing)}/{len(configured)} found"
            + (f"; missing: {', '.join(missing)}" if missing else ""),
            not missing,
        ),
        (
            "Unexpected PDFs",
            ", ".join(unexpected) if unexpected else "none",
            not unexpected,
        ),
        (
            "Tesseract OCR",
            (
                f"{tesseract}; tessdata={tessdata}"
                if tesseract and tessdata
                else "not found (OCR disabled)"
                if not settings.enable_ocr
                else "executable or requested language data not found"
            ),
            (bool(tesseract) and bool(tessdata)) or not settings.enable_ocr,
        ),
        (
            "OpenAI API key",
            (
                "configured"
                if settings.openai_api_key
                else f"blank in {settings.project_root / '.env'}"
            ),
            bool(settings.openai_api_key),
        ),
    ]
    with connect_db(settings) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    checks.append(("SQLite integrity", integrity, integrity == "ok"))

    table = Table(title="History Matrix doctor")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Status", justify="center")
    for label, detail, passed in checks:
        table.add_row(label, detail, "[green]PASS[/green]" if passed else "[yellow]ACTION[/yellow]")
    console.print(table)
    if any(not passed for _, _, passed in checks):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    # A bare `python main.py` is the production one-command path.
    if len(sys.argv) == 1:
        sys.argv.append("run")
    try:
        app()
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise SystemExit(1) from None
