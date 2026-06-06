import sys
import tempfile
from pathlib import Path
from unittest import mock

import fitz


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from runtime.pipeline.render_plan import RenderPlan
from runtime.pipeline.render_inputs import RenderInputs
from foundation.config import layout
from services.rendering.source.prewarm import RenderPrewarmSpec
from services.rendering.source.prewarm import PAYLOAD_RENDER_ALGORITHM_VERSION
from services.rendering.source.prewarm import build_render_prewarm_fingerprint
from services.rendering.source.prewarm import prewarm_manifest_path_from_artifacts_dir
from services.rendering.source.prewarm import start_render_source_prewarm
from services.rendering.source.prewarm import try_load_render_payload_prewarm
from services.rendering.source.prewarm import try_load_prewarmed_render_source_pdf
from services.rendering.source.prewarm import _pages_for_prewarm_mode_probe
from services.rendering.workflow.executor import execute_render_plan
from runtime.pipeline.render_preprocess import run_ocr_render_preprocess


def _source_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "inside source", fontsize=12)
    doc.save(path)
    doc.close()


def _pseudo_editable_scan_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
    pix.clear_with(255)
    page.insert_image(page.rect, pixmap=pix)
    page.insert_textbox(
        fitz.Rect(10, 20, 150, 60),
        "inside source",
        fontsize=12,
    )
    doc.save(path)
    doc.close()


def _document_v1(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "schema": "normalized_document_v1",
  "schema_version": "1.1",
  "document_id": "test-doc",
  "source": {"provider": "test"},
  "page_count": 1,
  "derived": {},
  "markers": {},
  "pages": [
    {
      "page_index": 0,
      "page": 1,
      "width": 200,
      "height": 200,
      "unit": "pt",
      "blocks": [
        {
          "block_id": "p001-b001",
          "page_index": 0,
          "order": 0,
          "type": "text",
          "sub_type": "text",
          "bbox": [10.0, 20.0, 150.0, 60.0],
          "text": "inside source",
          "geometry": {"bbox": [10.0, 20.0, 150.0, 60.0]},
          "content": {"kind": "text", "text": "inside source", "text_flow": "flow"},
          "layout_role": "paragraph",
          "semantic_role": "body",
          "structure_role": "body",
          "policy": {"translate": true, "translate_reason": "test"},
          "provenance": {
            "provider": "test",
            "raw_label": "text",
            "raw_sub_type": "text",
            "raw_bbox": [10.0, 20.0, 150.0, 60.0],
            "raw_path": "$.pages[0].blocks[0]"
          },
          "continuation_hint": {
            "source": "",
            "group_id": "",
            "role": "single",
            "scope": "",
            "reading_order": 0,
            "confidence": 0.0
          },
          "metadata": {},
          "source": {"provider": "test", "raw_type": "text"},
          "lines": []
        }
      ]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )


def _page_payload() -> dict[int, list[dict]]:
    return {
        0: [
            {
                "item_id": "p001-b001",
                "page_idx": 0,
                "block_kind": "text",
                "block_type": "text",
                "layout_role": "paragraph",
                "semantic_role": "body",
                "structure_role": "body",
                "policy_translate": True,
                "bbox": [10.0, 20.0, 150.0, 60.0],
                "protected_source_text": "inside source",
                "protected_translated_text": "",
            }
        ]
    }


def _translated_page_payload() -> dict[int, list[dict]]:
    pages = _page_payload()
    pages[0][0]["protected_translated_text"] = "内部来源"
    return pages


def _empty_region_page_payload() -> dict[int, list[dict]]:
    return {
        0: [
            {
                "item_id": "p001-b001",
                "page_idx": 0,
                "block_kind": "text",
                "block_type": "text",
                "layout_role": "paragraph",
                "semantic_role": "body",
                "structure_role": "body",
                "policy_translate": True,
                "bbox": [10.0, 120.0, 150.0, 170.0],
                "protected_source_text": "source outside",
                "protected_translated_text": "无重叠区域",
            }
        ]
    }


def _tight_gap_page_payload() -> dict[int, list[dict]]:
    return {
        0: [
            {
                "item_id": "p001-b001",
                "page_idx": 0,
                "block_kind": "text",
                "block_type": "text",
                "layout_role": "paragraph",
                "semantic_role": "body",
                "structure_role": "body",
                "bbox": [10.0, 20.0, 170.0, 70.0],
                "source_text": (
                    "This body paragraph has enough source text to be treated as body text "
                    "and it contains more than forty compact characters."
                ),
                "protected_source_text": (
                    "This body paragraph has enough source text to be treated as body text "
                    "and it contains more than forty compact characters."
                ),
                "protected_translated_text": "这是一个正文段落，用于触发预热阶段的紧邻 bbox 几何分析。",
            },
            {
                "item_id": "p001-b002",
                "page_idx": 0,
                "block_kind": "text",
                "block_type": "text",
                "layout_role": "paragraph",
                "semantic_role": "body",
                "structure_role": "body",
                "bbox": [10.0, 70.6, 170.0, 122.0],
                "source_text": (
                    "This second body paragraph follows closely in the same column and also "
                    "contains enough compact characters for body detection."
                ),
                "protected_source_text": (
                    "This second body paragraph follows closely in the same column and also "
                    "contains enough compact characters for body detection."
                ),
                "protected_translated_text": "这是同一栏的下一段正文，用于提供紧邻边界。",
            },
        ]
    }


def test_render_source_prewarm_manifest_is_reused_without_temp_cleanup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        translations_dir = root / "translated"
        output_pdf.parent.mkdir()
        translations_dir.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="bbox_text_strip",
            )
        )
        manifest_path = handle.wait()
        assert manifest_path == prewarm_manifest_path_from_artifacts_dir(artifacts_dir)
        assert manifest_path.exists()

        render_plan = RenderPlan(
            render_inputs=RenderInputs(
                source_pdf_path=source_pdf,
                translations_dir=translations_dir,
                translation_manifest_path=None,
            ),
            selected_pages=_translated_page_payload(),
            effective_render_mode="overlay",
        )

        def _fake_overlay(*, source_pdf_path, translated_pages, context):
            assert artifacts_dir in source_pdf_path.parents
            assert source_pdf_path.exists()
            return 1, {"route": "prewarm-test"}

        with mock.patch(
            "services.rendering.workflow.executor.build_render_source_pdf",
            side_effect=AssertionError("synchronous render source prep should not run"),
        ), mock.patch(
            "services.rendering.workflow.executor.run_overlay_render",
            side_effect=_fake_overlay,
        ):
            pages = execute_render_plan(
                render_plan=render_plan,
                output_pdf_path=output_pdf,
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="bbox_text_strip",
                render_prewarm_manifest_path=manifest_path,
            )

        assert pages == 1
        assert any(path.name.endswith(".source-bbox-text-stripped.pdf") for path in artifacts_dir.rglob("*.pdf"))


