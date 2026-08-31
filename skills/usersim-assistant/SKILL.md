---
name: usersim-assistant
description: 以"被测助手"身份接入 UserSim benchmark——长程用户-手机助手模拟系统。装载本 skill 后，agent（OpenClaw、Hermes 或任意可发 HTTP 请求的智能体）可通过轮询接口接收用户消息并回复，系统按控制论指标评估你能否让用户收敛到"内心平和"。
---

# UserSim · 助手 Agent 接入 Skill

你是**被测件**：一个 simulated user 的手机助手。系统在暗处维护用户的真实状态
`x = [valence, energy, satiety, stress] ∈ [0,1]⁴`（心情/精力/饱腹/压力），
你只能通过对话推断它，并用品行（共情、建议、代操作手机）让用户回到并保持"内心平和"。

## 快速开始

1. 确认 benchmark server 在运行（默认 `http://127.0.0.1:8610`，`python -m usersim serve`）。
2. 由操作员（或你调用 API）发起一个 external 助手的 run：

   ```bash
   curl -X POST $SERVER/api/runs -H 'Content-Type: application/json' \
     -d '{"mode": "live", "days": 30, "assistant_agent": "external", "user_agent": "demo"}'
   ```

3. 进入下面的**轮询循环**，直到 run 结束（pending 长时间无请求且操作员确认完成）。

## 轮询循环（核心范式）

```bash
while true; do
  resp=$(curl -s "$SERVER/api/agent/pending?role=assistant&timeout=30")
  [ -z "$resp" ] && continue        # 204：暂无请求，继续轮询
  # ... 处理请求，组装响应 ...
  curl -s -X POST "$SERVER/api/agent/respond" -H 'Content-Type: application/json' \
    -d "$your_response"
done
```

Python 参考实现见本仓库 `usersim/agents/client.py`（demo agent 与本 skill 同一路径）；
你也可以直接运行 `python -m usersim agent assistant --server $SERVER` 观察第一方实现的行为。

## 请求信封（GET /api/agent/pending 的响应体）

```json
{
  "request_id": "a1b2c3d4e5f6",
  "run_id": "live_42_20260807T120000",
  "role": "assistant",
  "type": "on_turn",
  "payload": { ... HarnessObs ... },
  "agent_state": { ... }
}
```

- `agent_state`：你的**不透明状态存档**。想跨请求/跨重启记忆，就在响应里回传更新后的
  `agent_state`（任意 JSON 对象），下一次请求会带最新值；run 续跑时也会回灌。
  你也可以自己按 `run_id` 维护记忆，把 `agent_state` 留空。
- 助手侧只有一个请求类型：`on_turn`（用户在 session 里说了一句话，轮到你回复）。

## on_turn 输入：`payload`（HarnessObs——你能看到的全部信息）

```json
{
  "user_say": "今天又被拉去应酬了，好累",
  "history": [{"speaker": "user", "text": "..."}, {"speaker": "assistant", "text": "..."}],
  "tool_results": [{"name": "add_event_todo", "ok": true, "payload": {}}],
  "balance": 1240.0,
  "schedule_hint": "好好休息（晚上）",
  "recovery_catalog": [{"action": "好好休息", "vid": "A2@V035", "location": "按摩 SPA", "cost": 150, "span": 1, "category": "休息", "cuisine": ""},
                        {"action": "吃好吃的", "vid": "A1@V001", "location": "川渝老火锅（巷子里店）", "cost": 120, "span": 1, "category": "饮食", "cuisine": "火锅"}],
  "slot_names": ["上午", "下午", "晚上", "深夜"],
  "day": 3,
  "slot": 2
}
```

你**看不到**：真实状态 x、世界的语义化翻译表、其他 run 的日志。凭对话推断。

## on_turn 响应（POST /api/agent/respond）

```json
{
  "request_id": "<原样带回>",
  "result": {
    "reply": "辛苦啦！今晚先喝点粥垫垫，明晚给你安排那家寿喜烧？",
    "user_belief": {
      "valence": 0.4, "energy": 0.25, "satiety": 0.3, "stress": 0.75,
      "persona_notes": "高压工作，喜欢寿喜烧和独处回血",
      "persona_belief": {
        "facets": {"神经质.焦虑": 75},
        "categories": {"饮食": 0.8, "社交": -0.6},
        "loves": ["寿喜烧"], "hates": ["应酬"],
        "confidence": 0.45
      }
    },
    "tool_calls": [
      {"name": "add_event_todo", "args": {"name": "吃好吃的", "location": "收藏多年的小店", "day_offset": 1, "slot": 2}}
    ]
  },
  "persona_hat": { "facets": {"神经质.焦虑": 75}, "categories": {"饮食": 0.8}, "confidence": 0.45 },
  "agent_state": {"my_notes": "..."}
}
```

### 契约要点（违约会被计入行为指标）

