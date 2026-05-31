import json
import subprocess
import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = REPO_SCRIPTS_ROOT.parent
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))

from services.document_schema import adapt_path_to_document_v1_with_report
from services.document_schema.provider_adapters.paddle import looks_like_paddle_layout
from services.document_schema.provider_adapters.paddle.column_signals import (
    analyze_page_column_signals,
)
from services.document_schema.provider_adapters.paddle.body_repair import repair_body_cross_column_blocks
from services.document_schema.provider_adapters.paddle.content_extract import build_lines
from services.document_schema.provider_adapters.paddle.page_reader import build_page_spec
from services.document_schema.provider_adapters.paddle.adapter import build_paddle_document
from services.document_schema.provider_adapters.paddle.relations import classify_page_blocks
from services.translation.core.ocr.json_extractor import extract_text_items
from foundation.shared.job_dirs import ensure_job_dirs
from foundation.shared.job_dirs import resolve_job_dirs


PADDLE_FIXTURE_JSON = REPO_ROOT / "rust_api" / "src" / "ocr_provider" / "paddle" / "json_full.json"
PADDLE_SCI_FIXTURE_JSON = REPO_ROOT / "rust_api" / "src" / "ocr_provider" / "paddle" / "json_sci.json"
PADDLE_FIXTURE_PDF = REPO_ROOT / "rust_api" / "src" / "ocr_provider" / "paddle" / "paddle_ocr_json_split.pdf"
NORMALIZE_ENTRYPOINT = REPO_SCRIPTS_ROOT / "entrypoints" / "run_normalize_ocr.py"

def test_paddle_build_lines_splits_tall_body_block_into_pseudo_lines() -> None:
    bbox = [53.48, 640.259, 292.39, 699.736]
    text = (
        "Theoretical studies of the effects of substituents on absorption and emission spectra have "
        "been performed, including studies on the indigo molecule and related compounds."
    )

    lines = build_lines(
        bbox=bbox,
        segments=[],
        text=text,
        raw_label="text",
        block_type="text",
        sub_type="body",
    )

    assert len(lines) >= 3
    assert all(len(line.get("bbox", [])) == 4 for line in lines)
    assert all(line["spans"] for line in lines)
    assert "Theoretical studies" in lines[0]["spans"][0]["text"]
