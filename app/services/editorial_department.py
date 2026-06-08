from __future__ import annotations

import json

from app.llm import TextGuard
from app.storage.repository import Repository


class EditorialDepartment:
    def __init__(self, repo: Repository, guard: TextGuard):
        self.repo = repo
        self.guard = guard

    def review(self, book_id: int, chapter_no: int, draft_id: int):
        draft = self.repo.get_artifact(draft_id)
        if draft is None:
            raise ValueError("editorial blocked: missing draft")
        result = self.guard.check_body(draft.content)
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        plan = ctx["plan"]
        settings = ctx["settings"]
        problems = list(result.problems)
        char_count = self._count_chars(draft.content)
        target_min = int(settings.get("target_chars_min", 1800))
        target_max = int(settings.get("target_chars_max", 2600))
        if char_count < target_min:
            problems.append(f"字数不达标：当前约 {char_count} 字，低于最低目标 {target_min} 字。")
        if char_count > target_max + 600:
            problems.append(f"字数失控：当前约 {char_count} 字，高于最高目标 {target_max} 字太多。")
        if settings.get("pov_policy", "third_limited") == "third_limited" and self._looks_first_person(draft.content):
            problems.append("人称错误：正文疑似第一人称叙述，当前项目要求第三人称有限视角。")
        story_problem = self._story_shape_problem(draft.content)
        if story_problem:
            problems.append(story_problem)
        if plan["forbidden_reveals"] and any(key in draft.content for key in ["废校真正来历", "完整世界观", "卷级终局"]):
            problems.append("推进过快：触碰了本章 forbidden_reveals。")
        status = "approved" if not problems else "rejected"
        report = {
            "department": "editorial_department",
            "draft_id": draft_id,
            "status": status,
            "problems": problems,
            "char_count": char_count,
            "target_chars_min": target_min,
            "target_chars_max": target_max,
            "checks": [
                "正文污染",
                "说明书式写作",
                "目标字数",
                "人称策略",
                "起因经过结果",
                "节奏推进",
                "AI模板化风险",
                "连续性风险",
            ],
        }
        review = self.repo.create_artifact(book_id, chapter_no, "review", status, json.dumps(report, ensure_ascii=False, indent=2))
        if status == "approved":
            self.repo.create_artifact(book_id, chapter_no, "draft", "approved", draft.content, visibility="approved")
        return review

    def _count_chars(self, body: str) -> int:
        return len("".join(body.split()))

    def _looks_first_person(self, body: str) -> bool:
        clean = body.strip()
        if clean.startswith("我") or clean.startswith("我的"):
            return True
        sample = clean[:700]
        first_person_hits = sample.count("我") + sample.count("我们")
        third_person_hits = sample.count("他") + sample.count("她") + sample.count("主角")
        return first_person_hits >= 8 and first_person_hits > third_person_hits

    def _story_shape_problem(self, body: str) -> str:
        paragraphs = [part.strip() for part in body.splitlines() if part.strip()]
        if len(paragraphs) < 10:
            return "故事结构不足：段落过少，缺少完整的起因、经过、结果。"
        pressure_words = ["倒计时", "惩罚", "处罚", "排名", "资格", "危机", "扣", "失去", "必须"]
        action_words = ["伸手", "盯", "走", "按", "推", "反问", "判断", "试", "改", "拿", "说"]
        result_words = ["终于", "结果", "资格", "赢", "输", "代价", "留下", "打开", "欠下", "通过"]
        if not any(word in body for word in pressure_words):
            return "故事结构不足：缺少明确起因或当场压力。"
        if sum(1 for word in action_words if word in body) < 2:
            return "故事结构不足：主角行动不足，经过不成立。"
        if not any(word in body for word in result_words):
            return "故事结构不足：缺少结果、兑现或下一章代价。"
        return ""
