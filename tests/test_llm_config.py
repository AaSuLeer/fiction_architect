from __future__ import annotations

import os
import unittest
from pathlib import Path

from app.config import Settings, get_settings
from app.llm.client import LlmClient


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
                "SQLITE_PATH": "data/test_llm_config.db",
                "ZHIPUAI_API_KEY": "",
            }
        )
        settings = get_settings()
        self.assertEqual("new-key", settings.llm_api_key)
        self.assertEqual("compatible", settings.llm_mode)
        self.assertEqual("qwen-max", settings.llm_outline_model)
        self.assertEqual("writer-model", settings.llm_writer_model)
        self.assertEqual("editor-model", settings.llm_editor_model)

    def test_legacy_zhipu_names_still_fall_back(self):
        os.environ.clear()
        os.environ.update({"LLM_API_KEY": "", "LLM_DEFAULT_MODEL": "", "ZHIPUAI_API_KEY": "old-key", "ZHIPUAI_MODEL": "legacy-model", "LLM_MODE": "", "SQLITE_PATH": "data/test_llm_config.db"})
        settings = get_settings()
        self.assertEqual("old-key", settings.llm_api_key)
        self.assertEqual("legacy-model", settings.llm_default_model)
        self.assertEqual("compatible", settings.llm_mode)

    def test_model_name_in_llm_mode_is_treated_as_compatible_model(self):
        os.environ.clear()
        os.environ.update({"LLM_API_KEY": "key", "LLM_DEFAULT_MODEL": "", "ZHIPUAI_API_KEY": "", "ZHIPUAI_MODEL": "", "LLM_MODE": "qwen-plus-2025-12-01", "SQLITE_PATH": "data/test_llm_config.db"})
        settings = get_settings()
        self.assertEqual("compatible", settings.llm_mode)
        self.assertEqual("qwen-plus-2025-12-01", settings.llm_default_model)

    def test_provider_alias_in_llm_mode_keeps_generic_compatible_mode(self):
        os.environ.clear()
        os.environ.update({"LLM_API_KEY": "key", "LLM_DEFAULT_MODEL": "qwen-plus", "LLM_MODE": "qwen", "SQLITE_PATH": "data/test_llm_config.db"})
        settings = get_settings()
        self.assertEqual("compatible", settings.llm_mode)
        self.assertEqual("qwen-plus", settings.llm_default_model)

    def test_client_accepts_sdk_style_base_url(self):
        client = LlmClient(self._settings_with_url("https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.assertEqual(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            client._chat_completions_url(client.settings.llm_base_url),
        )

    def test_client_keeps_full_chat_completions_url(self):
        client = LlmClient(self._settings_with_url("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"))
        self.assertEqual(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            client._chat_completions_url(client.settings.llm_base_url),
        )

    def _settings_with_url(self, url: str) -> Settings:
        return Settings(
            db_backend="sqlite",
            sqlite_path=Path("data/test_llm_config.db"),
            mysql_host="127.0.0.1",
            mysql_port=3306,
            mysql_user="",
            mysql_password="",
            mysql_database="fiction_architect",
            llm_api_key="key",
            llm_base_url=url,
            llm_default_model="qwen-plus",
            llm_outline_model="qwen-max",
            llm_writer_model="qwen-plus",
            llm_editor_model="qwen-plus",
            llm_timeout=60,
            llm_mode="compatible",
            app_host="127.0.0.1",
            app_port=8010,
        )


if __name__ == "__main__":
    unittest.main()
