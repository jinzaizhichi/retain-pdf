from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

import fitz
import pikepdf
import pytest


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.rendering.source.preparation import bbox_text_strip_document
from services.rendering.source.preparation.bbox_text_strip import build_bbox_text_stripped_pdf_copy
from services.rendering.source.preparation.bbox_text_strip import strip_bbox_text_rects_from_pdf_copy
from services.rendering.source.preparation.redact_restore_formula import build_redact_restore_formula_pdf_copy
from services.rendering.source.preparation.bbox_text_strip_pdf_math import IDENTITY_MATRIX
from services.rendering.source.preparation.bbox_text_strip_text_ops import TextState
from services.rendering.source.preparation.bbox_text_strip_text_ops import estimated_text_rect
from services.rendering.source.preparation.bbox_text_strip_text_ops import estimated_user_text_geometry
from services.rendering.source.preparation.bbox_text_strip_text_ops import text_advance_tx


def test_bbox_text_strip_removes_text_inside_bbox_without_redaction_bloat() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "inside text", fontsize=12)
        page.insert_text((20, 140), "outside text", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "bbox": [10.0, 20.0, 140.0, 55.0],
                        "protected_translated_text": "译文",
                    }
                ]
            },
        )

        assert result.changed is True
        assert result.text_show_ops_removed >= 1

        stripped = fitz.open(output_pdf)
        try:
            text = stripped[0].get_text()
        finally:
            stripped.close()
        assert "inside text" not in text
        assert "outside text" in text


def test_bbox_text_strip_accepts_untranslated_template_source_text() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "inside source", fontsize=12)
        page.insert_text((20, 140), "outside source", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "bbox": [10.0, 20.0, 140.0, 55.0],
                        "protected_source_text": "inside source",
                        "protected_translated_text": "",
                    }
                ]
            },
        )

        assert result.changed is True
        stripped = fitz.open(output_pdf)
        try:
            text = stripped[0].get_text()
        finally:
            stripped.close()
        assert "inside source" not in text
        assert "outside source" in text


def test_bbox_text_strip_skips_large_background_image_page_before_deletion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
        page.insert_text((20, 40), "inside source", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "bbox": [10.0, 20.0, 140.0, 55.0],
                        "protected_source_text": "inside source",
                        "protected_translated_text": "译文",
                    }
                ]
            },
        )

        assert result.changed is False
        assert result.changed_page_indices == frozenset()
        assert result.skipped_visual_background_page_indices == frozenset({0})
        assert output_pdf.exists() is False


def test_bbox_text_strip_skips_page_when_text_bbox_overlaps_vector_line() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "inside text", fontsize=12)
        page.draw_line((12, 45), (150, 45), color=(0, 0, 0), width=1)
        doc.save(source_pdf)
        doc.close()

        result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "bbox": [10.0, 20.0, 160.0, 60.0],
                        "protected_translated_text": "译文",
                    }
                ]
            },
        )

        assert result.changed is False
        assert output_pdf.exists() is False
        assert result.skipped_complex_page_indices == frozenset({0})


def test_bbox_text_strip_allows_toc_leader_vector_overlap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=260, height=180)
        page.insert_text((20, 50), "1.1 Introduction", fontsize=12)
        page.draw_line((120, 47), (210, 47), color=(0, 0, 0), width=0.5)
        page.insert_text((220, 50), "2", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "layout_role": "toc",
                        "semantic_role": "table_of_contents",
                        "structure_role": "table_of_contents",
                        "normalized_sub_type": "table_of_contents",
                        "bbox": [15.0, 30.0, 235.0, 60.0],
                        "protected_translated_text": "1.1 引言 ..... 2",
                    }
                ]
            },
        )

        assert result.changed is True
        assert result.skipped_complex_page_indices == frozenset()

        stripped = fitz.open(output_pdf)
        try:
            text = stripped[0].get_text()
            drawings = stripped[0].get_drawings()
        finally:
            stripped.close()
        assert "Introduction" not in text
        assert drawings


def test_bbox_text_strip_keeps_fast_path_when_vector_line_is_outside_text_bbox() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 40), "inside text", fontsize=12)
        page.draw_line((12, 120), (150, 120), color=(0, 0, 0), width=1)
        doc.save(source_pdf)
        doc.close()

        result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "bbox": [10.0, 20.0, 160.0, 60.0],
                        "protected_translated_text": "译文",
                    }
                ]
            },
        )

        assert result.changed is True
        assert result.skipped_complex_page_indices == frozenset()

        stripped = fitz.open(output_pdf)
        try:
            text = stripped[0].get_text()
        finally:
            stripped.close()
        assert "inside text" not in text


