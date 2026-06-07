from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from devtools import check_pipeline_architecture


def test_pipeline_architecture_contract_passes() -> None:
    assert check_pipeline_architecture.main() == 0


def test_pipeline_architecture_rejects_removed_bbox_preparation_import(tmp_path: Path) -> None:
    rendering_root = tmp_path / "services" / "rendering"
    source_root = rendering_root / "source"
    source_root.mkdir(parents=True)
    offender = source_root / "bad_import.py"
    offender.write_text(
        "from services.rendering.source.preparation.bbox_text_strip_engine import run\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    with (
        mock.patch.object(check_pipeline_architecture, "RENDERING_ROOT", rendering_root),
        mock.patch.object(check_pipeline_architecture, "RENDERING_SOURCE_ROOT", source_root),
        mock.patch.object(
            check_pipeline_architecture,
            "RENDERING_SOURCE_CLEANUP_ROOT",
            rendering_root / "source_cleanup",
        ),
        mock.patch.object(
            check_pipeline_architecture,
            "RENDERING_PROFILE_ROOT",
            rendering_root / "analysis" / "profile",
        ),
        mock.patch.object(
            check_pipeline_architecture,
            "RENDERING_ROUTE_ROOT",
            rendering_root / "analysis" / "route",
        ),
        mock.patch.object(
            check_pipeline_architecture,
            "RENDERING_TYPST_ROOT",
            rendering_root / "output" / "typst",
        ),
        mock.patch.object(
            check_pipeline_architecture,
            "RENDERING_LAYOUT_ROOT",
            rendering_root / "layout",
        ),
        mock.patch.object(check_pipeline_architecture, "SCRIPTS_ROOT", tmp_path),
    ):
        check_pipeline_architecture.check_rendering_internal_boundaries(errors)

    assert any("removed bbox source-preparation module" in item for item in errors)
