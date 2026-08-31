# 01 · 世界模拟器

> ⚠️ 注：replay 模式已于 R4 下线（已知组效度检验 known-groups validity 迁移至 live 对照组 reference vs stub），文中 replay/脚本三档内容为历史记录。

World 是 UserSim 的纯规则核心：0 次 LLM 调用，不 import agents / evaluator / llm。同一 seed 在规则回放模式下产出完全相同的轨迹。

---

## 状态向量

```text
x = [valence, energy, satiety, stress] ∈ [0, 1]⁴
```

| 维度 | 含义 | 设定点 r | 容差带半宽 |
| --- | --- | --- | --- |
| valence | 心情愉悦度 | config 可调 | config 可调 |
| energy | 精力/活力 | config 可调 | config 可调 |
| satiety | 饱腹感 | config 可调 | config 可调 |
| stress | 压力（越低越好） | config 可调 | config 可调 |

设定点 `r` 与容差带半宽在 `config/system.toml [state]` 中配置。

---

## 双层时钟

- **外层 slot 时钟**：一天 `[clock].slots_per_day` 个时段（默认 4：上午/下午/晚上/深夜），世界按 slot 推进，事件之间"快进"，不存在全局连续 tick。
- **内层 turn 时钟**：session 开启期间按 turn 步进；session 关闭后回到外层。
- `t_logical = day * slots_per_day + slot` 是全系统唯一排序键；turn 用 `(session_id, turn_id)` 定位。

---

## 天气系统

5 种天气状态：晴 / 多云 / 阴 / 小雨 / 暴雨。每天（slot 0）根据马尔可夫转移矩阵转移一次：

```text
      晴    多云   阴    小雨   暴雨
晴  [ 0.6   0.3   0.07  0.03   0    ]
多云[ 0.3   0.4   0.2   0.1    0    ]
阴  [ 0.1   0.25  0.35  0.25  0.05  ]
小雨[ 0.05  0.1   0.3   0.4   0.15  ]
暴雨[ 0     0.05  0.15  0.4   0.4   ]
```

天气影响心情（valence 基线偏移）和户外事件效果（暴雨使户外恢复事件效果减半）。

---

## 需求动力学

4 个需求持续累积，由生物钟调制。需求 urges 经 `plan_slot` 请求流向用户侧，但 live 模式下意图由用户侧 LLM 生成（数值不进 prompt，状态-表达解耦；见 docs/02-user-agent.md）；replay 脚本用户仍直接由 urges 驱动。

### 四个需求与驱动力公式

| 需求 | 驱动力 u(x) | 特征 |
| --- | --- | --- |
| hunger | `[(1 - satiety) / 0.6]^1.5` | 低饱腹时加速增长 |
| social | `social_level²` | 平方增长，积累慢但后劲足 |
| stimulation | `1 - (2 * stim_level - 1)²` | 倒 U 曲线：中等水平最强 |
| achievement | `achieve_level^2.5` | 临近截止时陡增 |

### 生物钟调制规则

| 时段 | 调制规则 |
| --- | --- |
| slot 1（下午，饭点） | hunger 驱动力 × 生物钟因子（约 1.5） |
| slot 3（深夜） | 疲劳驱动力上升，sleep 意图优先 |
| 工作日 vs 周末 | 不同的需求基线 |

---

## 习惯化曲线

重复执行同类事件，效果递减；间隔足够长后恢复。实现在 `balance-sheet/UserSim数值配表.xlsx` 的习惯化曲线 sheet，可在 Web 配表编辑器中实时修改并预览函数曲线。

venue 餐厅（`config/balance/venues.json` 的具体场所，见 docs/08-event-catalog.md）同样参与习惯化（habituation.json 有 6 条覆盖）；模板"三餐"豁免。最近一次执行的动作习惯化权重 < 0.6 时，world 产出 `satiation_note` 餍足提示（"最近总是{动作}，感觉有点腻了"）注入用户侧 context，让"腻了"可表达。

R7 起，感知通道升级为 `utility_menu`：world 对 `_last_done` 里每个活动算当前 hab_weight 并翻译成语义档位（≥0.85 还很新鲜 / 0.6~0.85 吸引力降了 / 0.35~0.6 效果明显打折 / <0.35 腻了基本没用，权重升序排列），外加"还没试过的"候选清单（规范动作键，上限 8 个）。与效果裁决同一数据源、同一公式——用户感知到的边际效用与世界实际施加的衰减一致，用户据此在规划时权衡各事件实际 utility、在反馈时拒绝重复安排。

---

