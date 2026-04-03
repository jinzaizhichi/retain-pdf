import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_SCRIPTS_ROOT = Path("/home/wxyhgk/tmp/Code/backend/scripts")


def load_retrying_translator():
    sys.path.insert(0, str(REPO_SCRIPTS_ROOT))
    package_paths = {
        "services": REPO_SCRIPTS_ROOT / "services",
        "services.translation": REPO_SCRIPTS_ROOT / "services" / "translation",
        "services.translation.llm": REPO_SCRIPTS_ROOT / "services" / "translation" / "llm",
        "services.translation.policy": REPO_SCRIPTS_ROOT / "services" / "translation" / "policy",
        "services.document_schema": REPO_SCRIPTS_ROOT / "services" / "document_schema",
    }
    for name, path in package_paths.items():
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            sys.modules[name] = module

    spec = importlib.util.spec_from_file_location(
        "services.translation.llm.retrying_translator",
        REPO_SCRIPTS_ROOT / "services" / "translation" / "llm" / "retrying_translator.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_formula_item(formula_count: int) -> dict:
    parts = []
    for index in range(1, formula_count + 1):
        parts.append(f"clause {index} explaining the result")
        parts.append(f"[[FORMULA_{index}]]")
    parts.append("final discussion sentence")
    source = " ".join(parts)
    return {
        "item_id": f"formula-{formula_count}",
        "block_type": "text",
        "protected_source_text": source,
        "translation_unit_protected_source_text": source,
        "metadata": {"structure_role": "body"},
        "formula_map": {"dummy": "dummy"},
    }


class RetryingTranslatorFormulaWindowTests(unittest.TestCase):
    def test_long_formula_block_prefers_windowed_route(self):
        module = load_retrying_translator()
        item = make_formula_item(20)
        self.assertEqual(module._formula_segment_translation_route(item), "windowed")
        self.assertFalse(module._should_use_formula_segment_translation(item))

    def test_plain_text_retry_uses_windowed_route_before_plain_text(self):
        module = load_retrying_translator()
        item = make_formula_item(20)
        calls: list[str] = []

        def fake_windowed(*args, **kwargs):
            calls.append("windowed")
            return {item["item_id"]: module._result_entry("translate", "窗口化结果 [[FORMULA_1]]")}

        def fake_plain(*args, **kwargs):
            raise AssertionError("plain-text path should not be reached for this test")

        module._translate_single_item_formula_segment_windows_with_retries = fake_windowed
        module._translate_single_item_plain_text = fake_plain

        result = module._translate_single_item_plain_text_with_retries(item, request_label="unit")
        self.assertEqual(calls, ["windowed"])
        self.assertEqual(result[item["item_id"]]["decision"], "translate")

    def test_windowed_formula_translation_degrades_only_local_window(self):
        module = load_retrying_translator()
        item = make_formula_item(20)
        calls: list[list[str]] = []

        def fake_request(messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            segment_ids = [segment["segment_id"] for segment in payload["segments"]]
            calls.append(segment_ids)
            if segment_ids[0] == "9":
                return "\n".join(
                    f"<<<SEG id={segment['segment_id']}>>>\nZH {segment['source_text']}\n<<<END>>>"
                    for segment in payload["segments"][:-1]
                )
            return "\n".join(
                f"<<<SEG id={segment['segment_id']}>>>\nZH {segment['source_text']}\n<<<END>>>"
                for segment in payload["segments"]
            )

        module.request_chat_content = fake_request
        result = module._translate_single_item_formula_segment_windows_with_retries(item, request_label="unit")
        translated_text = result[item["item_id"]]["translated_text"]

        self.assertGreaterEqual(len(calls), 3)
        self.assertIn("ZH clause 1 explaining the result", translated_text)
        self.assertIn("clause 9 explaining the result", translated_text)
        self.assertEqual(
            module._placeholder_sequence(translated_text),
            module._placeholder_sequence(item["translation_unit_protected_source_text"]),
        )
        self.assertEqual(result[item["item_id"]]["decision"], "translate")


if __name__ == "__main__":
    unittest.main()
