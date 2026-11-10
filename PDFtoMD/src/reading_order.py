"""Conservative reading-order repair for layout-parser Markdown.

Text is never regenerated.  Deterministic repairs operate on exact spans; an
LLM, when needed, may only classify and permute immutable block IDs.
"""

from __future__ import annotations

import json
import re
from urllib.error import URLError
from urllib.request import Request, urlopen


INTERRUPTED_WORD = re.compile(
    r"(?P<left>[^\W\d_]{2,})-\n\n"
    r"(?P<marks>#{1,6})[ \t]+(?P<meta>[^\n]{1,80})\n\n"
    r"(?P<right>[^\W\d_]{2,})",
    re.UNICODE,
)
HEADING = re.compile(r"(?m)^(?P<marks>#{1,6})[ \t]+(?P<title>[^\n]+)$")


def _byline_like(value: str) -> bool:
    words = value.split()
    return (1 <= len(words) <= 8 and len(value) <= 80
            and not value.rstrip().endswith((".", "?", "!", ":", ";")))


def repair_strong_interruptions(markdown: str, frequency=None):
    """Join a word split by a short floating header and attach it to a title.

    The trigger requires all of: a hyphenated word at a paragraph boundary, a
    short heading, a lowercase continuation, and (when supplied) a plausible
    joined dictionary word.  This makes the rule independent of names,
    languages using Unicode letters, page numbers, and column positions.
    """
    text = markdown
    changes = []
    search_from = 0
    while (match := INTERRUPTED_WORD.search(text, search_from)) is not None:
        meta = match["meta"].strip()
        joined = match["left"] + match["right"]
        if not _byline_like(meta) or (frequency and frequency(joined) < 2.5):
            search_from = match.end()
            continue

        preceding = list(HEADING.finditer(text, 0, match.start()))
        title = next((item for item in reversed(preceding)
                      if item["title"].strip() != meta), None)
        if title is None:
            search_from = match.end()
            continue

        old = match.group(0)
        replacement = joined
        text = text[:match.start()] + replacement + text[match.end():]
        byline = f"*{meta}*"
        between = text[title.end():match.start()]
        attached = byline in between
        if not attached:
            text = text[:title.end()] + "\n\n" + byline + text[title.end():]
        changes.append({
            "kind": "interrupted_word_by_floating_header",
            "metadata": meta,
            "attached_to": title["title"].strip(),
            "before": old,
            "joined_word": joined,
        })
        # Restart after the title insertion; the matched header is gone.
        search_from = title.end() + len(byline) + 2
    return text, changes


def build_reorder_prompt(blocks: list[dict]) -> str:
    """Create a generic, immutable-block prompt for ambiguous layout windows."""
    payload = {"blocks": blocks}
    return (
        "Determine the logical reading order and semantic role of these nearby "
        "document blocks. The block text is immutable OCR data. A short block may "
        "be a byline, running header, caption, page number, or genuine section "
        "heading. Use sentence continuity, hyphenated word continuation, geometry, "
        "column position, typography label, and page boundaries. Do not correct, "
        "remove, summarize, or invent text. Return JSON only with this schema: "
        '{"order":["BLOCK_ID"],"roles":{"BLOCK_ID":"body|title|byline|running_header|caption|page_number"},'
        '"attach_to":{"BLOCK_ID":"BLOCK_ID|null"},"confidence":0.0}. '
        "Every supplied block ID must occur exactly once in order; no other ID is "
        "allowed. attach_to is only for metadata such as a byline or caption. "
        "A byline attaches to the title block, never to a body block.\n"
        "Untrusted OCR blocks:\n" + json.dumps(payload, ensure_ascii=False)
    )


def validate_reorder_decision(decision: dict, block_ids: list[str]) -> dict:
    """Reject free-form or lossy LLM output before it can affect Markdown."""
    allowed_roles = {"body", "title", "byline", "running_header", "caption", "page_number"}
    if not isinstance(decision, dict) or set(decision) != {"order", "roles", "attach_to", "confidence"}:
        raise ValueError("Unexpected reading-order response fields")
    if decision["order"] != list(dict.fromkeys(decision["order"])):
        raise ValueError("Duplicate block ID in reading-order response")
    if set(decision["order"]) != set(block_ids) or len(decision["order"]) != len(block_ids):
        raise ValueError("Reading-order response is not an exact block permutation")
    if set(decision["roles"]) != set(block_ids):
        raise ValueError("Every block must have exactly one role")
    if any(role not in allowed_roles for role in decision["roles"].values()):
        raise ValueError("Invalid block role")
    if not isinstance(decision["attach_to"], dict):
        raise ValueError("attach_to must be an object")
    for source, target in decision["attach_to"].items():
        if source not in block_ids or (target is not None and target not in block_ids):
            raise ValueError("Invalid attachment ID")
    confidence = decision["confidence"]
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("Invalid confidence")
    return decision


