"""可插拔实现机制与 CLI 驱动的输出解析（纯函数/配置扫描，不起子进程、不调 LLM）。"""

import json

import pytest

from usersim.agents.cli_agent import CliHarness, _dig, split_reply_json
from usersim.agents.config import default_impl, list_impls, load_impl, load_impl_llm
from usersim.agents.registry import available, create, default_name
from usersim.config import ConfigError
from usersim.contracts import HarnessObs


# ---------------------------------------------------------------
# profiles/*.toml 扫描（增删文件即增删实现）
# ---------------------------------------------------------------

class TestImplScanning:
    def test_assistant_impls_discovered(self):
        impls = list_impls("assistant")
        assert {"reference", "stub", "openclaw", "hermes"} <= set(impls)
        assert impls["openclaw"]["type"] == "cli"
        assert impls["reference"]["type"] == "package"

    def test_user_impls_discovered(self):
        impls = list_impls("user")
        assert "standard" in impls
        assert impls["standard"]["type"] == "package"
        assert impls["standard"]["behavior"]["memory_capacity"] == 8

    def test_defaults_come_from_role_config(self):
        assert default_impl("assistant") == "openclaw"
        assert default_impl("user") == "standard"
        assert default_name() == "openclaw"

    def test_unknown_impl_lists_options(self):
        with pytest.raises(ConfigError, match="profiles"):
            load_impl("assistant", "不存在的实现")

    def test_available_for_frontend_dropdown(self):
        items = {i["name"]: i for i in available()}
        assert items["openclaw"]["type"] == "cli"
        assert items["reference"]["doc"]

    def test_impl_llm_inherits_role_provider(self):
        llm = load_impl_llm("assistant", load_impl("assistant", "reference"))
        assert llm.provider  # 引用 config/llm.toml 的 provider 注册表

    def test_create_dispatches_by_type(self):
        from agents.assistant.reference import ReferenceHarness
        from agents.assistant.stub import StubHarness

        assert isinstance(create("reference", None), ReferenceHarness)
        assert isinstance(create("stub", None), StubHarness)
        assert isinstance(create("openclaw", None), CliHarness)
        assert isinstance(create("hermes", None), CliHarness)

    def test_create_unknown_type_rejected(self):
        # 缺 [cli] 节的 spec 直接构造应报 ConfigError
        with pytest.raises(ConfigError, match="cli"):
            CliHarness({"name": "bad", "type": "cli"}, None)


# ---------------------------------------------------------------
# 契约块拆分
# ---------------------------------------------------------------

class TestSplitReplyJson:
    def test_reply_plus_block(self):
        text = '好的，我帮你安排一下。\n\n```json\n{"user_belief": {"valence": 0.6}, "tool_calls": []}\n```'
        reply, data = split_reply_json(text)
        assert reply == "好的，我帮你安排一下。"
        assert data["user_belief"]["valence"] == 0.6

    def test_takes_last_block_when_agent_quotes_example(self):
        text = ('```json\n{"示例": 1}\n```\n这样的格式对吧？\n'
                '```json\n{"user_belief": {"stress": 0.4}, "tool_calls": []}\n```')
        reply, data = split_reply_json(text)
        assert "user_belief" in data
        assert "这样的格式对吧？" in reply

    def test_missing_block_raises(self):
        with pytest.raises(ValueError, match="契约块"):
            split_reply_json("只有正文，没有块")

    def test_empty_reply_raises(self):
        with pytest.raises(ValueError, match="正文为空"):
            split_reply_json('```json\n{"user_belief": {}}\n```')

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            split_reply_json('正文\n```json\n{不是json}\n```')


class TestDig:
    def test_nested_path(self):
        assert _dig({"a": {"b": "x"}}, "a.b") == ["x"]

    def test_star_expands_list(self):
        d = {"result": {"payloads": [{"text": "一"}, {"text": "二"}]}}
        assert _dig(d, "result.payloads.*.text") == ["一", "二"]

    def test_missing_path_returns_empty(self):
        assert _dig({"a": 1}, "b.c") == []


# ---------------------------------------------------------------
# 由真实 impl 文件驱动的 CLI harness（openclaw / hermes）
# ---------------------------------------------------------------

def _cli(name: str) -> CliHarness:
    return CliHarness(load_impl("assistant", name), None)


