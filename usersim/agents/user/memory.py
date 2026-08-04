"""用户跨 session 记忆：滚动保留最近 N 个 session 的摘要。"""
from __future__ import annotations
from collections import deque

INTENT_LABELS = {
    "eat": "吃饭", "social": "社交", "stimulate": "找乐子",
    "recover": "休息", "sleep": "睡觉", "achieve": "做正事",
    "emergency": "紧急事项",
}

class UserMemory:
    """跨 session 记忆，注入用户 prompt 以增加连贯性。"""

    def __init__(self, capacity: int = 8):
        self._sessions: deque[dict] = deque(maxlen=capacity)

    def add(self, session_id: str, intent_type: str, turns: int,
            outcome: str = "", day: int = 0) -> None:
        label = INTENT_LABELS.get(intent_type, intent_type)
        self._sessions.append({
            "sid": session_id, "intent": intent_type,
            "label": label, "turns": turns,
            "outcome": outcome, "day": day,
        })

    def prompt_block(self) -> str:
        """格式化为注入 prompt 的文字段落。"""
        if not self._sessions:
            return ""
        lines = []
        for s in list(self._sessions)[-5:]:
            outcome_str = f"，{s['outcome']}" if s['outcome'] else ""
            lines.append(f"- 第 {s['day']+1} 天：{s['label']}{outcome_str}")
        return "【你最近和助手聊过的事】\n" + "\n".join(lines)

    def to_dict(self) -> dict:
        return {"sessions": list(self._sessions)}

    @classmethod
    def from_dict(cls, data: dict, capacity: int = 8) -> "UserMemory":
        m = cls(capacity=capacity)
        for s in data.get("sessions", []):
            m._sessions.append(s)
        return m
