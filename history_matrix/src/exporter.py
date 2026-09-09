"""Styled Excel and flat CSV export from the normalized SQLite ledger."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo


EXCEL_CELL_LIMIT = 32767
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)


@dataclass(slots=True)
class ExportStats:
    facts: int
    evidence_rows: int
    workbook_path: Path
    csv_path: Path


def _cell_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    # Treat all externally derived text as text, never as an Excel formula.
    if value.lstrip().startswith(("=", "+", "-", "@")):
        value = "'" + value
    if len(value) <= EXCEL_CELL_LIMIT:
        return value
    return value[: EXCEL_CELL_LIMIT - 18] + "… [truncated]"


def _configure_sheet(worksheet, widths: dict[str, float], table_name: str | None = None) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for cell in worksheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for column, width in widths.items():
        worksheet.column_dimensions[column].width = width
    if table_name and worksheet.max_row >= 2:
        table = Table(displayName=table_name, ref=worksheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        worksheet.add_table(table)


def _evidence_text(conn: sqlite3.Connection, ids: list[str]) -> str:
    if not ids:
        return ""
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT rf.id, rf.evidence_quote, rf.page_number, p.page_label
        FROM raw_facts rf
        JOIN chunks c ON c.id = rf.chunk_id
        JOIN pages p ON p.id = c.page_id
        WHERE rf.id IN ({placeholders})
        """,
        tuple(ids),
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    citations = []
    for fact_id in ids:
        row = by_id.get(fact_id)
        if row:
            label = row["page_label"] or str(row["page_number"])
            citations.append(
                f"PDF p. {row['page_number']} (printed label {label}): “{row['evidence_quote']}”"
            )
    return "\n\n".join(citations)