def test_render_plan_persists_sync_source_prewarm_for_next_render() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        translations_dir = root / "translated"
        output_pdf.parent.mkdir()
        translations_dir.mkdir()
        _source_pdf(source_pdf)
        manifest_path = prewarm_manifest_path_from_artifacts_dir(artifacts_dir)
        render_plan = RenderPlan(
            render_inputs=RenderInputs(
                source_pdf_path=source_pdf,
                translations_dir=translations_dir,
                translation_manifest_path=None,
            ),
            selected_pages=_translated_page_payload(),
            effective_render_mode="overlay",
        )

        def _fake_overlay(*, source_pdf_path, translated_pages, context):
            assert source_pdf_path.exists()
            return 1, {"route": "sync-cache-test"}

        with mock.patch(
            "services.rendering.workflow.executor.run_overlay_render",
            side_effect=_fake_overlay,
        ):
            pages = execute_render_plan(
                render_plan=render_plan,
                output_pdf_path=output_pdf,
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="bbox_text_strip",
                render_prewarm_manifest_path=manifest_path,
            )

        assert pages == 1
        assert manifest_path.exists()
        assert any(path.name.endswith(".source-bbox-text-stripped.pdf") for path in artifacts_dir.rglob("*.pdf"))

        with mock.patch(
            "services.rendering.workflow.executor.build_render_source_pdf",
            side_effect=AssertionError("persisted sync render source should be reused"),
        ), mock.patch(
            "services.rendering.workflow.executor.run_overlay_render",
            side_effect=_fake_overlay,
        ):
            pages = execute_render_plan(
                render_plan=render_plan,
                output_pdf_path=output_pdf,
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="bbox_text_strip",
                render_prewarm_manifest_path=manifest_path,
            )

        assert pages == 1


