from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT, get_settings
from app.factory import build_runtime
from app.llm import TextGuard
from app.services.editorial_department import EditorialDepartment


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


@app.post("/books/create")
def create_book(title: str = Form(...), premise: str = Form("")):
    repo, _ = runtime()
    book_id = repo.create_book(title, premise)
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@app.post("/books/init-demo")
def init_demo():
    repo, _ = runtime()
    book_id = repo.create_demo_book()
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@app.post("/books/{book_id}/update")
def update_book(book_id: int, title: str = Form(...), premise: str = Form("")):
    repo, _ = runtime()
    repo.update_book(book_id, title, premise)
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@app.post("/books/{book_id}/controls")
def update_controls(
    book_id: int,
    style_rules: str = Form(...),
    market_channel: str = Form(...),
    target_chars_min: int = Form(...),
    target_chars_max: int = Form(...),
    chapter_unit_size: int = Form(...),
    pov_policy: str = Form("third_limited"),
    hook_policy: str = Form(...),
    pacing_policy: str = Form(...),
):
    repo, _ = runtime()
    repo.update_style_and_settings(book_id, style_rules, market_channel, target_chars_min, target_chars_max, chapter_unit_size, pov_policy, hook_policy, pacing_policy)
    return RedirectResponse(f"/books/{book_id}", status_code=303)


@app.post("/books/{book_id}/architecture")
def update_architecture(
    book_id: int,
    volume_title: str = Form(...),
    volume_goal: str = Form(...),
    arc_title: str = Form(...),
    arc_goal: str = Form(...),
    arc_pressure: str = Form(...),
):
    repo, _ = runtime()
    repo.update_architecture(book_id, volume_title, volume_goal, arc_title, arc_goal, arc_pressure)
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
        {"book": book, "plans": repo.list_chapter_plans(book_id), "events": repo.list_events(book_id), "controls": repo.get_book_controls(book_id)},
    )


@app.get("/books/{book_id}/chapters/{chapter_no}", response_class=HTMLResponse)
def chapter_detail(request: Request, book_id: int, chapter_no: int):
    repo, _ = runtime()
    plan = repo.get_chapter_plan(book_id, chapter_no)
    if plan is None:
        return templates.TemplateResponse(request, "error.html", {"message": "Chapter plan not found"}, status_code=404)
    body = repo.get_chapter_body(book_id, chapter_no)
    artifacts = {
        label: repo.latest_artifact(book_id, chapter_no, key)
        for label, key in [
            ("写作任务书", "author_brief"),
            ("连续性资料包", "ref_pack"),
            ("章节草稿", "draft"),
            ("编辑审稿意见", "review"),
            ("连续性写回候选", "continuity_patch"),
        ]
    }
    return templates.TemplateResponse(
        request,
        "chapter_detail.html",
        {"plan": plan, "body": body, "artifacts": artifacts, "controls": repo.get_book_controls(book_id)},
    )


@app.post("/books/{book_id}/chapters/{chapter_no}/plan")
def update_chapter_plan(
    book_id: int,
    chapter_no: int,
    title: str = Form(...),
    objective: str = Form(...),
    allowed_reveals: str = Form(...),
    forbidden_reveals: str = Form(...),
    pace_limit: str = Form(...),
):
    repo, _ = runtime()
    repo.update_chapter_plan(book_id, chapter_no, title, objective, allowed_reveals, forbidden_reveals, pace_limit)
    return RedirectResponse(f"/books/{book_id}/chapters/{chapter_no}", status_code=303)


@app.post("/books/{book_id}/chapters/{chapter_no}/run")
def run_chapter(book_id: int, chapter_no: int):
    _, pipe = runtime()
    pipe.run_chapter(book_id, chapter_no)
    return RedirectResponse(f"/books/{book_id}/chapters/{chapter_no}", status_code=303)


@app.get("/departments/{department}", response_class=HTMLResponse)
def department_page(request: Request, department: str, book_id: int | None = None):
    repo, _ = runtime()
    books = repo.list_books()
    selected = book_id or (books[0].id if books else None)
    book = repo.get_book(selected) if selected else None
    controls = repo.get_book_controls(selected) if selected else None
    plans = repo.list_chapter_plans(selected) if selected else []
    return templates.TemplateResponse(
        request,
        "department.html",
        {"department": department, "books": books, "book": book, "controls": controls, "plans": plans},
    )


@app.get("/debug", response_class=HTMLResponse)
def debug_page(request: Request, book_id: int | None = None):
    repo, _ = runtime()
    books = repo.list_books()
    selected = book_id or (books[0].id if books else None)
    book = repo.get_book(selected) if selected else None
    controls = repo.get_book_controls(selected) if selected else None
    return templates.TemplateResponse(request, "debug.html", {"books": books, "book": book, "controls": controls, "result": None, "sample": ""})


@app.post("/debug", response_class=HTMLResponse)
def run_debug(request: Request, book_id: int = Form(...), sample: str = Form("")):
    repo, _ = runtime()
    books = repo.list_books()
    book = repo.get_book(book_id)
    controls = repo.get_book_controls(book_id)
    guard_result = TextGuard().check_body(sample)
    char_count = len("".join(sample.split()))
    target_min = int(controls["settings"].get("target_chars_min", 2200))
    target_max = int(controls["settings"].get("target_chars_max", 3200))
    problems = list(guard_result.problems)
    if char_count < target_min:
        problems.append(f"字数不达标：当前约 {char_count} 字，低于最低目标 {target_min} 字。")
    if char_count > target_max + 600:
        problems.append(f"字数失控：当前约 {char_count} 字，高于最高目标 {target_max} 字太多。")
    editorial = EditorialDepartment(repo, TextGuard())
    if controls["settings"].get("pov_policy", "third_limited") == "third_limited" and editorial._looks_first_person(sample):
        problems.append("人称错误：正文疑似第一人称叙述，当前设置为第三人称有限视角。")
    story_problem = editorial._story_shape_problem(sample)
    if story_problem:
        problems.append(story_problem)
    result = {"passed": not problems, "problems": problems, "char_count": char_count}
    return templates.TemplateResponse(request, "debug.html", {"books": books, "book": book, "controls": controls, "result": result, "sample": sample})


@app.get("/health")
def health():
    repo, _ = runtime()
    return {"status": "ok", "books": len(repo.list_books())}


@app.get("/favicon.ico")
def favicon():
    return FileResponse(PROJECT_ROOT / "app" / "static" / "icons" / "favicon.svg", media_type="image/svg+xml")


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)