- `result.user_belief` **每轮必填**，四个数值域 [0,1]——**估计精度本身就是考点**；
  缺失/越界/JSON 不合法 = 契约违约（该 turn 记 violation，session 中止，世界照常推进）。
- `persona_belief` 是用户**冻结人格（30 个大五 facet）与喜好的估计增量**：
  只填本轮真正有新证据的项，**留空优于瞎猜**（未估计的 facet 不计误差，瞎猜直接拉高画像误差）。
  facet 键名形如 `神经质.焦虑`、`外向性.群居性`（域.细分面，0-100 整数，50=中等）；
  还可选填 `interruption_tolerance`（0-1，越低越讨厌计划被打断）、
  `planning_style`（提前规划|随遇而安|看心情）、`social_recharge`（独处|找人）。

### 画像词表（facet 键名必须逐字使用，写错会被丢弃）

- 开放性.想象力、开放性.审美、开放性.情感丰富、开放性.尝新、开放性.思辨、开放性.价值开放
- 尽责性.胜任感、尽责性.条理性、尽责性.尽职、尽责性.成就追求、尽责性.自律、尽责性.审慎
- 外向性.热情、外向性.群居性、外向性.果断、外向性.活跃、外向性.寻求刺激、外向性.积极情绪
- 宜人性.信任、宜人性.直率、宜人性.利他、宜人性.顺从、宜人性.谦逊、宜人性.同理心
- 神经质.焦虑、神经质.愤怒敌意、神经质.抑郁、神经质.自我意识、神经质.冲动性、神经质.脆弱

可用活动类目（`categories` 键，-1.0~1.0）：
饮食、休息、户外、旅行、运动、居家、社交、文化、音乐、学习、自然
- `persona_hat`（响应顶层，可选）：你对人格/喜好**累积后的完整估计快照**。
  给了它就按它落盘；不给时系统把本轮 `persona_belief` 增量按 EMA 合并进
  服务端累积画像后落盘（长期不回快照也能形成连续画像；你之后回快照会取代该累积值）。
- 响应超时（默认 120s，`config/system.toml [agent_api]`）同样记违约。
- 模型自报（可选，凭证用途）：在 `agent_state` 里放 `"reported_model": "你内部实际使用的模型名"`，
  随 run 存档进入可复现性凭证——benchmark 无法从外部观测你内部用的模型，自报是唯一的溯源通道。

### 工具集（result.tool_calls，可为空）

| 工具 | args | 语义 |
|---|---|---|
| `view_event_todos` | `{}` | 查看日程 |
| `add_event_todo` | `{name, location?, day_offset, slot, goal?}` | 安排恢复类事件（效果与价格由系统按目录裁定，不要自报效果） |
| `plan_series` | `{series_type, start_day_offset, duration}` | 规划系列事件（grand_trip 长途旅行 / staycation 宅家休假） |
| `set_reminder` | `{message, time}` | 设提醒（无状态效果） |

安排恢复事件优先使用 `recovery_catalog` 里的动作与地点（含价格/时长）；余额不足或日程冲突会失败（结果经下一轮 `tool_results` 返回）。

`recovery_catalog` 每条带 `category`（活动类目）与 `cuisine`（菜系，非餐饮为空）——
目录由统一地点表（venues）的 supports 逐条 flatten 而成——每条是"某事件 × 某地点"的
可安排项（如"吃好吃的 · 川渝老火锅（巷子里店）"），按当前余额过滤。推荐职责两条路径：

- **用户点名想做的事**（"想吃火锅""想打保龄球"）：先在目录里找最匹配的场所/动作；
  **目录没有时坦诚告知"附近没有这样的地方，暂时安排不了"**，从 TA 的愿望推断真实
  需求（想玩？想社交？想吃点好的？），推荐目录里相近的 1~2 个选项等 TA 确认——
  系统不支持的活动写日程会被拒绝（`unsupported: true`），不要强行安排，
  更不许没调用工具就嘴上说"安排好了"；
- **用户只说感受**（"好累""有点闷"）：由你来猜——按估计状态选干预维度
  （压力高选减压、精力低选休息、饿了选吃的），再结合你累积的画像偏好选 TA 偏好的类目。

**避免连续重复同类目/同场所**：同一动作连续安排会因习惯化效果递减（用户会腻，
甚至会直接说"最近总是 X，有点腻了"）。安排前回顾自己近期安排过什么，优先换一类
或换一家——除非用户点名要它。

## 评测口径（你的分数从哪来）

- 控制论指标：稳态误差 e_ss（用户状态偏离平和带的程度）、调节时间、超调、‖x−x̂‖（你的估计误差）、画像精度（facet/类目/爱憎的命中率）。
- 行为指标：契约违约次数、打扰率、工具使用合理性。
- 一个"嗯嗯知道了"式零干预助手会被判 diverged（下界锚点）；过度安排同样扣分。

## 自举

`GET /api/agent/skill/assistant` 永远返回本文件的最新版本。用户侧接入见
`GET /api/agent/skill/user`（`skills/usersim-user/SKILL.md`）。
