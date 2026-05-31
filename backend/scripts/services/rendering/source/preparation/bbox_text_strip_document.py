from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import as_completed
import os
from pathlib import Path
import shutil
import time

import fitz
import pikepdf
from pikepdf import Name

from services.rendering.source.preparation.bbox_text_strip_engine import strip_bbox_text_from_page
from services.rendering.source.preparation.bbox_text_strip_types import BBoxTextStripResult


BBOX_TEXT_STRIP_PARALLEL_PAGE_THRESHOLD = 12
BBOX_TEXT_STRIP_PARALLEL_MAX_WORKERS = 6
BBOX_TEXT_STRIP_PAGES_PER_WORKER = 6


def strip_bbox_text_rects_from_pdf_copy(
    *,
    source_pdf_path: Path,
    output_pdf_path: Path,
    page_rects: dict[int, list[fitz.Rect]],
    page_protected_rects: dict[int, list[fitz.Rect]] | None = None,
    recurse_forms: bool | None = None,
    skipped_complex: int = 0,
    skipped_no_text_overlap: int = 0,
    skipped_visual_background: int = 0,
    skipped_complex_page_indices: frozenset[int] = frozenset(),
    skipped_no_text_overlap_page_indices: frozenset[int] = frozenset(),
    skipped_visual_background_page_indices: frozenset[int] = frozenset(),
    candidate_elapsed: float = 0.0,
) -> BBoxTextStripResult:
    page_protected_rects = page_protected_rects or {}
    if not page_rects:
        return BBoxTextStripResult(
            changed=False,
            pages_skipped_complex=skipped_complex,
            pages_skipped_no_text_overlap=skipped_no_text_overlap,
            pages_skipped_visual_background=skipped_visual_background,
            skipped_complex_page_indices=frozenset(skipped_complex_page_indices),
            skipped_no_text_overlap_page_indices=frozenset(skipped_no_text_overlap_page_indices),
            skipped_visual_background_page_indices=frozenset(skipped_visual_background_page_indices),
        )

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    copy_started = time.perf_counter()
    shutil.copy2(source_pdf_path, output_pdf_path)
    copy_elapsed = time.perf_counter() - copy_started

    pages_changed = 0
    attempted_page_indices = set(page_rects)
    changed_page_indices: set[int] = set()
    removed_total = 0
    forms_changed_total = 0
    parse_elapsed = 0.0
    save_elapsed = 0.0
    effective_recurse_forms = True if recurse_forms is None else recurse_forms
    with pikepdf.Pdf.open(output_pdf_path, allow_overwriting_input=True) as pdf:
        page_results, parse_elapsed = _strip_pages(
            source_pdf_path=source_pdf_path,
            pdf=pdf,
            page_rects=page_rects,
            page_protected_rects=page_protected_rects,
            recurse_forms=effective_recurse_forms,
        )
        for page_idx, content_stream, removed, forms_changed in page_results:
            forms_changed_total += forms_changed
            if not content_stream or removed <= 0:
                if forms_changed > 0:
                    pages_changed += 1
                    changed_page_indices.add(page_idx)
                    removed_total += removed
                continue
            pdf.pages[page_idx].obj[Name("/Contents")] = pdf.make_stream(content_stream)
            pages_changed += 1
            changed_page_indices.add(page_idx)
            removed_total += removed

        if pages_changed <= 0:
            output_pdf_path.unlink(missing_ok=True)
            return BBoxTextStripResult(
                changed=False,
                pages_skipped_complex=skipped_complex,
                pages_skipped_no_text_overlap=skipped_no_text_overlap,
                pages_skipped_visual_background=skipped_visual_background,
                pages_strip_no_effect=len(attempted_page_indices),
                skipped_complex_page_indices=frozenset(skipped_complex_page_indices),
                skipped_no_text_overlap_page_indices=frozenset(skipped_no_text_overlap_page_indices),
                skipped_visual_background_page_indices=frozenset(skipped_visual_background_page_indices),
                strip_no_effect_page_indices=frozenset(attempted_page_indices),
            )

        save_started = time.perf_counter()
        pdf.save(
            output_pdf_path,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            compress_streams=True,
            recompress_flate=False,
        )
        save_elapsed = time.perf_counter() - save_started

    print(
        f"bbox text strip: mode=strip pages={pages_changed} text_show_ops={removed_total} "
        f"forms={forms_changed_total} skipped_complex_pages={skipped_complex} "
        f"skipped_no_text_overlap_pages={skipped_no_text_overlap} "
        f"skipped_visual_background_pages={skipped_visual_background} "
        f"strip_no_effect_pages={len(attempted_page_indices - changed_page_indices)} "
        f"copy={copy_elapsed:.2f}s candidates={candidate_elapsed:.2f}s parse={parse_elapsed:.2f}s save={save_elapsed:.2f}s "
        f"output={output_pdf_path}",
        flush=True,
    )
    return BBoxTextStripResult(
        changed=True,
        output_pdf_path=output_pdf_path,
        pages_changed=pages_changed,
        text_show_ops_removed=removed_total,
        pages_skipped_complex=skipped_complex,
        pages_skipped_no_text_overlap=skipped_no_text_overlap,
        pages_skipped_visual_background=skipped_visual_background,
        pages_strip_no_effect=len(attempted_page_indices - changed_page_indices),
        forms_changed=forms_changed_total,
        changed_page_indices=frozenset(changed_page_indices),
        skipped_complex_page_indices=frozenset(skipped_complex_page_indices),
        skipped_no_text_overlap_page_indices=frozenset(skipped_no_text_overlap_page_indices),
        skipped_visual_background_page_indices=frozenset(skipped_visual_background_page_indices),
        strip_no_effect_page_indices=frozenset(attempted_page_indices - changed_page_indices),
    )


