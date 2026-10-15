"""Page-faithful PDF text extraction and bounded chunking."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .config import Settings, SourceManifest, sync_manifest


PARSER_VERSION = "page-chunker-v2"


@dataclass(slots=True)
class ParseStats:
    parsed_books: int = 0
    rechunked_books: int = 0
    skipped_books: int = 0
    pages: int = 0
    chunks: int = 0
    ocr_pages: int = 0


def resolve_tessdata_path(settings: Settings) -> Path | None:
    """Find Tesseract language data even when Conda was not shell-activated."""
    candidates: list[Path] = []
    if settings.tessdata_prefix:
        candidates.append(settings.tessdata_prefix.expanduser())
    if value := os.environ.get("TESSDATA_PREFIX"):
        candidates.append(Path(value).expanduser())
    candidates.extend(
        [
            Path(sys.prefix) / "share" / "tessdata",
            Path("/usr/share/tesseract-ocr/5/tessdata"),
            Path("/usr/share/tesseract-ocr/4.00/tessdata"),
            Path("/usr/share/tessdata"),
        ]
    )
    required_languages = [item for item in settings.ocr_language.split("+") if item]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and all(
            (resolved / f"{language}.traineddata").is_file()
            for language in required_languages
        ):
            return resolved
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _split_page(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    if not text:
        return []
    chunks: list[tuple[int, int, str]] = []
    start = 0
    length = len(text)
    while start < length:
        hard_end = min(start + size, length)
        end = hard_end
        if hard_end < length:
            search_from = start + int(size * 0.65)
            candidates = [
                text.rfind("\n\n", search_from, hard_end),
                text.rfind(". ", search_from, hard_end),
                text.rfind("\n", search_from, hard_end),
            ]
            best = max(candidates)
            if best > start:
                end = best + (2 if text[best : best + 2] in {"\n\n", ". "} else 1)
        chunk_text = text[start:end]
        if chunk_text.strip():
            chunks.append((start, end, chunk_text))
        if end >= length:
            break
        next_start = max(0, end - overlap)
        if next_start <= start:
            next_start = end
        start = next_start
    return chunks


def _insert_chunks(
    conn: sqlite3.Connection,
    *,
    page_id: int,
    source_id: str,
    page_number: int,
    text: str,
    settings: Settings,
) -> int:
    page_chunks = _split_page(
        text,
        settings.chunk_size_chars,
        settings.chunk_overlap_chars,
    )
    for start, end, chunk_text in page_chunks:
        chunk_id = _sha256_text(
            f"{source_id}\0{page_number}\0{start}\0{end}\0{chunk_text}"
        )[:32]
        conn.execute(
            """
            INSERT INTO chunks(
                id, page_id, source_id, page_number, start_char, end_char,
                text, token_estimate, parser_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                page_id,
                source_id,
                page_number,
                start,
                end,
                chunk_text,
                max(1, len(chunk_text) // 4),
                PARSER_VERSION,
            ),
        )
    return len(page_chunks)


def _extract_text(page: pymupdf.Page, settings: Settings) -> tuple[str, bool]:
    text = page.get_text("text", sort=True)
    if len(text.strip()) >= settings.min_page_text_chars or not settings.enable_ocr:
        return text, False
    try:
        tessdata = resolve_tessdata_path(settings)
        text_page = page.get_textpage_ocr(
            language=settings.ocr_language,
            full=True,
            tessdata=str(tessdata) if tessdata else None,
        )
        return page.get_text("text", textpage=text_page, sort=True), True
    except Exception as exc:  # pragma: no cover - depends on system Tesseract
        raise RuntimeError(
            f"OCR failed on PDF page {page.number + 1}. Install Tesseract language data "
            f"or disable ENABLE_OCR. Original error: {exc}"
        ) from exc


