from __future__ import annotations

from app.llm import LlmClient
from app.storage.repository import Repository


class WritingDepartment:
    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.llm = llm

    def draft(self, book_id: int, chapter_no: int, brief_id: int, ref_pack_id: int, rewrite_feedback: str = ""):
        brief = self.repo.get_artifact(brief_id)
        ref_pack = self.repo.get_artifact(ref_pack_id)
        if brief is None or ref_pack is None:
            raise ValueError("drafting blocked: missing brief or ref pack")
        system = "你是商业网文写作部门。只输出章节正文，不输出标题、解释、交付说明、部门名或审稿说明。"
        feedback = f"\n\n编辑意见，必须修复：\n{rewrite_feedback}" if rewrite_feedback else ""
        prompt = (
            "请根据四级大纲、本章写作任务和连续性资料写一章小说正文。\n"
            "正文必须有当场压力、主角行动、对手或规则反应、小兑现、代价或新钩子。\n"
            "全书大纲、卷纲、单元纲、世界观和人物关系只用于控制，不得说明书式写入正文。\n"
            f"{feedback}\n\n本章写作任务:\n{brief.content}\n\n连续性资料:\n{ref_pack.content}\n\n只输出章节正文。"
        )
        body = self.llm.complete(system, prompt)
        return self.repo.create_artifact(book_id, chapter_no, "draft", "drafted", body, visibility="draft")