def _strip_pages(
    *,
    source_pdf_path: Path,
    pdf: pikepdf.Pdf,
    page_rects: dict[int, list[fitz.Rect]],
    page_protected_rects: dict[int, list[fitz.Rect]],
    recurse_forms: bool,
) -> tuple[list[tuple[int, bytes | None, int, int]], float]:
    if len(page_rects) < BBOX_TEXT_STRIP_PARALLEL_PAGE_THRESHOLD:
        started = time.perf_counter()
        results = [
            _strip_page_in_open_pdf(
                pdf=pdf,
                page_idx=page_idx,
                rects=rects,
                protected_rects=page_protected_rects.get(page_idx, []),
                recurse_forms=recurse_forms,
            )
            for page_idx, rects in page_rects.items()
        ]
        return results, time.perf_counter() - started

    worker_count = _parallel_worker_count(len(page_rects))
    if worker_count <= 1:
        started = time.perf_counter()
        results = [
            _strip_page_in_open_pdf(
                pdf=pdf,
                page_idx=page_idx,
                rects=rects,
                protected_rects=page_protected_rects.get(page_idx, []),
                recurse_forms=recurse_forms,
            )
            for page_idx, rects in page_rects.items()
        ]
        return results, time.perf_counter() - started

    started = time.perf_counter()
    results_by_page: dict[int, tuple[int, bytes | None, int, int]] = {}
    plain_page_rects: dict[int, list[fitz.Rect]] = {}
    form_page_rects: dict[int, list[fitz.Rect]] = {}
    for page_idx, rects in page_rects.items():
        if recurse_forms and _page_has_form_xobjects(pdf, page_idx):
            form_page_rects[page_idx] = rects
        else:
            plain_page_rects[page_idx] = rects

    if plain_page_rects:
        page_chunks = _page_chunks(plain_page_rects, page_protected_rects, worker_count)
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(_strip_page_chunk_worker, str(source_pdf_path), chunk)
                for chunk in page_chunks
            ]
            for future in as_completed(futures):
                for page_idx, content_stream, removed, forms_changed in future.result():
                    results_by_page[page_idx] = (page_idx, content_stream, removed, forms_changed)
    if form_page_rects:
        for page_idx, rects in form_page_rects.items():
            results_by_page[page_idx] = _strip_page_in_open_pdf(
                pdf=pdf,
                page_idx=page_idx,
                rects=rects,
                protected_rects=page_protected_rects.get(page_idx, []),
                recurse_forms=recurse_forms,
            )
    results = [results_by_page[page_idx] for page_idx in page_rects]
    return results, time.perf_counter() - started


