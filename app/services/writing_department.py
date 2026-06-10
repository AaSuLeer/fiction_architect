from __future__ import annotations

import json

from app.llm import LlmClient
from app.storage.repository import Repository, json_safe


class WritingDepartment:
    """Writer activity.

    The official path consumes construction_packet and writes chapter_draft.
    The old artifact draft method remains only for historical tools/tests.
    """

    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.llm = llm

    def draft(self, book_id: int, chapter_no: int, brief_id: int, ref_pack_id: int, rewrite_feedback: str = ""):
        brief = self.repo.get_artifact(brief_id)
        ref_pack = self.repo.get_artifact(ref_pack_id)
        if brief is None or ref_pack is None:
            raise ValueError("drafting blocked: missing legacy brief/ref_pack")
        system = "你是小说正文写作活动。只输出章节正文，不输出说明、JSON、部门名或交付话术。"
        feedback = f"\n\n编辑返工要求：\n{rewrite_feedback}" if rewrite_feedback else ""
        prompt = (
            "根据旧兼容 brief/ref_pack 写一章正文。旧链路只用于历史兼容，新主链路不会调用它。\n"
            f"{feedback}\n\nbrief:\n{brief.content}\n\nref_pack:\n{ref_pack.content}"
        )
        body = self.llm.complete(system, prompt, role="writer")
        return self.repo.create_artifact(book_id, chapter_no, "draft", "drafted", body, visibility="draft")

    def draft_from_packet(self, book_id: int, chapter_no: int, packet: dict, rewrite_feedback: str = ""):
        if not packet:
            raise ValueError("drafting blocked: missing construction packet")
        packet_text = self._packet_text(packet)
        if getattr(self.llm.settings, "llm_mode", "") == "mock":
            body = self._mock_body_from_packet(packet)
            return self.repo.create_chapter_draft(book_id, chapter_no, packet.get("run_id"), body, packet.get("id"))
        system = (
            "You are the Writer activity inside a long-form fiction workflow. "
            "Write only chapter prose. Do not output plans, reviews, JSON, department notes, or delivery comments."
        )
        feedback = f"\n\nEditor rework ticket:\n{rewrite_feedback}" if rewrite_feedback else ""
        prompt = (
            "The construction_packet is binding.\n"
            "Priority: chapter_task > optional_prev_excerpt > recent_transitions > active_unit_state > hard_constraints > style_pack.\n"
            "If optional_prev_excerpt is empty, treat this as chapter 1 or no published previous chapter. Do not invent a previous chapter.\n"
            "If optional_prev_excerpt exists, continue from the previous ending without resetting permissions, relationships, location, or completed outcomes.\n"
            "Fulfill mission, scene_route, definition_of_done, irreversible_change, and handoff_to_next.\n"
            "Use outlines and worldbuilding as controls, not exposition blocks.\n"
            "Output natural novel prose only."
            f"{feedback}\n\nconstruction_packet:\n{packet_text}"
        )
        body = self.llm.complete(system, prompt, role="writer")
        return self.repo.create_chapter_draft(book_id, chapter_no, packet.get("run_id"), body, packet.get("id"))

    def _packet_text(self, packet: dict) -> str:
        content = packet.get("content")
        if isinstance(content, str):
            return content
        return json.dumps(json_safe(packet), ensure_ascii=False, indent=2)

    def _mock_body_from_packet(self, packet: dict) -> str:
        data = self._packet_data(packet)
        task = data.get("chapter_task") or {}
        active_state = data.get("active_unit_state") or {}
        unit = active_state.get("unit") or {}
        plan = active_state.get("chapter_plan") or {}
        prev = data.get("optional_prev_excerpt") or ""
        mission = str(task.get("mission") or plan.get("unique_task") or "主角处理当前压力")
        route = str(task.get("scene_route") or task.get("core_event") or plan.get("core_event") or mission)
        done = str(task.get("definition_of_done") or plan.get("objective") or mission)
        change = str(task.get("irreversible_change") or plan.get("irreversible_change") or "局势出现不可逆变化")
        hook = str(task.get("handoff_to_next") or plan.get("ending_hook") or "新的问题被留到下一章")
        roles = str(plan.get("character_roles") or task.get("character_roles") or unit.get("character_change") or "主角负责行动与判断，关键同伴推动局势")
        pressure = str(unit.get("pressure") or "眼前压力已经落到现场")
        target_chars = int(plan.get("target_chars") or 1800)

        paragraphs = [
            f"{prev[-160:] if prev else '开局的压力没有给主角太多缓冲。'} {pressure}，所有人都在等一个结果，主角却先看见了被忽略的缝隙。",
            f"{mission}。这不是一句口号，而是本章现场真正要解决的事：{route}。",
            f"主角没有急着解释设定，他先做出判断，再把证据、行动和代价一步步摆到场上。{roles}",
            "阻力没有消失，反而换了一种方式压下来。主角每推进一步，都必须回答一个更具体的问题：为什么现在做，为什么由他做，失败后谁来承担。",
            f"{done}。这组结果让局势不再停在原地，至少有一个人、一个资源或一个判断被迫改变。",
            f"到了章末，{change}。主角知道自己没有赢完整场仗，只是把故事推到了下一扇门前。",
            f"{hook}",
        ]
        body = "\n\n".join(paragraphs)
        filler = (
            f"他把刚才发生的一切重新压回眼前的行动里，没有解释给旁人听，只把下一步做得更具体。"
            f"{mission} 仍然压在这里，{route} 也没有被跳过。现场的沉默、对手的犹豫、同伴的反应和规则的压力同时落下，"
            f"逼着这个选择变成无法撤回的结果。"
        )
        while len("".join(body.split())) < max(1200, target_chars - 120):
            body += "\n\n" + filler
        return body

    def _packet_data(self, packet: dict) -> dict:
        content = packet.get("content")
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {}
        return packet
