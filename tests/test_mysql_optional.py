from __future__ import annotations

import os
import unittest

from app.config import get_settings
from app.storage import Database, Repository, initialize_database


class MySqlOptionalTests(unittest.TestCase):
    def test_mysql_backend_when_explicitly_configured(self):
        if os.environ.get("DB_BACKEND", "").lower() != "mysql":
            self.skipTest("MySQL smoke test requires DB_BACKEND=mysql in .env or environment.")
        settings = get_settings()
        db = Database(settings)
        initialize_database(db)
        repo = Repository(db)
        book_id = repo.create_demo_book()
        self.assertGreaterEqual(book_id, 1)
        self.assertGreaterEqual(len(repo.list_chapter_plans(book_id)), 3)


if __name__ == "__main__":
    unittest.main()

