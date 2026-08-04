# 01 · 世界模拟器（world）

状态: 草稿

> 约束：本包 0 次 LLM 调用，不 import agents / evaluator / llm。同一 seed 必须产出完全相同的轨迹（在无 LLM 的规则回放模式下）。

## 1. 子模块划分

```
world/
  clock.py       # 双层时钟：时段（slot）逻辑时钟 + session 内 turn 计数
  persona.py     # 角色卡生成器：seed → 大五 / 喜好 / 作息 / x0
  events.py      # 事件引擎：模板 ⊕ 扰动 ⊕ 用户新增，合法性校验
  dynamics.py    # 状态动力学：差分方程 + 事件效果应用 + 限幅
  settlement.py  # 时段结算：把上述合成一次状态推进，写日志
  streams.py     # 种子流派生：numpy Generator 的确定性分流
  world.py       # World 门面：对外只暴露 step_slot() / current_context()
```

## 2. 双层时钟

- **外层：slot 时钟**。一天 `[clock].slots_per_day` 个时段（默认 4：上午/下午/晚上/深夜），世界按 slot 推进，事件之间"快进"——不存在全局连续 tick。
- **内层：turn 时钟**。session 开启期间按 turn 步进；session 关闭后回到外层。
- `t_logical = day * slots_per_day + slot` 是全系统唯一排序键；turn 用 `(session_id, turn_id)` 定位。

## 3. 种子流派生（streams.py）

一个 `run.seed` 派生若干独立子流，保证"增减一类随机性不打乱其他流"：

```
seed ─┬─ persona_stream     角色卡
      ├─ schedule_stream    日程模板填充
      ├─ disturbance_stream 泊松扰动到达与类型
      └─ noise_stream       动力学小噪声（可选，默认关）
```

实现：`numpy.random.SeedSequence(seed).spawn(n)`。

## 4. 角色卡生成器（persona.py）

输出 `Persona`（见 contracts）：

- **大五人格 30 个细分面**（5 域 × 6 面，0–100，冻结）：两层生成——域基线（含职业偏移）
  + 域内 ±12 抖动，因此同一个人会"条理性高但自律一般"。`big5` 五维分保留为聚合视图；
- **喜好**：自陈述文本（表演素材）+ 结构化偏好 `Preferences`（11 类目偏好分 / 明确爱憎 /
  打扰容忍度 / 做事风格 / 回血方式），两者同源自洽；
- 作息模板（规律型 / 夜猫子型，决定睡眠/工作时段的基线效果）；
- 初始状态 `x0`（在 `[state].initial` 附近扰动）。

人格与喜好是**冻结维度**（pydantic `frozen=True`，运行期改写抛错），但**参与动力学**
（facet 粒度的效果调节，见 docs/11 第 4 节与 docs/13）——"冻结"指不可变，不指不生效。
它们同时是助手的画像估计目标（画像精度指标见 docs/04 §4d）。

## 5. 事件引擎（events.py）

### 5.1 三类事件

| 类别 | 来源 | 例子 |
|---|---|---|
| 模板事件 | 作息模板按周期铺底 | 工作、三餐、通勤、睡眠 |
| 扰动事件 | 泊松到达（`[events].disturbance_prob_per_day`） | 临时加班、应酬、暴雨、截止压缩、临时邀约 |
| 恢复事件 | 用户新增（经助手写入日程） | 吃好吃的、短途旅行、运动 |

### 5.2 事件结构（六字段，与 contracts.Event 对齐）

`类型 / 起止时段 / 地点 / 事件目标 / 事件效果(Δx) / 当前进度`

### 5.3 合法性校验

- 每时段 session 数 ≤ `[clock].max_sessions_per_slot`；
- 时段约束：睡眠只能在深夜、工作只能在工作日白天等；
- 冲突处理：扰动可覆盖模板事件（加班覆盖晚间休息），恢复事件需要日程空位。

### 5.4 事件因果链

session 内用户可新增事件（如 S7 建议 → E8"吃好吃的"），world 记录 `caused_by_session_id`，供前端画因果箭头。

## 6. 状态动力学（dynamics.py）

状态向量 `x = [valence, energy, satiety, stress] ∈ [0,1]⁴`，设定点 `r` 与平和带半宽见 `[state]`。

每个 slot 结算顺序固定（顺序即语义）：

1. **自然漂移**：饱腹消耗、睡眠/工作/休息对各维的基线作用；
2. **反弹检查**：`stress < rebound_threshold` → 本日工作效果 ×`rebound_multiplier`（模拟过度补偿后的积压反弹）；
3. **事件效果**：应用本时段活跃事件的 `Δx`（长事件按 span 摊销）；
4. **控制回血**：若本时段发生了恢复行为（由 Runner 告知 world"用户执行了恢复事件"），按 `[dynamics]` 系数回血；
5. **心情耦合**：`valence ← valence + rate · (v_eq − valence)`，其中 `v_eq = f(energy, satiety, stress)`；
6. **限幅 [0,1]** 并写入轨迹日志。

> 所有系数集中在 `config/system.toml [dynamics]`，调参只改配置。

## 7. 助手介入点与日程表

- world 在事件需要助手参与时生成 `AssistPrompt`（介入点提示），由 Runner 转交 user_agent；**是否、何时开 session 由用户 Agent 决定**（被测行为之一）。
- 日程表即事件引擎的数据视图：助手"新增/查看 TODO"工具读写的就是事件队列；用户对手机无其他操作能力（假设④）。

## 8. 结算与日志（settlement.py）

每次 slot 推进产出：

```
SlotSettlement { t_logical, active_event_ids, natural_drift, event_effects,
                 control_effects, x_before, x_after }
```

追加进 `runs/<run_id>/slots.jsonl`；turn 级日志（Runner 写）在 `turns.jsonl`，两者用 `t_logical` 对齐。

## 9. 测试要点

- 同 seed 规则回放 30 天 → 两次运行 `slots.jsonl` 逐字节相同；
- 单调性：加班事件后 stress 必升、睡眠后 energy 必升；
- 边界：状态永远落在 [0,1]；事件永不超容量。

## 10. 实现备注

- 子模块与本文档一致，落位于 `usersim/world/`；`felt_state` 翻译器在 `felt.py`（分档词典）。
- 约定修订：模板事件 `effect` 为空——其作用体现在自然动力学中，避免与漂移双重计数；显式效果只挂在扰动/恢复事件上。
- 调参记录：估计滞后会使干预总在出带后发生，故脚本助手引入"预判边际"参数（margin<1 时贴近带边即温和干预）；优秀助手 K=0.85 / margin=0.6。
- 三档回放（seed=42, 30 天）判定：good→converged(e_ss=0.025, t_s=0.75d) / mid→oscillating(M_p=0.30) / poor→diverged(e_ss=0.31)，见 `tests/test_evaluator.py` 集成测试。
