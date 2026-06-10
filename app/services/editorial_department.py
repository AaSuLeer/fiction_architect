from __future__ import annotations

import json
import re

from app.llm import TextGuard
from app.storage.repository import POV_LABELS, Repository


class EditorialDepartment:
    """Structured editor for the phase-2 production state machine."""

    def __init__(self, repo: Repository, guard: TextGuard):
        self.repo = repo
        self.guard = guard

    def review_draft(self, book_id: int, chapter_no: int, draft: dict, run_id: int | None = None) -> dict:
        if not draft:
            raise ValueError("editorial blocked: missing chapter_draft")
        report = self._build_report(book_id, chapter_no, str(draft.get("content") or ""))
        decision = self.repo.create_editorial_decision(
            book_id,
            chapter_no,
            str(report["status"]),
            run_id=run_id,
            payload=report,
            draft_id=int(draft["id"]),
        )
        if report["status"] == "approved":
            self.repo.set_chapter_task_status(book_id, chapter_no, "editorial_passed")
        else:
            self.repo.create_rework_ticket(book_id, chapter_no, run_id, int(decision["id"]), report)
            self.repo.set_chapter_task_status(book_id, chapter_no, "rewrite_needed")
        decision["report"] = report
        return decision

    def review(self, book_id: int, chapter_no: int, draft_id: int):
        """Legacy adapter kept only for historical tests/tools."""
        draft = self.repo.get_artifact(draft_id)
        if draft is None:
            raise ValueError("editorial blocked: missing draft")
        report = self._build_report(book_id, chapter_no, draft.content)
        review = self.repo.create_artifact(book_id, chapter_no, "review", str(report["status"]), json.dumps(report, ensure_ascii=False, indent=2))
        if report["status"] == "approved":
            self.repo.create_artifact(book_id, chapter_no, "draft", "editor_approved", draft.content, visibility="draft")
        else:
            self.repo.create_rewrite_task(book_id, chapter_no, review.id)
        return review

    def _build_report(self, book_id: int, chapter_no: int, body: str) -> dict:
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        plan = ctx["plan"]
        book = ctx["book"]
        editor = ctx.get("editor_profile") or {}
        problems = list(self.guard.check_body(body).problems)

        char_count = self._count_chars(body)
        target_chars = int(plan.get("target_chars") or book.get("target_chars_min") or 2200)
        if char_count < max(800, target_chars - 500):
            problems.append(f"字数不达标：当前约 {char_count} 字，目标约 {target_chars} 字。")
        if char_count > target_chars + 1200:
            problems.append(f"字数失控：当前约 {char_count} 字，明显高于目标 {target_chars} 字。")

        if book.get("pov_policy") == "third_limited" and self._looks_first_person_narration(body):
            problems.append("人称错误：本书设定为第三人称有限视角，正文疑似长期第一人称旁白。")

        problems.extend(self._task_alignment_problems(body, plan))
        problems.extend(self._continuity_problems(book_id, chapter_no, body))

        status = "approved" if not problems else "rejected"
        failure_codes = self._failure_codes(problems)
        route = self._route_for_failure(failure_codes)
        score = 100 if not problems else max(0, 100 - len(problems) * 18)
        return {
            "status": status,
            "score": score,
            "failure_codes": failure_codes,
            "evidence": problems,
            "route": route,
            "required_fixes": problems[:8],
            "editor": editor.get("name", "默认编辑"),
            "platform": editor.get("platform", ""),
            "pov": POV_LABELS.get(book.get("pov_policy", "third_limited"), "第三人称有限视角"),
            "char_count": char_count,
            "target_chars": target_chars,
            "rewrite_direction": "；".join(problems[:5]),
        }

    def _task_alignment_problems(self, body: str, plan: dict) -> list[str]:
        problems: list[str] = []
        for field, label in [
            ("unique_task", "本章唯一任务"),
            ("core_event", "具体核心事件"),
            ("irreversible_change", "不可逆变化"),
        ]:
            value = str(plan.get(field) or "").strip()
            if not value:
                problems.append(f"章节卡缺少{label}，不能进入正式生产。")
                continue
            terms = self._important_terms(value)
            if terms and not any(term in body for term in terms[:10]):
                problems.append(f"纲要贴合不足：正文未命中{label}中的关键内容：{terms[:4]}。")
        return problems

    def _continuity_problems(self, book_id: int, chapter_no: int, body: str) -> list[str]:
        if chapter_no <= 1:
            return []
        previous = self.repo.get_chapter_body(book_id, chapter_no - 1)
        if not previous:
            return ["上一章尚未发布，当前章不得进入正式审稿。"]
        prev_body = previous.get("body") or ""
        problems = []
        if self._permission_regression(prev_body, body):
            problems.append("连续性回退：上一章已取得的权限、资源、承诺或结论，本章又当作新目标重新索取。")
        if str(previous.get("status") or "") not in {"exported", "published", "canonized"}:
            problems.append("上一章未发布/入账，当前章不能作为正史续写。")
        return problems

    def _failure_codes(self, problems: list[str]) -> list[str]:
        text = "\n".join(problems)
        checks = [
            ("word_count", ["字数"]),
            ("pov_error", ["人称"]),
            ("meta_pollution", ["污染", "部门", "交付", "根据规则"]),
            ("plan_misalignment", ["未命中", "章节卡", "任务", "核心事件"]),
            ("continuity_regression", ["连续性", "回退", "上一章未发布"]),
        ]
        codes = [code for code, needles in checks if any(needle in text for needle in needles)]
        return codes or (["editorial_rewrite"] if problems else [])

    def _route_for_failure(self, failure_codes: list[str]) -> str:
        if not failure_codes:
            return "human_release_check"
        if any(code in failure_codes for code in {"plan_misalignment", "continuity_regression"}):
            return "planner"
        return "writer"

    def _count_chars(self, body: str) -> int:
        return len("".join(body.split()))

    def _looks_first_person_narration(self, body: str) -> bool:
        sample = self._remove_dialogue(body.strip()[:1600])
        return sample.count("我") + sample.count("我们") >= 8

    def _remove_dialogue(self, text: str) -> str:
        return re.sub(r"[“\"].*?[”\"]", "", text, flags=re.DOTALL)

    def _important_terms(self, text: str) -> list[str]:
        stop = {
            "本章", "必须", "当前", "具体", "剧情", "推进", "状态", "角色", "信息", "目标",
            "章节", "细纲", "行动", "结果", "问题", "阶段", "正文", "人物", "关系", "主角",
            "不得", "完成", "一个", "以及", "通过", "形成", "改变",
        }
        normalized = re.sub(r"[\s，。；：、！？（）《》“”\"'\[\]{}]+", " ", text)
        terms = []
        for part in normalized.split():
            cleaned = part.strip()
            if 2 <= len(cleaned) <= 16 and cleaned not in stop:
                terms.append(cleaned)
        return terms

    def _permission_regression(self, previous: str, body: str) -> bool:
        achieved_words = ["获得", "拿到", "通过", "成立", "组建", "批准", "确认", "验证", "锁定", "取得"]
        asset_words = ["权限", "资源", "小组", "团队", "资格", "承诺", "结论", "参数", "证据", "方案"]
        request_words = ["需要", "申请", "争取", "重新", "再次", "还要", "必须拿到", "要求"]
        had = any(a in previous for a in achieved_words) and any(asset in previous for asset in asset_words)
        asks_again = any(req in body for req in request_words) and any(asset in body for asset in asset_words)
        return had and asks_again
