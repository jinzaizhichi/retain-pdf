from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from foundation.config import layout
from services.document_schema.semantics import block_kind as schema_block_kind
from services.rendering.source.prewarm_contracts import BBOX_TEXT_STRIP_ALGORITHM_VERSION
from services.rendering.source.prewarm_contracts import GEOMETRY_ADJUSTMENT_ALGORITHM_VERSION
from services.rendering.source.prewarm_contracts import HIDDEN_TEXT_STRIP_ALGORITHM_VERSION
from services.rendering.source.prewarm_contracts import IMAGE_COMPRESSION_ALGORITHM_VERSION
from services.rendering.source.prewarm_contracts import PAYLOAD_RENDER_ALGORITHM_VERSION
from services.rendering.source.prewarm_manifest import float_or_zero
from services.rendering.source.prewarm_manifest import int_or_default


def build_payload_structure_hash(translated_pages: dict[int, list[dict]]) -> str:
    digest = hashlib.sha256()
    for page_idx in sorted(translated_pages):
        compact_items = [
            _payload_structure_item(page_idx, item)
            for item in translated_pages[page_idx]
            if _is_bbox_text_strip_candidate(item)
        ]
        if not compact_items:
            continue
        digest.update(f"page:{page_idx}\n".encode("utf-8"))
        for compact in compact_items:
            digest.update(json.dumps(compact, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def build_render_prewarm_fingerprint(
    *,
    source_pdf_path: Path,
    translated_pages: dict[int, list[dict]],
    effective_render_mode: str,
    start_page: int,
    end_page: int,
    pdf_compress_dpi: int,
    source_cleanup_strategy: str = "pikepdf_text_strip",
) -> dict[str, Any]:
    source_pdf_path = Path(source_pdf_path).resolve()
    stat = source_pdf_path.stat()
    cleanup_strategy = layout.normalize_source_cleanup_strategy(source_cleanup_strategy)
    selected_pages = _bbox_text_strip_page_indexes(translated_pages) if layout.use_bbox_text_strip_cleanup(cleanup_strategy) else []
    return {
        "source_pdf_path": str(source_pdf_path),
        "source_pdf_size": int(stat.st_size),
        "source_pdf_mtime_ns": int(stat.st_mtime_ns),
        "selected_page_indexes": selected_pages,
        "page_range": {"start_page": int(start_page), "end_page": int(end_page)},
        "effective_render_mode": str(effective_render_mode),
        "strip_hidden_text": bool(effective_render_mode != "overlay"),
        "pdf_compress_dpi": int(pdf_compress_dpi),
        "source_cleanup_strategy": cleanup_strategy,
        "payload_structure_hash": build_payload_structure_hash(translated_pages),
        "bbox_text_strip_algorithm": BBOX_TEXT_STRIP_ALGORITHM_VERSION,
        "hidden_text_strip_algorithm": HIDDEN_TEXT_STRIP_ALGORITHM_VERSION,
        "image_compression_algorithm": IMAGE_COMPRESSION_ALGORITHM_VERSION,
        "geometry_adjustment_algorithm": GEOMETRY_ADJUSTMENT_ALGORITHM_VERSION,
        "payload_render_algorithm": PAYLOAD_RENDER_ALGORITHM_VERSION,
    }


def _payload_structure_item(page_idx: int, item: dict) -> dict[str, Any]:
    item_kind = schema_block_kind(item)
    return {
        "item_id": str(item.get("item_id", "") or ""),
        "page_idx": int_or_default(item.get("page_idx"), page_idx),
        "block_type": str(item.get("block_type", "") or ""),
        "block_kind": item_kind,
        "bbox": [float_or_zero(value) for value in list(item.get("bbox", []) or [])[:4]],
        "layout_role": str(item.get("layout_role", "") or ""),
        "semantic_role": str(item.get("semantic_role", "") or ""),
        "structure_role": str(item.get("structure_role", "") or ""),
        "raw_block_type": str(item.get("raw_block_type", "") or ""),
        "normalized_sub_type": str(item.get("normalized_sub_type", "") or ""),
        "strip_candidate": _has_render_source_or_output_text(item),
    }


def _bbox_text_strip_page_indexes(translated_pages: dict[int, list[dict]]) -> list[int]:
    return [
        int(page_idx)
        for page_idx in sorted(translated_pages)
        if any(_is_bbox_text_strip_candidate(item) for item in translated_pages[page_idx])
    ]


def _is_bbox_text_strip_candidate(item: dict) -> bool:
    if schema_block_kind(item) != "text":
        return False
    bbox = item.get("bbox", [])
    if len(bbox) != 4:
        return False
    if all(float_or_zero(value) == 0.0 for value in bbox):
        return False
    return _has_render_source_or_output_text(item)


def _has_render_source_or_output_text(item: dict) -> bool:
    return bool(_render_source_text(item))


def _render_source_text(item: dict) -> str:
    return str(
        item.get("translation_unit_protected_source_text")
        or item.get("protected_source_text")
        or item.get("source_text")
        or ""
    ).strip()


__all__ = [
    "build_payload_structure_hash",
    "build_render_prewarm_fingerprint",
]
