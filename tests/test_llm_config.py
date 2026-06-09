from __future__ import annotations

import os
import unittest

from app.config import get_settings


class LlmConfigTests(unittest.TestCase):
    def setUp(self):
        self.original = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original)

    def test_new_llm_names_take_precedence(self):
        os.environ.clear()
        os.environ.update(
            {
                "LLM_API_KEY": "new-key",
                "LLM_BASE_URL": "https://example.test/v1/chat/completions",
                "LLM_DEFAULT_MODEL": "default-model",
                "LLM_OUTLINE_MODEL": "qwen-max",
                "LLM_WRITER_MODEL": "writer-model",
                "LLM_EDITOR_MODEL": "editor-model",
                "LLM_MODE": "",
                "ZHIPUAI_API_KEY": "",
            }
        )
        settings = get_settings()
        self.assertEqual("new-key", settings.llm_api_key)
        self.assertEqual("openai", settings.llm_mode)
        self.assertEqual("qwen-max", settings.llm_outline_model)
        self.assertEqual("writer-model", settings.llm_writer_model)
        self.assertEqual("editor-model", settings.llm_editor_model)

    def test_legacy_zhipu_names_still_fall_back(self):
        os.environ.clear()
        os.environ.update({"LLM_API_KEY": "", "LLM_DEFAULT_MODEL": "", "ZHIPUAI_API_KEY": "old-key", "ZHIPUAI_MODEL": "legacy-model", "LLM_MODE": ""})
        settings = get_settings()
        self.assertEqual("old-key", settings.llm_api_key)
        self.assertEqual("legacy-model", settings.llm_default_model)
        self.assertEqual("openai", settings.llm_mode)

    def test_model_name_in_llm_mode_is_treated_as_compatible_model(self):
        os.environ.clear()
        os.environ.update({"LLM_API_KEY": "key", "LLM_DEFAULT_MODEL": "", "ZHIPUAI_API_KEY": "", "ZHIPUAI_MODEL": "", "LLM_MODE": "qwen-plus-2025-12-01"})
        settings = get_settings()
        self.assertEqual("openai", settings.llm_mode)
        self.assertEqual("qwen-plus-2025-12-01", settings.llm_default_model)


if __name__ == "__main__":
    unittest.main()
