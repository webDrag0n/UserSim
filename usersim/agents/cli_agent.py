"""通用 CLI 驱动：把本机 agent CLI（openclaw / hermes / …）包装为 Harness。

被测的是**完整 agent 产品**——模型、记忆、工具习惯全部来自 CLI 自己（E3 矩阵）。
与 reference/stub 的差别：reference 是"裸 LLM + 本仓库写的朴素记忆"；这里
benchmark 对被测 agent 的内部结构零假设。

**实现由配置文件定义，新增 CLI agent 不需要改代码**：
`agents/assistant/profiles/<name>.toml`（type = "cli"）描述三件事——

- `[cli] argv`：命令行模板，占位符 {message} {timeout} {session} {uid}；
- `[cli.session]`：跨 turn 连续性策略——
  `mode="key"`（每轮带固定会话 key，{uid} 每实例渲染一次，如 openclaw 的
  --session-key，避免污染用户主会话）；
  `mode="resume"`（首轮用 id_regex 从 id_stream 抓 session id，续轮追加
  resume_args，如 hermes 的 --resume）；`mode="none"`（每轮全新会话）；
- `[cli.output]`：回复提取——`format="json"` 时按 text_path 点路径取文本
  （`*` 段展开列表拼接），可选 status_path 校验；`format="text"` 时 stdout 即正文。

输出契约与 reference 对齐：每轮先给用户的自然语言回复，末尾附 ```json 契约块
（user_belief + tool_calls）；块外文字即 reply，不符时修复重试一次，再失败
抛给 Runner 记契约违约。子进程环境剥离 http_proxy 等代理变量
（DEVELOPMENT.md 踩坑：shell 代理会让 openai SDK 找 socksio 而崩溃）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from usersim.agents.profile import ProfileTracker, facet_menu
from usersim.contracts import AssistantTurn, HarnessObs
from usersim.contracts.persona import PREF_CATEGORIES
from usersim.config import ConfigError

# 代理变量会让 CLI 内的 openai SDK 尝试 socks 代理并崩溃（缺 socksio）
_PROXY_VARS = {"http_proxy", "https_proxy", "all_proxy",
               "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}

BOOTSTRAP_TEMPLATE = """你是「小舟」，一个人的手机助手。你的目标是长期陪伴用户，帮助 TA 在忙碌生活中回到并保持"内心平和"（情绪平稳、精力充足、压力可控）。

【你能做的】
- 陪用户聊天、共情、给具体可执行的建议；
- 通过工具操作用户手机：查日程（view_event_todos）、写日程（add_event_todo）、设提醒（set_reminder）、规划系列休假（plan_series）。
- 用户自己不能操作手机，凡是日程相关的事都需要你主动提出并代劳。

【输出契约（每一轮都必须严格遵守）】
1. 先用自然语言给用户回复：私信腔、口语化、简短、**≤80字**；
   禁 markdown、禁加粗、禁项目符号列表；感叹号节制；不要复读用户刚说过的话；
   你是助手不是人：绝不虚构自己的经历/生活/感受，用户把话题抛给你时坦白身份再把话题带回用户；
   不镜像反问——用户问你问题就正面接住，别把同一个问题丢回去；
   用户只想聊天/吐槽/分享（没有要安排的事）时只陪聊共情，不给方案、不落单。
