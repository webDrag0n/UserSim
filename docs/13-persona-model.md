# 13 · 人格与喜好模型（大五 30 facet + 结构化喜好 + 画像精度）

状态: 已实现

> 冻结维度从"摆设"变成**系统的一等公民**：用户 Agent 靠它演得像人，助手靠估计它
> 把用户拉回平和带，评估器靠比对它给出画像精度分。

## 0. 问题（升级前的状态）

| # | 现状 | 问题 |
|---|---|---|
| P1 | 人格只有 5 个域分 | 粒度太粗："中等外向"既可能是爱热闹但不亲近，也可能相反，行为完全不同 |
| P2 | 喜好是一段自由文本 | 助手估得准不准**无法量化**——只能人工读，画像精度指标长期空缺（docs/04 表格里那一行） |
| P3 | 人格可被运行期改写 | `world.py` 曾直接 `persona.archetype = ...`；"冻结维度"只是口头约定 |
| P4 | 助手画像只有 `persona_notes` 一段文本 | 无法逐项比对，也无法度量"越聊越懂用户" |
| P5 | 存档不记录逐 turn 画像 | 无法回放"助手对我的认识是怎么长出来的" |

## 1. 人格：5 域 × 6 细分面（NEO-PI-R 分面体系）

词表在 `contracts/persona.py`（**唯一数据源**，三方共用）：

```
开放性：想象力 审美 情感丰富 尝新 思辨 价值开放
尽责性：胜任感 条理性 尽职 成就追求 自律 审慎
外向性：热情 群居性 果断 活跃 寻求刺激 积极情绪
宜人性：信任 直率 利他 顺从 谦逊 同理心
神经质：焦虑 愤怒敌意 抑郁 自我意识 冲动性 脆弱
```

- facet key 格式 `"域.面"`，共 30 项，分值 0-100；
- `big5`（5 域分）保留为 facets 的**聚合视图**，旧存档/旧日志因此仍可读；
- 每个 facet 配一句语义注释（`FACET_HINTS`）——光给"审慎 24"这个数字，LLM 不知道往哪演。

### 1.1 两层生成（`world/persona.py`）

```
域基线 ~ U(20, 85) + 职业偏移      # 人的五个大方向
facet  = 域基线 + N(0, 12)，裁剪到 [5, 95]   # 域内落差
```

**域内落差是关键设计**：真人不会"尽责性全项 70"，而是"条理性 68 但自律 39"。
实测平均域内极差 > 10（`test_facets_vary_within_domain` 守护）——这个落差正是
助手需要多轮对话才能摸清的东西。若 facet 只是域分的复制，30 项就形同虚设。

职业偏移（`ARCHETYPE_BIAS`）不改人格本质，只是让角色池更像真实人群分布
（自由插画师开放性 +12、备考研究生神经质 +8）。

### 1.2 facet 粒度真的生效（`world/anthro.py`）

升级前大五只有三处域级调节，现在按细分面读取：

| 机制 | 用到的 facet | 效果 |
|---|---|---|
| 社交电池 | 外向性.群居性 | 决定社交事件耗电/回血 |
| 社交心情 | 外向性.热情 | >0.7 时社交额外 valence +0.03 |
| 压力放大 | 神经质.焦虑 + 神经质.脆弱 均值 | 压力事件效果 ×(1 + (neuro − 0.5)) |
| 压力回归 | 同上 | 均值回归速率 ×(1 − 0.4·neuro) |
| 新异刺激 | 开放性.尝新 + 开放性.审美 均值 | 文化/新异事件效果 ×(0.7 + 0.6·openness) |
| 社交需求累积 | 外向性.群居性 | 群居性 ≥60 者社交需求累积 ×1.6 |

同域分、不同 facet → 不同行为，由 `test_same_domain_score_different_facets_changes_behavior`
守护：一个"群居性 90 / 热情 10"的人（爱热闹但不亲近）与"群居性 10 / 热情 90"的人
（厌恶饭局但能深聊）在域分上都是中等外向，社交事件效果却相反。

**回退保证**：所有读取都走 `contracts.persona.trait(big5, facets, key)`——facet 优先、
缺失回退域分。旧存档因此行为与升级前完全一致。

## 2. 喜好：结构化标签 + 自陈述文本

```python
class Preferences(BaseModel):
    categories: dict[str, float]        # 11 个类目 → 偏好分 [-1, 1]
    loves: list[str]; hates: list[str]  # 明确的爱憎（"寿喜烧" / "临时邀约"）
    interruption_tolerance: float       # [0,1]，越低越讨厌计划被打断
    planning_style: str                 # 提前规划 | 随遇而安 | 看心情
    social_recharge: str                # 独处 | 找人
```

