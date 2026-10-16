import ast
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import toml

from utils.config import Config
from utils.thinking_control import (
    MODE_ENV, configure_thinking, install_thinking_control, thinking_request_body,
)


class ThinkingControlTest(unittest.TestCase):
    def test_glm_and_deepseek_default_to_explicitly_disabled(self):
        for model in ("glm-4.5-flash", "glm-4.7-flash", "deepseek-v4-flash"):
            self.assertEqual(thinking_request_body(model, "https://open.bigmodel.cn/api/paas/v4"),
                             {"thinking": {"type": "disabled"}})

    def test_enabled_choice_and_provider_specific_protocol(self):
        self.assertEqual(thinking_request_body("glm-4.5-flash", "https://open.bigmodel.cn", "enabled"),
                         {"thinking": {"type": "enabled"}})
        self.assertEqual(thinking_request_body("Qwen/Qwen3-8B", "https://api.siliconflow.cn/v1"),
                         {"enable_thinking": False})
        self.assertEqual(thinking_request_body("deepseek-v4-pro", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                         {"enable_thinking": False})
        self.assertEqual(thinking_request_body("Qwen3-8B", "http://localhost:8000/v1"),
                         {"chat_template_kwargs": {"enable_thinking": False}})

    def test_unknown_and_reasoning_only_models_do_not_get_unrecognized_fields(self):
        for model in ("custom-model", "gpt-4o-mini", "deepseek-r1", "qwen3-235b-thinking-2507"):
            self.assertEqual(thinking_request_body(model, "https://example.org/v1"), {})

    def test_real_translator_options_override_stale_thinking_and_separate_cache(self):
        cache = {}
        translator = SimpleNamespace(
            options={"extra_body": {"thinking": {"type": "enabled"}, "custom": 1},
                     "reasoning_effort": "high"},
            add_cache_impact_parameters=lambda key, value: cache.update({key: value}),
        )
        with patch.dict(os.environ, {MODE_ENV: "disabled"}):
            configure_thinking(translator, "glm-4.5-flash", "https://open.bigmodel.cn")
        self.assertEqual(translator.options["extra_body"],
                         {"thinking": {"type": "disabled"}, "custom": 1})
        self.assertNotIn("reasoning_effort", translator.options)
        self.assertIn("thinking_control", cache)

    def test_plugin_transport_is_not_written_as_an_unknown_toml_field(self):
        for mode in ("enabled", "disabled"):
            with tempfile.TemporaryDirectory() as folder, redirect_stdout(StringIO()):
                path = Path(folder) / "config.toml"
                path.write_text('[translation]\n[pdf]\n', encoding="utf-8")
                config = Config({"engine": "pdf2zh_next", "next_service": "zhipu", "enableThinking": mode == "enabled",
                                 "llm_api": {"model": "glm-4.5-flash", "apiKey": "test-key",
                                             "extraData": {"llm_thinking_mode": mode}}})
                config.update_config_file(path)
                self.assertEqual(config.thinking_mode, mode)
                self.assertNotIn("llm_thinking_mode", toml.load(path)["zhipu_detail"])

    def test_global_switch_overrides_legacy_provider_thinking_preferences(self):
        for enabled in (False, True):
            with redirect_stdout(StringIO()):
                config = Config({"engine": "pdf2zh_next", "next_service": "deepseek",
                                 "enableThinking": enabled,
                                 "llm_api": {"model": "deepseek-v4-flash", "extraData": {
                                     "deepseek_thinking_mode": "disabled" if enabled else "enabled"}}})
            expected = "enabled" if enabled else "disabled"
            self.assertEqual(config.thinking_mode, expected)
            self.assertEqual(config.llm_api["extraData"]["deepseek_thinking_mode"], expected)

    def test_both_runtime_hooks_are_valid_idempotent_and_backed_up(self):
        fixtures = {
            "pdf2zh_next": ("pdf2zh_next/translator/translator_impl/openai.py",
                            "        self.model = settings.translate_engine_settings.openai_model\n"),
            "pdf2zh": ("pdf2zh/translator.py",
                       "        self.think_filter_regex = re.compile(think_filter_regex, flags=re.DOTALL)\n"),
        }
        for engine, (relative, anchor) in fixtures.items():
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "Lib/site-packages" / relative
                target.parent.mkdir(parents=True)
                original = "class Translator:\n    def __init__(self):\n" + anchor
                target.write_text(original, encoding="utf-8")
                self.assertTrue(install_thinking_control(folder, engine))
                self.assertFalse(install_thinking_control(folder, engine))
                ast.parse(target.read_text(encoding="utf-8"))
                backup = target.with_suffix(".py.before_zotero_thinking_control")
                self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_unsupported_runtime_does_not_get_partially_patched(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "Lib/site-packages/pdf2zh/translator.py"
            target.parent.mkdir(parents=True)
            target.write_text("# unknown runtime\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                install_thinking_control(folder, "pdf2zh")
            self.assertEqual(target.read_text(encoding="utf-8"), "# unknown runtime\n")


if __name__ == "__main__":
    unittest.main()
