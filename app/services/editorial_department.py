from __future__ import annotations

import json

from app.llm import TextGuard
from app.storage.repository import POV_LABELS, Repository


class EditorialDepartment:
    def __init__(self, repo: Repository, guard: TextGuard):
        self.repo = repo
        self.guard = guard

    def review(self, book_id: int, chapter_no: int, draft_id: int):
        draft = self.repo.get_artifact(draft_id)
        if draft is None:
            raise ValueError("editorial blocked: missing draft")
        ctx = self.repo.get_architecture_context(book_id, chapter_no)
        plan = ctx["plan"]
        book = ctx["book"]
        editor = ctx.get("editor_profile") or {}
        problems = list(self.guard.check_body(draft.content).problems)
        char_count = self._count_chars(draft.content)
        target_chars = int(plan.get("target_chars") or book.get("target_chars_min") or 2200)
        if char_count < max(800, target_chars - 500):
            problems.append(f"字数不达标：当前约 {char_count} 字，目标约 {target_chars} 字。")
        if char_count > target_chars + 1200:
            problems.append(f"字数失控：当前约 {char_count} 字，明显高于目标 {target_chars} 字。")
        if book.get("pov_policy") == "third_limited" and self._looks_first_person(draft.content):
            problems.append("人称错误：本书设定为第三人称有限视角，正文疑似第一人称旁白。")
        story_problem = self._story_shape_problem(draft.content)
        if story_problem:
            problems.append(story_problem)
        drift_problem = self._outline_drift_problem(draft.content)
        if drift_problem:
            problems.append(drift_problem)
        status = "approved" if not problems else "rejected"
        report = {
            "name": "编辑意见",
            "status": status,
            "editor": editor.get("name", "默认编辑"),
            "platform": editor.get("platform", ""),
            "pov": POV_LABELS.get(book.get("pov_policy", "third_limited"), "第三人称有限视角"),
            "char_count": char_count,
            "target_chars": target_chars,
            "problems": problems,
            "rewrite_direction": "；".join(problems[:5]),
        }
        review = self.repo.create_artifact(book_id, chapter_no, "review", status, json.dumps(report, ensure_ascii=False, indent=2))
        if status == "approved":
            self.repo.create_artifact(book_id, chapter_no, "draft", "editor_approved", draft.content, visibility="draft")
        else:
            self.repo.create_rewrite_task(book_id, chapter_no, review.id)
        return review

    def _count_chars(self, body: str) -> int:
        return len("".join(body.split()))

    def _looks_first_person(self, body: str) -> bool:
        sample = body.strip()[:700]
        return sample.count("我") + sample.count("我们") >= 8 and sample.count("我") > sample.count("他") + sample.count("她")

    def _story_shape_problem(self, body: str) -> str:
        if len([line for line in body.splitlines() if line.strip()]) < 8:
            return "故事结构不足：段落过少，缺少完整起因、经过、结果。"
        pressure = ["倒计时", "惩罚", "处罚", "排名", "资格", "危机", "失去", "必须", "退"]
        action = ["伸手", "盯", "走", "按", "接", "反问", "判断", "证", "改", "转身"]
        result = ["终于", "通过", "赢", "败", "代价", "留下", "打开", "欠下", "换来"]
        if not any(word in body for word in pressure):
            return "故事结构不足：缺少明确起因或当场压力。"
        if sum(1 for word in action if word in body) < 2:
            return "故事结构不足：主角行动不足，经过不成立。"
        if not any(word in body for word in result):
            return "故事结构不足：缺少结果、兑现或下一章代价。"
        return ""

    def _outline_drift_problem(self, body: str) -> str:
        risky_terms = ["全书终局", "最终秘密", "完整世界观", "卷级终局", "彻底解决所有问题"]
        if any(term in body for term in risky_terms):
            return "大纲漂移风险：疑似越过章节/单元限制，提前推进卷级或全书级目标。"
        return ""
