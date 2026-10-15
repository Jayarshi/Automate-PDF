from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .config import AppConfig
from .engines.nllb import NLLBEngine
from .engines.postedit import LocalLLMPostEditor, NoOpPostEditor, PostEditor
from .languages import resolve_language
from .protect import ProtectedText, TextProtector
from .quality import QualityEvaluator
from .segment import Segmenter, TextSegment
from .types import SegmentResult, TranslationRequest, TranslationResult


class TranslationPipeline:
    def __init__(
        self,
        config: AppConfig,
        engine: NLLBEngine | Any | None = None,
        post_editor: PostEditor | None = None,
        evaluator: QualityEvaluator | None = None,
    ) -> None:
        self.config = config
        self.engine = engine or NLLBEngine(config.nllb)
        self.post_editor = post_editor or (
            LocalLLMPostEditor(config.post_edit) if config.post_edit.enabled else NoOpPostEditor()
        )
        self.evaluator = evaluator or QualityEvaluator(config.quality)
        self.protector = TextProtector()
        self.segmenter = Segmenter(config.segmentation, self.engine.count_tokens)
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path: str | Path) -> TranslationPipeline:
        return cls(AppConfig.from_file(path))

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if not request.text.strip():
            raise ValueError("Input text cannot be empty")
        source_lang = resolve_language(request.source_lang)
        target_lang = resolve_language(request.target_lang)
        if source_lang == target_lang:
            raise ValueError("Source and target languages must be different")
        if request.tone not in {"faithful", "formal", "literary", "academic", "colloquial"}:
            raise ValueError(f"Unsupported tone: {request.tone}")

        # NLLB tokenizer source-language state and CT2 calls are serialized for API safety.
        with self._lock:
            return self._translate_locked(request, source_lang, target_lang)

    def _translate_locked(
        self, request: TranslationRequest, source_lang: str, target_lang: str
    ) -> TranslationResult:
        source_segments = self.segmenter.segment(request.text, source_lang)
        protected = [
            self.protector.protect(item.text, request.glossary) for item in source_segments
        ]
        raw_candidates: list[str] = []
        for start in range(0, len(protected), max(1, self.config.segmentation.batch_size)):
            batch = protected[start : start + self.config.segmentation.batch_size]
            raw_candidates.extend(
                self.engine.translate_batch([item.text for item in batch], source_lang, target_lang)
            )

        results: list[SegmentResult] = []
        for source_segment, protected_segment, raw in zip(
            source_segments, protected, raw_candidates, strict=True
        ):
            results.append(
                self._finish_segment(
                    source_segment,
                    protected_segment,
                    raw,
                    request,
                    source_lang,
                    target_lang,
                )
            )

        text = _join(source_segments, [item.translation for item in results])
        raw_text = _join(source_segments, [item.raw_translation for item in results])
        document_score, metrics, document_issues = self.evaluator.evaluate(
            request.text,
            text,
            request.glossary,
            [],
            request.reference,
        )
        segment_average = sum(item.score for item in results) / len(results)
        metrics["segment_average"] = round(segment_average, 4)
        score = round(min(document_score, segment_average), 4)
        passed = all(item.passed for item in results) and score >= self.config.quality.threshold
        issues = list(
            dict.fromkeys([*(issue for item in results for issue in item.issues), *document_issues])
        )
        result = TranslationResult(
            text=text,
            raw_text=raw_text,
            score=score,
            passed=passed,
            needs_review=not passed,
            source_lang=source_lang,
            target_lang=target_lang,
            tone=request.tone,
            segments=results,
            metrics=metrics,
            issues=issues,
        )
        if result.needs_review:
            result.review_file = self._write_review(request, result)
        return result

    def _finish_segment(
        self,
        source_segment: TextSegment,
        protected: ProtectedText,
        raw: str,
        request: TranslationRequest,
        source_lang: str,
        target_lang: str,
    ) -> SegmentResult:
        attempts = 1
        current_raw = raw
        best: SegmentResult | None = None
        retry_issues: list[str] = []
        while attempts <= self.config.quality.max_retries + 1:
            editor_issues: list[str] = []
            try:
                edited = self.post_editor.edit(
                    protected.text,
                    current_raw,
                    source_lang,
                    target_lang,
                    request.tone,
                    request.glossary,
                    retry_issues,
                )
            except RuntimeError as exc:
                edited = current_raw
                editor_issues.append(f"post-editor unavailable: {exc}")
            restored_raw, raw_restore_issues = protected.restore(current_raw)
            restored, restore_issues = protected.restore(edited)
            inherited = [*editor_issues, *restore_issues]
            score, metrics, issues = self.evaluator.evaluate(
                source_segment.text, restored, request.glossary, inherited
            )
            candidate = SegmentResult(
                source=source_segment.text,
                raw_translation=restored_raw,
                translation=restored,
                score=score,
                passed=score >= self.config.quality.retry_threshold and not raw_restore_issues,
                attempts=attempts,
                metrics=metrics,
                issues=list(dict.fromkeys([*raw_restore_issues, *issues])),
            )
            if candidate.passed or best is None or candidate.score > best.score:
                best = candidate
            if candidate.passed or attempts > self.config.quality.max_retries:
                break
            retry_issues = candidate.issues
            attempts += 1
            current_raw = self.engine.translate_batch(
                [protected.text],
                source_lang,
                target_lang,
                beam_size=max(self.config.nllb.beam_size + 2, self.config.nllb.beam_size * 2),
            )[0]
        assert best is not None
        best.attempts = attempts
        return best

    def _write_review(self, request: TranslationRequest, result: TranslationResult) -> str:
        path = Path(self.config.quality.review_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "document_id": request.document_id,
            "source": request.text,
            "translation": result.text,
            "raw_translation": result.raw_text,
            "source_lang": result.source_lang,
            "target_lang": result.target_lang,
            "tone": result.tone,
            "score": result.score,
            "metrics": result.metrics,
            "issues": result.issues,
            "segments": result.to_dict()["segments"],
            "status": "pending_human_review",
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return str(path)


def _join(segments: list[TextSegment], values: list[str]) -> str:
    return "".join(
        segment.prefix + value + segment.separator
        for segment, value in zip(segments, values, strict=True)
    )
