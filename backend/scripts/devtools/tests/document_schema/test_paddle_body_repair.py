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

def test_paddle_page_spec_repairs_first_empty_right_slot_from_left_carryover() -> None:
    page_spec = build_page_spec(
        page_payload={
            "prunedResult": {
                "width": 1191,
                "height": 1600,
                "model_settings": {"enable_body_repair": True},
                "parsing_res_list": [
                    {
                        "block_label": "text",
                        "block_content": "left intro text",
                        "block_bbox": [106, 895, 584, 943],
                    },
                    {
                        "block_label": "text",
                        "block_content": "left middle text",
                        "block_bbox": [106, 944, 585, 1087],
                    },
                    {
                        "block_label": "text",
                        "block_content": (
                            "Differences were found between Thioindigo and Indigo and the donor paragraph keeps "
                            "running into the next column because the sentence is still open and ends with"
                        ),
                        "block_bbox": [105, 1255, 586, 1473],
                    },
                    {
                        "block_label": "text",
                        "block_content": "",
                        "block_bbox": [603, 895, 1082, 967],
                    },
                    {
                        "block_label": "text",
                        "block_content": "For Dichloroindigo the next right column paragraph starts here.",
                        "block_bbox": [603, 968, 1083, 1111],
                    },
                    {
                        "block_label": "text",
                        "block_content": "Another right column paragraph remains intact.",
                        "block_bbox": [602, 1112, 1083, 1422],
                    },
                ],
                "layout_det_res": {"boxes": []},
            },
            "markdown": {"text": "", "images": {}},
            "outputImages": {},
            "inputImage": "",
        },
        page_index=0,
        page_meta={"width": 1191, "height": 1600},
        preprocessed_image="",
    )

    blocks = page_spec["blocks"]
    donor = blocks[2]
    slot = blocks[3]

    assert donor["metadata"]["provider_body_repair_applied"] is True
    assert donor["metadata"]["provider_body_repair_strategy"] == "column_carryover"
    assert slot["metadata"]["provider_body_repair_applied"] is True
    assert slot["metadata"]["provider_body_repair_strategy"] == "column_carryover"
    assert donor["metadata"]["body_repair_applied"] is True
    assert donor["metadata"]["body_repair_strategy"] == "column_carryover"
    assert slot["metadata"]["body_repair_applied"] is True
    assert slot["metadata"]["body_repair_strategy"] == "column_carryover"
    assert donor["text"] != ""
    assert slot["text"] != ""
    assert page_spec["metadata"]["body_repair_pair_count"] == 1


def test_paddle_page_spec_skips_body_repair_when_merge_layout_blocks_is_disabled() -> None:
    page_spec = build_page_spec(
        page_payload={
            "prunedResult": {
                "width": 1191,
                "height": 1600,
                "model_settings": {
                    "merge_layout_blocks": False,
                },
                "parsing_res_list": [
                    {
                        "block_label": "text",
                        "block_content": "left intro text",
                        "block_bbox": [106, 895, 584, 943],
                    },
                    {
                        "block_label": "text",
                        "block_content": "left middle text",
                        "block_bbox": [106, 944, 585, 1087],
                    },
                    {
                        "block_label": "text",
                        "block_content": (
                            "Differences were found between Thioindigo and Indigo and the donor paragraph keeps "
                            "running into the next column because the sentence is still open and ends with"
                        ),
                        "block_bbox": [105, 1255, 586, 1473],
                    },
                    {
                        "block_label": "text",
                        "block_content": "",
                        "block_bbox": [603, 895, 1082, 967],
                    },
                    {
                        "block_label": "text",
                        "block_content": "For Dichloroindigo the next right column paragraph starts here.",
                        "block_bbox": [603, 968, 1083, 1111],
                    },
                    {
                        "block_label": "text",
                        "block_content": "Another right column paragraph remains intact.",
                        "block_bbox": [602, 1112, 1083, 1422],
                    },
                ],
                "layout_det_res": {"boxes": []},
            },
            "markdown": {"text": "", "images": {}},
            "outputImages": {},
            "inputImage": "",
        },
        page_index=0,
        page_meta={"width": 1191, "height": 1600},
        preprocessed_image="",
    )

    assert page_spec["metadata"]["body_repair_pair_count"] == 0
    assert page_spec["metadata"]["body_repair_block_count"] == 0
    assert page_spec["metadata"]["body_repair_pairs"] == []
    assert page_spec["blocks"][2]["text"].endswith("ends with")
    assert page_spec["blocks"][3]["text"] == ""


