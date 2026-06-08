from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import Settings


class LlmClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self.settings.llm_mode != "zhipu" or not self.settings.zhipu_api_key:
            return self.mock_completion(user_prompt)
        payload = {
            "model": self.settings.zhipu_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.8,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.settings.zhipu_base_url,
            data=data,
            headers={"Authorization": f"Bearer {self.settings.zhipu_api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.zhipu_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Zhipu request failed: {exc}") from exc
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("Zhipu response did not contain choices.")
        return choices[0]["message"]["content"]

    def mock_completion(self, user_prompt: str) -> str:
        if "章节正文" in user_prompt or "draft" in user_prompt.lower():
            return (
                "林砚站在验词台前，木牌上的倒计时只剩三十息。\n\n"
                "考官把他的名册翻到最后一页，红笔压住三个字：无效新生。\n\n"
                "台下有人笑出声，笑声刚冒头，就被校规铃压成一片死静。林砚没有争辩。他盯着那枚红印，忽然伸手，把名册上的“效”字往旁边推了一寸。\n\n"
                "纸面没有破，红印却像被刀背顶住，慢慢歪开。\n\n"
                "“无效？”林砚抬眼，“现在只剩‘无新生’。按你们自己的规矩，名单里没有我，就不能罚我迟到。”\n\n"
                "考官的脸色终于变了。校规铃第二次响起，验词台下方裂开一道黑缝，一枚灰白词条滚到林砚脚边。\n\n"
                "他赢下了三十息，也欠下了第一笔账。"
            )
        return "mock result"