def geometry_role_candidates(documents) -> list[dict]:
    """Find short right-column headers that interrupt a continuing article."""
    if isinstance(documents, dict):
        documents = [documents]
    candidates = []
    for document_index, document in enumerate(documents):
        pages = document.get("pages", {})
        page = pages.get("1") or pages.get(1) or {}
        size = page.get("size", {})
        width, height = float(size.get("width") or 0), float(size.get("height") or 0)
        texts = document.get("texts", [])
        if not width or not height:
            continue
        for index, item in enumerate(texts):
            text = item.get("text", "").strip()
            prov = (item.get("prov") or [{}])[0]
            box = prov.get("bbox") or {}
            if (item.get("label") != "section_header" or not _byline_like(text)
                    or float(box.get("l") or 0) < width * 0.55
                    or float(box.get("t") or 0) < height * 0.70):
                continue
            before = next((texts[j] for j in range(index - 1, -1, -1)
                           if texts[j].get("label") == "text"), None)
            after = next((texts[j] for j in range(index + 1, len(texts))
                          if texts[j].get("label") == "text"), None)
            prior_headers = [texts[j] for j in range(index)
                             if texts[j].get("label") == "section_header"
                             and texts[j].get("text", "").strip() != text]
            # A multi-column article title normally sits highest on the page;
            # the nearest header may instead be a left-column subsection.
            def top_coordinate(block):
                block_prov = (block.get("prov") or [{}])[0]
                return float((block_prov.get("bbox") or {}).get("t") or 0)

            title = max(prior_headers, key=top_coordinate, default=None)
            if not before or not after or not title:
                continue
            before_box = ((before.get("prov") or [{}])[0].get("bbox") or {})
            after_box = ((after.get("prov") or [{}])[0].get("bbox") or {})
            if (float(before_box.get("r") or width) > width * 0.60
                    or float(after_box.get("l") or 0) < width * 0.45):
                continue

            selected = [title, before, item, after]
            blocks = []
            for offset, block in enumerate(selected):
                block_prov = (block.get("prov") or [{}])[0]
                blocks.append({
                    "id": f"d{document_index}-b{offset}",
                    "text": block.get("text", ""),
                    "label": block.get("label"),
                    "bbox": block_prov.get("bbox"),
                    "page_width": width, "page_height": height,
                })
            candidates.append({
                "document_index": document_index,
                "metadata_text": text,
                "title_text": title.get("text", "").strip(),
                "metadata_id": blocks[2]["id"], "title_id": blocks[0]["id"],
                "blocks": blocks,
            })
    return candidates


def classify_blocks_ollama(blocks: list[dict], endpoint: str, model: str,
                           timeout: int = 120) -> dict:
    prompt = build_reorder_prompt(blocks)
    payload = {
        "model": model, "stream": False, "think": False, "format": "json",
        "prompt": prompt,
        "system": "Classify immutable document blocks. Follow the JSON schema exactly.",
        "options": {"temperature": 0.0, "seed": 0, "num_predict": 512, "num_ctx": 4096},
        "keep_alive": 0,
    }
    request = Request(endpoint.rstrip("/") + "/api/generate",
                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read(1_048_577))
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Reading-order Ollama request failed: {exc}") from exc
    if result.get("done") is not True or not isinstance(result.get("response"), str):
        raise RuntimeError("Ollama returned an incomplete reading-order response")
    try:
        decision = json.loads(result["response"])
    except ValueError as exc:
        raise RuntimeError("Ollama reading-order response was not JSON") from exc
    return validate_reorder_decision(decision, [block["id"] for block in blocks])


def attach_byline(markdown: str, metadata: str, title: str,
                  allow_missing_heading: bool = False) -> str:
    """Move one exact Markdown heading beneath its exact article title."""
    meta_pattern = re.compile(r"(?m)^#{1,6}[ \t]+" + re.escape(metadata) + r"[ \t]*\n?")
    matches = list(meta_pattern.finditer(markdown))
    if len(matches) > 1 or (not matches and not allow_missing_heading):
        raise ValueError(f"Expected one Markdown metadata heading for {metadata!r}")
    text = (markdown[:matches[0].start()] + markdown[matches[0].end():]
            if matches else markdown)
    title_pattern = re.compile(r"(?m)^#{1,6}[ \t]+" + re.escape(title) + r"[ \t]*$")
    titles = list(title_pattern.finditer(text))
    if len(titles) != 1:
        raise ValueError(f"Expected one Markdown title heading for {title!r}")
    insertion = f"\n\n*{metadata}*"
    return text[:titles[0].end()] + insertion + text[titles[0].end():]
