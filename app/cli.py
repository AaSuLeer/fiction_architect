from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.factory import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="fiction_architect CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-demo")
    run = sub.add_parser("run-chapter")
    run.add_argument("--book-id", type=int, default=1)
    run.add_argument("--chapter", type=int, default=1)
    args = parser.parse_args()
    repo, pipe = build_runtime()
    if args.command == "init-demo":
        book_id = repo.create_demo_book()
        print(f"demo_book_id={book_id}")
    elif args.command == "run-chapter":
        result = pipe.run_chapter(args.book_id, args.chapter)
        print(f"run_id={result['run_id']} status={result['status']}")


if __name__ == "__main__":
    main()

