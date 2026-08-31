# 04 · 评估器（Evaluator）

> ⚠️ 注：replay 模式已于 R4 下线（量程守护迁移至 live 锚点对 reference vs stub），文中 replay/脚本三档内容为历史记录。

状态: 草稿

> **核心原则：0 次 LLM 调用；只读 `runs/` 日志；可离线重放，与世界迭代解耦。**

---

## 1. 评估哲学与三层解耦

### 1.1 为什么需要三层独立评估

UserSim 是一个**异质系统**——三个组件的质量通过同一条轨迹耦合在一起：

```
世界的规则仿真 → 用户 Agent 的表演 → 助手 Agent 的观测与控制
```

如果只看最终的控制效果（用户状态是否收敛到平和），我们无法区分：
- 助手不行，还是世界太极端？
- 用户言行不一致导致助手被误导，还是助手本身估计能力差？
- 收敛失败是因为助手没安排恢复，还是用户 Agent 违背人格拒绝了合理的安排？

因此，评估器将指标按**被评估对象**分为三层：

| Layer | 评估对象 | 核心问题 | 指标族 |
|-------|---------|---------|--------|
| **Layer 1** | 世界仿真 | 仿真本身的动力学是否健康、是否有足够分辨力？ | 状态饱和率、日内节律、经济平衡、系列后效 |
| **Layer 2** | 用户 Agent | 用户的言行是否与冻结人格自洽？（reward 信号是否可信） | M1-PAC, M2-WSC, M3-PRA, M4-PBA, M5-CSPS, 拟人性 |
| **Layer 3** | 助手 Agent | 助手能否控制状态趋近目标？能否正确估计用户？能否学会用户的人格？ | 控制论指标、估计误差、画像精度、行为质量 |

**Layer 2 是 Layer 3 的前提**：如果用户 Agent 本身行为不一致（比如极度讨厌户外的人开心接受了露营安排），那基于此计算的"助手估计误差"和"控制效果"就失去了参考意义——不是助手不懂用户，而是用户自己没演好。

### 1.2 因果链与评估边界

系统的完整因果链：

```
世界事件/动力学 → x_true（真实状态）
    ↓ (world.felt_state 翻译)
felt_state（语义化感受）→ 用户台词 → 助手 x̂ → 助手工具调用 → 新事件 → ...
    ↑ 用户 Agent（LLM）          ↑ 助手 Agent（LLM / Harness）
    ↑ 只能看到 felt_state        ↑ 只能看到用户台词+工具结果
    ↑ 不能看到 x_true 数值       ↑ 不能看到 x_true 数值
```

评估边界：
- **评估器能看到的**：`x_true`（世界写入）、`x_hat`（助手输出）、`persona_hat`（助手输出）、工具调用结果、对话文本（仅用于关键词匹配，不做语义理解）
- **评估器不能做的**：调用 LLM 解读对话内容、修改任何世界/Agent 状态、访问 Agent 内部 prompt

### 1.3 评估器约束

1. **0 LLM 调用**：所有指标是轨迹的确定性函数，由纯数值计算 + 关键词匹配完成
2. **只读 `runs/` 日志**：输入为 `slots.jsonl`（世界每时段结算）、`turns.jsonl`（对话记录）、`meta.json`（配置快照+角色卡）
3. **可离线重放**：任何时候都可以对已有 run 重算评估，不依赖运行中的任何状态
4. **向后兼容**：旧日志缺失字段时，对应指标返回 `NaN` 或 `None`，不报错

---

## 2. 状态空间与误差定义

### 2.1 四维状态向量

用户状态建模为 $\mathbf{x} \in [0, 1]^4$：

| 维度 | 符号 | 中文 | 含义 | 方向 |
|------|------|------|------|------|
| Valence | $x_v$ | 心情 | 主观幸福感 | 越高越好 |
| Energy | $x_e$ | 精力 | 身心能量水平 | 越高越好 |
| Satiety | $x_s$ | 饱腹 | 饥饿/饱足程度 | 越高越好 |
| Stress | $x_\sigma$ | 压力 | 心理压力 | 越低越好 |

实现：`contracts/models.py` `StateVec`（pydantic, 带 `[0,1]` 边界校验）。

### 2.2 目标设定点与平和带

来自 `config/system.toml [state]`：

$$\mathbf{x}^* = \begin{bmatrix} v^* = 0.72 \\ e^* = 0.70 \\ s^* = 0.65 \\ \sigma^* = 0.30 \end{bmatrix}, \quad \beta = 0.10 \text{（平和带半宽）}$$

### 2.3 逐维单侧误差

定义为**单侧偏差**——只惩罚"不够好"的方向（"过度开心"不算失控）：

$$e_d(\mathbf{x}) = \begin{cases} \max(0, x_d - x_d^*) & \text{if } d = \text{stress} \quad \text{（越低越好，只罚超标）}\\ \max(0, x_d^* - x_d) & \text{otherwise} \quad \text{（越高越好，只罚不足）} \end{cases}$$

综合误差为四维算术平均：

$$e(\mathbf{x}) = \frac{1}{4} \sum_{d} e_d(\mathbf{x})$$

**平和带判定**：$\mathbf{x}$ 处于平和带内 $\iff \forall d: e_d(\mathbf{x}) \leq \beta$。

实现：`contracts/metrics.py` `dim_error()` / `total_error()`。

### 2.4 估计误差

助手在每个 turn 输出对用户状态的估计 $\hat{\mathbf{x}}$，估计误差为欧氏距离：

$$\varepsilon = \|\mathbf{x} - \hat{\mathbf{x}}\|_2 = \sqrt{\sum_{d} (x_d - \hat{x}_d)^2}$$

该误差度量的是**助手的观测器质量**——它从对话中推断用户真实状态的能力。

---

## 3. Layer 1：世界仿真质量

这些指标回答：**仿真本身的动力学是否健康？** 如果世界失真（状态频繁顶到边界、经济崩溃等），Layer 2/3 的评估就失去了生态效度。

### 3.1 状态饱和率（分辨力）

$$\text{clamp\_ratio} = \frac{|\{(i, d) : x_{i,d} \leq 0.001 \lor x_{i,d} \geq 0.999\}|}{\text{slots} \times 4}$$

**阈值**：$\text{clamp\_ratio} > 0.08$ 触发 warning（`insights.py:182`）。

**含义**：状态频繁顶到 $[0,1]$ 边界意味着动力学系数量级失衡——扰动力度过大或恢复力不足。饱和区间的状态变化无法被观测（截断），损失分辨力。

**诊断方向**：检查 `config/balance/` 中扰动事件的 effect 量级、工作消耗与恢复回血的平衡。

### 3.2 日内节律与压力高峰

按四个时段（上午/下午/晚上/深夜）聚合各维度均值，识别压力峰值时段：

$$\bar{\sigma}_{\text{slot}} = \frac{1}{|\text{该时段所有 slot}|} \sum_{i \in \text{slot}} x_{\sigma,i}$$

