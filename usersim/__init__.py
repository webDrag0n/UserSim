"""UserSim · 长程用户-手机助手模拟与 Benchmark 系统。

架构边界（AGENT.md 第一公理）：
- world 与 evaluator 禁止任何 LLM 调用；
- 四组件（world / user_agent / assistant_agent / evaluator）只通过 contracts 通信。
"""

__version__ = "0.1.0"
