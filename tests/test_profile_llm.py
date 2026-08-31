"""profile [llm] 覆盖链路回归（0 token）：同实现换模型的对照 profile 必须真正生效。

R6 实测 bug：`_make_harness` 构造 client 时没传 impl spec，reference_pro 静默退回
角色级配置（flash），模型分级对照差点全程跑错对象。
"""

from __future__ import annotations

from usersim.agents.client import _make_harness
from usersim.agents.config import load_impl, load_impl_llm


def test_impl_llm_override_beats_role_config():
    pro = load_impl_llm("assistant", load_impl("assistant", "reference_pro"))
    assert pro.model == "deepseek-v4-pro"
    pro_nm = load_impl_llm("assistant", load_impl("assistant", "reference_nomem_pro"))
    assert pro_nm.model == "deepseek-v4-pro"
    base = load_impl_llm("assistant", load_impl("assistant", "reference"))
    assert base.model == "deepseek-v4-flash"


def test_make_harness_passes_spec_to_client():
    h = _make_harness("reference_pro", None)
    assert h.client.role.model == "deepseek-v4-pro"
    h2 = _make_harness("reference", None)
    assert h2.client.role.model == "deepseek-v4-flash"