**阈值**：$\bar{\sigma}_{\text{slot}} > 0.5$ 触发 info。

**含义**：如果压力集中在特定时段（如下午工作时段），说明工作扰动的日内分布合理；如果深夜压力也高，说明恢复机制不足。

### 3.3 经济平衡

追踪金钱轨迹：初始余额、最终余额、负债天数。

**含义**：长期负债说明生活成本或恢复消费与职业收入不匹配，可能压缩了助手的干预空间（没钱安排恢复事件）。

### 3.4 系列事件后效

多日系列事件（出差、度假、大考）结束后，检查心情是否出现预期外的下降：

$$v_{\text{after}} - v_{\text{before}} < -0.05 \quad \text{触发 info}$$

**含义**：系列事件的后效设计可能不合理——期待落空、过度疲惫或预算失控。

### 3.5 Layer 1 解读指南

| 异常信号 | 可能原因 | 排查方向 |
|---------|---------|---------|
| 状态饱和率 > 0.08 | 动力学系数量级失衡 | 减小扰动 effect 或增大恢复强度 |
| 压力高峰在深夜 | 工作/休息分布不合理 | 调整时段模板或动力学时间系数 |
| 负债天数 > 30% | 经济模型不平衡 | 提高职业收入或降低恢复事件定价 |
| 系列后心情反而下降 | 后效曲线不合理 | 调整 peak-end 权重或期间开销 |

---

## 4. Layer 2：用户 Agent 质量（Reward 信号可信度门）

### 4.1 为什么用户 Agent 需要独立评估

UserSim 的 benchmark 有效性依赖于一个前提：**用户 Agent 忠实地扮演了角色卡定义的人格**。如果用户 Agent 言行不一致——比如讨厌户外的人开心接受了露营安排——那么：

- 助手估计用户偏好的"真值"就被污染了（用户自己没按偏好行事）
- 控制效果的评估就失去了意义（用户不抗拒讨厌的事 → 助手不需要精准理解用户也能"成功"）

因此，Layer 2 是 **Layer 3 的质量门**：如果 Layer 2 指标大面积报警，Layer 3 的结果不可信。

5 项一致性指标（M1-M5）实现于 `evaluator/consistency.py`（904 行，纯关键词匹配，0 LLM）。

### 4.2 M1：偏好-行动冲突率（PAC）

**研究问题**：用户是否接受了人格中明确讨厌的事件？如果接受了，抗拒表达是否与顺从度匹配？

**方法**：

1. 定位助手成功安排恢复事件（`add_event_todo` 且 `ok`）的 turn
2. 将事件名映射到 11 个偏好类目之一（`contracts/persona.py` `pref_category()`）
3. 读取用户对该类目的偏好分 $p_c \in [-1, 1]$（角色卡冻结值）
4. 对用户的下一个回应文本做接受类型分类（`consistency.py:137-155`）：

| 接受类型 | 关键词规则 |
|---------|-----------|
| `explicit_resistance` | 含"不喜欢""讨厌""不想""不要""算了"等 |
| `reluctant_accept` | 含"好吧""行吧""那就""随便""勉强"等 |
| `positive_accept` | 含积极词（"好呀""可以""喜欢"等），排除否定前缀（"不想"不算"想"） |
| `neutral` | 以上皆无 |

5. 读入用户的顺从度（大五 facet `宜人性.顺从`，0-100 归一化到 $[0,1]$）

**冲突判定表**：

| 偏好分 $p_c$ | 接受类型 | 顺从度 | 严重度 | 含义 |
|-------------|---------|--------|--------|------|
| $\leq -0.5$（极度厌恶） | `positive_accept` | 任意 | error | 开心接受极度讨厌的事——人格崩坏 |
| $\leq -0.5$ | 无抗拒表达 | 任意 | error | 对极度厌恶事件无任何抗拒 |
| $\in (-0.5, -0.3]$ | 无抗拒表达 | $< 0.35$（低顺从） | error | 低顺从者应直接拒绝讨厌的事 |
| $\in (-0.5, -0.3]$ | 无抗拒表达 | $\geq 0.35$ | warn | 应有至少勉强的表达 |
| $\in (-0.5, -0.3]$ | 有抗拒表达 | 任意 | info | 这是人格一致的表现（扣分豁免） |

**输出指标**：

$$\text{pac\_conflict\_rate} = \frac{\text{conflict\_count}}{\text{total\_acceptances}}$$

$$\text{pac\_severity} = \begin{cases} \text{"error"} & \text{if any error-level conflict} \\ \text{"warn"} & \text{if any warn-level, no error} \\ \text{"none"} & \text{otherwise} \end{cases}$$

### 4.3 M2：会话内情感一致性（WSC）

**研究问题**：用户在同一个 session 内的情感轨迹是否自洽？是否存在无理由的情绪翻转？

**方法**：

**情感得分**（`sentiment_score()`，`consistency.py:157-171`）：

$$s(t) = \frac{n_{\text{pos}} - n_{\text{neg}}}{n_{\text{pos}} + n_{\text{neg}} + 1} \in [-1, 1]$$

其中 $n_{\text{pos}}$ 为积极关键词计数（带否定前缀检测），$n_{\text{neg}}$ 为抗拒关键词 + 抱怨关键词计数。若 $s > 0$ 且存在 hedging 修饰词（"但""不过""有点"等），正分被打折：

$$s' = s \cdot \max(0.5, 1.0 - 0.15 \cdot n_{\text{hedging}})$$

**类型 A — 无因翻转**：用户从消极（$s \leq -0.3$）翻转为积极（$s \geq 0.3$），且中间的助手 turn 没有提供新信息（无工具调用、无建议关键词如"安排""推荐""试试"）。

**类型 B — 持续抗拒后接受**：用户在同一 session 中至少 2 轮表达不满（$s < -0.2$），但最终未以 `explicit_resistance` 结束。

低顺从用户（$< 0.35$）出现类型 B 记为 error；高顺从者记为 warn。

**输出指标**：

$$\text{wsc\_incoherent\_sessions} = N_{\text{typeA}} + N_{\text{typeB}}$$

$$\text{wsc\_coherence\_score} = 1.0 - \min\left(1.0, 2 \cdot \frac{N_{\text{incoherent}}}{\max(1, N_{\text{sessions}})}\right)$$

### 4.4 M3：喜好-请求对齐（PRA）

**研究问题**：落地的日程安排是否与人格偏好对齐？人格中讨厌的类型是否仍被安排？喜爱的类型是否从未被安排？

**信号源迁移（公式 v2）**：新范式下用户不再直接点名方案（prompt v3：用户有时点名想做的事、有时只说感受，由助手搜索推荐），"请求"的主要可观察信号从"用户台词关键词"迁移为**世界裁决后实际落地的日程事件类目**（`add_event_todo` 成功的 turn，事件名经 `pref_category()` 映射到偏好类目）。用户文本关键词降级为辅助：仅当 session 内没有任何裁决事件时，才用首条用户消息的类目做补充提取。

