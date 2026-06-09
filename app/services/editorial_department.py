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
        structure_problems = self._structure_problems(book_id, chapter_no, draft.content, plan)
        problems.extend(structure_problems)
        problems.extend(self._outline_alignment_problems(draft.content, plan))
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
        sample = body.strip()[:1200]
        outside_dialogue = self._remove_dialogue(sample)
        return outside_dialogue.count("我") + outside_dialogue.count("我们") >= 8 and outside_dialogue.count("我") > outside_dialogue.count("他") + outside_dialogue.count("她")

    def _remove_dialogue(self, text: str) -> str:
        cleaned = []
        inside = False
        pairs = {"“": "”", "「": "」", '"': '"'}
        end = ""
        for char in text:
            if inside:
                if char == end:
                    inside = False
                continue
            if char in pairs:
                inside = True
                end = pairs[char]
                continue
            cleaned.append(char)
        return "".join(cleaned)

    def _structure_problems(self, book_id: int, chapter_no: int, body: str, plan: dict) -> list[str]:
        problems: list[str] = []
        required = {
            "unique_task": "缺少本章唯一任务，作者部门没有锁定章节功能。",
            "core_event": "缺少具体核心事件，章节可能退回模板写作。",
        }
        for field, message in required.items():
            if not str(plan.get(field) or "").strip():
                problems.append(message)
        previous = self.repo.get_chapter_body(book_id, chapter_no - 1) if chapter_no > 1 else None
        if previous:
            prev_body = previous.get("body") or ""
            if self._permission_regression(prev_body, body):
                problems.append("连续性回退：上一章已获得的权限/资源/承诺/结论，本章又当作新目标重新索取。")
        if plan.get("character_roles") and not self._body_uses_character_roles(body, str(plan.get("character_roles"))):
            problems.append("人物职能不足：章节卡片指定的人物职能没有在正文中形成有效剧情作用。")
        return problems

    def _outline_alignment_problems(self, body: str, plan: dict) -> list[str]:
        problems: list[str] = []
        core_terms = self._important_terms(str(plan.get("core_event") or ""))
        task_terms = self._important_terms("\n".join(str(plan.get(field) or "") for field in ["unique_task", "plot_summary", "ending_hook"]))
        if core_terms and not any(term in body for term in core_terms[:8]):
            problems.append("纲要贴合不足：正文没有命中本章细纲的核心事件。")
        if task_terms and not any(term in body for term in task_terms[:10]):
            problems.append("纲要贴合不足：正文没有执行本章任务、剧情梗概或结尾交接。")
        return problems

    def _important_terms(self, text: str) -> list[str]:
        stop = {
            "本章", "必须", "当前", "一个", "具体", "剧情", "推进", "状态", "角色", "信息", "目标",
            "章节", "细纲", "行动", "结果", "问题", "阶段", "正文", "人物", "关系", "主角",
        }
        terms = []
        for token in self._tokens(text):
            cleaned = token.strip()
            if 2 <= len(cleaned) <= 12 and cleaned not in stop and not cleaned.startswith("第"):
                terms.append(cleaned)
        return terms

    def _too_similar(self, left: str, right: str) -> bool:
        left_tokens = {token for token in self._tokens(left) if len(token) >= 2}
        right_tokens = {token for token in self._tokens(right) if len(token) >= 2}
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
        return overlap >= 0.72

    def _tokens(self, text: str) -> list[str]:
        for mark in "，。；：、！？（）《》“”\"' \n\t":
            text = text.replace(mark, " ")
        return [part.strip() for part in text.split() if part.strip()]

    def _permission_regression(self, previous: str, body: str) -> bool:
        achieved_words = ["获得", "拿到", "通过", "成立", "组建", "批准", "确认", "验证", "锁定", "取得"]
        asset_words = ["权限", "资源", "小组", "团队", "资格", "承诺", "结论", "参数", "证据", "方案"]
        request_words = ["需要", "申请", "争取", "重新", "再次", "还要", "必须拿到", "要求"]
        had = any(a in previous for a in achieved_words) and any(asset in previous for asset in asset_words)
        asks_again = any(req in body for req in request_words) and any(asset in body for asset in asset_words)
        return had and asks_again

    def _body_reflects_change(self, body: str, change: str) -> bool:
        change_terms = ["获得", "失去", "改变", "确认", "通过", "失败", "代价", "留下", "打开", "成立", "批准", "锁定", "暴露", "升级", "退让", "承诺"]
        plan_terms = [token for token in self._tokens(change) if len(token) >= 2 and token not in {"本章", "结束", "必须", "至少", "一项", "默认", "落点"}][:6]
        return any(term in body for term in change_terms) or any(term in body for term in plan_terms)

    def _body_uses_character_roles(self, body: str, roles: str) -> bool:
        names = []
        for token in self._tokens(roles):
            if 2 <= len(token) <= 6 and token not in {"负责", "承担", "验证", "协调", "提出", "边界", "阻力", "人物", "必须", "改变", "主角", "关键同伴"}:
                names.append(token)
        if not names:
            return True
        return any(name in body for name in names[:4])

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