def test_paddle_page_spec_prefers_last_left_body_for_first_right_empty_slot() -> None:
    page_spec = build_page_spec(
        page_payload={
            "prunedResult": {
                "width": 1191,
                "height": 1600,
                "model_settings": {"enable_body_repair": True},
                "parsing_res_list": [
                    {
                        "block_label": "text",
                        "block_content": "left support text",
                        "block_bbox": [120, 761, 833, 789],
                    },
                    {
                        "block_label": "text",
                        "block_content": (
                            "Substituent effects on molecules have always been a subject of study because it is our goal "
                            "to modify molecules based on our needs. A way in which to study this phenomenon is to analyze "
                            "the effects of substituents on the spectra of molecules. Solvent [1], substituent [2] and "
                            "synthesis effects [3], as well as combinations of these effects [4], have been shown."
                        ),
                        "block_bbox": [106, 847, 585, 1016],
                    },
                    {
                        "block_label": "text",
                        "block_content": (
                            "Theoretical studies of the effects of substituents on absorption and emission spectra [8-16] "
                            "have been performed, including studies on the indigo molecule [17]. The present work attempts "
                            "to explain, perhaps vaguely but completely based on the obtained results, the effects observed "
                            "when the absorption and emission spectra of indigo are compared."
                        ),
                        "block_bbox": [107, 1209, 585, 1306],
                    },
                    {
                        "block_label": "text",
                        "block_content": "",
                        "block_bbox": [602, 823, 1081, 898],
                    },
                    {
                        "block_label": "paragraph_title",
                        "block_content": "Theory and computational details",
                        "block_bbox": [604, 925, 927, 949],
                    },
                    {
                        "block_label": "text",
                        "block_content": "GAUSSVIEW 03 software was used to generate the molecular structures.",
                        "block_bbox": [602, 950, 1083, 1334],
                    },
                ],
                "layout_det_res": {"boxes": []},
            },
            "markdown": {"text": "", "images": {}},
            "outputImages": {},
            "inputImage": "",
        },
        page_index=0,
        page_meta={"width": 1191, "height": 1600},
        preprocessed_image="",
    )

    blocks = page_spec["blocks"]
    left_middle = blocks[1]
    donor = blocks[2]
    slot = blocks[3]

    assert left_middle["text"].endswith("have been shown.")
    assert donor["metadata"]["provider_body_repair_applied"] is True
    assert donor["metadata"]["provider_body_repair_strategy"] == "column_carryover"
    assert donor["metadata"]["provider_suspected_peer_block_id"] == "p001-b0003"
    assert slot["metadata"]["provider_body_repair_applied"] is True
    assert slot["metadata"]["provider_body_repair_strategy"] == "column_carryover"
    assert donor["metadata"]["body_repair_applied"] is True
    assert donor["metadata"]["body_repair_strategy"] == "column_carryover"
    assert donor["metadata"]["body_repair_peer_block_id"] == "p001-b0003"
    assert slot["metadata"]["body_repair_applied"] is True
    assert slot["metadata"]["body_repair_strategy"] == "column_carryover"
    assert "but completely based on the obtained results" in slot["text"]


