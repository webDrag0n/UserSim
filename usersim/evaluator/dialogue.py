"""对话质量表层指标：纯字符串统计，0 LLM，不读语义。

边界声明：评估器不评判对话"内容好坏"（那需要语义理解，会破坏 0-LLM 红线），
本模块只测**形态**——复读率、口癖率、session 轮数分布。这些指标不进 benchmark_score，
用于 prompt/机制改动的 before/after 对照与退化回归（R4 实测教训：低温用户复读机、
双向回声死循环，过去只能靠人工抽查存档发现）。
"""

from __future__ import annotations

from difflib import SequenceMatcher

from usersim.contracts import TurnRecord

# 与 runner 复读熔断同阈值：相邻同发言人相似度超过它即计复读
_REPEAT_RATIO = 0.75
# 助手客服腔口癖表：只收纯口癖（"好嘞"与感叹号）——"帮你/安排"是域词汇，
# 真实订单的确认语天然命中（"我帮你订了"），会把事务型 session 误判为腔调问题
_FILLERS = ("好嘞", "！", "!")
# runner 熔断落盘的 system 日志标记
_FUSE_MARK = "复读熔断"


def _similar(a: str, b: str) -> bool:
    return bool(a) and bool(b) and SequenceMatcher(None, a, b).ratio() > _REPEAT_RATIO


def compute_dialogue_stats(turns: list[TurnRecord]) -> dict:
    """输入整 run 的 turn 序列，输出形态指标（全部纯字符串统计）。

    复读率的分母是"同一 session 内同发言人的相邻对"（跨 session 不比：
    隔天说同样的话是人之常情，不构成复读）。
    """
    user_pairs = user_repeat = 0
    asst_pairs = asst_repeat = 0
    asst_total = asst_filler = 0
    fused_sessions = 0
    sess_turns: dict[str, int] = {}

    # 每 session 内按 turn 顺序追踪同发言人上一条文本
    last_in_session: dict[tuple[str, str], str] = {}
    for t in turns:
        if t.session_id:
            sess_turns[t.session_id] = sess_turns.get(t.session_id, 0) + 1
        if t.speaker == "system" and _FUSE_MARK in (t.text or ""):
            fused_sessions += 1
            continue
        if t.speaker not in ("user", "assistant"):
            continue
        key = (t.session_id or "", t.speaker)
        prev = last_in_session.get(key)
        if t.speaker == "user":
            if prev is not None:
                user_pairs += 1
                user_repeat += 1 if _similar(prev, t.text or "") else 0
        else:
            asst_total += 1
            if any(f in (t.text or "") for f in _FILLERS):
                asst_filler += 1
            if prev is not None:
                asst_pairs += 1
                asst_repeat += 1 if _similar(prev, t.text or "") else 0
        last_in_session[key] = t.text or ""

    n_sess = len(sess_turns)
    return {
        "user_repeat_rate": (user_repeat / user_pairs) if user_pairs else None,
        "assistant_repeat_rate": (asst_repeat / asst_pairs) if asst_pairs else None,
        "assistant_filler_rate": (asst_filler / asst_total) if asst_total else None,
        "fused_sessions": fused_sessions,
        "sessions": n_sess,
        "session_turns_mean": (sum(sess_turns.values()) / n_sess) if n_sess else None,
    }