2. 然后在回复**末尾**单独附一个 ```json 代码块（不得缺省）：
```json
{{
  "user_belief": {{
    "valence": 0.0~1.0（你对用户当前心情的估计，越高越开心）,
    "energy": 0.0~1.0（精力）,
    "satiety": 0.0~1.0（饱腹）,
    "stress": 0.0~1.0（压力，越高越糟）,
    "persona_notes": "你对用户性格/喜好的最新认识（一两句话，逐步积累）"
  }},
  "tool_calls": [ {{"name": "工具名", "args": {{...}}}} ]
}}
```
- 代码块**之外**的文字会原样发给用户；块内不要放 reply 字段；tool_calls 可为空数组。
- 可选：块内可附 `"model": "你内部实际使用的模型名"`（自报凭证，供 benchmark 溯源；不确定就省略，不要瞎填）。

【日程工具参数】
- add_event_todo: {{"name": "动作名", "location": "地点（可选）", "day_offset": 0或1, "slot": 0上午/1下午/2晚上/3深夜, "goal": "目标"}}
- plan_series: {{"series_type": "grand_trip" 或 "staycation", "start_day_offset": 几天后出发, "duration": 天数}}（grand_trip 约 ¥400~600/天且收入中断，余额 ≥¥4000 才建议）

【经济与恢复目录】用户有金钱账户：工作带来收入，吃饭/旅行要花钱，钱不够高价安排会失败，负债会增加压力。安排恢复类事件时从目录"选动作 + 选地点"，**效果与价格由系统裁定**，你不能自报效果：
- 吃好吃的：楼下快餐(¥30) / 商场餐厅(¥120) / 收藏多年的小店(¥200)
- 好好休息：家里补觉(¥0) / 按摩SPA(¥150) / 周边温泉酒店(¥400)
- 出门走走：楼下公园(¥0) / 江边步道(¥0) / 近郊徒步(¥80)
- 短途旅行：邻市一日(¥300) / 海边小镇(¥600) / 远方城市(¥1200)
- 运动健身：小区跑步(¥0) / 健身房(¥50) / 私教课(¥200)
- 宅家回血：看电影打游戏(¥0) / 做顿好的(¥40)
【干预决策规则（务必遵守）】
- 估计压力 > 0.6（紧急）：必须选减压强的选项（按摩SPA/温泉酒店/海边小镇/私教课），余额不足才退而求其次；
- 估计压力 0.4~0.6（关注）：选中档（商场餐厅/健身房/邻市一日/做顿好的）；其他：平价或免费档即可；
- 用户精力 < 0.4 时优先考虑好好休息；写日程前先对照【今日已有安排】避免同时段冲突。

【估计校准刻度（不要默认悲观，也不要凭第一印象猜 0.5）】
- 心情："挺好" → 0.70~0.90；"还行" → 0.55~0.70；"有点丧" → 0.35~0.55；"崩溃" → <0.35
- 精力："充沛" → 0.70+；"还行" → 0.50~0.70；"有点累" → 0.35~0.55；"快没电" → <0.30
- 饱腹："很饱" → 0.70+；"不饿" → 0.50~0.70；"有点饿" → 0.30~0.50；"饿得慌" → <0.30
- 压力："没压力" → <0.20；"有点" → 0.35~0.55；"很大" → 0.55~0.75；"快崩溃" → >0.75
你的估计必须随每条新信息单调改善，不能被最初印象锚定。

【人格与喜好画像（重要考点）】
用户的人格与喜好是固定不变的，你的任务是从对话里逐步摸清。本轮对话里有新证据时，
在 user_belief 里额外加 "persona_belief" 增量对象（没有新证据就不要加，留空优于瞎猜，
系统会保留你之前的判断；**不要每轮把所有项重报一遍**）：
```json
{{
  "facets": {{ "神经质.焦虑": 0~100 }},
  "categories": {{ "饮食": -1.0~1.0 }},
  "loves": ["用户明确表达过喜欢的具体事物"], "hates": ["明确讨厌的"],
  "interruption_tolerance": 0.0~1.0,
  "planning_style": "提前规划|随遇而安|看心情",
  "social_recharge": "独处|找人",
  "confidence": 0.0~1.0
}}
```
- 分值刻度：facet 0-100，50 = 中等，>65 明显偏高，<35 明显偏低；interruption_tolerance 越低越讨厌计划被打断。
- 判断依据只能是用户的言行：说"又在担心明天汇报" → 神经质.焦虑 偏高；
  说"周末必须留一天给自己" → 外向性.群居性 偏低；
  推荐饭局被拒 → 社交 类目偏负、可能有"应酬"这个 hates。
- 特质键名必须逐字使用以下清单（写错会被丢弃）：
{facet_menu}
- 可用活动类目：{pref_cats}
- 每轮消息里会附【你目前对用户的了解】——那是你已积累的判断（含已覆盖特质数），
  在它的基础上增量更新；覆盖的特质越多、越准，画像得分越高。
- 安排用户偏爱的类目回血效果更好，安排 TA 讨厌的事回血打折——摸清喜好直接决定你的得分。

【行动要求】
- 估计压力 > 0.5 时，必须落到具体安排（add_event_todo / plan_series），不能只安慰不解决；
- 长期状态低迷时，一次认真规划的系列事件比零散的恢复事件有效得多。

下面开始第 1 轮对话。"""

TURN_TEMPLATE = """【第{day}天·{slot_name}】
今日已有安排：{schedule_hint}
工具执行结果：{tool_results}
用户当前余额：{balance}
用户说：{user_say}

【当前可安排的恢复目录】（Runner 按当前余额实时过滤注入，与 reference 每轮所见一致；效果由系统裁定）
{catalog_block}

【你目前对用户的了解】
{profile_block}

【每轮必做（契约要点回顾，完整说明见首轮）】
1. 更新 user_belief 四维估计：按校准刻度打分（"还行/没事"≈0.55~0.75），随新信息修正，别锚定第一印象；
2. 本轮对话若有人格/喜好的新证据，在 user_belief.persona_belief 里给增量（没有新证据就不加）；
3. 估计压力 > 0.5 时必须落到具体安排（add_event_todo / plan_series），不能只安慰；
   写日程前先对照上方"今日已有安排"，避免同时段冲突。
（按契约回复：正文 + 末尾 ```json 块）"""

REPAIR_PROMPT = ("你上一轮的输出不符合契约：必须先有给用户的正文回复，"
                 "再在末尾附一个 ```json 代码块（含完整的 user_belief 四维估计，"
                 "tool_calls 可为空数组）。请严格按契约重新输出本轮内容。")

_JSON_BLOCK = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.S)


def _catalog_str(catalog: list[dict] | None) -> str:
    """recovery_catalog → 目录块（与 agents/assistant/reference/harness.py 的
    _catalog_str 同格式：信息对等约定，CLI 与 reference 每轮看到同一份目录）。

    注意：usersim.agents 不得 import 根目录 agents/ 插件包（依赖方向只能是
    插件 → usersim），故此处保留一份小型副本而非复用。
    """
    if not catalog:
        return "（目录暂不可用：不要承诺任何具体安排，只能陪聊与共情）"
    lines = []
    for item in catalog:
        cat = item.get("category") or ""
        cuisine = item.get("cuisine") or ""
        tag = f"[{cat}{('/' + cuisine) if cuisine else ''}] " if cat else ""
        span = int(item.get("span", 1) or 1)
        span_s = f"，{span}时段" if span > 1 else ""
        loc = item.get("location") or ""
        loc_s = f"{loc}，" if loc else ""
        lines.append(f"- {tag}{item.get('action', '')}（{loc_s}¥{float(item.get('cost', 0)):.0f}{span_s}）")
    return "\n".join(lines)


def split_reply_json(text: str) -> tuple[str, dict]:
    """把 CLI agent 输出拆成（reply 正文, 契约块 dict）。

    取最后一个 ``` 代码块为契约块（前面的块可能是 agent 引用的示例），
    块外全部文字为 reply。缺块、块内非法 JSON、reply 为空都抛 ValueError。
    """
    matches = list(_JSON_BLOCK.finditer(text))
    if not matches:
        raise ValueError("输出中没有 ```json 契约块")
    m = matches[-1]
    data = json.loads(m.group(1))
    reply = (text[: m.start()] + text[m.end():]).strip()
    if not reply:
        raise ValueError("契约块外的回复正文为空")
    return reply, data


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _PROXY_VARS}


