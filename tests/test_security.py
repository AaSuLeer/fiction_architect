from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SecurityTests(unittest.TestCase):
    def test_env_is_ignored_and_example_has_no_secret(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("MYSQL_PASSWORD=", example)
        self.assertIn("LLM_API_KEY=", example)
        self.assertIn("LLM_OUTLINE_MODEL=qwen-max", example)
        self.assertNotIn("ZHIPUAI_API_KEY=", example)
        forbidden_literals = ["230" + "17330", "sk-", "apikey"]
        for literal in forbidden_literals:
            self.assertNotIn(literal, example.lower())

    def test_repository_files_do_not_contain_known_secret(self):
        forbidden = "230" + "17330"
        for path in ROOT.rglob("*"):
            if path.is_dir() or ".git" in path.parts or path.name.endswith(".pyc"):
                continue
            if path.name == ".env":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn(forbidden, text, f"secret leaked in {path}")


if __name__ == "__main__":
    unittest.main()