**两个子检查**：

1. **misaligned**：落地事件的类目偏好分 $p_c < -0.3$，记为一次 misaligned——度量的是"讨厌类目被安排"本身（用户接受时是否抗拒由 M1-PAC 判定）。
2. **loved_never_requested**（键名保留，语义已变）：偏好分 $\geq 0.5$ 的 loved 类目在整个 run 中从未被安排——从用户侧考点变为 **assistant 画像利用考点**（摸清喜好后应主动推荐热爱类目；若用户从未表达相关需求，才回看用户侧 plan prompt 的偏好注入是否与角色卡一致）。

### 4.5 M4：人格-行为一致性（PBA）

**研究问题**：用户的对话行为模式（消息长度、表情频率、抱怨率、拒绝方式等）是否与大五人格特质一致？

**方法**：从全部用户 turn 文本中提取 7 个行为特征：

| 行为特征 | 计算方式 | 对应人格 |
|---------|---------|---------|
| 平均消息长度 | $\frac{1}{n}\sum \vert \text{text}\vert$ | 外向性.热情 |
| 表情符号率 | $\frac{\text{emoji\_count}}{n}$ | 外向性.群居性 |
| 抱怨率 | $\frac{\vert \{t: \text{含抱怨词}\}\vert }{n}$ | 神经质.焦虑 |
| 直接拒绝率 | $\frac{\vert \{t: \text{含抗拒词}\}\vert }{n}$ | 宜人性.顺从 |
| 委婉拒绝率 | $\frac{\vert \{t: \text{含委婉词}\}\vert }{n}$ | 宜人性 |
| 好奇心表达率 | $\frac{\vert \{t: \text{含探索词}\}\vert }{n}$ | 开放性.尝新 |

当人格分数 $> 65$ 但对应行为特征不达标时，产生偏差记录（warn 或 info）。

**输出指标**：

$$\text{pba\_correlation} = \max\left(0, 1 - \frac{N_{\text{warn\_deviations}}}{5}\right)$$

### 4.6 M5：跨 Session 偏好稳定性（CSPS）

**研究问题**：同一用户对同一类目事件的态度在不同 session 间是否稳定？

**方法**：对每个偏好类目，收集各 session 中用户的平均情感分。类目的归属信号源与 M3 相同——**主信号为世界裁决后落地的事件类目**（`add_event_todo` 成功的事件名映射），用户文本关键词仅在 session 内无裁决事件时作辅助。若类目的情感分极差超过 1.0：

$$\max_{j} s_{c,j} - \min_{j} s_{c,j} > 1.0$$

则该类目标记为不稳定。

**输出指标**：

$$\text{csps\_stability\_score} = 1.0 - \min\left(1.0, \frac{N_{\text{unstable\_categories}}}{\max(1, N_{\text{categories\_with\_data}})}\right)$$

**含义**：态度不稳定意味着 LLM 在不同 session 中随机表演（temperature 导致的方差淹没了人格信号），而非基于固定偏好的一致性行为。

### 4.7 拟人性补充指标

以下指标也在 Layer 2 范围内，来自 `insights.py`：

| 指标 | 触发条件 | 含义 |
|------|---------|------|
| 台词连续重复 | 相邻 user turn 文本完全相同 $\geq 2$ 次 | LLM 表演同质化，需提高温度 |
| 高频台词 | 同一文本出现 $\geq 3$ 次（非连续） | 口头禅式表达，felt_state 分档词典需增加同义变体 |
| 扰动后无求助 | 扰动 slot 后用户从未开 session | decide_open 的 prompt 倾向过于消极 |
| 求助时延过长 | 平均时延 > 3 个时段 | help_seek 阈值或 assist_prompt 紧迫感不足 |

### 4.7.1 对话形态指标（report["dialogue"]，R4 新增）

`evaluator/dialogue.py` 对 turns.jsonl 做**纯字符串统计**（0 LLM，不测语义只测形态），
结果写入 `report.json` 顶层 `dialogue` 字段，**不进 benchmark_score**——
用途是 prompt/机制改动的 before/after 对照与退化回归：

| 字段 | 含义 |
|------|------|
| `user_repeat_rate` | session 内相邻 user turn 相似度 > 0.75 的占比（跨 session 不比） |
| `assistant_repeat_rate` | 同上，助手侧 |
| `assistant_filler_rate` | 助手回合含纯口癖（好嘞/感叹号）的占比；域词汇（帮你/安排）不计入——真实订单确认语会误命中 |
| `fused_sessions` | runner 复读熔断强制收尾的次数（熔断日志含"复读熔断"标记） |
| `sessions` / `session_turns_mean` | session 数与平均轮数（熔断应使其回归正常区间） |

熔断机制本身在 runner（用户连续 3 次 / 助手连续 2 次相似发言强制收尾），
阈值与这里的统计口径同源（相似度 0.75），保证"熔断数"与"复读率"互相印证。

### 4.8 Layer 2 解读指南

| 异常信号 | 可能原因 | 修复方向 |
|---------|---------|---------|
| PAC conflict rate > 0 且 severity=error | 用户 Agent 的 prompt 中偏好权重被 LLM 忽视 | 强化 prompt 铁律："你的性格与喜好是固定的，不要为了迎合助手而改变偏好"；提高 hates 类目的抗拒引导强度 |
| WSC 无因翻转频繁 | 用户 LLM "讨好助手"——态度转变缺乏合理过渡 | 在 prompt 中要求"态度转变时应有合理的情感过渡"；降低 temperature |
| PBA 多种人格偏离 | 温度过高导致随机行为覆盖人格信号 | 降低 temperature；简化 prompt 使人格描述更突出 |
| CSPS 稳定性差 | 同一种子不同 session 的 LLM 表现不一致 | 检查 prompt 是否每次充分注入偏好；检查是否有随机采样导致的关键词缺失 |
| 扰动后无求助 | decide_open 过于保守 | 降低 help_seek 阈值；提高 assist_prompt 的紧迫感 |

**关键判断**：如果 M1-M5 全部 clean，说明用户 Agent 忠实地扮演了角色卡——此时 Layer 3 的评估结果是可信的。如果 M1-M5 有 error 级别违规，优先修复用户 Agent 再评估助手。

---

## 5. Layer 3：助手 Agent 质量

助手 Agent（Harness）的质量从四个维度度量：**控制质量**（能不能把状态带回目标）、**估计质量**（能不能从对话中推断用户状态）、**画像学习质量**（能不能学会用户的固定人格和喜好）、**行为质量**（有没有违反协议、有没有及时响应扰动）。

### 5.1 控制质量（控制论指标体系）

全部基于 slot 序列 $\{\mathbf{x}_i\}_{i=0}^{n-1}$（每个 slot 的世界结算后状态）。