def export_ledger(conn: sqlite3.Connection, output_dir: Path) -> ExportStats:
    output_dir.mkdir(parents=True, exist_ok=True)
    workbook_path = output_dir / "fact_consensus_matrix.xlsx"
    csv_path = output_dir / "fact_consensus_matrix.csv"
    facts = conn.execute(
        """
        SELECT cf.*, sc.believability_score, sc.support_mass,
               sc.contradiction_mass, sc.total_source_weight,
               sc.evidence_coverage, sc.conflict_index, sc.grade
        FROM canonical_facts cf
        JOIN scores sc ON sc.canonical_id = cf.id
        ORDER BY sc.believability_score DESC, cf.canonical_claim
        """
    ).fetchall()
    if not facts:
        raise RuntimeError("No scored facts found. Run score before export.")

    source_rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    source_by_id = {row["id"]: row for row in source_rows}
    matrix_headers = [
        "Fact ID",
        "Canonical atomic fact",
        "Subject",
        "Time",
        "Location",
        "Believability %",
        "Assessment",
        "Evidence coverage %",
        "Conflict index %",
        "Supporting books",
        "Contradicting books",
        "Mixed books",
        "Silent books",
        "Support mass",
        "Contradiction mass",
        "Total source weight",
    ]
    matrix_data: list[list[object]] = []
    evidence_data: list[list[object]] = []
    for fact in facts:
        stances = conn.execute(
            "SELECT * FROM stances WHERE canonical_id=? ORDER BY source_id", (fact["id"],)
        ).fetchall()
        books: dict[str, list[str]] = {
            "supports": [], "contradicts": [], "mixed": [], "silent": []
        }
        for stance in stances:
            source = source_by_id[stance["source_id"]]
            books[stance["stance"]].append(source["title"])
            support_ids = json.loads(stance["support_evidence_ids_json"])
            contradiction_ids = json.loads(stance["contradiction_evidence_ids_json"])
            evidence_data.append(
                [
                    fact["id"],
                    fact["canonical_claim"],
                    source["id"],
                    source["title"],
                    source["role"],
                    source["credibility_weight"],
                    source["independence_factor"],
                    source["credibility_weight"] * source["independence_factor"],
                    stance["stance"],
                    stance["support_strength"],
                    stance["contradiction_strength"],
                    stance["confidence"],
                    _evidence_text(conn, support_ids),
                    _evidence_text(conn, contradiction_ids),
                    stance["rationale"],
                ]
            )
        matrix_data.append(
            [
                fact["id"],
                fact["canonical_claim"],
                fact["subject"],
                fact["time_expression"] or "",
                fact["location"] or "",
                fact["believability_score"] / 100.0,
                fact["grade"],
                fact["evidence_coverage"],
                fact["conflict_index"],
                "\n".join(books["supports"]),
                "\n".join(books["contradicts"]),
                "\n".join(books["mixed"]),
                "\n".join(books["silent"]),
                fact["support_mass"],
                fact["contradiction_mass"],
                fact["total_source_weight"],
            ]
        )

    workbook = Workbook()
    matrix_sheet = workbook.active
    matrix_sheet.title = "Consensus Matrix"
    matrix_sheet.append(matrix_headers)
    for row in matrix_data:
        matrix_sheet.append([_cell_text(value) for value in row])
    for row_number in range(2, matrix_sheet.max_row + 1):
        for column in (6, 8, 9):
            matrix_sheet.cell(row_number, column).number_format = "0.0%"
        for column in (14, 15, 16):
            matrix_sheet.cell(row_number, column).number_format = "0.000"
    matrix_sheet.conditional_formatting.add(
        f"F2:F{matrix_sheet.max_row}",
        ColorScaleRule(
            start_type="num", start_value=0, start_color="F8696B",
            mid_type="num", mid_value=0.5, mid_color="FFEB84",
            end_type="num", end_value=1, end_color="63BE7B",
        ),
    )
    _configure_sheet(
        matrix_sheet,
        {
            "A": 34, "B": 70, "C": 28, "D": 18, "E": 22, "F": 16,
            "G": 20, "H": 18, "I": 16, "J": 32, "K": 32, "L": 30,
            "M": 30, "N": 14, "O": 18, "P": 18,
        },
        "ConsensusMatrixTable",
    )

    evidence_headers = [
        "Fact ID", "Canonical fact", "Source ID", "Book", "Role",
        "Credibility", "Independence", "Effective weight", "Stance",
        "Support strength", "Contradiction strength", "Decision confidence",
        "Supporting quotes and pages", "Contradicting quotes and pages", "Rationale",
    ]
    evidence_sheet = workbook.create_sheet("Book Evidence")
    evidence_sheet.append(evidence_headers)
    for row in evidence_data:
        evidence_sheet.append([_cell_text(value) for value in row])
    for row_number in range(2, evidence_sheet.max_row + 1):
        for column in range(6, 13):
            evidence_sheet.cell(row_number, column).number_format = "0.000"
    _configure_sheet(
        evidence_sheet,
        {
            "A": 34, "B": 60, "C": 18, "D": 34, "E": 12, "F": 13,
            "G": 13, "H": 15, "I": 14, "J": 16, "K": 20, "L": 18,
            "M": 75, "N": 75, "O": 55,
        },
        "BookEvidenceTable",
    )

    sources_sheet = workbook.create_sheet("Sources")
    sources_sheet.append(
        [
            "Source ID", "Filename", "Title", "Author", "Role", "Credibility",
            "Independence", "Effective weight", "Description", "Bias notes",
            "SHA-256", "PDF pages",
        ]
    )
    for source in source_rows:
        sources_sheet.append(
            [
                source["id"], source["filename"], source["title"], source["author"] or "",
                source["role"], source["credibility_weight"], source["independence_factor"],
                source["credibility_weight"] * source["independence_factor"],
                source["description"], source["bias_notes"], source["file_sha256"] or "",
                source["page_count"] or 0,
            ]
        )
    _configure_sheet(
        sources_sheet,
        {"A": 18, "B": 28, "C": 42, "D": 25, "E": 12, "F": 13,
         "G": 13, "H": 15, "I": 55, "J": 55, "K": 66, "L": 12},
        "SourcesTable",
    )

    method_sheet = workbook.create_sheet("Methodology")
    methodology = [
        ("Generated (UTC)", datetime.now(timezone.utc).isoformat()),
        ("Scoring formula", "50 + 50 × (support mass − contradiction mass) ÷ total effective source weight"),
        ("Effective source weight", "credibility_weight × independence_factor"),
        ("Support mass", "Σ effective weight × alignment confidence × support strength"),
        ("Contradiction mass", "Σ effective weight × alignment confidence × contradiction strength"),
        ("Silence", "Neutral: contributes neither support nor contradiction, leaving its weight at 50%."),
        ("Coverage", "min(total weight, support mass + contradiction mass) ÷ total weight"),
        ("Conflict index", "2 × min(support mass, contradiction mass) ÷ (support mass + contradiction mass)"),
        ("Important caveat", "The score is a reproducible weighted consensus, not proof of historical truth."),
    ]
    method_sheet.append(["Item", "Definition"])
    for row in methodology:
        method_sheet.append(row)
    _configure_sheet(method_sheet, {"A": 28, "B": 110}, "MethodologyTable")

    workbook.save(workbook_path)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(matrix_headers)
        for row in matrix_data:
            csv_row = list(row)
            csv_row[5] = round(float(csv_row[5]) * 100, 4)
            csv_row[7] = round(float(csv_row[7]) * 100, 4)
            csv_row[8] = round(float(csv_row[8]) * 100, 4)
            writer.writerow(csv_row)
    return ExportStats(
        facts=len(matrix_data),
        evidence_rows=len(evidence_data),
        workbook_path=workbook_path,
        csv_path=csv_path,
    )