def test_ocr_render_preprocess_manifest_matches_translated_payload() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        source_json = root / "ocr" / "normalized" / "document.v1.json"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)
        _document_v1(source_json)

        manifest_path = run_ocr_render_preprocess(
            source_json_path=source_json,
            source_pdf_path=source_pdf,
            output_pdf_path=output_pdf,
            artifacts_dir=artifacts_dir,
            render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="bbox_text_strip",
            math_mode="direct_typst",
        )

        translated_payload = _translated_page_payload()
        translated_payload[0][0]["item_id"] = "p001-b000"
        translated_payload[0][0]["translation_unit_id"] = "p001-b000"
        translated_payload[0][0]["translation_unit_member_ids"] = ["p001-b000"]
        translated_payload[0][0]["raw_block_type"] = "text"
        translated_payload[0][0]["normalized_sub_type"] = "text"

        assert manifest_path == prewarm_manifest_path_from_artifacts_dir(artifacts_dir)
        prepared = try_load_prewarmed_render_source_pdf(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=translated_payload,
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="bbox_text_strip",
        )
        assert prepared is not None
        assert prepared.path.exists()


def test_prewarm_mode_probe_uses_source_text_without_mutating_payload() -> None:
    pages = _page_payload()
    assert pages[0][0].get("render_protected_text") is None

    probed = _pages_for_prewarm_mode_probe(pages)

    assert probed[0][0]["render_protected_text"] == "inside source"
    assert pages[0][0].get("render_protected_text") is None


def test_second_prewarm_reuses_existing_source_and_refreshes_payload() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        first_handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="bbox_text_strip",
            )
        )
        manifest_path = first_handle.wait()

        with mock.patch(
            "services.rendering.source.prewarm.build_render_source_pdf",
            side_effect=AssertionError("existing prewarmed source should be reused"),
        ):
            second_handle = start_render_source_prewarm(
                RenderPrewarmSpec(
                    source_pdf_path=source_pdf,
                    output_pdf_path=output_pdf,
                    artifacts_dir=artifacts_dir,
                    translated_pages=_translated_page_payload(),
                    render_mode="overlay",
                    start_page=0,
                    end_page=0,
                    pdf_compress_dpi=0,
                    source_cleanup_strategy="bbox_text_strip",
                )
            )
            assert second_handle.wait() == manifest_path

        payload_prewarm = try_load_render_payload_prewarm(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="bbox_text_strip",
        )
        assert payload_prewarm is not None
        assert payload_prewarm.render_colors_by_item_id


def test_payload_prewarm_manifest_exposes_bbox_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="bbox_text_strip",
            )
        )
        manifest_path = handle.wait()

        payload_prewarm = try_load_render_payload_prewarm(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="bbox_text_strip",
        )

        assert payload_prewarm is not None
        assert payload_prewarm.bbox_text_strip_candidates is not None
        assert payload_prewarm.bbox_text_strip_candidates.page_rects


def test_payload_prewarm_pikepdf_text_strip_exposes_bbox_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="pikepdf_text_strip",
            )
        )
        manifest_path = handle.wait()

        payload_prewarm = try_load_render_payload_prewarm(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="pikepdf_text_strip",
        )

        assert payload_prewarm is not None
        assert payload_prewarm.bbox_text_strip_candidates is not None
        assert payload_prewarm.bbox_text_strip_candidates.page_rects


def test_render_source_prewarm_keeps_no_text_overlap_pages_as_precleaned() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_empty_region_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="bbox_text_strip",
            )
        )
        manifest_path = handle.wait()

        prepared = try_load_prewarmed_render_source_pdf(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_empty_region_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="bbox_text_strip",
        )

        assert prepared is not None
        assert prepared.bbox_text_stripped_page_indices == frozenset()
        assert prepared.bbox_text_strip_skipped_page_indices == frozenset({0})
        assert prepared.source_text_precleaned_page_indices == frozenset()


def test_pseudo_editable_scan_pages_keep_cover_fallback_after_text_strip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _pseudo_editable_scan_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="pikepdf_text_strip",
            )
        )
        manifest_path = handle.wait()

        prepared = try_load_prewarmed_render_source_pdf(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="pikepdf_text_strip",
        )

        assert prepared is not None
        assert prepared.bbox_text_stripped_page_indices == frozenset()
        assert prepared.bbox_text_strip_skipped_page_indices == frozenset({0})
        assert prepared.source_text_precleaned_page_indices == frozenset()


