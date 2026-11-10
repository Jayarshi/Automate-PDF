"""Explicit settings; importing this module never loads models or reads .env files."""

from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    root: Path = ROOT
    dpi: int = 300
    scantailor: str = "scantailor-cli"
    layout: str = "0"
    direction: str = "lr"
    scan_timeout: int = 600
    page_timeout: int = 600
    max_pixels: int = 80_000_000
    max_pages: int = 5000
    keep_temp: bool = False
    use_llm: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct-q4_K_M"
    ollama_timeout: int = 60
    max_corrections: int = 64
    context_chars: int = 600
    language: str = "en"
    confusion_file: Path | None = None
    confidence_threshold: float = 0.75
    recognition_batch_size: int = 4

    def __post_init__(self):
        for name in ("dpi", "scan_timeout", "page_timeout", "max_pixels", "max_pages",
                     "ollama_timeout", "context_chars", "recognition_batch_size"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_corrections < 0:
            raise ValueError("max_corrections must be nonnegative")
        if not 0 <= self.confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if self.layout not in {"0", "1", "1.5", "2"} or self.direction not in {"lr", "rl"}:
            raise ValueError("Invalid ScanTailor layout/direction")
        if self.root.resolve() != ROOT:
            raise ValueError("All pipeline data must remain inside PDFtoMD")
        if self.confusion_file and not self.confusion_file.resolve().is_relative_to(ROOT):
            raise ValueError("The confusion file must be inside PDFtoMD")

    @property
    def input_dir(self):
        return self.root / "input"

    @property
    def output_dir(self):
        return self.root / "output"

    def signature_settings(self):
        values = asdict(self)
        for key in ("root", "keep_temp"):
            values.pop(key)
        return {k: str(v) if isinstance(v, Path) else v for k, v in values.items()}