def test_paddle_document_suppresses_provider_continuation_after_body_repair() -> None:
    payload = {
        "dataInfo": {"pages": [{"width": 1191, "height": 1600}]},
        "layoutParsingResults": [
            {
                "prunedResult": {
                    "width": 1191,
                    "height": 1600,
                    "model_settings": {"enable_body_repair": True},
                    "parsing_res_list": [
                        {
                            "block_label": "text",
                            "block_content": "left support text",
                            "block_bbox": [120, 761, 833, 789],
                            "group_id": 10,
                            "block_order": 10,
                        },
                        {
                            "block_label": "text",
                            "block_content": (
                                "Theoretical studies of the effects of substituents on absorption and emission spectra [8-16] "
                                "have been performed, including studies on the indigo molecule [17]. The present work attempts "
                                "to explain, perhaps vaguely but completely based on the obtained results, the effects observed "
                                "when the absorption and emission spectra of indigo are compared."
                            ),
                            "block_bbox": [107, 1209, 585, 1306],
                            "group_id": 14,
                            "block_order": 13,
                        },
                        {
                            "block_label": "text",
                            "block_content": "",
                            "block_bbox": [602, 823, 1081, 898],
                            "group_id": 14,
                            "block_order": 14,
                        },
                        {
                            "block_label": "text",
                            "block_content": "GAUSSVIEW 03 software was used to generate the molecular structures.",
                            "block_bbox": [602, 950, 1083, 1334],
                            "group_id": 15,
                            "block_order": 15,
                        },
                    ],
                    "layout_det_res": {"boxes": []},
                },
                "markdown": {"text": "", "images": {}},
            }
        ],
        "preprocessedImages": [""],
    }

    document = build_paddle_document(
        payload=payload,
        document_id="paddle-repair-continuation",
        source_json_path=PADDLE_FIXTURE_JSON,
        provider_version="PaddleOCR-VL",
    )
    blocks = document["pages"][0]["blocks"]

    assert blocks[1]["metadata"]["provider_body_repair_applied"] is True
    assert blocks[2]["metadata"]["provider_body_repair_applied"] is True
    assert blocks[1]["metadata"]["body_repair_applied"] is True
    assert blocks[2]["metadata"]["body_repair_applied"] is True
    assert blocks[1]["continuation_hint"]["group_id"] == ""
    assert blocks[2]["continuation_hint"]["group_id"] == ""
    assert blocks[1]["metadata"]["provider_continuation_suppressed"] is True
    assert blocks[1]["metadata"]["provider_continuation_suppressed_reason"] == "body_repair_applied"
    assert blocks[1]["metadata"]["continuation_suppressed"] is True
    assert blocks[1]["metadata"]["continuation_suppressed_reason"] == "body_repair_applied"


def test_paddle_page_spec_keeps_unsafe_split_unrepaired() -> None:
    page_spec = build_page_spec(
        page_payload={
            "prunedResult": {
                "width": 1200,
                "height": 1600,
                "model_settings": {"enable_body_repair": True},
                "parsing_res_list": [
                    {
                        "block_label": "text",
                        "block_content": "left support text",
                        "block_bbox": [100, 100, 360, 160],
                    },
                    {
                        "block_label": "text",
                        "block_content": "ABCDEFGHIJKLMN",
                        "block_bbox": [100, 220, 380, 300],
                    },
                    {
                        "block_label": "text",
                        "block_content": "",
                        "block_bbox": [760, 220, 1040, 300],
                    },
                    {
                        "block_label": "text",
                        "block_content": "right support text",
                        "block_bbox": [760, 360, 1040, 430],
                    },
                    {
                        "block_label": "text",
                        "block_content": "another right support text",
                        "block_bbox": [760, 480, 1040, 550],
                    },
                ],
                "layout_det_res": {"boxes": []},
            },
            "markdown": {"text": "", "images": {}},
            "outputImages": {},
            "inputImage": "",
        },
        page_index=0,
        page_meta={"width": 1200, "height": 1600},
        preprocessed_image="",
    )

    blocks = page_spec["blocks"]
    absorber = blocks[1]["metadata"]
    empty_peer = blocks[2]["metadata"]

    assert blocks[1]["text"] == "ABCDEFGHIJKLMN"
    assert blocks[2]["text"] == ""
    assert absorber["provider_cross_column_merge_suspected"] is True
    assert absorber["provider_peer_block_absorbed_text"] is True
    assert absorber["provider_body_repair_attempted"] is True
    assert absorber["provider_body_repair_applied"] is False
    assert absorber["provider_body_repair_reason"] == "unsafe_split"
    assert absorber["cross_column_merge_suspected"] is True
    assert absorber["peer_block_absorbed_text"] is True
    assert absorber["body_repair_attempted"] is True
    assert absorber["body_repair_applied"] is False
    assert empty_peer["provider_text_missing_but_bbox_present"] is True
    assert empty_peer["provider_body_repair_attempted"] is True
    assert empty_peer["provider_body_repair_applied"] is False
    assert empty_peer["text_missing_but_bbox_present"] is True
    assert empty_peer["body_repair_attempted"] is True
    assert empty_peer["body_repair_applied"] is False


