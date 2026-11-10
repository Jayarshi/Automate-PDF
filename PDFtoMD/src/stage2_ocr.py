"""Docling structure + primary Surya OCR + pix2tex equation crops.

Heavy libraries are imported only when processing the first uncached document.
The small Docling pipeline override is deliberately version-pinned: it inserts
Surya cells BEFORE layout/table assembly, including multilingual table text.
"""

from dataclasses import dataclass
import logging
import math
from pathlib import Path
import re
import uuid

from .config import Config

log = logging.getLogger(__name__)
MATH = re.compile(r"\$\$(.+?)\$\$|(?<![\\$])\$(?!\$)(.+?)(?<!\\)\$(?!\$)"
                  r"|\\\((.+?)\\\)|\\\[(.+?)\\\]|<math[^>]*>(.+?)</math>", re.DOTALL)


def latex_body(value: str) -> str:
    value = value.strip()
    for opening, closing in (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$")):
        if value.startswith(opening) and value.endswith(closing):
            value = value[len(opening):-len(closing)].strip()
            break
    if not value or re.search(r"(?<!\\)\$", value) or "```" in value or len(value) > 16384:
        raise RuntimeError("Formula recognizer returned empty/invalid LaTeX delimiters")
    # This is delimiter/bracket validation, not a full TeX grammar/type checker.
    depth = 0
    for index, char in enumerate(value):
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and value[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if depth < 0:
            raise RuntimeError("Unbalanced braces from formula recognizer")
    if depth:
        raise RuntimeError("Unbalanced braces from formula recognizer")
    return value


def crop_box(image, box, padding=2):
    if len(box) != 4 or not all(math.isfinite(float(x)) for x in box):
        raise RuntimeError("Invalid equation bounding box")
    left, top, right, bottom = box
    left, top = max(0, math.floor(left) - padding), max(0, math.floor(top) - padding)
    right = min(image.width, math.ceil(right) + padding)
    bottom = min(image.height, math.ceil(bottom) + padding)
    if right <= left or bottom <= top:
        raise RuntimeError("Empty equation bounding box")
    return image.crop((left, top, right, bottom))


class FormulaRecognizer:
    def __init__(self):
        self.model = None

    def __call__(self, image):
        if self.model is None:
            from pix2tex.cli import LatexOCR
            self.model = LatexOCR()
            # pix2tex divides logits by temperature, so zero is not valid here.
            self.model.args.temperature = 0.1
        import torch
        torch.manual_seed(0)
        return latex_body(str(self.model(image)))


def refine_inline(line, image, formula, stats):
    """Crop inline math only when Surya supplies an exact character-to-box map.

    Surya may mark math-token geometry invalid. In that case its existing LaTeX
    is retained; inventing a box or sending an entire paragraph to pix2tex would
    erase surrounding text. All skipped crops are exposed in the report.
    """
    text = line.text
    matches = list(MATH.finditer(text))
    if not matches:
        return text
    chars = list(line.chars or [])
    mapped = "".join(char.text for char in chars) == text
    intervals = []
    offset = 0
    for char in chars:
        intervals.append((offset, offset + len(char.text), char))
        offset += len(char.text)
    for match in reversed(matches):
        # Include only actual expression characters, not delimiter tokens.
        group = next(i for i in range(1, 6) if match[i] is not None)
        selected = [char for start, end, char in intervals
                    if start < match.end(group) and end > match.start(group) and char.text.strip()]
        if mapped and selected and all(char.bbox_valid for char in selected):
            boxes = [char.bbox for char in selected]
            box = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                   max(b[2] for b in boxes), max(b[3] for b in boxes)]
            with crop_box(image, box) as crop:
                body = formula(crop)
            stats["inline_crops"] += 1
        else:
            body = latex_body(match[group])
            stats["inline_without_geometry"] += 1
        delimiter = "$$" if group in (1, 4) else "$"
        text = text[:match.start()] + delimiter + body + delimiter + text[match.end():]
    return text


@dataclass
class OCRResult:
    markdown: str
    report: dict


class OCREngine:
    def __init__(self, config: Config):
        self.config = config
        self.formula = FormulaRecognizer()
        self.converter = None
        self.stats = {}

    def _converter(self):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, OcrOptions
        from docling.document_converter import DocumentConverter, ImageFormatOption
        from docling.models.base_ocr_model import BaseOcrModel
        from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
        from docling_core.types.doc import BoundingBox, CoordOrigin
        from docling_core.types.doc.page import BoundingRectangle, TextCell
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
        from surya.detection import DetectionPredictor

        engine = self
        recognizer = RecognitionPredictor(FoundationPredictor())
        detector = DetectionPredictor()

        class SuryaOptions(OcrOptions):
            kind: str = "pdftomd_surya"

        class SuryaModel(BaseOcrModel):
            @classmethod
            def get_options_type(cls):
                return SuryaOptions

            def __call__(self, conv_res, page_batch):
                for page in page_batch:
                    if page._backend is None or not page._backend.is_valid():
                        raise RuntimeError("Docling could not read the rectified page")
                    # Image backend dimensions are pixels; scale=1 keeps original DPI.
                    with page._backend.get_page_image(scale=1.0).convert("RGB") as image:
                        prediction = recognizer(
                            [image], det_predictor=detector,
                            recognition_batch_size=engine.config.recognition_batch_size,
                            detection_batch_size=1, math_mode=True, return_words=True,
                        )[0]
                        sx, sy = page.size.width / image.width, page.size.height / image.height
                        cells = []
                        for line in prediction.text_lines:
                            if not line.text.strip():
                                continue
                            engine.stats["lines"] += 1
                            confidence = float(line.confidence or 0)
                            if confidence < engine.config.confidence_threshold:
                                engine.stats["low_confidence_lines"] += 1
                            text = refine_inline(line, image, engine.formula, engine.stats)
                            # Fine-grained boxes let Docling match multilingual words
                            # to individual table cells instead of entire table rows.
                            words = line.words or []
                            use_words = (not MATH.search(text) and words
                                         and all(word.bbox_valid for word in words)
                                         and re.sub(r"\s", "", "".join(w.text for w in words))
                                         == re.sub(r"\s", "", text))
                            pieces = [(word.text, word.bbox, float(word.confidence or 0))
                                      for word in words] if use_words else [(text, line.bbox, confidence)]
                            for content, box, score in pieces:
                                left, top, right, bottom = box
                                cells.append(TextCell(
                                    index=len(cells), text=content, orig=content,
                                    confidence=score, from_ocr=True,
                                    rect=BoundingRectangle.from_bounding_box(BoundingBox(
                                        l=left * sx, t=top * sy, r=right * sx, b=bottom * sy,
                                        coord_origin=CoordOrigin.TOPLEFT)),
                                ))
                        self.post_process_cells(cells, page)
                    yield page

        class SuryaPipeline(StandardPdfPipeline):
            def _make_ocr_model(self, art_path):
                return SuryaModel(enabled=True, artifacts_path=art_path,
                                  options=SuryaOptions(lang=[engine.config.language], force_full_page_ocr=True),
                                  accelerator_options=self.pipeline_options.accelerator_options)

        options = PdfPipelineOptions(
            do_ocr=True, do_table_structure=True, do_formula_enrichment=False,
            generate_page_images=True, images_scale=1.0,
            document_timeout=self.config.page_timeout,
            ocr_batch_size=1, layout_batch_size=1, table_batch_size=1,
        )
        options.table_structure_options.do_cell_matching = True
        return DocumentConverter(allowed_formats=[InputFormat.IMAGE], format_options={
            InputFormat.IMAGE: ImageFormatOption(pipeline_cls=SuryaPipeline, pipeline_options=options)
        })

    def _export(self, document):
        from docling_core.types.doc import DocItemLabel, ImageRefMode

        # Placeholders keep the normal Docling exporter from escaping inline TeX.
        substitutions = {}

        def shield(text):
            def replace(match):
                key = "PDFTOMDMATH" + uuid.uuid4().hex.upper()
                body = next(value for value in match.groups() if value is not None)
                delimiter = "$$" if match[1] is not None or match[4] is not None else "$"
                substitutions[key] = delimiter + latex_body(body) + delimiter
                return key
            return MATH.sub(replace, text)

        for item, _ in document.iterate_items():
            if item.label == DocItemLabel.FORMULA:
                crop = item.get_image(document)
                if crop is None:
                    raise RuntimeError("Docling formula has no usable image provenance")
                with crop:
                    item.text = self.formula(crop)
                self.stats["display_crops"] += 1
            elif hasattr(item, "text") and item.label != DocItemLabel.CODE:
                item.text = shield(item.text)
            elif item.label == DocItemLabel.TABLE:
                for cell in item.data.table_cells:
                    cell.text = shield(cell.text)
        markdown = document.export_to_markdown(image_mode=ImageRefMode.EMBEDDED)
        for key, formula in substitutions.items():
            markdown = markdown.replace(key, formula)
        return markdown

    def run(self, pages: list[Path]) -> OCRResult:
        if self.converter is None:
            self.converter = self._converter()
        from docling.datamodel.base_models import ConversionStatus

        chunks, reports = [], []
        for index, page in enumerate(pages, 1):
            log.info("Stage 2: rectified page %d/%d (%s)", index, len(pages), page.name)
            self.stats = {"page": page.name, "lines": 0, "low_confidence_lines": 0,
                          "display_crops": 0, "inline_crops": 0, "inline_without_geometry": 0}
            result = self.converter.convert(page, raises_on_error=True)
            if result.status != ConversionStatus.SUCCESS:
                raise RuntimeError(f"Docling returned {result.status} for {page.name}")
            chunks.append(self._export(result.document))
            reports.append(dict(self.stats))
            if self.stats["low_confidence_lines"] or self.stats["inline_without_geometry"]:
                log.warning("Page %s: %d low-confidence lines; %d inline formulas lack crop geometry",
                            page.name, self.stats["low_confidence_lines"], self.stats["inline_without_geometry"])
            del result
        markdown = "\n\n".join(chunks)
        if not markdown.strip():
            raise RuntimeError("OCR produced an empty document; refusing to cache it as success")
        return OCRResult(markdown, {"pages": reports})