def parse_books(
    conn: sqlite3.Connection,
    settings: Settings,
    manifest: SourceManifest,
    *,
    force: bool = False,
) -> ParseStats:
    sync_manifest(conn, manifest)
    configured = {source.filename.casefold(): source for source in manifest.sources}
    actual_paths = sorted(settings.books_dir.glob("*.pdf"), key=lambda p: p.name.casefold())
    actual = {path.name.casefold(): path for path in actual_paths}
    missing = [source.filename for source in manifest.sources if source.filename.casefold() not in actual]
    unconfigured = [path.name for path in actual_paths if path.name.casefold() not in configured]
    if missing or unconfigured:
        details = []
        if missing:
            details.append(f"missing PDFs declared in sources.md: {', '.join(missing)}")
        if unconfigured:
            details.append(f"PDFs without source metadata: {', '.join(unconfigured)}")
        raise ValueError("; ".join(details))

    hashes = {path.name.casefold(): _sha256_file(path) for path in actual_paths}
    chunk_fingerprint = (
        f"{PARSER_VERSION}:{settings.chunk_size_chars}:{settings.chunk_overlap_chars}"
    )
    old_chunk_row = conn.execute(
        "SELECT value FROM pipeline_meta WHERE key='chunk_fingerprint'"
    ).fetchone()
    chunking_changed = old_chunk_row is None or old_chunk_row["value"] != chunk_fingerprint
    changed_ids: list[str] = []
    for source in manifest.sources:
        row = conn.execute(
            "SELECT file_sha256 FROM sources WHERE id = ?", (source.id,)
        ).fetchone()
        if force or not row or row["file_sha256"] != hashes[source.filename.casefold()]:
            changed_ids.append(source.id)

    unchanged_ids = [
        source.id for source in manifest.sources if source.id not in changed_ids
    ]
    stats = ParseStats(skipped_books=len(unchanged_ids))
    if not changed_ids and not chunking_changed:
        return stats

    # Any changed evidence invalidates canonicalization and every downstream judgment.
    conn.execute("DELETE FROM canonical_facts")

    if chunking_changed:
        for source_id in unchanged_ids:
            pages = conn.execute(
                """
                SELECT id, page_number, text FROM pages
                WHERE source_id=? ORDER BY page_number
                """,
                (source_id,),
            ).fetchall()
            if not pages:
                if source_id not in changed_ids:
                    changed_ids.append(source_id)
                continue
            conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
            for page in pages:
                stats.chunks += _insert_chunks(
                    conn,
                    page_id=page["id"],
                    source_id=source_id,
                    page_number=page["page_number"],
                    text=page["text"],
                    settings=settings,
                )
            stats.rechunked_books += 1
            stats.skipped_books -= 1
        conn.commit()

    for source in manifest.sources:
        if source.id not in changed_ids:
            continue
        pdf_path = actual[source.filename.casefold()]
        conn.execute("DELETE FROM pages WHERE source_id = ?", (source.id,))
        with pymupdf.open(pdf_path) as document:
            if document.needs_pass:
                raise ValueError(f"Encrypted PDF requires a password: {pdf_path.name}")
            book_chunk_count = 0
            for page_index, page in enumerate(document):
                text, used_ocr = _extract_text(page, settings)
                page_number = page_index + 1
                try:
                    page_label = page.get_label() or str(page_number)
                except Exception:
                    page_label = str(page_number)
                cursor = conn.execute(
                    """
                    INSERT INTO pages(source_id, page_number, page_label, text, text_sha256, used_ocr)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source.id,
                        page_number,
                        page_label,
                        text,
                        _sha256_text(text),
                        int(used_ocr),
                    ),
                )
                page_id = int(cursor.lastrowid)
                page_chunk_count = _insert_chunks(
                    conn,
                    page_id=page_id,
                    source_id=source.id,
                    page_number=page_number,
                    text=text,
                    settings=settings,
                )
                stats.pages += 1
                stats.chunks += page_chunk_count
                book_chunk_count += page_chunk_count
                stats.ocr_pages += int(used_ocr)
            if len(document) and book_chunk_count == 0:
                raise RuntimeError(
                    f"No extractable text found in {pdf_path.name}. If it is scanned, "
                    "install Tesseract and set ENABLE_OCR=true."
                )
            conn.execute(
                """
                UPDATE sources
                SET file_sha256 = ?, page_count = ?, pdf_metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    hashes[source.filename.casefold()],
                    len(document),
                    json.dumps(document.metadata or {}, ensure_ascii=False),
                    source.id,
                ),
            )
        conn.commit()
        stats.parsed_books += 1
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_meta(key, value) VALUES('chunk_fingerprint', ?)",
        (chunk_fingerprint,),
    )
    conn.commit()
    return stats
