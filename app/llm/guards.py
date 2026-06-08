from __future__ import annotations

from dataclasses import dataclass


FORBIDDEN_BODY_TERMS = [
    "交付",
    "审稿通过",
    "根据规则",
    "连续性工作室",
    "作者部",
    "写作部门",
    "编辑部门",
    "比上一章更稳",
    "pipeline",
    "ref pack",
    "brief",
]

EXPOSITION_TERMS = [
    "世界观是",
    "人物关系为",
    "设定说明",
    "这里需要说明",
    "这个系统的规则如下",
]


@dataclass(frozen=True)
class ContaminationResult:
    passed: bool
    problems: list[str]


class TextGuard:
    def check_body(self, body: str) -> ContaminationResult:
        problems: list[str] = []
        for term in FORBIDDEN_BODY_TERMS:
            if term in body:
                problems.append(f"正文污染：出现部门或交付话术 `{term}`")
        for term in EXPOSITION_TERMS:
            if term in body:
                problems.append(f"说明书式写作：出现 `{term}`")
        long_paragraphs = [part for part in body.split("\n\n") if len(part) > 420]
        if long_paragraphs:
            problems.append("AI味风险：存在过长段落，容易变成设定说明或整齐模板。")
        if body.count("。") < 6:
            problems.append("章节过薄：正文动作、反应和代价不足。")
        return ContaminationResult(not problems, problems)