class TestOpenClawSpec:
    def _envelope(self, text="OK", status="ok"):
        return json.dumps({
            "runId": "r1", "status": status, "summary": "completed",
            "result": {
                "payloads": [{"text": text, "mediaUrl": None}],
                "meta": {"agentMeta": {"sessionId": "sid-1"}},
            },
        })

    def test_argv_renders_session_key_per_instance(self):
        h = _cli("openclaw")
        argv = h._argv("你好", resume=False)
        assert argv[0] == "openclaw"
        key = argv[argv.index("--session-key") + 1]
        assert key.startswith("agent:main:usersim-")
        assert "你好" in argv
        # key 模式：session_key 在实例内稳定且首轮/续轮 argv 相同（每轮都带 key）
        assert h._argv("x", resume=True) == h._argv("x", resume=False)
        assert h._session_value() == key

    def test_parse_json_envelope(self):
        h = _cli("openclaw")
        out = h._parse(self._envelope(text="你好\n```json\n{}\n```"))
        assert out.text.startswith("你好")
        assert out.session_id is None  # key 模式不从输出抓 id

    def test_non_ok_status_raises(self):
        h = _cli("openclaw")
        with pytest.raises(RuntimeError, match="状态异常"):
            h._parse(self._envelope(status="error"))

    def test_empty_payload_raises(self):
        h = _cli("openclaw")
        with pytest.raises(RuntimeError, match="空回复"):
            h._parse(self._envelope(text="  "))

    def test_snapshot_keeps_uid_for_restore(self):
        h = _cli("openclaw")
        _ = h._session_value()
        snap = h.snapshot()
        h2 = _cli("openclaw")
        h2.restore(snap)
        assert h2._session_value() == snap["session_key"]


class TestTurnMessage:
    """每轮消息必须携带画像反馈与任务提醒（v2：长 session 遗忘 bootstrap 的防线）。"""

    def _obs(self):
        return HarnessObs(user_say="今天好累", day=3, slot=2,
                          slot_names=["上午", "下午", "晚上", "深夜"], balance=500.0)

    def test_render_includes_profile_feedback_and_reminders(self):
        h = _cli("openclaw")
        msg = h._render_turn(self._obs())
        assert "你目前对用户的了解" in msg
        assert "每轮必做" in msg
        assert "persona_belief" in msg
        assert "第3天·晚上" in msg

    def test_render_reflects_accumulated_profile(self):
        from usersim.contracts import PersonaBeliefDelta

        h = _cli("openclaw")
        h.profile.update(PersonaBeliefDelta(facets={"神经质.焦虑": 80}, loves=["爵士乐"]))
        msg = h._render_turn(self._obs())
        assert "神经质.焦虑" in msg and "爵士乐" in msg
        assert "已覆盖 1/30" in msg

    def test_bootstrap_contains_full_persona_schema(self):
        h = _cli("openclaw")
        boot = h._bootstrap()
        for needle in ("interruption_tolerance", "planning_style", "social_recharge",
                       "【行动要求】", "神经质.焦虑", "50 = 中等"):
            assert needle in boot


class TestHermesSpec:
    def test_argv(self):
        h = _cli("hermes")
        argv = h._argv("你好", resume=False)
        assert argv[:2] == ["hermes", "chat"]
        assert "--pass-session-id" in argv
        assert argv[argv.index("--reasoning") + 1] == "none"  # reasoning 框会污染正文
        # 首轮无 session id：不追加 resume_args
        assert "--resume" not in argv

    def test_resume_args_after_session_captured(self):
        h = _cli("hermes")
        h.session_id = "20260811_x"
        argv = h._argv("继续", resume=True)
        assert argv[argv.index("--resume") + 1] == "20260811_x"

    def test_session_id_comes_from_stderr(self):
        # 实测：hermes 把 session_id 打在 stderr，stdout 是纯回复
        h = _cli("hermes")
        out = h._parse("你好！\n\n再见。", "\nsession_id: 20260811_180215_87942c\n")
        assert out.session_id == "20260811_180215_87942c"
        assert out.text == "你好！\n\n再见。"

    def test_session_line_on_stdout_is_stripped(self):
        h = _cli("hermes")
        h2_spec = dict(h.spec)
        h2_spec["cli"] = {**h.spec["cli"],
                          "session": {**h.spec["cli"]["session"], "id_stream": "stdout"}}
        h2 = CliHarness(h2_spec, None)
        out = h2._parse("session_id: abc123\n正式回复\n")
        assert out.session_id == "abc123"
        assert out.text == "正式回复"

    def test_empty_raises(self):
        with pytest.raises(RuntimeError, match="空回复"):
            _cli("hermes")._parse("  \n")

    def test_bad_spec_rejected(self):
        with pytest.raises(ConfigError):
            CliHarness({"name": "x", "cli": {"argv": ["-m"]}}, None)  # 缺 {message}
        with pytest.raises(ConfigError):
            CliHarness({"name": "x",
                        "cli": {"argv": ["{message}"], "session": {"mode": "key"}}},
                       None)  # key 模式缺 key 模板