## 每个 Slot 的结算顺序

顺序即语义，不可随意调换：

```text
1. 天气转移（每天 slot 0 执行一次）
2. 自然漂移
      - satiety 衰减（饥饿感累积）
      - energy 消耗（睡眠/工作/休息的基线作用）
3. 反弹检查
      - stress < rebound_threshold → 本日工作效果 × rebound_multiplier
        （模拟过度补偿后的积压反弹）
4. 事件效果
      - 应用本时段活跃事件的 Δx（长事件按 span 摊销）
      - 习惯化修正：重复事件效果递减
5. 控制回血
      - 若本时段发生了恢复行为，按 [dynamics] 系数回血
6. 心情耦合
      - valence ← valence + rate · (v_eq − valence)
      - v_eq = f(energy, satiety, stress)
7. 限幅 [0, 1]，写入轨迹日志
```

所有系数集中在 `config/system.toml [dynamics]`，调参只改配置。

---

## 事件引擎

### 三类事件

| 类别 | 来源 | 例子 |
| --- | --- | --- |
| 模板事件 | 作息模板按周期铺底 | 工作、三餐、通勤、睡眠 |
| 扰动事件 | 泊松到达（`[events].disturbance_prob_per_day`） | 临时加班、应酬、截止压缩 |
| 恢复事件 | 用户新增（经助手写入日程） | 吃好吃的、短途旅行、运动 |

### 事件结构（六字段）

`类型 / 起止时段 / 地点 / 事件目标 / 事件效果 Δx / 当前进度`

模板事件的 `effect` 为空——其作用体现在自然漂移中，避免与基线双重计数；显式 Δx 只挂在扰动和恢复事件上。

餐饮场所事件（venues 饮食类，或带 `replaces_meal` 标记的场所）活跃时，当日模板"三餐"在**同 slot**（午/晚饭时段，slot 1/2）的效果被抑制——按 slot 粒度抑制，不删事件；该标记落在 `Event.replaces_meal`（docs/05-contracts.md）。

### 因果链记录

Session 内用户可新增事件（如助手建议 → "吃好吃的"），World 记录 `caused_by_session_id`，供前端画因果箭头。

---

## 个性化事件库

每个用户根据人格生成不同的主动事件库（17 条事件）。高开放性用户有更多新奇刺激类事件，高尽责性用户有更多成就类事件，外向性决定社交类事件的种类与数量。

---

## 种子流派生

一个 `run.seed` 派生若干独立子流，保证"增减一类随机性不打乱其他流"：

```text
seed ─┬─ persona_stream      角色卡
      ├─ schedule_stream     日程模板填充
      ├─ disturbance_stream  泊松扰动到达与类型
      └─ noise_stream        动力学小噪声（可选，默认关）
```

实现：`numpy.random.SeedSequence(seed).spawn(n)`。

---

## 快照与向后兼容

结算日志格式遵循只加不删原则：

```json
{
  "t_logical": 7,
  "active_event_ids": ["e1", "e3"],
  "natural_drift": { "satiety": -0.04, "energy": -0.06 },
  "event_effects": { "stress": 0.12 },
  "control_effects": { "energy": 0.08, "valence": 0.05 },
  "x_before": [0.55, 0.40, 0.30, 0.65],
  "x_after": [0.58, 0.42, 0.26, 0.77]
}
```

老存档字段缺失时前端回退显示，不报错。新增字段不破坏离线 eval。

---

## 子模块

```text
world/
  clock.py       双层时钟
  persona.py     角色卡生成器（seed → 大五 30 facet / 喜好 / 作息 / x0）
  events.py      事件引擎（模板 / 扰动 / 恢复，合法性校验）
  dynamics.py    状态动力学（差分方程 + 事件效果 + 习惯化 + 限幅）
  settlement.py  时段结算（合成一次状态推进，写日志）
  streams.py     种子流派生（numpy SeedSequence）
  felt.py        felt_state 翻译器（数值 → 语义摘要，分档词典）
  world.py       World 门面（对外只暴露 step_slot() / current_context()）
```

---

## 实现备注

- 三档回放（seed=42，30 天）判定：good → converged（e_ss=0.025，t_s=0.75d）/ mid → oscillating（M_p=0.30）/ poor → diverged（e_ss=0.31），见 `tests/test_evaluator.py` 集成测试。
- 脚本助手"预判边际"参数：优秀助手 K=0.85 / margin=0.6，贴近带边时温和干预。
- 天气系统、需求动力学、个性化事件库在第七轮 Phase 1 实现，由 `usersim/world/` 各子模块承载。