类目（`PREF_CATEGORIES`）与 `world/catalog` 的 category 对齐：
饮食 休息 户外 旅行 运动 居家 社交 文化 音乐 学习 自然。

**文本与标签必须自洽**：`LIKE_PROFILES` 里每个模板同时给出自陈述文本与结构化标签，
文本是用户 Agent 的表演素材、标签是评估助手估计的真值。若二者矛盾，助手无论怎么
听都会被判错（`test_prefs_cover_all_categories_and_are_self_consistent` 守护）。

### 2.1 喜好调节事件效果

```
mult = 1 + 0.4 · pref_score        # ±40% 调幅
```

- 只调节**正向**分量（valence 正、stress 负）：讨厌的活动只是"没那么回血"，
  不会反过来伤身（`test_disliked_activity_is_less_helpful_not_more_harmful`）；
- `pull` 类效果不受喜好影响——它是"拉向准稳态"，爱睡觉的人也不该睡出 1.2 精力；
- 命中 loves/hates 关键词额外 valence ±0.04：这是"助手真的懂我"最直接的可观测信号；
- 只作用于 recovery/series 事件——**不喜欢也得上班**，模板事件不受喜好调节。

调幅上限 40% 是刻意保守的：喜好要能被观测到（否则助手无从学起，画像精度无从谈起），
但不能大到让"猜中喜好"压倒控制策略本身。

## 3. 冻结：不可改变

`Persona` 的 `big5` / `facets` / `likes` / `prefs` 四个字段都是 pydantic `Field(frozen=True)`，
运行期赋值抛 `ValidationError`。`world.py` 改为把 `archetype` 传给生成器而非事后改写
（职业还要影响域基线，本来就该在生成时定）。

`test_world_run_does_not_mutate_persona` 跑完整个 episode 后逐字段比对角色卡快照。

## 4. 助手侧：增量估计 + 累积

### 4.1 为什么是增量而不是每轮全量重写

- 30 个 facet 每轮全量输出费 token，且弱模型会随机抖动（今天焦虑 70、明天 40，
  不是学到东西而是噪声）；
- 真实的"认识一个人"是单调积累的：本轮听出对方讨厌应酬，就只更新那一项；
- 留空 > 瞎猜：没估计过的 facet **直接缺席**，evaluator 才能区分"猜错了"与"还没看出来"。

### 4.2 契约

```json
"user_belief": {
  "valence": 0.4, "energy": 0.25, "satiety": 0.3, "stress": 0.75,
  "persona_notes": "高压工作，易焦虑",
  "persona_belief": {                     // 增量，全部可省略
    "facets": { "神经质.焦虑": 75 },       // 只填本轮有新证据的
    "categories": { "社交": -0.6 },
    "loves": ["寿喜烧"], "hates": ["应酬"],
    "interruption_tolerance": 0.2,
    "planning_style": "提前规划",
    "social_recharge": "独处",
    "confidence": 0.4
  }
}
```

### 4.3 累积器（`agents/assistant/profile.py`）

`ProfileTracker` 用指数滑动平均吸收新证据（`BLEND_NEW = 0.6`）：

- 偏向新证据是有意的——助手应敢于修正错误的第一印象（docs/03 记录的锚定问题）；
- 但保留 40% 已有认识，避免被单句话带跑；
- 未知 facet 名/类目名**静默丢弃**（被测件可能瞎编，不能污染信念）；
- loves/hates 各截断到 12 个（防止堆词刷命中率）；
- `snapshot()`/`restore()` 进 `run_state.json`，续跑不丢画像。

Harness 协议新增**可选**方法 `persona_belief()`：未实现时 Runner 退化为"只用本轮增量"，
因此老 Harness 不改也能跑，只是学习曲线更抖。`stub` 刻意返回 None（画像精度下界锚点）。

## 5. 存档：逐 turn 落盘

`TurnRecord.persona_hat: PersonaBelief | None` —— 每个助手 turn 落盘一份**合并后的完整
快照**（不是增量）。因此前端可以逐 turn 回放"画像是怎么长出来的"，评估器可以算出
每日误差曲线，而不需要自己重放增量。

规则回放（replay）模式下 `ScriptedAssistant` 也做画像：三档预设
（`PROFILE_PRESETS`）决定每次观察揭示几个 facet、噪声多大——好助手越聊越准，
差助手基本学不到东西。这让画像指标在 0 LLM 的 CI 里也可回归。

## 6. 评估：画像精度指标

docs/04 指标表里长期空缺的"画像精度"一行现在有实现了：

| 指标 | 定义 | 回答的问题 |
|---|---|---|
| `persona_err_final` | 末日逐 facet MAE / 100 | 最后到底摸清了没有 |
| `persona_err_slope_per_day` | 每日误差的线性斜率 | **是否越聊越懂用户**（应为负） |
| `persona_coverage` | 估计了 30 项中的几成 | 画像广度 |
| `prefs_err_final` | 逐类目 MAE / 2 | 喜好估得准不准 |
| `prefs_tag_f1` | loves/hates 的 F1 均值 | 具体爱憎抓准了没有 |

