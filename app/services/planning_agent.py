from __future__ import annotations

import json
import re
from typing import Any

from app.llm import LlmClient
from app.storage.repository import Repository, json_safe


class PlanningAgent:
    def __init__(self, repo: Repository, llm: LlmClient):
        self.repo = repo
        self.llm = llm

    def plan_chapter_batch(self, book_id: int, batch_id: int) -> list[dict[str, Any]]:
        batch = self.repo.get_chapter_batch(batch_id)
        if not batch:
            raise ValueError("章节批次不存在。")
        plans = self.repo.list_chapter_plan_rows(book_id, batch_id)
        if not plans:
            return []
        ctx = self.repo.get_architecture_context(book_id, int(plans[0]["chapter_no"]))
        context = {
            "book": ctx["book"],
            "volume": ctx["volume"],
            "unit": ctx["arc"],
            "characters": ctx["characters"],
            "canon": ctx["canon"],
            "batch": batch,
            "chapters": [{"chapter_no": row["chapter_no"], "title": row["title"]} for row in plans],
            "previous": self._previous_context(book_id, int(plans[0]["chapter_no"])),
        }
        planned = self._mock_plan(context) if self.llm.settings.llm_mode == "mock" else self._llm_plan(context)
        self.repo.apply_planned_chapter_cards(book_id, batch_id, planned)
        return planned

    def _llm_plan(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        system = (
            "你是长篇小说章节规划 Agent。只输出 JSON 数组，不输出解释。"
            "你的任务是把当前单元纲拆成顺序递进的章节细纲，而不是写规则。"
            "每章必须是具体剧情路线，必须服务全书大纲、卷纲和单元纲。"
        )
        user = (
            "请为章节批次生成细纲 JSON 数组。每个对象必须包含："
            "chapter_no,title,unique_task,core_event,progression,character_roles,"
            "antagonist_move,external_pressure,state_change,ending_handoff,"
            "objective,plot_summary,allowed_reveals,forbidden_reveals,pace_limit,target_chars。\n"
            "注意：第 1 章或没有上一章正文时，不要写上一章禁复用规则。不要使用模板句，不要写技术突破等题材专有要求，除非当前书纲明确需要。\n\n"
            f"上下文：\n{json.dumps(json_safe(context), ensure_ascii=False, indent=2)}"
        )
        raw = self.llm.complete(system, user, role="outline")
        data = self._parse_json_array(raw)
        if not data:
            raise ValueError("规划 Agent 没有返回可用章节 JSON。")
        return [self._normalize_plan(item) for item in data]

    def _parse_json_array(self, raw: str) -> list[dict[str, Any]]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("规划 Agent 输出不是数组。")
        return [item for item in data if isinstance(item, dict)]

    def _mock_plan(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        unit = context.get("unit") or {}
        volume = context.get("volume") or {}
        chapters = context.get("chapters") or []
        characters = context.get("characters") or []
        lead = (characters[0] or {}).get("name") if characters else "主角"
        support = "、".join([row.get("name", "") for row in characters[1:3] if row.get("name")]) or "关键同伴"
        unit_goal = unit.get("goal") or "完成当前单元目标"
        cause = unit.get("cause") or unit.get("pressure") or "当前局势出现具体压力"
        process = unit.get("process") or "主角采取行动推动局势"
        result = unit.get("result") or "形成阶段结果"
        stages = [
            ("压力落地", f"{lead}面对{cause}，被迫确认本单元问题已经落到眼前。"),
            ("主动试探", f"{lead}围绕{process}做出第一次主动选择，并让{support}承担一个可见职能。"),
            ("阻力升级", f"外部规则或对手改变条件，使{lead}原本的行动方案付出代价。"),
            ("阶段兑现", f"{lead}用已经取得的信息完成一次阶段处理，让{result}变成可见后果。"),
            ("交接下一步", f"阶段结果暴露新的问题，把故事交接到下一段行动。"),
        ]
        planned = []
        for index, row in enumerate(chapters):
            chapter_no = int(row["chapter_no"])
            label, event = stages[index % len(stages)]
            has_previous = chapter_no > 1 or bool((context.get("previous") or {}).get("body_excerpt"))
            handoff = "承接上一章结尾状态，进入本章行动。" if has_previous else "从本书开局设定进入本章行动。"
            planned.append(
                self._normalize_plan(
                    {
                        "chapter_no": chapter_no,
                        "title": f"第{chapter_no}章 {label}",
                        "unique_task": f"本章完成具体剧情：{event}",
                        "core_event": event,
                        "progression": f"从“{unit_goal}”中抽出一个可见步骤：{process}。",
                        "character_roles": f"{lead}负责行动与判断；{support}负责验证、推动、提醒或制造关系压力。",
                        "antagonist_move": "阻力来自当前单元的规则、对手、资源或时间限制，并在本章改变主角的可选行动。",
                        "external_pressure": volume.get("core_conflict") or unit.get("pressure") or "当前卷核心矛盾落到本章现场。",
                        "state_change": f"本章结束时，局势必须从“{cause}”推进到“{result}”的一个阶段后果。",
                        "ending_handoff": handoff,
                        "objective": f"{event}\n{handoff}",
                        "plot_summary": f"{event}\n{process}\n{result}",
                        "allowed_reveals": "只揭示本章角色通过行动、观察、交易或冲突得到的信息。",
                        "forbidden_reveals": "不得提前完成当前单元、卷或全书目标。",
                        "pace_limit": "按本章细纲推进，不跳过因果，不改写四级纲要。",
                    }
                )
            )
        return planned

    def _normalize_plan(self, item: dict[str, Any]) -> dict[str, Any]:
        def text(*keys: str, default: str = "") -> str:
            for key in keys:
                value = item.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return default

        chapter_no = int(item.get("chapter_no") or 0)
        title = text("title", default=f"第{chapter_no}章 待命名")
        core_event = text("core_event", "event", default="待人工填写本章具体核心事件。")
        objective = text("objective", default=text("unique_task", default=core_event))
        plot_summary = text("plot_summary", "summary", default=core_event)
        return {
            "chapter_no": chapter_no,
            "title": title,
            "objective": objective,
            "allowed_reveals": text("allowed_reveals", default="只揭示本章角色可见、可验证的信息。"),
            "forbidden_reveals": text("forbidden_reveals", default="不得提前完成单元、卷或全书目标。"),
            "pace_limit": text("pace_limit", default="按本章细纲推进，不跳过因果。"),
            "plot_summary": plot_summary,
            "target_chars": int(item.get("target_chars") or 0),
            "unique_task": text("unique_task", default=objective),
            "core_event": core_event,
            "tech_progression": text("progression", "tech_progression", default=""),
            "character_roles": text("character_roles", default=""),
            "antagonist_move": text("antagonist_move", default=""),
            "external_pressure": text("external_pressure", default=""),
            "irreversible_change": text("state_change", "irreversible_change", default=""),
            "ending_hook": text("ending_handoff", "ending_hook", default=""),
            "no_repeat_guard": "",
        }

    def _previous_context(self, book_id: int, chapter_no: int) -> dict[str, str]:
        if chapter_no <= 1:
            return {"body_excerpt": "", "terminal_state": "无上一章。"}
        previous = self.repo.get_chapter_body(book_id, chapter_no - 1)
        if previous:
            body = previous.get("body") or ""
            return {"body_excerpt": body[-1800:], "terminal_state": body[-500:]}
        return {"body_excerpt": "", "terminal_state": "上一章尚无正文。"}
