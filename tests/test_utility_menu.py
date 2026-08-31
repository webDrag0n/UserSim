"""R7 边际效用感知通道测试（0 token）：utility_menu 档位、确定性与 prompt 注入。"""

from __future__ import annotations

from agents.user.standard.llm_user import LLMUserAgent
from usersim.config import load_system_config
from usersim.contracts import EventContext, UserContext
from usersim.world.world import World


def _world(seed=7, days=5) -> World:
    return World(seed=seed, days=days, cfg=load_system_config())


def test_utility_menu_empty_at_start():
    w = _world()
    menu = w.utility_menu()
    assert len(menu) == 1 and menu[0].startswith("还没试过的："), "开局无执行记录时应只有没试过清单"
    assert "自定义活动" not in menu[0]
    assert "出门走走" in menu[0]  # 规范动作键入选


def test_utility_menu_tiers_reflect_habituation():
    w = _world()
    # 同一活动刚执行 → 权重触底（腻了）；另一个很久以前执行 → 恢复新鲜
    w._last_done = {"出门走走": w.t, "文化看展": w.t - 999}
    menu = w.utility_menu()
    by_name = {line.split("——")[0]: line for line in menu if "——" in line}
    assert "已经腻了" in by_name["出门走走"]
    assert "还很新鲜" in by_name["文化看展"]
    # 最腻的排最前
    assert menu[0].startswith("出门走走")
    # 两者都已执行 → 不再出现在"没试过"
    fresh_line = [l for l in menu if l.startswith("还没试过的")]
    assert fresh_line and "出门走走" not in fresh_line[0] and "文化看展" not in fresh_line[0]


def test_utility_menu_deterministic():
    a, b = _world(seed=9), _world(seed=9)
    a._last_done = b._last_done = {"出门走走": 3, "音乐放松": 8}
    assert a.utility_menu() == b.utility_menu()


def test_contexts_carry_utility_menu():
    ec = EventContext(t_logical=0, day=0, slot=0, slot_name="上午",
                      utility_menu=["出门走走——已经腻了，基本没什么用"])
    assert ec.utility_menu and EventContext(
        t_logical=0, day=0, slot=0, slot_name="上午").utility_menu == []


def test_sys_prompt_injects_utility_block():
    agent = LLMUserAgent.__new__(LLMUserAgent)  # 不触发 client 构造
    w = _world()
    ctx = UserContext(persona=w.persona, felt_state="有点累",
                      utility_menu=["出门走走——已经腻了，基本没什么用",
                                    "还没试过的：文化看展、音乐放松"])
    sys_prompt = agent._sys(ctx)
    # 注意：铁律 9 提及块名，断言须用菜单内容行而非块标题
    assert "出门走走——已经腻了，基本没什么用" in sys_prompt
    assert "还没试过的：文化看展、音乐放松" in sys_prompt
    # 空菜单不注入内容
    ctx2 = UserContext(persona=w.persona, felt_state="有点累")
    assert "出门走走——" not in agent._sys(ctx2)


def test_utility_menu_shows_recent_variants():
    """变体名必须出现在菜单里——否则用户会把做过的变体当新花样（SPA 失忆 bug）。"""
    w = _world()
    w._last_done = {"好好休息": w.t}
    w._last_variants = {"好好休息": ["家里补觉", "按摩 SPA"]}
    line = next(l for l in w.utility_menu() if l.startswith("好好休息"))
    assert "按摩 SPA" in line and "家里补觉" in line and "——" in line


def test_last_variants_dedupe_and_cap():
    w = _world()
    w._last_variants = {"好好休息": ["家里补觉", "按摩 SPA"]}
    # 模拟 _effective_events 的变体登记逻辑：去重 + 保留最近 3 个
    for label in ["按摩 SPA", "电影院", "足疗店"]:
        seen = [v for v in w._last_variants["好好休息"] if v != label]
        seen.append(label)
        w._last_variants["好好休息"] = seen[-3:]
    assert w._last_variants["好好休息"] == ["按摩 SPA", "电影院", "足疗店"]


def test_last_variants_survive_snapshot():
    w = _world()
    w._last_variants = {"好好休息": ["按摩 SPA"]}
    w2 = World.from_snapshot(w.to_snapshot(), w.cfg)
    assert w2._last_variants == {"好好休息": ["按摩 SPA"]}
