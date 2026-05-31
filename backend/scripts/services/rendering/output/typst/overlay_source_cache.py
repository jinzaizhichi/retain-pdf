from __future__ import annotations

from pathlib import Path
import re

from foundation.config import fonts
from services.rendering.output.typst.source_builder import build_typst_book_overlay_source


PREBUILT_SOURCE_RENDER_VERSION = "overlay_cover_fill_title_color_v6_math_text_tags"
PAGE_SIZE_TOLERANCE_PT = 0.5
TYPST_PAGE_SIZE_RE = re.compile(
    r"#set\s+page\(\s*width:\s*(?P<width>[0-9.]+)pt,\s*height:\s*(?P<height>[0-9.]+)pt",
)


def prebuilt_source_matches_page_specs(
    prebuilt_source_path: Path,
    book_specs: list[tuple[float, float, list[dict]]],
    *,
    include_cover_rect: bool = False,
) -> bool:
    try:
        source = prebuilt_source_path.read_text(encoding="utf-8")
    except OSError:
        return False
    version_marker = _source_version_marker(include_cover_rect=include_cover_rect)
    if version_marker not in source:
        return False
    sizes = [
        (float(match.group("width")), float(match.group("height")))
        for match in TYPST_PAGE_SIZE_RE.finditer(source)
    ]
    if len(sizes) != len(book_specs):
        return False
    for (actual_w, actual_h), (expected_w, expected_h, _items) in zip(sizes, book_specs):
        if abs(actual_w - float(expected_w)) > PAGE_SIZE_TOLERANCE_PT:
            return False
        if abs(actual_h - float(expected_h)) > PAGE_SIZE_TOLERANCE_PT:
            return False
    return True


def resolve_prebuilt_overlay_source(
    *,
    prebuilt_source_path: Path | None,
    temp_root: Path | None,
    stem: str,
    book_specs: list[tuple[float, float, list[dict]]],
    font_family: str = fonts.TYPST_DEFAULT_FONT_FAMILY,
    include_cover_rect: bool = False,
) -> tuple[Path | None, float]:
    import time

    started = time.perf_counter()
    active_path = Path(prebuilt_source_path) if prebuilt_source_path is not None else None
    if (
        active_path is not None
        and active_path.exists()
        and prebuilt_source_matches_page_specs(
            active_path,
            book_specs,
            include_cover_rect=include_cover_rect,
        )
    ):
        print(f"typst book overlay source prewarm: hit {active_path}", flush=True)
        return active_path, time.perf_counter() - started
    if temp_root is None:
        return None, time.perf_counter() - started
    source_work_dir = temp_root / "book-overlay-sources"
    source_work_dir.mkdir(parents=True, exist_ok=True)
    active_path = source_work_dir / f"{stem}.typ.prebuilt"
    active_path.write_text(
        f"// {_source_version_marker(include_cover_rect=include_cover_rect)}\n"
        + build_typst_book_overlay_source(
            book_specs,
            font_family=font_family,
            include_cover_rect=include_cover_rect,
        ),
        encoding="utf-8",
    )
    return active_path, time.perf_counter() - started


def _source_version_marker(*, include_cover_rect: bool) -> str:
    suffix = "_cover_fill" if include_cover_rect else ""
    return f"{PREBUILT_SOURCE_RENDER_VERSION}{suffix}"


__all__ = [
    "PAGE_SIZE_TOLERANCE_PT",
    "PREBUILT_SOURCE_RENDER_VERSION",
    "prebuilt_source_matches_page_specs",
    "resolve_prebuilt_overlay_source",
]
