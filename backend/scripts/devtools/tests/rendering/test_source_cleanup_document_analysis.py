from __future__ import annotations

import sys
import tempfile
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from devtools.tests.rendering_support.prewarm_fixtures import translated_page_payload
from devtools.tests.rendering_support.prewarm_fixtures import write_source_pdf
from services.rendering.analysis.document.builder import build_render_page_analysis
from services.rendering.analysis.document.models import RenderDocumentAnalysis
from devtools.tests.rendering_support.page_profiles import sample_render_page_profile
from services.rendering.source_cleanup.planning.planner import plan_source_cleanup


def test_source_cleanup_uses_document_analysis_to_skip_visual_pages() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source_pdf = Path(tmp) / "source.pdf"
        write_source_pdf(source_pdf)
        page_analysis = build_render_page_analysis(sample_render_page_profile("pseudo_editable_scan"))

        candidates = plan_source_cleanup(
            source_pdf_path=source_pdf,
            translated_pages=translated_page_payload(),
            document_analysis=RenderDocumentAnalysis(pages={0: page_analysis}),
        )

    assert candidates.page_rects == {}
    assert candidates.pages_skipped_visual_background == 1
    assert candidates.skipped_visual_background_page_indices == frozenset({0})