def test_paddle_page_spec_does_not_repair_non_body_blocks() -> None:
    page_spec = build_page_spec(
        page_payload={
            "prunedResult": {
                "width": 1200,
                "height": 1600,
                "parsing_res_list": [
                    {
                        "block_label": "header",
                        "block_content": "left header merged with right",
                        "block_bbox": [100, 60, 360, 100],
                    },
                    {
                        "block_label": "header",
                        "block_content": "",
                        "block_bbox": [760, 60, 1040, 100],
                    },
                    {
                        "block_label": "text",
                        "block_content": "left support text",
                        "block_bbox": [100, 180, 360, 250],
                    },
                    {
                        "block_label": "text",
                        "block_content": "right support text",
                        "block_bbox": [760, 180, 1040, 250],
                    },
                    {
                        "block_label": "text",
                        "block_content": "another right support text",
                        "block_bbox": [760, 320, 1040, 390],
                    },
                ],
                "layout_det_res": {"boxes": []},
            },
            "markdown": {"text": "", "images": {}},
            "outputImages": {},
            "inputImage": "",
        },
        page_index=0,
        page_meta={"width": 1200, "height": 1600},
        preprocessed_image="",
    )

    blocks = page_spec["blocks"]
    assert blocks[0]["text"] == "left header merged with right"
    assert blocks[1]["text"] == ""
    assert blocks[0]["metadata"].get("provider_body_repair_applied") is None
    assert blocks[1]["metadata"].get("provider_body_repair_applied") is None


def test_paddle_body_repair_requires_raw_label_text_even_if_kind_is_body() -> None:
    parsing_res_list = [
        {
            "block_label": "paragraph_title",
            "block_content": "left merged heading from right side",
            "block_bbox": [100, 220, 380, 300],
        },
        {
            "block_label": "paragraph_title",
            "block_content": "",
            "block_bbox": [760, 220, 1040, 300],
        },
        {
            "block_label": "text",
            "block_content": "right support text",
            "block_bbox": [760, 360, 1040, 430],
        },
        {
            "block_label": "text",
            "block_content": "another right support text",
            "block_bbox": [760, 480, 1040, 550],
        },
    ]
    column_signals = analyze_page_column_signals(
        parsing_res_list=parsing_res_list,
        page_width=1200,
    )

    repaired_blocks, repair_metadata, repair_summary = repair_body_cross_column_blocks(
        parsing_res_list=parsing_res_list,
        column_signals=column_signals,
    )

    assert repaired_blocks[0]["block_content"] == "left merged heading from right side"
    assert repaired_blocks[1]["block_content"] == ""
    assert repair_metadata == {}
    assert repair_summary["body_repair_pair_count"] == 0


