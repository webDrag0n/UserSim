# 02 · 用户模拟 Agent（agents/user）

状态: 草稿

> 约束：只能 import contracts 与 llm；**永远不能改写状态向量**；随机性只允许来自 LLM 采样本身。

## 1. 职责

把"真实的人"演出来：基于真实状态、人格与事件上下文，生成对话、情绪化的表达、求助决策与 session 的开启/结束。它是世界的"感受器官"，不是世界的"手"。

## 2. 输入（由 Runner 注入， contracts.UserContext）

```json
{
  "persona": { "big5": {...}, "likes": "...", "routine": "..." },
  "felt_state": "你现在很疲惫，压力很大，肚子有点饿",   // world 规则翻译器产出的语义化摘要
  "active_events": [ {类型/地点/目标/进度…} ],
  "assist_prompt": "加班事件刚结束，可能需要安排恢复",   // 介入点提示，可空
  "schedule_view": [ ... ],                              // 可见日程
  "dialogue_history": [ ... ]                            // 当前 session 内历史
}
```

注意：user_agent **看不到原始数值 x**。数值→语言的翻译在 world 侧用规则完成（分档词典：压力>0.7 →"快崩溃了"…），这有三重好处：

1. 防止用户 LLM 精确报数，使助手的估计任务变得平凡；
2. 表达风格由人格调制（高神经质者把 0.6 说成"糟透了"），增加估计难度与真实感；
3. 从结构上杜绝"用户 LLM 篡改状态"的通道。

## 3. 输出（contracts.UserAction）

```json
{
  "say": "唉，今天加班到现在，人要散架了……",
  "tool_calls": [ {"name": "open_session"} | {"name": "close_session"} | {"name": "request_assistant", "args": {...}} ],
  "end_session": false
}
```

## 4. 工具集（用户侧只有三个）

| 工具 | 语义 |
|---|---|
| `open_session` | 主动找助手（时机是被测行为） |
| `close_session` | 结束对话 |
| `request_assistant` | 请助手代为操作手机（查日程/写日程/设提醒） |

**写日程等手机操作一律不在用户侧**（假设④：用户不能自己操作手机）——助手侧工具见 03。

## 5. Prompt 结构（系统提示骨架）

```
你是 {persona.name}，{persona.archetype}。
性格（大五）：...  喜好：...  作息：...
【铁律】你不是一个 AI 助手，你就是这个人本人；
你只能表达感受与做出现实决策，不能篡改、预言自己的状态数值。
【当前感受】{felt_state}
【正在发生】{active_events}
{assist_prompt}
```

行为调制参数（`[user_agent]`）：

- `help_seek_stress_threshold`：felt_state 档位超过阈值时，在 prompt 中强化"考虑找助手聊聊"的倾向（不强制——决策仍是 LLM 做的）；
- `max_turns_per_session`：防死循环，达到上限由 Runner 强制结算 session。

## 6. 参考用户实现（Reference User）

评测矩阵中冻结的参照物：固定 provider + 低温（`config/llm.toml [roles.reference_user]`），prompt 模板版本化（`agents/user/prompts/v1.md`），变更即升版本号并在报告中标注。

## 7. 失败与降级

- LLM 超时/解析失败：Runner 重试 `llm.toml [runtime].max_retries` 次；仍失败则本 turn 记 `degraded=true`（计入行为指标），用户说"（沉默）"并跳过；
- 契约违约（输出了状态数值 / 调了不存在的工具）：记违约事件，该动作不生效。

## 8. 实现备注

- 落位于 `agents/user/llm_user.py`（prompt v1，JSON 模式输出 `{"say","end_session"}`；求助决策为单独的 `decide_open` 调用）。
- 实测（DeepSeek）：对话自然、人格稳定；偶见连续两轮重复措辞，后续可在 prompt 加"不要重复上一句"。
- 降级路径已实现：LLM 失败记 `degraded=true` 并跳过该 turn。