def _strip_page_in_open_pdf(
    *,
    pdf: pikepdf.Pdf,
    page_idx: int,
    rects: list[fitz.Rect],
    protected_rects: list[fitz.Rect],
    recurse_forms: bool,
) -> tuple[int, bytes | None, int, int]:
    content_stream, removed, forms_changed = strip_bbox_text_from_page(
        pdf.pages[page_idx],
        rects,
        protected_rects=protected_rects,
        recurse_forms=recurse_forms,
    )
    return page_idx, content_stream, removed, forms_changed


def _strip_page_chunk_worker(
    source_pdf_path: str,
    chunk: list[tuple[int, tuple[tuple[float, float, float, float], ...], tuple[tuple[float, float, float, float], ...]]],
) -> list[tuple[int, bytes | None, int, int]]:
    results: list[tuple[int, bytes | None, int, int]] = []
    with pikepdf.Pdf.open(source_pdf_path) as pdf:
        for page_idx, rects, protected_rects in chunk:
            content_stream, removed, forms_changed = strip_bbox_text_from_page(
                pdf.pages[page_idx],
                [fitz.Rect(rect) for rect in rects],
                protected_rects=[fitz.Rect(rect) for rect in protected_rects],
                recurse_forms=False,
            )
            results.append((page_idx, content_stream, removed, forms_changed))
    return results


def _parallel_worker_count(page_count: int) -> int:
    raw = str(os.environ.get("RETAIN_BBOX_TEXT_STRIP_WORKERS", "") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    cpu_count = os.cpu_count() or 1
    page_limited_workers = max(1, (page_count + BBOX_TEXT_STRIP_PAGES_PER_WORKER - 1) // BBOX_TEXT_STRIP_PAGES_PER_WORKER)
    return max(1, min(BBOX_TEXT_STRIP_PARALLEL_MAX_WORKERS, cpu_count, page_count, page_limited_workers))


def _rect_tuples(rects: list[fitz.Rect]) -> tuple[tuple[float, float, float, float], ...]:
    return tuple((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)) for rect in rects)


def _page_chunks(
    page_rects: dict[int, list[fitz.Rect]],
    page_protected_rects: dict[int, list[fitz.Rect]],
    worker_count: int,
) -> list[list[tuple[int, tuple[tuple[float, float, float, float], ...], tuple[tuple[float, float, float, float], ...]]]]:
    chunks: list[list[tuple[int, tuple[tuple[float, float, float, float], ...], tuple[tuple[float, float, float, float], ...]]]] = [
        [] for _ in range(max(1, worker_count))
    ]
    for index, (page_idx, rects) in enumerate(page_rects.items()):
        chunks[index % len(chunks)].append(
            (
                page_idx,
                _rect_tuples(rects),
                _rect_tuples(page_protected_rects.get(page_idx, [])),
            )
        )
    return [chunk for chunk in chunks if chunk]


def _page_has_form_xobjects(pdf: pikepdf.Pdf, page_idx: int) -> bool:
    try:
        page = pdf.pages[page_idx]
        resources = page.obj.get(Name("/Resources"))
        if resources is None:
            return False
        xobjects = resources.get(Name("/XObject"))
        if xobjects is None:
            return False
        for xobject in xobjects.values():
            if str(xobject.get(Name("/Subtype"))) == "/Form":
                return True
    except Exception:
        return True
    return False