def test_bbox_text_strip_skips_formula_pages() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=240, height=180)
        page.insert_text((30, 50), "body text", fontsize=12)
        page.insert_text((80, 90), "I/I0 = A1 + A2", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        result = build_bbox_text_stripped_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "bbox": [20.0, 30.0, 130.0, 65.0],
                        "protected_translated_text": "正文",
                    },
                    {
                        "block_kind": "formula",
                        "bbox": [70.0, 70.0, 190.0, 105.0],
                        "protected_translated_text": "",
                    },
                ]
            },
        )

        assert result.changed is False
        assert output_pdf.exists() is False
        assert result.skipped_complex_page_indices == frozenset({0})


def test_redact_restore_formula_wrapper_only_marks_changed_pages_precleaned() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "redact-restore.pdf"
        doc = fitz.open()
        page = doc.new_page(width=240, height=180)
        page.insert_text((30, 50), "body text", fontsize=12)
        page.insert_text((80, 90), "I/I0 = A1 + A2", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        result = build_redact_restore_formula_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            translated_pages={
                0: [
                    {
                        "block_kind": "text",
                        "block_type": "text",
                        "bbox": [20.0, 30.0, 150.0, 65.0],
                        "protected_translated_text": "正文",
                    },
                    {
                        "block_kind": "formula",
                        "block_type": "formula",
                        "bbox": [70.0, 70.0, 200.0, 105.0],
                        "protected_translated_text": "",
                    },
                ]
            },
        )

        assert result.changed is True
        assert result.redaction_rects == 1
        assert result.formula_rects_restored == 0
        restored = fitz.open(output_pdf)
        try:
            text = restored[0].get_text()
        finally:
            restored.close()
        assert "body text" not in text
        assert "I/I0 = A1 + A2" in text


def test_strip_bbox_text_rects_from_pdf_copy_removes_text_without_translated_pages() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        page = doc.new_page(width=240, height=180)
        page.insert_text((30, 50), "remove me", fontsize=12)
        page.insert_text((30, 100), "keep me", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        result = strip_bbox_text_rects_from_pdf_copy(
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            page_rects={0: [fitz.Rect(20.0, 115.0, 120.0, 150.0)]},
        )

        assert result.changed is True
        stripped = fitz.open(output_pdf)
        try:
            text = stripped[0].get_text()
        finally:
            stripped.close()
        assert "remove me" not in text
        assert "keep me" in text


def test_bbox_text_strip_single_worker_preserves_form_recursion(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "stripped.pdf"
        doc = fitz.open()
        for _index in range(85):
            page = doc.new_page(width=240, height=180)
            page.insert_text((30, 50), "remove me", fontsize=12)
        doc.save(source_pdf)
        doc.close()

        monkeypatch.setenv("RETAIN_BBOX_TEXT_STRIP_WORKERS", "1")
        monkeypatch.setattr(bbox_text_strip_document, "BBOX_TEXT_STRIP_PARALLEL_PAGE_THRESHOLD", 1)
        seen_recurse_forms: list[bool] = []

        def fake_strip_page(
            *,
            pdf: pikepdf.Pdf,
            page_idx: int,
            rects: list[fitz.Rect],
            protected_rects: list[fitz.Rect],
            recurse_forms: bool,
        ):
            seen_recurse_forms.append(recurse_forms)
            return page_idx, b"", 0, 0

        with mock.patch.object(bbox_text_strip_document, "_strip_page_in_open_pdf", side_effect=fake_strip_page):
            strip_bbox_text_rects_from_pdf_copy(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                page_rects={index: [fitz.Rect(20.0, 35.0, 120.0, 65.0)] for index in range(85)},
                recurse_forms=True,
            )

    assert seen_recurse_forms
    assert set(seen_recurse_forms) == {True}


def test_bbox_text_strip_parallel_worker_count_scales_for_medium_documents() -> None:
    assert bbox_text_strip_document._parallel_worker_count(30) >= 2
    assert bbox_text_strip_document._parallel_worker_count(500) <= bbox_text_strip_document.BBOX_TEXT_STRIP_PARALLEL_MAX_WORKERS


def test_text_state_advance_uses_font_size_spacing_and_tj_adjustments() -> None:
    state = TextState(font_size=12.0, char_spacing=1.0, word_spacing=3.0)

    plain = text_advance_tx(IDENTITY_MATRIX, ["hello"], text_state=state)
    with_space = text_advance_tx(IDENTITY_MATRIX, ["a b"], text_state=state)
    with_tj_pull = text_advance_tx(IDENTITY_MATRIX, [pikepdf.Array(["a", -120, "b"])], text_state=state)

    assert plain == pytest.approx(35.0)
    assert with_space == pytest.approx(24.0)
    assert with_tj_pull > text_advance_tx(IDENTITY_MATRIX, ["ab"], text_state=state)


def test_estimated_text_rect_uses_font_size_from_text_state() -> None:
    state = TextState(font_size=12.0)
    _point, rect = estimated_user_text_geometry(
        IDENTITY_MATRIX,
        (1, 0, 0, 1, 20, 40),
        state,
        text_length=4,
    )

    assert rect[0] == pytest.approx(20.0)
    assert rect[1] < 40.0
    assert rect[2] >= 44.0
    assert rect[3] > 50.0