def test_payload_prewarm_default_pikepdf_text_strip_exposes_bbox_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
            )
        )
        manifest_path = handle.wait()

        payload_prewarm = try_load_render_payload_prewarm(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
        )

        assert payload_prewarm is not None
        assert payload_prewarm.bbox_text_strip_candidates is not None
        assert payload_prewarm.bbox_text_strip_candidates.page_rects


def test_render_prewarm_fingerprint_tracks_payload_render_algorithm() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        _source_pdf(source_pdf)

        fingerprint = build_render_prewarm_fingerprint(
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
        )

    assert fingerprint["payload_render_algorithm"] == PAYLOAD_RENDER_ALGORITHM_VERSION


def test_payload_prewarm_exposes_background_render_page_specs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="typst_visual",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
            )
        )
        manifest_path = handle.wait()

        payload_prewarm = try_load_render_payload_prewarm(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="typst_visual",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
        )

        assert payload_prewarm is not None
        assert payload_prewarm.background_render_page_specs is not None
        assert len(payload_prewarm.background_render_page_specs) == 1
        assert payload_prewarm.background_render_page_specs[0].blocks[0].plain_text


def test_execute_typst_visual_uses_prewarmed_background_page_specs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        translations_dir = root / "translated"
        output_pdf.parent.mkdir()
        translations_dir.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="typst_visual",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
            )
        )
        manifest_path = handle.wait()
        render_plan = RenderPlan(
            render_inputs=RenderInputs(
                source_pdf_path=source_pdf,
                translations_dir=translations_dir,
                translation_manifest_path=None,
            ),
            selected_pages=_translated_page_payload(),
            effective_render_mode="typst_visual",
        )

        def _fake_background(*, source_pdf_path, translated_pages, context, visual_only_background):
            assert visual_only_background is True
            assert context.background_render_page_specs is not None
            assert context.background_render_page_specs[0].blocks[0].plain_text
            return 1, {"route": "prewarmed-background-specs"}

        with mock.patch(
            "services.rendering.workflow.executor.run_background_typst_render",
            side_effect=_fake_background,
        ):
            pages = execute_render_plan(
                render_plan=render_plan,
                output_pdf_path=output_pdf,
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="pikepdf_text_strip",
                render_prewarm_manifest_path=manifest_path,
            )

        assert pages == 1


def test_redact_restore_formula_strategy_is_runtime_alias_for_pikepdf_text_strip() -> None:
    assert layout.normalize_source_cleanup_strategy("redact_restore_formulas") == "pikepdf_text_strip"
    assert layout.use_bbox_text_strip_cleanup("redact_restore_formulas") is True
    assert layout.use_redact_restore_formula_cleanup("redact_restore_formulas") is False


def test_payload_prewarm_explicit_typst_fill_skips_bbox_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_translated_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
                source_cleanup_strategy="typst_fill",
            )
        )
        manifest_path = handle.wait()

        payload_prewarm = try_load_render_payload_prewarm(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_translated_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
            source_cleanup_strategy="typst_fill",
        )

        assert payload_prewarm is not None
        assert payload_prewarm.bbox_text_strip_candidates is None


def test_payload_prewarm_manifest_exposes_geometry_adjustments() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_pdf = root / "source.pdf"
        output_pdf = root / "rendered" / "out.pdf"
        artifacts_dir = root / "artifacts"
        output_pdf.parent.mkdir()
        _source_pdf(source_pdf)

        handle = start_render_source_prewarm(
            RenderPrewarmSpec(
                source_pdf_path=source_pdf,
                output_pdf_path=output_pdf,
                artifacts_dir=artifacts_dir,
                translated_pages=_tight_gap_page_payload(),
                render_mode="overlay",
                start_page=0,
                end_page=0,
                pdf_compress_dpi=0,
            )
        )
        manifest_path = handle.wait()

        payload_prewarm = try_load_render_payload_prewarm(
            manifest_path=manifest_path,
            source_pdf_path=source_pdf,
            translated_pages=_tight_gap_page_payload(),
            effective_render_mode="overlay",
            start_page=0,
            end_page=0,
            pdf_compress_dpi=0,
        )

        assert payload_prewarm is not None
        adjusted = payload_prewarm.effective_inner_bbox_lookup["p001-b001"]
        assert adjusted[1] > 20.0
        assert adjusted[3] < 70.0
