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

def test_paddle_json_sci_empty_text_slots_stay_on_text_only_repair_path() -> None:
    payload = json.loads(PADDLE_SCI_FIXTURE_JSON.read_text(encoding="utf-8"))
    repaired_pages: dict[int, list[dict]] = {}
    empty_slot_pages: dict[int, list[int]] = {}

    for page_index, page_payload in enumerate(payload["layoutParsingResults"], start=1):
        page_meta = payload["dataInfo"]["pages"][page_index - 1]
        page_spec = build_page_spec(
            page_payload=page_payload,
            page_index=page_index - 1,
            page_meta=page_meta,
            preprocessed_image=payload["preprocessedImages"][page_index - 1],
        )
        page_blocks = page_payload["prunedResult"]["parsing_res_list"]
        empty_orders = [
            order
            for order, block in enumerate(page_blocks)
            if block.get("block_label") == "text" and not str(block.get("block_content", "") or "").strip()
        ]
        if empty_orders:
            empty_slot_pages[page_index] = empty_orders
        if page_spec["metadata"]["body_repair_pairs"]:
            repaired_pages[page_index] = list(page_spec["metadata"]["body_repair_pairs"])
            for pair in page_spec["metadata"]["body_repair_pairs"]:
                absorber = page_blocks[pair["absorber_order"]]
                peer = page_blocks[pair["peer_order"]]
                assert absorber.get("block_label") == "text"
                assert peer.get("block_label") == "text"

    assert empty_slot_pages == {
        1: [17],
        2: [6],
        3: [12],
        4: [16],
        6: [18],
        9: [16],
        11: [8],
        14: [10],
        15: [8],
        16: [12],
    }
    assert repaired_pages == {}


def test_paddle_json_sci_front_matter_text_does_not_become_body() -> None:
    payload = json.loads(PADDLE_SCI_FIXTURE_JSON.read_text(encoding="utf-8"))
    page_blocks = payload["layoutParsingResults"][0]["prunedResult"]["parsing_res_list"]
    classified = classify_page_blocks(page_blocks)

    assert classified[8][:2] == ("text", "metadata")
    assert classified[9][:2] == ("text", "metadata")
    assert classified[10][:2] == ("text", "metadata")
    assert classified[11][:2] == ("text", "body")
    assert classified[14][:2] == ("text", "heading")
    assert classified[15][:2] == ("text", "body")


def test_paddle_classifies_metadata_text_cues_before_translation() -> None:
    classified = classify_page_blocks(
        [
            {"block_label": "text", "block_content": "The authors declare that they have no competing interests."},
            {"block_label": "text", "block_content": "This work was funded by Consejo Nacional de Ciencia y Tecnologia."},
            {"block_label": "text", "block_content": "Received: 6 April 2012 Accepted: 19 June 2012 Published: 18 July 2012"},
            {"block_label": "text", "block_content": "Cite this article as: Example Journal 2012, 6:70"},
            {"block_label": "text", "block_content": "Submit your manuscript here: http://example.test/manuscript/"},
            {"block_label": "text", "block_content": "Normal body paragraph should remain in body classification."},
        ]
    )

    assert classified[0][:2] == ("text", "metadata")
    assert classified[1][:2] == ("text", "metadata")
    assert classified[2][:2] == ("text", "metadata")
    assert classified[3][:2] == ("text", "metadata")
    assert classified[4][:2] == ("text", "metadata")
    assert classified[5][:2] == ("text", "body")


def test_paddle_does_not_treat_body_bullets_as_metadata() -> None:
    classified = classify_page_blocks(
        [
            {
                "block_label": "text",
                "block_content": (
                    "• Knowledge: In assessments of broad world knowledge, DeepSeek-V4-Pro-Max "
                    "significantly outperforms leading open-source models on the SimpleQA benchmark."
                ),
            },
            {
                "block_label": "text",
                "block_content": (
                    "• Reasoning: Through the expansion of reasoning tokens, DeepSeek-V4-Pro-Max "
                    "demonstrates superior performance relative to GPT-5.2 on standard reasoning benchmarks."
                ),
            },
            {
                "block_label": "text",
                "block_content": "• Keywords: document parsing; translation; layout analysis",
            },
        ]
    )

    assert classified[0][:2] == ("text", "body")
    assert classified[1][:2] == ("text", "body")
    assert classified[2][:2] == ("text", "metadata")


def test_paddle_limits_metadata_bullet_by_word_count() -> None:
    classified = classify_page_blocks(
        [
            {
                "block_label": "text",
                "block_content": (
                    "• Keywords: a b c d e f g h i j k l m n o p q r s t u v w x y z "
                    "this is already too long to be treated as a tiny metadata fragment"
                ),
            },
            {
                "block_label": "text",
                "block_content": "• DOI: 10.1000/xyz123",
            },
        ]
    )

    assert classified[0][:2] == ("text", "body")
    assert classified[1][:2] == ("text", "metadata")


