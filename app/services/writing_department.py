from __future__ import annotations

import json

from app.llm import LlmClient
from app.storage.repository import Repository


class WritingDepartment:
    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.llm = llm

    def draft(self, book_id: int, chapter_no: int, brief_id: int, ref_pack_id: int):
        brief = self.repo.get_artifact(brief_id)
        ref_pack = self.repo.get_artifact(ref_pack_id)
        if brief is None or ref_pack is None:
            raise ValueError("drafting blocked: missing brief or ref pack")
        system = (
            "你是商业男频网文写作部门。只输出章节正文，不输出解释、交付说明、部门名、审稿说明。"
            "大纲和细纲只用于控制节奏，不得以说明书形式写入正文。"
            "必须严格遵守 author_brief 中的人称策略。必须写成有起因、经过、结果的小说章节。"
        )
        prompt = (
            "请根据 author_brief 和 continuity ref_pack 写一章正文。\n"
            "章节正文必须有当场压力、主角行动、对手反应、小兑现和未解代价。\n"
            "必须尽量满足 author_brief 中的 target_chars_min 和 target_chars_max。\n"
            "正文禁止写作说明，禁止只写设定或气氛；人称以 author_brief 的 pov_policy 为准。\n"
            f"author_brief:\n{brief.content}\n\nref_pack:\n{ref_pack.content}\n\n只输出章节正文。"
        )
        body = self.llm.complete(system, prompt)
        return self.repo.create_artifact(book_id, chapter_no, "draft", "drafted", body, visibility="draft")