#### 5.1.1 稳态误差 $e_{ss}$

$$e_{ss} = \frac{1}{T_{\text{tail}}} \sum_{i=n-T_{\text{tail}}}^{n-1} e(\mathbf{x}_i)$$

其中 $T_{\text{tail}} = 12$（`config/system.toml [eval] tail_slots_for_ess`，相当于最后 3 天）。

**回答的问题**：系统最终收敛了吗？

**阈值**：$e_{ss} \leq 0.060$ 为"收敛"条件之一（v4.1 按 20 个干净 live episode 标定）；$e_{ss} > 0.080$ 为"发散"条件之一。

#### 5.1.2 调节时间 $t_s$

找到首次压力冲出带外的时刻 $d_0$（$e_{\text{stress}}(\mathbf{x}_{d_0}) > \beta$），随后寻找第一个满足"从 $i$ 起 3 天滑窗（12 个时段）内带内驻留占比 ≥ 70%"的位置 $i^*$：

$$t_s = \frac{i^* - d_0}{\text{spd}} \quad \text{[天]}$$

（v5 起改为**窗口驻留判定**：旧版要求连续 8 个时段全部在带——日内正常摆幅会永久打断连续计数，控制良好的 run 也永远"未稳定"。滑窗参数：`[eval] settle_window_days=3`、`settle_in_band_ratio=0.70`。）

边界语义：**全程从未冲出带外**（$d_0$ 不存在）记 $t_s = 0$——从未失控即是从起点就稳定；**冲出带外但到运行结束都没有任何完整滑窗达标**才记 $t_s = \text{None}$（从未回带）。

**回答的问题**：系统受到扰动后，多久能恢复？

**阈值**：$t_s \leq 5.0$ 天为"收敛"条件之一（R4 起按 live reference 实测校准；旧值 2.5 天为 replay 脚本口径）。

#### 5.1.3 超调量 $M_p$

$$M_p = \max_{i \in \text{hot\_windows}} \max(0, \sigma^* - x_{\sigma,i})$$

其中 hot window 定义为：stress 冲出带外后激活的 10-slot 窗口期间。**两种排除**：
- **释放冷却**：如果某个 slot 的 event_effects 中 stress 下降幅度 $\geq 0.08$（大型 stress-releasing 事件如度假结束），触发 8-slot 冷却期——期间不记录 overshoot（这是事件效果，不是控制器过校正）
- **前置条件**：stress 必须已经超过 $0.30 + 0.10 = 0.40$ 才能激活 hot window

**回答的问题**：控制器是不是"用力过猛"——把 stress 压到了目标以下很远？

**阈值**：$M_p < 0.20$ 为"收敛"条件之一（R4 起按 live reference 实测校准；旧值 0.15 为 replay 脚本口径）。

#### 5.1.4 积分指标（IAE / ISE / ITAE）

所有按天归一（除以 `slots_per_day`）：

$$\text{IAE} = \frac{1}{\text{spd}} \sum_{i=0}^{n-1} e(\mathbf{x}_i) \quad \text{（全程平均误差）}$$

$$\text{ISE} = \frac{1}{\text{spd}} \sum_{i=0}^{n-1} e(\mathbf{x}_i)^2 \quad \text{（惩罚大偏差）}$$

$$\text{ITAE} = \frac{1}{\text{spd}} \sum_{i=0}^{n-1} \frac{i}{\text{spd}} \cdot e(\mathbf{x}_i) \quad \text{（惩罚晚期误差）}$$

**对比含义**：
- ISE $\gg$ IAE：存在少数大幅度偏离（被平方放大）
- ITAE $\gg$ IAE：误差集中在运行后期（越往后越差）
- ISE $\ll$ IAE：小幅度波动为主，无剧烈冲击

#### 5.1.5 状态方差 $\sigma^2$

$$\sigma^2_e = \frac{1}{n} \sum_{i=0}^{n-1} (e(\mathbf{x}_i) - \bar{e})^2$$

**回答的问题**：状态是平稳波动还是剧烈振荡？

#### 5.1.6 带内驻留比 $\rho$

$$\rho = \frac{|\{i \in [n - W \cdot \text{spd}, n) : \text{in\_band}(\mathbf{x}_i)\}|}{W \cdot \text{spd}}, \quad W = 10 \text{ 天}$$

**回答的问题**：最后 10 天中，有多少时间用户处于"平和"状态？

#### 5.1.7 滑动窗口指标序列

对于超长 run（$\gg$ 10 天），评估器逐日滑动 $W$ 天窗口输出指标序列：

$$W_j = \{\text{start\_day}_j, \text{end\_day}_j, \overline{e}_j, \max(e)_j, \rho_j\}$$

用于健康监控——检测是否存在"中期收敛、后期退化"的时间模式。

实现：`metrics.py` `_sliding_windows()`。

### 5.2 估计质量（State Estimation）

#### 5.2.1 信念误差学习曲线

每日聚合所有助手 turn 的估计误差（$\varepsilon = \|\mathbf{x} - \hat{\mathbf{x}}\|_2$），形成学习曲线：

