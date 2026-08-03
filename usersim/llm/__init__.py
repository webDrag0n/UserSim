"""llm 包：唯一允许联网的地方（OpenAI 兼容协议）。"""

from usersim.llm.client import LLMClient, LLMError

__all__ = ["LLMClient", "LLMError"]