def test_paddle_body_repair_ignores_tiny_empty_text_slots() -> None:
    parsing_res_list = [
        {
            "block_label": "text",
            "block_content": "A donor sentence that is long enough to tempt a repair but should stay intact.",
            "block_bbox": [107, 1209, 585, 1306],
        },
        {
            "block_label": "text",
            "block_content": "",
            "block_bbox": [617, 1402, 983, 1422],
        },
        {
            "block_label": "text",
            "block_content": "right support text",
            "block_bbox": [603, 968, 1083, 1111],
        },
        {
            "block_label": "text",
            "block_content": "another right support text",
            "block_bbox": [602, 1112, 1083, 1422],
        },
    ]
    column_signals = analyze_page_column_signals(
        parsing_res_list=parsing_res_list,
        page_width=1191,
    )

    repaired_blocks, repair_metadata, repair_summary = repair_body_cross_column_blocks(
        parsing_res_list=parsing_res_list,
        column_signals=column_signals,
    )

    assert repaired_blocks[0]["block_content"].startswith("A donor sentence")
    assert repaired_blocks[1]["block_content"] == ""
    assert repair_metadata == {}
    assert repair_summary["body_repair_pair_count"] == 0


def test_paddle_body_repair_ignores_empty_slot_without_same_column_body_context() -> None:
    parsing_res_list = [
        {
            "block_label": "text",
            "block_content": "A donor sentence that is long enough to tempt a repair across columns and keep running for a while.",
            "block_bbox": [107, 1209, 585, 1306],
        },
        {
            "block_label": "text",
            "block_content": "",
            "block_bbox": [603, 823, 1082, 920],
        },
        {
            "block_label": "text",
            "block_content": "Short badge",
            "block_bbox": [618, 1451, 778, 1469],
        },
        {
            "block_label": "text",
            "block_content": "Submit here",
            "block_bbox": [618, 1469, 855, 1486],
        },
    ]
    column_signals = analyze_page_column_signals(
        parsing_res_list=parsing_res_list,
        page_width=1191,
    )

    repaired_blocks, repair_metadata, repair_summary = repair_body_cross_column_blocks(
        parsing_res_list=parsing_res_list,
        column_signals=column_signals,
    )

    assert repaired_blocks[0]["block_content"].startswith("A donor sentence")
    assert repaired_blocks[1]["block_content"] == ""
    assert repair_metadata.get(0, {}).get("provider_body_repair_applied") is None
    assert repair_metadata.get(1, {}).get("provider_body_repair_applied") is None
    assert repair_summary["body_repair_pair_count"] == 0


def test_paddle_body_repair_ignores_front_matter_text_before_body_heading() -> None:
    parsing_res_list = [
        {
            "block_label": "doc_title",
            "block_content": "Document Title",
            "block_bbox": [100, 200, 900, 300],
        },
        {
            "block_label": "paragraph_title",
            "block_content": "Abstract",
            "block_bbox": [120, 430, 220, 455],
        },
        {
            "block_label": "abstract",
            "block_content": "Abstract content block.",
            "block_bbox": [120, 470, 980, 740],
        },
        {
            "block_label": "text",
            "block_content": "Keywords: Indigo, DFT",
            "block_bbox": [120, 761, 833, 789],
        },
        {
            "block_label": "text",
            "block_content": "",
            "block_bbox": [602, 823, 1081, 898],
        },
        {
            "block_label": "paragraph_title",
            "block_content": "Introduction",
            "block_bbox": [108, 824, 232, 845],
        },
        {
            "block_label": "text",
            "block_content": "Body paragraph starts here and should be the first repairable body block.",
            "block_bbox": [106, 847, 585, 1016],
        },
    ]
    column_signals = analyze_page_column_signals(
        parsing_res_list=parsing_res_list,
        page_width=1191,
    )

    repaired_blocks, repair_metadata, repair_summary = repair_body_cross_column_blocks(
        parsing_res_list=parsing_res_list,
        column_signals=column_signals,
    )

    assert repaired_blocks[3]["block_content"] == "Keywords: Indigo, DFT"
    assert repaired_blocks[4]["block_content"] == ""
    assert repair_metadata == {}
    assert repair_summary["body_repair_pair_count"] == 0