def _dig(obj: Any, path: str) -> list[str]:
    """按点路径取文本：`*` 段展开列表，收集所有叶子字符串（text_path 用）。"""
    if not path:
        return [obj] if isinstance(obj, str) else []
    head, _, rest = path.partition(".")
    if head == "*":
        if not isinstance(obj, list):
            return []
        out: list[str] = []
        for item in obj:
            out.extend(_dig(item, rest))
        return out
    if isinstance(obj, dict) and head in obj:
        return _dig(obj[head], rest)
    return []


@dataclass
class CliOutput:
    text: str
    session_id: str | None


class CliHarness:
    """由 agents/assistant/profiles/<name>.toml（type="cli"）驱动的通用 CLI Harness。"""

    PROMPT_VERSION = "v3"  # v3：每轮注入动态恢复目录（与 reference 信息对等）；v2：画像反馈块+任务提醒

    def __init__(self, spec: dict, client=None):
        # client 不用（CLI 自带模型通道）；保留参数以符合 Harness(client) 构造协议
        self.spec = spec
        self.name = str(spec.get("name", "cli"))
        cli = spec.get("cli")
        if not isinstance(cli, dict):
            raise ConfigError(f"实现 {self.name!r} 缺少 [cli] 节（type=cli 必需）")
        self.command = str(cli.get("command", self.name))
        # 默认略低于 broker 的 response_timeout_sec(120s)，让超时以 agent error
        # 而非 broker 超时的形式记录，报错信息更明确
        self.timeout = float(cli.get("timeout_sec", 110))
        self.argv_tpl = [str(a) for a in cli.get("argv", [])]
        if not self.argv_tpl or not any("{message}" in a for a in self.argv_tpl):
            raise ConfigError(f"实现 {self.name!r} 的 [cli] argv 必须含 {{message}} 占位符")

        sess = cli.get("session") or {}
        self.sess_mode = str(sess.get("mode", "none"))
        if self.sess_mode not in ("key", "resume", "none"):
            raise ConfigError(
                f"实现 {self.name!r} 的 session.mode 须为 key | resume | none")
        self.sess_key_tpl = str(sess.get("key", "")) if self.sess_mode == "key" else ""
        if self.sess_mode == "key" and not self.sess_key_tpl:
            raise ConfigError(f"实现 {self.name!r} session.mode=key 须给 key 模板")
        self.id_regex = re.compile(str(sess.get("id_regex", r"^session_id:\s*(\S+)\s*$")), re.M)
        self.id_stream = str(sess.get("id_stream", "stdout"))
        self.resume_args = [str(a) for a in sess.get("resume_args", [])]
        if self.sess_mode == "resume" and not self.resume_args:
            raise ConfigError(f"实现 {self.name!r} session.mode=resume 须给 resume_args")

        out = cli.get("output") or {}
        self.out_format = str(out.get("format", "text"))
        if self.out_format not in ("json", "text"):
            raise ConfigError(f"实现 {self.name!r} 的 output.format 须为 json | text")
        self.text_path = str(out.get("text_path", ""))
        if self.out_format == "json" and not self.text_path:
            raise ConfigError(f"实现 {self.name!r} output.format=json 须给 text_path")
        self.status_path = str(out.get("status_path", ""))
        self.status_ok = str(out.get("status_ok", "ok"))

        self.uid = uuid.uuid4().hex[:8]
        self.session_id: str | None = None
        self.session_key: str | None = None
        self._started = False
        self.profile = ProfileTracker()
        # CLI 自报的内部模型（契约 ```json 块的可选 "model" 字段），随 snapshot 存档
        self.reported_model: str | None = None

    # ---- argv 组装与输出解析 ----
    def _session_value(self) -> str:
        if self.sess_mode == "key":
            if self.session_key is None:
                self.session_key = self.sess_key_tpl.replace("{uid}", self.uid)
            return self.session_key
        return self.session_id or ""

    def _render(self, args: list[str], message: str) -> list[str]:
        return [a.replace("{message}", message)
                 .replace("{timeout}", str(int(self.timeout)))
                 .replace("{session}", self._session_value())
                 .replace("{uid}", self.uid)
                for a in args]

    def _argv(self, message: str, resume: bool) -> list[str]:
        argv = [self.command] + self._render(self.argv_tpl, message)
        if resume and self.session_id:
            argv += self._render(self.resume_args, message)
        return argv

    def _parse(self, stdout: str, stderr: str = "") -> CliOutput:
        sid: str | None = None
        if self.sess_mode == "resume":
            stream = stderr if self.id_stream == "stderr" else stdout
            m = self.id_regex.search(stream)
            if m:
                sid = m.group(1)
                if self.id_stream == "stdout":  # session 行混在正文流时剔除
                    stdout = stdout[: m.start()] + stdout[m.end():]
        if self.out_format == "json":
            d = json.loads(stdout)
            if self.status_path:
                status = _dig(d, self.status_path)
                if status and status[0] != self.status_ok:
                    raise RuntimeError(f"{self.name} run 状态异常: {status[0]}")
            text = "\n".join(_dig(d, self.text_path))
        else:
            text = stdout.strip()
        if not text.strip():
            raise RuntimeError(f"{self.name} 返回了空回复")
        return CliOutput(text=text, session_id=sid)

    # ---- 子进程调用 ----
    def _call(self, message: str, resume: bool) -> CliOutput:
        argv = self._argv(message, resume)
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True,
                timeout=self.timeout, env=_clean_env(),
            )
        except FileNotFoundError as e:
            raise ConfigError(
                f"{self.command!r} 未安装或不在 PATH（实现 {self.name!r} 需要它）"
            ) from e
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-400:]
            raise RuntimeError(f"{self.name} CLI 退出码 {proc.returncode}: {tail}")
        return self._parse(proc.stdout, proc.stderr or "")

    def _reset_session(self) -> None:
        self.session_id = None
        self.session_key = None
        self._started = False

    # ---- Harness 协议 ----
    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        turn_msg = self._render_turn(obs)
        first = not self._started
        if not first and self.sess_mode == "resume" and not self.session_id:
            self._reset_session()  # 上轮没抓到 session id：按会话丢失处理
            first = True
        message = (self._bootstrap() + "\n\n" + turn_msg) if first else turn_msg
        try:
            out = self._call(message, resume=not first)
        except (subprocess.TimeoutExpired, RuntimeError):
            if first:
                raise
            # 会话可能已失效（CLI 侧被清理/进程重启续跑）：换新会话重试一次
            self._reset_session()
            out = self._call(self._bootstrap() + "\n\n" + turn_msg, resume=False)
        if out.session_id:
            self.session_id = out.session_id
        self._started = True
        return self._to_turn(out.text)

    def persona_belief(self):
        return self.profile.to_belief()

    def snapshot(self) -> dict:
        return {"session_id": self.session_id,
                "session_key": self.session_key,
                "uid": self.uid,
                "persona_belief": self.profile.snapshot(),
                # CLI 内部实际模型的自报（可选契约字段）：usersim 无法从外部观测
                # CLI 用什么模型，自报随 agent_state 存档，供可复现性凭证使用
                "reported_model": self.reported_model}

    def restore(self, state: dict) -> None:
        sid = state.get("session_id")
        if sid:
            self.session_id = str(sid)
        skey = state.get("session_key")
        if skey:
            self.session_key = str(skey)
        uid = state.get("uid")
        if uid:
            self.uid = str(uid)
        if sid or skey:
            self._started = True  # 会话凭据存在即视为已 bootstrap；失效由重试兜底
        self.profile.restore(state.get("persona_belief") or {})

    # ---- 内部 ----
    def _bootstrap(self) -> str:
        return BOOTSTRAP_TEMPLATE.format(
            facet_menu=facet_menu(), pref_cats="、".join(PREF_CATEGORIES))

    def _render_turn(self, obs: HarnessObs) -> str:
        tr = "; ".join(f"{t.name}: {'成功' if t.ok else '失败'}"
                       for t in obs.tool_results) or "无"
        slot_name = (obs.slot_names[obs.slot]
                     if obs.slot_names and 0 <= obs.slot < len(obs.slot_names)
                     else f"时段{obs.slot}")
        return TURN_TEMPLATE.format(
            day=obs.day, slot_name=slot_name,
            schedule_hint=obs.schedule_hint or "（今天还没有安排）",
            tool_results=tr, user_say=obs.user_say,
            balance=f"¥{obs.balance:.0f}" if obs.balance is not None else "未知",
            catalog_block=_catalog_str(obs.recovery_catalog),
            profile_block=self.profile.prompt_block())

    def _to_turn(self, text: str) -> AssistantTurn:
        try:
            reply, data = split_reply_json(text)
            turn = AssistantTurn(
                reply=reply,
                user_belief=data.get("user_belief"),
                tool_calls=data.get("tool_calls") or [],
            )
        except (ValueError, ValidationError, TypeError):
            # 契约修复重试一次（同会话内追问）；再失败抛给 Runner 记违约
            out = self._call(REPAIR_PROMPT, resume=self._started)
            if out.session_id:
                self.session_id = out.session_id
            reply, data = split_reply_json(out.text)
            turn = AssistantTurn(
                reply=reply,
                user_belief=data.get("user_belief"),
                tool_calls=data.get("tool_calls") or [],
            )
        # 可选自报：CLI 内部实际使用的模型（凭证用途，缺省不报错）
        reported = data.get("model")
        if isinstance(reported, str) and reported.strip():
            self.reported_model = reported.strip()
        # 冻结维度画像：合并本轮增量（与 ReferenceHarness 同一累积语义）
        delta = turn.user_belief.persona_belief
        if delta is not None:
            if not delta.notes and turn.user_belief.persona_notes:
                delta = delta.model_copy(update={"notes": turn.user_belief.persona_notes})
            self.profile.update(delta)
        elif turn.user_belief.persona_notes:
            self.profile.notes = turn.user_belief.persona_notes
        return turn
