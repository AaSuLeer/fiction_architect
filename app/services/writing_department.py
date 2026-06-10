from __future__ import annotations

import json

from app.llm import LlmClient
from app.storage.repository import Repository, json_safe


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
            "优先级：本章细纲 > 上一章结尾状态 > 当前单元纲 > 当前卷纲 > 全书大纲 > 连续性事实。\n"
            "如果连续性资料中 previous_chapter_body 为空，说明这是首章或前文缺失，不要编造上一章。\n"
            "如果 previous_chapter_body 不为空，必须从上一章最后状态自然续写，不得重置场景、权限、人物关系或已经完成的结果。\n"
            "正文必须执行本章细纲指定的核心事件、人物职能、推进链路和结尾交接，不得自行改写题材、主线、地点、人物关系或章节目标。\n"
            "正文长度必须接近本章目标字数，低于目标 500 字以上会被退稿。\n"
            "全书大纲、卷纲、单元纲、世界观和人物关系只用于控制，不得说明书式写入正文。\n"
            f"{feedback}\n\n本章写作任务:\n{brief.content}\n\n连续性资料:\n{ref_pack.content}\n\n只输出章节正文。"
        )
        body = self.llm.complete(system, prompt, role="writer")
        return self.repo.create_artifact(book_id, chapter_no, "draft", "drafted", body, visibility="draft")

    def draft_from_packet(self, book_id: int, chapter_no: int, packet: dict, rewrite_feedback: str = ""):
        if not packet:
            raise ValueError("drafting blocked: missing construction packet")
        content = packet.get("content")
        if isinstance(content, str):
            packet_text = content
        else:
            packet_text = json.dumps(json_safe(packet), ensure_ascii=False, indent=2)
        system = (
            "You are the Writer in a long-form fiction production state machine. "
            "Write only chapter prose. Do not output plans, department notes, reviews, JSON, or delivery comments."
        )
        feedback = f"\n\nEditor rewrite ticket to fix:\n{rewrite_feedback}" if rewrite_feedback else ""
        prompt = (
            "Use the construction_packet as the binding work order.\n"
            "Priority: chapter_task > optional_prev_excerpt/previous_terminal_state > active_unit_state > hard_constraints > style_pack.\n"
            "If optional_prev_excerpt is empty, this is chapter 1 or there is no published previous chapter. Do not invent a previous chapter.\n"
            "If optional_prev_excerpt is present, continue from its ending state and do not reset permissions, relationships, locations, or completed outcomes.\n"
            "The chapter must fulfill the mission, scene_route, definition_of_done, irreversible_change, and handoff_to_next in chapter_task.\n"
            "Worldbuilding and outline information are controls, not exposition blocks.\n"
            "Output natural novel prose only.\n"
            f"{feedback}\n\nconstruction_packet:\n{packet_text}"
        )
        if getattr(self.llm.settings, "llm_mode", "") == "mock":
            body = self._mock_body_from_packet(packet)
            return self.repo.create_chapter_draft(book_id, chapter_no, packet.get("run_id"), body, packet.get("id"))
        body = self.llm.complete(system, prompt, role="writer")
        return self.repo.create_chapter_draft(book_id, chapter_no, packet.get("run_id"), body, packet.get("id"))

    def _mock_body_from_packet(self, packet: dict) -> str:
        if isinstance(packet.get("content"), str):
            try:
                data = json.loads(packet["content"])
            except json.JSONDecodeError:
                data = {}
        else:
            data = packet
        task = data.get("chapter_task") or {}
        active_state = data.get("active_unit_state") or {}
        unit = active_state.get("unit") or {}
        plan = active_state.get("chapter_plan") or {}
        prev = data.get("optional_prev_excerpt") or ""
        mission = task.get("mission") or "主角处理当前压力"
        route = task.get("scene_route") or mission
        done = task.get("definition_of_done") or ""
        change = task.get("irreversible_change") or "局势出现不可逆变化"
        hook = task.get("handoff_to_next") or "新的问题被留到下一章"
        roles = plan.get("character_roles") or task.get("character_roles") or unit.get("character_change") or "主角负责行动与判断，关键同伴推动局势。"
        target_chars = int(plan.get("target_chars") or 1800)
        pressure = unit.get("pressure") or "眼前压力已经落到现场"
        paragraphs = [
            f"{prev[-160:] if prev else '开局的压力没有给主角太多缓冲。'} {pressure}，所有人都在等一个结果，主角却先看见了被忽略的缝隙。",
            f"{mission}。这不是一句口号，而是本章现场真正要解决的事：{route}。",
            f"主角没有急着解释设定，他先做出判断，再把证据、行动和代价一步步摆到场上。{roles}",
            f"阻力没有消失，反而换了一种方式压下来。主角每推进一步，都必须回答一个更具体的问题：为什么现在做，为什么由他做，失败后谁来承担。",
            f"{done}。这组结果让局势不再停在原地，至少有一个人、一个资源或一个判断被迫改变。",
            f"到了章末，{change}。主角知道自己没有赢完整场仗，只是把故事推到了下一扇门前。",
            f"{hook}",
        ]
        body = "\n\n".join(paragraphs)
        while len("".join(body.split())) < max(1200, target_chars - 120):
            body += "\n\n" + "他把刚才发生的一切重新压回眼前的行动里，没有解释给旁人听，只把下一步做得更具体。现场的沉默、对手的犹豫、同伴的反应和制度的压力同时落下，逼着这个选择变成无法撤回的结果。"
        return body