$$\text{daily\_est\_err}[k] = \frac{1}{|\text{day}_k\text{'s turns with }\hat{x}|} \sum_{t \in \text{day}_k} \varepsilon_t$$

**最终估计误差**：$\varepsilon_{\text{final}} = \text{daily\_est\_err}[-1]$

**误差斜率**（线性回归）：

$$m_{\varepsilon} = \frac{n \sum d_k \varepsilon_k - (\sum d_k)(\sum \varepsilon_k)}{n \sum d_k^2 - (\sum d_k)^2}$$

**回答的问题**：助手是不是越用越懂用户？（$m_{\varepsilon} < 0$ = 是；$m_{\varepsilon} > 0$ = 反而更差了）

> **基线断代声明**：Phase 1（R1/R2）的 `est_err_final` 数值不可与 Phase 2 直接比较——Phase 1 存在刻度泄漏（提示词中的逐维校准刻度与世界分档词典互为逆映射，助手做字符串查表即可压低偏差）。Phase 2 去泄漏后应以 $m_{\varepsilon}$ 为主要判断依据。

#### 5.2.2 系统性偏差

对每个维度，计算 $\hat{x}_d - x_d$ 的均值（符号）：

$$\text{bias}_d = \frac{1}{|\text{turns with }\hat{x}|} \sum_{t} (\hat{x}_{t,d} - x_{t,d})$$

**阈值**：$|\text{bias}_d| > 0.08$ 触发 warning（`insights.py:105`）。

**含义**：正 bias = 系统性高估（助手上乐观滤镜），负 bias = 系统性低估。单维偏差提示该维度的用户表达与助手刻度之间存在映射误差。

#### 5.2.3 估计更新停滞

$$\text{frozen\_ratio} = \frac{|\{(t, t+1) : \hat{\mathbf{x}}_t = \hat{\mathbf{x}}_{t+1}\}|}{\max(1, N_{\text{hats}} - 1)}$$

**阈值**：$\text{frozen\_ratio} > 0.3$ 触发 warning（`insights.py:346`）。

**含义**：相邻 turn 的 user_belief 大量不变——Harness 可能在缓存旧估计而非每次刷新。

### 5.3 画像学习质量（Persona Profiling）

助手的目标不仅是控制状态，还包括**学习用户的人格与喜好**（"冻结维度"——这些在整个 run 期间不变，但助手只能从对话中推断）。

真值来自 `meta.json` 的角色卡（30 NEO-PI-R 细分面 × 0-100 分 + 11 类目偏好 × [-1,1] + loves/hates 标签集）。

#### 5.3.1 人格 Facet 误差

**末期误差**（取最后一天，而非全程均值——"最后学没学会"才是考点）：

$$e_{\text{persona}} = \frac{1}{|K_{\text{estimated}}|} \sum_{k \in K_{\text{estimated}}} \frac{|f_k^{\text{true}} - f_k^{\text{est}}|}{100}$$

其中 $K_{\text{estimated}}$ 是助手实际给出了估计值的 facet 集合。

#### 5.3.2 人格覆盖率

$$\text{persona\_coverage} = \frac{|K_{\text{estimated}}|}{30}$$

**阈值**：$\text{coverage} < 0.4$ 触发 warning——多轮对话应逐步覆盖更多特质。

#### 5.3.3 人格学习斜率

对每日平均 facet 误差做线性回归，得到 $m_{\text{persona}}$。

**阈值**：$m_{\text{persona}} > 0.002$/天 触发 warning（越聊越差）。

#### 5.3.4 喜好类目误差

$$e_{\text{prefs}} = \frac{1}{|C_{\text{estimated}}|} \sum_{c \in C_{\text{estimated}}} \frac{|p_c^{\text{true}} - p_c^{\text{est}}|}{2}$$

（类目分在 $[-1,1]$，除以 2 归一化到 $[0,1]$）

#### 5.3.5 标签命中率（F1）

loves 和 hates 标签集的 F1（支持双向子串匹配——真值"寿喜烧"与估计"喜欢吃寿喜烧"算命中）：

$$\text{prefs\_tag\_f1} = \frac{\text{F1}_{\text{loves}} + \text{F1}_{\text{hates}}}{2}$$

**关键设计取舍**：
1. **取末期而非全程均值**：画像是学习任务，全程均值会惩罚"一开始不懂"这件必然的事
2. **没有估计 ≠ 零误差**：未估计的 facet 不参与误差计算，覆盖率单独报告；但在健康分里，没有估计按满误差 0.5 计——"不作为不能免罚"
3. **标签命中双向包含**：不要求复现原文，子串匹配即可

实现：`contracts/persona.py` `facet_error()` / `facet_coverage()` / `prefs_error()` / `tag_hit_rate()`。

### 5.4 行为质量

| 指标 | 触发条件 | 严重度 | 含义 |
|------|---------|--------|------|
| 契约违约 | `contract_violation` 字段非空 | error | AssistantTurn 未按契约输出（缺 user_belief / JSON 失败） |
| LLM 降级 | `degraded` 字段非空 | warn | LLM 超时/失败重试耗尽后跳过 turn |
| 扰动无响应 | 无恢复安排的扰动数 $\geq \max(2, N_{\text{扰动}}/3)$ | warn | 扰动是最明确的干预时机，覆盖率过低说明助手反应迟钝 |
| 高压无恢复日 | 日均 stress > 0.55 且无恢复安排 $\geq 3$ 天 | warn | 干预缺失——压力高时应有更强的主动建议 |
| 纯聊天 Session | 无工具调用的多轮 session（$\geq 4$ turns）$\geq 3$ 个 | info | 只安慰不解决——鼓励助手在共情后落到具体安排 |
| Session 内估计恶化 | session 内 belief_err $\uparrow > 0.05$ 出现 $\geq 2$ 次 | warn | 对话深入后估计反而变差——新信息在带偏估计器而非改善它 |
| 恢复缓慢 | 扰动后回带时间 > 6 时段 | info | 恢复强度不足（选档太低）或恢复时机过晚 |
| 工具预算被拒 | `add_event_todo` 因余额不足失败 | info | 正常的经纪博弈信号；高频出现则教助手先查余额 |
| 日程冲突 | 同一时段重复安排事件 | warn | 助手不看已有日程就写——应先 `view_event_todos` |
| 推荐被明确拒绝 | `add_event_todo` 成功后用户下一句为明确抗拒的比率 > 0.3（且成功安排 ≥ 3 次） | warn | 推荐与用户需求/偏好不匹配——应利用画像信念推荐（偏好类目/loves），并尊重用户的餍足反馈（`insights.py` `stats["rec_rejected"]`，只进 findings，不进 benchmark 分数） |

### 5.5 Layer 3 解读指南

| 异常信号 | 可能原因 | 修复方向 |
|---------|---------|---------|
| $e_{ss} > 0.08$（发散） | 助手控制能力根本不足 | 检查 Harness 的工具使用率、恢复事件强度（档位选择）、时序安排合理性 |
| $t_s = \text{None}$（永不收敛） | 持续的扰动未被充分应对 | 检查扰动响应覆盖率；增加扰动的恢复事件配对 |
| $M_p > 0.20$（过冲） | 恢复事件强度过大 | 降低高 stress 时安排的恢复事件档位 |
| $\varepsilon_{\text{final}}$ 大且 $m_{\varepsilon} > 0$ | Harness 估计器有结构性缺陷 | 检查 user_model 提示中的状态刻度；加入逐维校准 |
| $\text{frozen\_ratio} > 0.3$ | 估计器未在每次对话后刷新 | 确保每条新 user 消息后调用 user_model |
| `persona_coverage` < 0.4 | 助手不主动了解用户 | 在 persona_belief 提示中强调"每次有线索时更新相应 facet" |
| $m_{\text{persona}} > 0$ | 累积器被单句话带跑方向 | 提示助手"没证据的 facet 留空比填 50 更好；有证据时渐进修正" |
| 扰动无响应频繁 | 助手 trigger 链路断了 | 检查 assist_prompt 注入 → 用户求助 → 助手安排 的全链路 |

---

## 6. 综合判定体系

### 6.1 三级判定

对单次 run，评估器输出三级 verdict（`metrics.py` `_verdict()`）：

| Verdict | 条件 | 含义 |
|---------|------|------|
| **converged** | $e_{ss} \leq 0.030$ **且** $t_s \neq \text{None}$ **且** $t_s \leq 5.0$ 天 **且** $M_p < 0.20$ | 系统最终收敛到平和带，恢复速度合理，无过冲 |
| **diverged** | worsening **或** $e_{ss} > 0.080$ | 系统在恶化（后 5 天均值 > 前 5 天 × 1.5 + 0.02），或稳态误差过大 |
| **oscillating** | 以上皆非 | 能回稳但反复过冲，存在极限环——需要更精细的控制策略 |

其中 **worsening** 使用窗口均值对比（比端点斜率抗振荡噪声）：

$$\text{worsening} \iff \bar{e}_{\text{last 5 days}} > \bar{e}_{\text{prev 5 days}} \times 1.5 + 0.02 \quad (\text{且至少有 10 天数据})$$

### 6.2 健康分（0-100）

健康分是对所有维度的加权综合——**不是"助手有多好"，而是"这次运行的总体质量（含世界+用户+助手）有多高"**：

$$H = \max\left(0, 100 - \sum_{k} \min(\text{cap}_k, o_k \cdot \text{coeff}_k)\right)$$

每项扣分 $= \min(\text{上限}, \text{观测值} \times \text{系数})$。权重在 `config/system.toml [score]` 中配置。

### 6.3 扣分权重表与设计依据

| 扣分项 | 系数 | 上限 | 观测值 $o_k$ | 设计依据 |
|--------|------|------|-------------|---------|
| `ess` | 200 | 40 | 稳态误差（尾 12 slot 均值） | 控制目标本身，权重最重。$e_{ss}=0.20$ 即扣满 |
| `violations` | 5 | 15 | 契约违约率（每 100 助手 turn） | 协议遵守是硬要求，但单次违约不应主导总分。v4 起按话务量归一——原始计数随 turn 数漂移（348-1286/30天），话多的 run 被冤枉 |
| `xhat_bias` | 80 | 10 | 最大系统性偏差 | 观测器质量：0.125 偏差即扣满——系统性偏移比随机误差更致命 |
| `user_dup` | 1.5 | 10 | 连续重复台词次数 | 拟人性：台词复读是 LLM 退化的最明显信号 |
| `clamp_ratio` | 80 | 10 | 状态饱和率 | 世界分辨力：12.5% 饱和率即扣满——饱和区间损失信息 |
| `no_recover` | 2 | 10 | 无响应的扰动数 | 干预覆盖：5 次无响应即扣满——扰动是最明确的介入时机 |
| `persona_err` | 40 | 10 | 画像末期误差 | 人格/喜好估计精度：0.25 误差即扣满。**没有估计按 0.5 满误差计**——不作为不能免罚（否则 stub 反而占便宜） |
| `pac_conflict` | 25 | 12 | 偏好-行动冲突率 | 用户一致性：48% 冲突率即扣满 |
| `wsc_incoherent` | 15 | 8 | 1.0 - coherence_score | 用户一致性：53% 不一致即扣满 |
| `pra_misaligned` | 10 | 5 | 错位请求比例 | 用户一致性：50% 错位即扣满 |

总扣分上限 140，健康分最低为 0。

### 6.4 洞察（Finding）生成规则全集

`insights.py` `compute_insights()` 产出分类诊断发现（findings），每条包含 severity / category / title / detail / suggestion / evidence。

**严重度排序**：error（故障级，必须修）→ warn（问题级，建议修）→ info（信息级，了解即可）。

完整触发条件如下（按 category 分组）：

#### 世界（World）

| 触发条件 | 严重度 | 标题模板 |
|---------|--------|---------|
| 最差维度 mean_err > 0.06 | warn | "控制最差维度：{label}（平均误差 {err:.3f}）" |
| 状态饱和率 > 0.08 | warn | "状态饱和率 {ratio:.1%}" |
| 存在负债时段 | info | "负债 {n} 时段（{days} 天）" |
| 压力高峰时段均值 > 0.5 | info | "压力高峰时段：{slot_name}（均 {stress:.2f}）" |
| 系列事件后心情下降 > 0.05 | info | "系列「{name}」后心情反而下降" |

#### 助手（Assistant）

| 触发条件 | 严重度 | 标题模板 |
|---------|--------|---------|
| 最大 x̂ 偏差 > 0.08 | warn | "x̂ 系统性偏差：{dim} {'高估'/'低估'} {bias:.2f}" |
| 高压无恢复日 ≥ 3 | warn | "高压无恢复日 ×{n}" |
| 扰动无响应 ≥ max(2, 扰动数/3) | warn | "{n}/{total} 次扰动后无恢复安排" |
| 估计更新停滞率 > 0.3 | warn | "估计更新停滞率 {ratio:.0%}" |
| Session 内估计恶化 ≥ 2 次 | warn | "session 内估计反而变差 ×{n}" |
| 从未估计人格 | warn | "从未估计用户人格/喜好" |
| 人格覆盖率 < 0.4 | warn | "人格画像覆盖率仅 {cov:.0%}" |
| 人格误差 > 0.25 | warn | "人格估计偏差 {err:.2f}" |
| 人格学习斜率 > 0.002/天 | warn | "画像越聊越差" |
| 恢复缓慢（回带 > 6 时段） | info | "恢复缓慢扰动 ×{n}" |
| 纯聊天 session ≥ 3（≥ 4 turns 无工具） | info | "纯聊天 session ×{n}" |
| 推荐被明确拒绝比率 > 0.3 且成功安排 ≥ 3 | warn | "推荐被明确拒绝 ×{rejected}/{scheduled}" |

#### 契约（Contract）

| 触发条件 | 严重度 | 标题模板 |
|---------|--------|---------|
| 存在 contract_violation turn | error | "助手契约违约 ×{n}" |

#### 故障（Fault）

| 触发条件 | 严重度 | 标题模板 |
|---------|--------|---------|
| 存在 degraded turn | warn | "LLM 调用降级 ×{n}" |

#### 工具（Tool）

| 触发条件 | 严重度 | 标题模板 |
|---------|--------|---------|
| 预算被拒 × N | info | "预算被拒 ×{n}" |
| 日程冲突 × N | warn | "日程冲突 ×{n}" |
| 其他工具失败 | warn | "工具失败：{reason} ×{n}" |

#### 拟人性（Humane-ness）

| 触发条件 | 严重度 | 标题模板 |
|---------|--------|---------|
| 连续重复台词 ≥ 2 次 | warn | "用户连续重复台词 ×{n}" |
| 高频台词（≥ 3 次） | warn | "高频台词：「{text}…」×{n}" |
| 扰动后未求助 | warn | "{n} 次扰动后用户始终未求助" |
| 平均求助时延 > 3 时段 | info | "平均求助时延 {lat:.1f} 时段" |

#### 一致性（Consistency）

由 `consistency.py` 的 M1-M5 各计算函数返回，已在 §4.2-§4.6 详述。

---

## 7. 模型对比与 Benchmark 协议

### 7.1 单 Run 解读工作流

研究者的标准解读流程：

1. **看 health_score**：快速判断整体质量（90+ = 优秀，70-90 = 良好，50-70 = 有问题，<50 = 严重问题）
2. **看 verdict**：converged → 控制成功；oscillating → 深入看 IAE/ISE 和 oscillating 的模式；diverged → 优先排查
3. **看 Layer 2 报警**：如果 M1-M5 有 error，先修用户 Agent 再评估助手（Layer 3 结果暂时不可信）
4. **看 Layer 3 控制指标**：$e_{ss}$ 和 $t_s$——最终收敛了吗？恢复快吗？
5. **看 Layer 3 估计学习曲线**：$\varepsilon_{\text{final}}$ 和 $m_{\varepsilon}$——助手懂用户吗？越来越懂还是越来越差？
6. **看 Layer 3 画像学习曲线**：$e_{\text{persona}}$ 和 $m_{\text{persona}}$——助手了解用户的人格和喜好吗？
7. **看 findings**：逐条 reading，从 error → warn → info，每条 check suggestion
8. **看 Layer 1**：世界仿真健康吗？有没有饱和、经济崩溃？

### 7.2 多 Seed 统计聚合

Benchmark 对同一配置跑多个 seed（不同角色卡），跨 episode 聚合：

- **均值 $\pm$ CI95**：$n \leq 30$ 用 Student's t-distribution，$n > 30$ 用正态近似 $z=1.96$
- **verdict_share**：各 verdict 占比
- **verdict_mode**：最频繁的 verdict（平局时偏向更差的类别——保守原则）
- **never_settled**：$t_s = \text{None}$ 的 episode 数（= 出带后从未回带；v5 起"全程未出带"记 $t_s=0$ 不再计入。单独统计，不与 settling_time 的均值混淆）

实现：`bench/aggregate.py`。

### 7.3 量程守护与判别力验证

**量程守护（Range Guard）**：验证 benchmark 本身是否能区分 good 与 poor 两种助手质量。

对两组跑多 seed，检查：

$$\text{Cohen's } d = \frac{\bar{x}_{\text{poor}} - \bar{x}_{\text{good}}}{s_{\text{pooled}}}, \quad s_{\text{pooled}} = \sqrt{\frac{(n_A-1)s_A^2 + (n_B-1)s_B^2}{n_A + n_B - 2}}$$

**要求**：$d \geq 0.8$（large effect），且两组 IAE 的 95% CI 不重叠。

如果量程守护失败（good 和 poor 区分不开），benchmark 本身缺乏判别力——此时跨模型对比也没有意义。

### 7.4 消融实验设计指南

UserSim 的三层解耦天然支持消融实验：

| 消融类型 | 具体操作 | 验证的目标 |
|---------|---------|-----------|
| **用户 Agent 消融** | 将 LLM 用户替换为 scripted user，对比 consistency 指标 | 验证 M1-M5 能否检测 LLM 的一致性退化 |
| **助手能力消融** | 对比 good / mid / poor 三档（scripted 模式下精确控制恢复强度） | 验证控制指标的判别力 |
| **提示词消融** | 修改 Harness 的 user_model 提示（加/去刻度、加/去 persona 引导） | 验证估计/画像指标对提示变化的敏感度 |
| **世界参数消融** | 改变扰动频率、恢复强度、动力学系数 | 验证 Layer 1 指标能否检测仿真退化 |

### 7.5 结果报告模板

跨模型对比的标准报告应包含：

| 模块 | 内容 |
|------|------|
| **量程守护** | Cohen's d, good/poor 的 IAE CI 范围，判别力 PASS/FAIL |
| **控制能力对比** | 各模型的 $e_{ss}$、$t_s$、IAE、$\rho$（均值 $\pm$ CI95），verdict 分布 |
| **估计能力对比** | $\varepsilon_{\text{final}}$、$m_{\varepsilon}$、偏差维度 |
| **画像学习对比** | $e_{\text{persona}}$、coverage、$m_{\text{persona}}$、$e_{\text{prefs}}$ |
| **用户一致性** | M1-M5 指标汇总（确保对比基线可信） |
| **异常摘要** | 各模型的 finding 数（按 severity 汇总） |

---

## 8. Benchmark 分数（存档综合分）

**一个存档 → 一个百分制分数。** 它把本文件前面定义的全部存档指标折算成单一 KPI，
回答"这个被测 assistant 到底打了多少分"。前端指标栏直接展示公式与逐项扣分明细；
实现：`evaluator/score.py`，权重配置：`config/system.toml [benchmark]`。

### 8.1 公式

$$B = \max\Big(0,\; 100 - \sum_k \min(\text{cap}_k,\; w_k \cdot x_k)\Big)$$

每个存档指标先归一为**"越大越差"的观测量** $x_k$，乘系数 $w_k$、封顶 $\text{cap}_k$
后从 100 扣减。观测量的归一规则：

| 观测量 | 来源指标 | 归一规则 |
|--------|---------|---------|
| `ess` | $e_{ss}$ | 原值 |
| `settle_frac` | $t_s$ | 未稳定 = 1.0；已稳定 = $t_s$ / 总天数 |
| `overshoot` | $M_p$ | 原值 |
| `iae_daily` | IAE | IAE / 总天数（≈ mean\|e\|，与 run 长短无关才可横向比较） |
| `variance` | $\sigma^2$ | 原值 |
| `band_deficit` | $\rho$ | $1 - \rho$ |
| `est_err` / `est_slope` | $\varepsilon_{\text{final}}$ / $m_{\varepsilon}$ | 原值 / 只计正斜率 |
| `persona_err` / `coverage_deficit` / `prefs_err` / `f1_deficit` | 画像指标组 | 原值 / $1-$coverage / 原值 / $1-$F1 |
| `violations` / `no_recover` / `pac_conflict` / `pra_misaligned` | insights 观测量 | 原值（单一数据源：insights.json `stats.score_observations`） |

> **v3 起移出 benchmark 的仿真健康指标**（仍归 health_score，见 §6.2）：`user_dup`
> （用户 LLM 台词多样性）、`clamp_ratio`（世界饱和分辨力）、`wsc_incoherent`
> （用户台词情感摆荡）。移除理由：归因混杂——它们度量的是用户 LLM 与世界动力学
> 的属性而非被测 assistant 能力，且实测同 harness 跨轮漂移数倍（噪声主导）。

### 8.2 设计理由

1. **为什么是扣分制而不是加权平均加分**：存档指标方向不一（$e_{ss}$ 越小越好、$\rho$
   越大越好、$t_s$ 可能"未稳定"缺失），加分制对缺失值没有自然处理。扣分制先把一切
   归一为"越大越差"，缺失即满观测——**不作为不能免罚**：不报画像的 assistant
   （如 stub）按满误差 0.5 扣，否则"什么都不做"反而占便宜。
2. **为什么每项封顶（cap）**：防止单一病态指标把分数打到 0，抹掉其他维度的区分度。
   例如 stub 的 $e_{ss}$ 极差，但它的契约违约是 0——cap 让"控制崩了但契约干净"
   与"控制崩了且契约也崩"仍然可区分。
3. **为什么是线性系数而非 log/sigmoid**：可解释、可调参。"改 0.01 的 $e_{ss}$ 值
   多少分"必须能心算（0.01 × 200 = 2 分），非线性变换会把调参变成试错。所有
   [系数, 上限] 都在 `config/system.toml [benchmark]`，与 [score] 健康分同构。
4. **权重分配的理由**（三组的封顶总额，v3）：**控制表现 ≈64 分 > 状态估计与画像
   ≈35 分 > 契约与仿真有效性 ≈30 分（门槛项，单项上限小）**。
   - 控制表现是主体：benchmark 的存在意义就是测"把用户状态控制在平和带"，
     $e_{ss}$ 一项上限 30，是全场最重单项；
   - 估计与画像是第二公理（助手要"理解用户"），但它服务于控制，故次之；
   - 契约违约与扰动响应是**门槛**而非主体：违约说明 assistant 连协议都守不住，
     必须重罚（单项上限 15，仅次于 ess）；v3 起，归因混杂的仿真有效性项
     （user_dup、clamp、一致性——度量的是用户/世界质量）不再从此扣分，
     全部归 health_score：仿真缺陷应去修仿真，而不是让 assistant 分数被淹没。
5. **IAE 为什么要除天数**：IAE 是累计总量，30 天 run 天然比 10 天 run 大；
   归一为 `iae_daily`（≈ mean|e|）后不同天数的存档才可横向比较。
   `settle_frac` 同理用占比而非绝对天数。
6. **与 health_score 的分工**：health_score（§6.2）诊断**仿真本身**是否健康
   （用户复读、状态饱和、一致性占大头，是给仿真维护者的）；benchmark 分给
   **被测 assistant** 打分（控制与画像占主体，是给模型对比用的）。两者数据源
   相同（insights 观测量只算一遍，经 `stats.score_observations` 复用），
   但权重表互相独立，避免"改健康分权重影响模型排名"。

### 8.3 调参与扩展

- 改权重：只动 `config/system.toml [benchmark]`（[系数, 上限] 对），代码默认值与其一致；
- 加新指标项：在 `evaluator/score.py` 的 `_TERMS` 注册（组、标签、默认权重），
  并在 `report_observations()` 给出归一规则；前端明细表自动出现新行；
- 公式版本：report.json `benchmark.version`（当前 **v3**），改归一规则时递增，
  跨版本分数不可直接比较。**v2 变更**：M3-PRA 的信号源从"用户台词关键词"迁移为
  "世界裁决后落地的日程事件类目"（§4.4）。**v3 变更**：① 归因混杂的三个仿真健康
  指标（`user_dup`/`clamp_ratio`/`wsc_incoherent`）移出扣分项（归 health_score）；
  ② `est_err_final`/`persona_err_final` 从"最后一天单日采样"改为**末端 5 天均值**，
  抗末端剧情相位噪声（单日恰遇扰动日不再毁掉终值）。

---

## 9. 实现参考

### 9.1 代码入口与文件清单

| 文件 | 职责 |
|------|------|
| `evaluator/__init__.py` | 导出 `compute_metrics`, `load_run` |
| `evaluator/metrics.py` | 控制论指标 + 三级判定 + 画像/估计指标（296 行） |
| `evaluator/insights.py` | 多类目诊断发现 + 健康分 + 摘要生成（509 行） |
| `evaluator/consistency.py` | 5 项行为一致性指标 M1-M5（904 行） |
| `evaluator/report.py` | 报告构造：加载 → 计算 → 写入 `report.json` + `insights.json` |
| `evaluator/score.py` | benchmark 分数：全部存档指标 → 单一百分制（§8；权重在 `[benchmark]`） |
| `contracts/metrics.py` | 共享误差函数：`dim_error`, `total_error`, `belief_error` |
| `contracts/persona.py` | 人格词表 + 画像精度函数：`facet_error`, `facet_coverage`, `prefs_error`, `tag_hit_rate` |
| `bench/aggregate.py` | 跨 episode 统计聚合 + Cohen's d |
| `config/system.toml` | `[eval]` 阈值 + `[score]` 权重 + `[benchmark]` 分数权重 + `[state]` 目标与 band |

### 9.2 配置项速查

所有阈值集中在 `config/system.toml`，改后不必重跑 LLM——直接对历史 `runs/` 重算报告即可：

```bash
python -m usersim.evaluator.report runs/<run_id>
```

| 节 | 键 | 默认值 | 用途 |
|----|-----|--------|------|
| `[eval]` | `window_days` | 10 | 滑窗大小 & 带内驻留比窗口 |
| `[eval]` | `tail_slots_for_ess` | 12 | $e_{ss}$ 采样时段数 |
| `[eval]` | `settle_window_days` | 3 | 调节时间滑窗（天）：窗内 in_band ≥ 阈值即稳定（v5 起替换连续入带判定） |
| `[eval]` | `settle_in_band_ratio` | 0.70 | 滑窗内带内驻留占比阈值（旧 `settle_band_slots=8` 连续判定已下线） |
| `[eval]` | `converged_ess_max` | 0.060 | 收敛 $e_{ss}$ 上限（v4.1 按 20 个干净 live episode 标定） |
| `[eval]` | `converged_settle_max` | 5.0 | 收敛 $t_s$ 上限（天；R4 起按 live reference 实测校准，旧值 2.5 为 replay 口径） |
| `[eval]` | `converged_overshoot_max` | 0.20 | 收敛 $M_p$ 上限（R4 重校准，旧值 0.15 为 replay 口径） |
| `[eval]` | `diverged_ess_min` | 0.080 | 发散 $e_{ss}$ 下限 |
| `[state]` | `targets` | {v:0.72, e:0.70, s:0.65, σ:0.30} | 各维度目标值 |
| `[state]` | `band` | 0.10 | 平和带半宽 |
| `[score]` | 各扣分项 | 见 §6.3 | 健康分系数与上限 |
| `[benchmark]` | 各扣分项 | 见 §8 | benchmark 分数系数与上限（被测 assistant 主 KPI） |

另有硬编码在 `insights.py` 的诊断项：`stats["rec_rejected"]`（推荐被明确拒绝比率——
`add_event_todo` 成功后用户下一句明确抗拒的占比；阈值 0.3、最小样本 3 次成功安排）
只产出 findings 告警，不进 benchmark 分数，也不在 `config/system.toml` 配置。

### 9.3 扩展指南

新增指标时：
1. 指标函数放在 `evaluator/` 下对应文件（控制类 → `metrics.py`，诊断类 → `insights.py`，一致性类 → `consistency.py`）
2. 零 LLM 约束：只能使用 `slots.jsonl` / `turns.jsonl` / `meta.json` 的结构化数据 + 关键词匹配；不得调用 LLM 解读对话语义
3. 如果指标跨 episode 聚合有意义，在 `bench/aggregate.py` 中注册（自动纳入多 seed 统计）
4. 配置阈值放在 `config/system.toml` 的相关节下
5. 同步更新本文档对应的 Layer 和指标表
