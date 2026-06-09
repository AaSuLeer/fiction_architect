from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from app.config import Settings


class LlmClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, system_prompt: str, user_prompt: str, model: str | None = None, role: str = "default") -> str:
        if self.settings.llm_mode == "mock" or not self.settings.llm_api_key:
            return self.mock_completion(user_prompt)
        selected_model = model or self._model_for_role(role)
        if not self.settings.llm_base_url.strip():
            raise RuntimeError("LLM_BASE_URL is not configured for compatible model calls.")
        if not selected_model.strip():
            raise RuntimeError("LLM model is not configured. Set LLM_DEFAULT_MODEL or the role-specific model in .env.")
        payload = {
            "model": selected_model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.82,
        }
        request = urllib.request.Request(
            self.settings.llm_base_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        last_error: BaseException | None = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=self.settings.llm_timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                choices = body.get("choices") or []
                if not choices:
                    raise RuntimeError("LLM response did not contain choices.")
                content = choices[0].get("message", {}).get("content", "")
                if not content.strip():
                    raise RuntimeError("LLM response content was empty.")
                return content
            except (TimeoutError, OSError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt >= 3:
                    raise RuntimeError(f"LLM request failed after {attempt} attempts: {exc}") from exc
                time.sleep(1.5 * attempt)
            except RuntimeError as exc:
                last_error = exc
                if attempt >= 3:
                    raise
                time.sleep(1.5 * attempt)
        raise RuntimeError(f"LLM request failed: {last_error}")

    def _model_for_role(self, role: str) -> str:
        if role == "outline":
            return self.settings.llm_outline_model
        if role == "writer":
            return self.settings.llm_writer_model
        if role == "editor":
            return self.settings.llm_editor_model
        return self.settings.llm_default_model

    def mock_completion(self, user_prompt: str) -> str:
        if "本章写作任务" in user_prompt and "连续性资料" in user_prompt:
            return self._mock_story_from_prompt(user_prompt)
        paragraphs = [
            "林砚站在验词台前，木牌上的倒计时只剩三十息。台下三百名新生全看着他，名单最后一页被红印压住，三个字像钉子一样扎在纸面上：无效新生。",
            "考官把红印往前推了半寸。按废校校规，无效新生不能入门，不能补考，不能申辩；若在铃响前仍站在台上，就按冒名顶替处置，扣掉三年宿数。",
            "有人在下面轻轻笑了一声。笑声刚冒头，校规铃便震了一下，所有人的脸色同时白了。这里连嘲笑都要按次计分，谁多说半句，谁就可能替别人受罚。",
            "林砚没有争。争辩是最便宜的动作，也是最容易被规则抓住的动作。他低头看名册，看红印，看考官拇指上那一圈没有擦净的朱砂，忽然明白这场验词不是核对身份，而是逼他承认身份无效。",
            "他伸手，指尖落在“效”字旁边。旁人只看见他按住纸面，只有林砚自己听见脑子里轻轻一响，像旧门轴被推开。他把那个字往旁边拨了一寸。",
            "纸没有破，墨没有散，红印却偏了。原本压住“无效新生”的印章，被他硬生生挤到了“效”字之外。名册上只剩两个词能连起来读：无新生。",
            "考官眯起眼。“你在改校册？”",
            "林砚抬头，声音不高，却足够让台下听清：“我在读校册。名册里没有我，就不能判我冒名。你若要罚，先证明我在名册里。”",
            "台下那点笑意没了。几个原本等着看热闹的新生同时往前倾。废校规矩冷得像铁，铁也有缝。林砚没有砸开它，只是把一枚钉子拔歪了。",
            "考官的拇指压住红印，朱砂在皮肤上裂出细纹。他当然可以再盖一次，可再盖就等于承认第一次判定不稳。验词台上最忌讳的不是失误，是让所有人看见失误。",
            "倒计时还剩十二息。林砚没有追击，他知道自己现在只赢了半步。能力像一根细线缠在指骨上，刚才那一拨之后，线已经勒进肉里，疼得他掌心发麻。",
            "考官忽然笑了。“好，按校册读。既然没有新生，就先不罚冒名。”",
            "台下有人松了口气，林砚却没有。他听见第二声铃响，这一次不是从台上传来，而是从脚下。验词台中央裂开一道黑缝，一枚灰白色词条滚出来，停在他鞋尖前。",
            "词条上只有四个字：临时有效。",
            "考官把木牌翻过来，倒计时消失，换成一行更小的字：临时资格，三日后复验；若复验失败，今日规避之罚双倍追缴。",
            "这才是废校的规矩。它允许你钻一次空子，然后把空子的价码记在你身上。林砚弯腰捡起词条，指尖碰到灰白边缘时，掌心那道疼忽然变成了烫。",
            "他看见台下第一排，一个穿旧校服的女生对他极轻地摇了下头。不是劝他别拿，而是提醒他，拿了就别回头。",
            "林砚把词条扣进掌心。“三日就三日。”",
            "考官脸上的笑终于淡了。台下的新生也不再把他当笑话看。一个无效新生，在三十息里把处罚改成了资格；这不是胜利，却足够让所有人记住他的名字。",
            "可记住名字不等于认可。林砚刚走下验词台，前排就有人故意伸脚，把一只装着墨砂的铜盆踢到他面前。铜盆没有翻，盆沿却撞出一声脆响，像在提醒所有人：临时有效仍然是临时。",
            "那人笑着说：“新来的，你刚才钻的是考官的空子，不是我们的空子。废校宿舍按资格排位，你这个临时的，今晚睡哪？”",
            "这句话比嘲笑更狠。台下的新生立刻看向门后的石阶。石阶尽头挂着一排木牌，甲乙丙丁一路排到末等，每块木牌后面都对应着床位、饭额和夜巡豁免。没有床位的人，夜里只能留在操场。废校夜巡从不问原因。",
            "林砚掌心还在疼。他没有急着回答，而是看那人腰间的木牌。丙七。位置不高，但足够欺负一个临时新生。木牌边缘溅着一点新墨，和验词台红印下面的黑线一样，都是刚刚登记过的痕迹。",
            "他忽然明白，考官让他下台，不是放过他，而是把他丢进下一道更细的规矩里。这里每一步都有门槛，每个人都能借门槛收一次利息。",
            "林砚抬手，把灰白词条露出来。“睡哪不急。先问清一件事。临时资格算不算资格？”",
            "丙七脸上的笑顿了一下。“算又怎样？”",
            "“算，就能参加排位。不算，你刚才那句‘按资格排位’就是错读校规。”林砚看向石阶旁的灰袍值守，“错读校规要扣谁的分？”",
            "灰袍值守原本像石头一样站着，听见这句，眼皮终于抬了抬。丙七的脸色变了。他想骂，却又不敢在值守面前把话说死。",
            "林砚没有等他开口，直接往石阶走去。每走一步，掌心那枚词条就烫一下，像在数他还能透支多少力气。",
            "他停在丙七旁边，没有抢牌，只伸手点了点木牌下方那行小字：同级挑战，败者退一位；临时资格者只可挑战一次。",
            "丙七冷笑：“你要挑战我？”",
            "“不。”林砚摇头，“我挑战丙八。”",
            "人群安静了一瞬，随即有人忍不住笑。丙八的位置没人，木牌下面只挂着一枚旧锁。挑战空位，赢了也没人可退；按常理，这是浪费唯一机会。",
            "“规则写的是同级挑战，没写必须有人。”林砚把临时词条按在旧锁上，“如果空位不能挑战，木牌就不该挂在这里。它挂着，就得认。”",
            "旧锁咔哒一声开了。笑声像被人掐住，断在半空。",
            "灰袍值守走过来，看了林砚一眼，又看了看丙七。“丙八，临时入住。三日复验失败，床位收回，欠罚并入夜巡。”",
            "林砚把木牌摘下。丙七的表情难看得像吞了砂子，却不能再拦。因为林砚没有赢他，只绕过了他；这种赢法不够痛快，却更让人心里发堵。",
            "走进宿舍前，林砚回头看向验词台。考官还站在那里，远远地望着他，像是在确认一件东西是否真的会自己咬钩。",
            "校门在他身后缓慢打开，门缝里吹出的风带着潮冷的墨味。林砚踏进去前，回头看了一眼名册。那个被他拨歪的“效”字正在一点点爬回原位。",
            "他赢下了入门的一步，也欠下了第一笔账。三日之后，废校会连本带利地来收。",
        ]
        return "\n\n".join(paragraphs)

    def _mock_story_from_prompt(self, user_prompt: str) -> str:
        def field(name: str, default: str = "") -> str:
            match = re.search(rf'"{name}"\s*:\s*"((?:\\.|[^"\\])*)"', user_prompt)
            if not match:
                return default
            try:
                return json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                return match.group(1)

        title = field("chapter_title", field("title", "本章"))
        core_event = field("core_event", "主角执行本章细纲中的核心事件")
        unique_task = field("unique_task", core_event)
        plot_summary = field("plot_summary", core_event)
        progression = field("tech_progression", field("progression", "局势按细纲推进"))
        character_roles = field("character_roles", "主角承担本章行动，关键同伴推动现场变化")
        ending = field("ending_hook", "本章结果自然交接到下一章")
        previous = field("previous_chapter_body", "")
        start = f"上一章的余波还没有散去，{previous[-120:]}" if previous else f"{title}开始时，局势已经压到主角眼前。"
        paragraphs = [
            start,
            f"{core_event}。这不是旁支事件，而是本章必须处理的现场问题。",
            f"主角先确认{unique_task}，随后把注意力落到最能改变局面的证据、人物和行动上。",
            f"{character_roles}。每个人的动作都围绕同一个目标展开，没有离开当前卷纲和单元纲。",
            f"推进链路很清楚：{progression}。主角没有绕开因果，也没有把后文答案提前说完。",
            f"事情的经过继续落到具体选择上：{plot_summary}。",
            "阻力并没有凭空消失，它换成更现实的限制，让主角必须在代价和机会之间做判断。",
            f"到本章末尾，{ending}。正文停在这个结果上，让下一章能够从这里继续。",
        ]
        body = "\n\n".join(paragraphs)
        while len("".join(body.split())) < 1800:
            body += "\n\n" + f"{core_event}继续向前压了一步，主角根据{progression}做出新判断，现场关系和局势因此发生变化。"
        return body
