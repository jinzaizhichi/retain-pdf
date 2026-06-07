import sys
from pathlib import Path


REPO_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_SCRIPTS_ROOT))


from services.rendering.layout.typography_memory.features import build_typography_feature
from services.rendering.layout.typography_memory.store import TypographyMemory


def _item() -> dict:
    return {
        "item_id": "p001-b001",
        "block_kind": "text",
        "block_type": "text",
        "layout_role": "paragraph",
        "semantic_role": "body",
        "structure_role": "body",
        "bbox": [40.0, 80.0, 300.0, 142.0],
        "source_text": "This is a stable body paragraph with enough source words.",
        "protected_source_text": "This is a stable body paragraph with enough source words.",
        "lines": [
            {"bbox": [40.0, 80.0, 300.0, 94.0]},
            {"bbox": [40.0, 98.0, 300.0, 112.0]},
        ],
    }


def test_typography_memory_learns_after_min_observations(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RETAIN_RENDER_TYPOGRAPHY_MEMORY", "1")
    monkeypatch.setenv("RETAIN_RENDER_TYPOGRAPHY_MEMORY_MIN_OBS", "2")
    memory = TypographyMemory(tmp_path / "typography.sqlite3")
    feature = build_typography_feature(
        item=_item(),
        translated_text="这是一个稳定的正文段落，用于测试字号和行距缓存。",
        font_size_pt=10.5,
        leading_em=0.78,
        page_width=595.0,
        page_height=842.0,
        page_text_width_med=260.0,
        is_body=True,
        dense_small_box=False,
        heavy_dense_small_box=False,
        wide_aspect_body_text=False,
        preserve_line_breaks=False,
    )

    assert feature is not None
    assert memory.lookup(feature.key) is None

    memory.observe(feature_key=feature.key, font_size_pt=10.8, leading_em=0.82)
    assert memory.lookup(feature.key) is None

    memory.observe(feature_key=feature.key, font_size_pt=10.9, leading_em=0.81)
    decision = memory.lookup(feature.key)

    assert decision is not None
    assert decision.observations == 2
    assert 10.8 <= decision.font_size_pt <= 10.9
    assert 0.81 <= decision.leading_em <= 0.82


def test_typography_memory_rejects_unstable_samples(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RETAIN_RENDER_TYPOGRAPHY_MEMORY", "1")
    monkeypatch.setenv("RETAIN_RENDER_TYPOGRAPHY_MEMORY_MIN_OBS", "3")
    memory = TypographyMemory(tmp_path / "typography.sqlite3")
    feature = build_typography_feature(
        item=_item(),
        translated_text="这是另一个稳定正文段落。",
        font_size_pt=10.5,
        leading_em=0.78,
        page_width=595.0,
        page_height=842.0,
        page_text_width_med=260.0,
        is_body=True,
        dense_small_box=False,
        heavy_dense_small_box=False,
        wide_aspect_body_text=False,
        preserve_line_breaks=False,
    )

    assert feature is not None
    for font_size in (8.0, 12.0, 16.0):
        memory.observe(feature_key=feature.key, font_size_pt=font_size, leading_em=0.8)

    assert memory.lookup(feature.key) is None
