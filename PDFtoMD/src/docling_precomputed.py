"""Docling adapter for OCR geometry checkpointed by a separate Surya process."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path


def convert_precomputed_pages(pages: list[Path], ocr_dir: Path, timeout: int = 1800,
                              language: str = "en"):
    """Run Docling layout/tables using saved OCR; never import or load Surya."""
    from docling.datamodel.base_models import InputFormat, ConversionStatus
    from docling.datamodel.pipeline_options import PdfPipelineOptions, OcrOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption
    from docling.models.base_ocr_model import BaseOcrModel
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
    from docling_core.types.doc import BoundingBox, CoordOrigin
    from docling_core.types.doc.page import BoundingRectangle, TextCell

    state = {"prediction": None}

    class CheckpointOptions(OcrOptions):
        kind: str = "pdftomd_precomputed"

    class CheckpointModel(BaseOcrModel):
        @classmethod
        def get_options_type(cls):
            return CheckpointOptions

        def __call__(self, conv_res, page_batch):
            prediction = state["prediction"]
            if prediction is None:
                raise RuntimeError("Precomputed OCR state was not set")
            image_box = prediction["image_bbox"]
            image_width = float(image_box[2] - image_box[0])
            image_height = float(image_box[3] - image_box[1])
            for page in page_batch:
                if page.size is None:
                    raise RuntimeError("Docling image page has no size")
                sx, sy = page.size.width / image_width, page.size.height / image_height
                cells = []
                for line in prediction.get("text_lines", []):
                    text = line.get("text", "").strip()
                    if not text:
                        continue
                    words = line.get("words") or []
                    compact = lambda value: "".join(value.split())
                    valid_words = (words and all(word.get("bbox_valid", True) for word in words)
                                   and compact("".join(word.get("text", "") for word in words))
                                   == compact(text))
                    pieces = words if valid_words else [line]
                    for piece in pieces:
                        content = piece.get("text", "").strip()
                        box = piece.get("bbox")
                        if not content or not box or len(box) != 4:
                            continue
                        left, top, right, bottom = map(float, box)
                        cells.append(TextCell(
                            index=len(cells), text=content, orig=content,
                            confidence=float(piece.get("confidence") or 0), from_ocr=True,
                            rect=BoundingRectangle.from_bounding_box(BoundingBox(
                                l=left * sx, t=top * sy, r=right * sx, b=bottom * sy,
                                coord_origin=CoordOrigin.TOPLEFT,
                            )),
                        ))
                self.post_process_cells(cells, page)
                yield page

    class CheckpointPipeline(StandardPdfPipeline):
        def _make_ocr_model(self, artifacts_path):
            return CheckpointModel(
                enabled=True, artifacts_path=artifacts_path,
                options=CheckpointOptions(lang=[language], force_full_page_ocr=True),
                accelerator_options=self.pipeline_options.accelerator_options,
            )

    options = PdfPipelineOptions(
        do_ocr=True, do_table_structure=True, do_formula_enrichment=False,
        generate_page_images=False, document_timeout=timeout,
        ocr_batch_size=1, layout_batch_size=1, table_batch_size=1,
    )
    options.table_structure_options.do_cell_matching = True
    converter = DocumentConverter(
        allowed_formats=[InputFormat.IMAGE],
        format_options={InputFormat.IMAGE: ImageFormatOption(
            pipeline_cls=CheckpointPipeline, pipeline_options=options,
        )},
    )

    markdown_pages = []
    document_json = []
    labels = Counter()
    for page in pages:
        checkpoint = ocr_dir / f"{page.stem}.json"
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        state["prediction"] = payload["prediction"]
        result = converter.convert(page, raises_on_error=True)
        if result.status != ConversionStatus.SUCCESS:
            raise RuntimeError(f"Docling returned {result.status} for {page.name}")
        markdown_pages.append(result.document.export_to_markdown())
        document_json.append(result.document.model_dump(mode="json"))
        for item, _ in result.document.iterate_items():
            labels[str(item.label)] += 1
    return "\n\n".join(markdown_pages), document_json, dict(labels)