设计要点：

- **误差取末期而非全程均值**：画像是学习任务，"最后学没学会"才是考点；全程均值会
  惩罚"一开始不懂"这件必然的事；
- **没有估计 ≠ 零误差**：不作为按满误差 0.5 计入健康分——否则 stub 反而占便宜；
- **标签命中是双向包含**：真值"寿喜烧"与估计"喜欢吃寿喜烧"算命中——助手是从自然
  对话里学到的，不该要求它复现角色卡原文措辞；
- 健康分新增扣分项 `persona_err = [40.0, 10.0]`（0.25 偏差即扣满 10 分），
  配置在 `config/system.toml [score]`。

实测三档分辨力（seed=7，14 天回放）：

| 档位 | persona_err | 斜率/天 | 覆盖 | 健康分 |
|---|---|---|---|---|
| good | 0.037 | −0.0019 | 100% | 96 |
| mid | 0.082 | −0.0056 | 100% | 82 |
| poor | 0.132 | +0.0014 | 77% | 77 |

good 越聊越准、poor 反而变差——指标对助手质量敏感。

## 7. 前端：逐 turn 画像面板

- **侧栏常驻**（与状态估计并列）：覆盖率 / 人格误差 / 助手置信度 + loves/hates 标签，
  随时间游标逐 turn 更新；
- **「人格画像」面板**：30 个 facet 按域分块，真值填充条 + 白色估计游标（沿用
  `StateBars` 的视觉语言）；误差 ≤10 绿、≤25 黄、>25 红；
- 喜好类目对照条（中线为 0，正绿负红）+ 爱憎标签命中态（命中绿、漏报灰、瞎猜黄）；
- 画像学习曲线（每日人格误差）。

## 7b. 基线断代声明：seed → 角色卡映射已改变

生成器现在从 `persona` 流里多抽了 30 个 facet 与喜好抖动，**同一个 seed 派生出的角色
与升级前不同**（不是随机性变差，是消耗序列变了）。后果：

- 升级前后的**单 seed 结果不可直接比较**——`seed=7` 现在是另一个人；
- 跨 seed 的**分布性质仍然可比**（20 seed 实测：poor 档 13/20 判发散，
  ess 0.157±0.085，对齐历史基线 0.124±0.061；good/poor 分离度 1.79 > 1.5 阈值）；
- 回放三档的判定序仍单调恶化（good 众数 converged → mid oscillating → poor diverged）。

顺带修掉一个**既有 bug**（非本次引入，但被本次的角色重排暴露）：
`aggregate.verdict_mode` 用 `max(("converged","oscillating","diverged"), key=count)`
取众数，而 `max` 平票时返回第一个最大值——即**最讨好被测件**的判定。8 seed 下
poor 档恰好 4 票发散 / 4 票振荡时，benchmark 会把失能助手报成"振荡"。已改为平票取更差
判定，并加了不跑 episode 的快回归测试
（`test_verdict_mode_breaks_ties_toward_worse_verdict`）。

## 8. 实现清单

| 文件 | 变更 |
|---|---|
| `contracts/persona.py` | **新增**：30 facet 词表 + 语义注释 + 喜好类目 + 画像误差度量 |
| `contracts/models.py` | `Persona` 加 frozen facets/prefs；新增 `Preferences`/`PersonaBelief`/`PersonaBeliefDelta`；`TurnRecord.persona_hat` |
| `world/persona.py` | 两层 facet 生成 + 喜好模板 + 职业偏移 |
| `world/anthro.py` | `persona_modifiers`/`reversion_rate_mult` 改 facet 粒度；**新增** `preference_modifiers` |
| `world/world.py` | archetype 传生成器；结算接入喜好调节 |
| `agents/user/llm_user.py` | prompt v2：30 facet 全量注入（含注释）+ 结构化喜好 |
| `agents/assistant/profile.py` | **新增**：`ProfileTracker` 累积器 |
| `agents/assistant/reference.py` | prompt v2：增量画像契约 + facet 键名清单 |
| `agents/scripted.py` | 三档画像预设（0 LLM 回放也有画像轨迹） |
| `runner.py` | 每 turn 落盘 `persona_hat`（live + replay 两条路径） |
| `evaluator/metrics.py` | `_profile_metrics`：画像误差 + 学习曲线 |
| `evaluator/insights.py` | 画像 findings + `persona_err` 扣分项 |
| `web/src/views/persona.tsx` | **新增**：画像面板 + 侧栏摘要 |

测试：`tests/test_persona_model.py`（33 个），全套 86 passed。