def test_paddle_metadata_cues_must_appear_at_start() -> None:
    classified = classify_page_blocks(
        [
            {
                "block_label": "text",
                "block_content": (
                    "This paragraph discusses benchmark setup and mentions keywords: translation, "
                    "layout, parsing in the middle of normal body text."
                ),
            },
            {
                "block_label": "text",
                "block_content": (
                    "The appendix also references doi: 10.1000/xyz123 inside a longer explanatory sentence."
                ),
            },
            {
                "block_label": "text",
                "block_content": "Keywords: translation; layout; parsing",
            },
            {
                "block_label": "text",
                "block_content": "• Keywords: translation; layout; parsing",
            },
        ]
    )

    assert classified[0][:2] == ("text", "body")
    assert classified[1][:2] == ("text", "body")
    assert classified[2][:2] == ("text", "metadata")
    assert classified[3][:2] == ("text", "metadata")


def test_paddle_figure_title_maps_to_figure_caption() -> None:
    classified = classify_page_blocks(
        [
            {"block_label": "figure_title", "block_content": "Figure 3: Overall pipeline."},
            {"block_label": "figure_title", "block_content": "Table note: Results improve after reranking."},
        ]
    )

    assert classified[0] == ("text", "figure_caption", ["caption", "figure_caption"], {"caption_target": "figure"})
    assert classified[1] == ("text", "figure_caption", ["caption", "figure_caption"], {"caption_target": "figure"})


def test_paddle_figure_title_is_translatable() -> None:
    payload = {
        "layoutParsingResults": [
            {
                "prunedResult": {
                    "parsing_res_list": [
                        {"block_label": "figure_title", "block_content": "Figure 1. Example caption."},
                    ]
                },
                "markdown": {"text": "", "images": {}},
            }
        ],
        "dataInfo": {"pages": [{"width": 1200, "height": 1600}], "type": "paddle"},
    }

    from services.document_schema.provider_adapters.paddle.page_reader import build_page_spec

    block = build_page_spec(page_payload=payload["layoutParsingResults"][0], page_index=0, page_meta={}, preprocessed_image="")["blocks"][0]
    assert block.get("sub_type") == "figure_caption"
    assert block.get("policy", {}).get("translate") is True


def test_paddle_figure_caption_enters_translation_items() -> None:
    payload = {
        "layoutParsingResults": [
            {
                "prunedResult": {
                    "parsing_res_list": [
                        {"block_label": "figure_title", "block_content": "Figure 1. Example caption."},
                    ]
                },
                "markdown": {"text": "", "images": {}},
            }
        ],
        "dataInfo": {"pages": [{"width": 1200, "height": 1600}], "type": "paddle"},
    }

    from services.document_schema.provider_adapters.paddle.page_reader import build_page_spec
    page_spec = build_page_spec(page_payload=payload["layoutParsingResults"][0], page_index=0, page_meta={}, preprocessed_image="")
    assert page_spec["blocks"][0]["sub_type"] == "figure_caption"
    assert page_spec["blocks"][0]["policy"]["translate"] is True


def test_paddle_doc_title_enters_translation_items_as_optional_title_candidate() -> None:
    payload = {
        "layoutParsingResults": [
            {
                "prunedResult": {
                    "parsing_res_list": [
                        {"block_label": "doc_title", "block_content": "Document Title"},
                    ]
                },
                "markdown": {"text": "", "images": {}},
            }
        ],
        "dataInfo": {"pages": [{"width": 1200, "height": 1600}], "type": "paddle"},
    }

    document = build_paddle_document(
        payload,
        document_id="title-policy-doc",
        source_json_path=PADDLE_FIXTURE_JSON,
        provider_version="PaddleOCR-VL",
    )

    block = document["pages"][0]["blocks"][0]
    assert block["sub_type"] == "title"
    assert block["structure_role"] == "title"
    assert block["policy"] == {"translate": True, "translate_reason": "provider_title_candidate"}
    assert [item.text for item in extract_text_items(document, 0)] == ["Document Title"]


def test_paddle_classifies_ancillary_tail_headings_as_metadata() -> None:
    classified = classify_page_blocks(
        [
            {"block_label": "paragraph_title", "block_content": "Competing interests"},
            {"block_label": "paragraph_title", "block_content": "Acknowledgments"},
            {"block_label": "paragraph_title", "block_content": "References"},
            {"block_label": "paragraph_title", "block_content": "Introduction"},
        ]
    )

    assert classified[0][:2] == ("text", "metadata")
    assert classified[1][:2] == ("text", "metadata")
    assert classified[2][:2] == ("text", "metadata")
    assert classified[3][:2] == ("text", "heading")

