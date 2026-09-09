"""Command-line entrypoint for the historical consensus pipeline."""

from __future__ import annotations

import json
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
from src.parser import parse_books
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
    with connect_db(settings) as conn:
        _print_stats("extract", extract_facts(conn, settings, force=force))


@app.command()
def deduplicate(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Rebuild every canonical fact family."),
) -> None:
    """Cluster assertions and synthesize canonical disputed fact families."""
    settings = _settings(project_dir)
    with connect_db(settings) as conn:
        _print_stats("deduplicate", deduplicate_facts(conn, settings, force=force))


@app.command()
def align(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Re-adjudicate every book/fact pair."),
) -> None:
    """Classify each book as supporting, contradicting, mixed, or silent."""
    settings = _settings(project_dir)
    with connect_db(settings) as conn:
        _print_stats("align", align_sources(conn, settings, force=force))


@app.command()
def score(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
    force: bool = typer.Option(False, help="Recompute all deterministic scores."),
) -> None:
    """Compute transparent source-weighted believability scores."""
    settings = _settings(project_dir)
    with connect_db(settings) as conn:
        _print_stats("score", score_facts(conn, force=force))


@app.command()
def export(
    project_dir: Path = typer.Option(Path(__file__).resolve().parent, help="Project root."),
) -> None:
    """Write the styled Excel consensus matrix and a flat summary CSV."""
    settings = _settings(project_dir)
    with connect_db(settings) as conn:
        _print_stats("export", export_ledger(conn, settings.output_dir))


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
                result = align_sources(conn, settings, force=stage_force)
            elif stage_name == "score":
                result = score_facts(conn, force=stage_force)
            else:
                result = export_ledger(conn, settings.output_dir)
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
        "Chunks": "SELECT COUNT(*) FROM chunks",
        "Pending extraction": "SELECT COUNT(*) FROM chunks WHERE extracted_at IS NULL",
        "Extraction errors": "SELECT COUNT(*) FROM chunks WHERE extraction_error IS NOT NULL",
        "Raw facts": "SELECT COUNT(*) FROM raw_facts",
        "Canonical facts": "SELECT COUNT(*) FROM canonical_facts",
        "Stance decisions": "SELECT COUNT(*) FROM stances",
        "Scores": "SELECT COUNT(*) FROM scores",
    }
    table = Table(title="History Matrix status")
    table.add_column("Artifact")
    table.add_column("Count", justify="right")
    with connect_db(settings) as conn:
        for label, query in queries.items():
            table.add_row(label, str(conn.execute(query).fetchone()[0]))
    console.print(table)


if __name__ == "__main__":
    app()
