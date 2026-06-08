from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT, get_settings
from app.factory import build_runtime


app = FastAPI(title="fiction_architect")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))


def runtime():
    return build_runtime()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    repo, _ = runtime()
    data = repo.dashboard()
    return templates.TemplateResponse(request, "dashboard.html", data)


@app.get("/books", response_class=HTMLResponse)
def books(request: Request):
    repo, _ = runtime()
    return templates.TemplateResponse(request, "books.html", {"books": repo.list_books()})


@app.post("/books/init-demo")
def init_demo():
    repo, _ = runtime()
    book_id = repo.create_demo_book()
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@app.get("/books/{book_id}", response_class=HTMLResponse)
def book_detail(request: Request, book_id: int):
    repo, _ = runtime()
    book = repo.get_book(book_id)
    if book is None:
        return templates.TemplateResponse(request, "error.html", {"message": "Book not found"}, status_code=404)
    return templates.TemplateResponse(
        request,
        "book_detail.html",
        {"book": book, "plans": repo.list_chapter_plans(book_id), "events": repo.list_events(book_id)},
    )


@app.get("/books/{book_id}/chapters/{chapter_no}", response_class=HTMLResponse)
def chapter_detail(request: Request, book_id: int, chapter_no: int):
    repo, _ = runtime()
    plan = repo.get_chapter_plan(book_id, chapter_no)
    if plan is None:
        return templates.TemplateResponse(request, "error.html", {"message": "Chapter plan not found"}, status_code=404)
    body = repo.get_chapter_body(book_id, chapter_no)
    artifacts = {
        name: repo.latest_artifact(book_id, chapter_no, name)
        for name in ["author_brief", "ref_pack", "draft", "review", "continuity_patch"]
    }
    return templates.TemplateResponse(request, "chapter_detail.html", {"plan": plan, "body": body, "artifacts": artifacts})


@app.post("/books/{book_id}/chapters/{chapter_no}/run")
def run_chapter(book_id: int, chapter_no: int):
    _, pipe = runtime()
    pipe.run_chapter(book_id, chapter_no)
    return RedirectResponse(f"/books/{book_id}/chapters/{chapter_no}", status_code=303)


@app.get("/health")
def health():
    repo, _ = runtime()
    return {"status": "ok", "books": len(repo.list_books())}


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)
