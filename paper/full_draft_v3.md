# UserSim: Efficient Lifelong Assistant Agent Benchmark Via Rule-Based World Model and Control Theory Inspired Metrics.

keywords: LLM, long-term evaluation, user simulation, rule-based simulation, human proxy, entropy, control theory
针对长程、针对日常生活assistant，相对general范围

> 数值占位约定：`[·]` 表示该数据尚无实验支撑，对应实验设计见 `paper/pending_experiments.md`。

## 1 Introduction

LLM 驱动的个人助手正在从"一次性问答工具"转变为*长期伴随式智能体*：它需要在数周乃至数月的连续交互中记住用户、理解用户、在恰当的时机介入、并在不该打扰时保持安静 (Park et al., 2023; Zheng et al., 2025)。然而主流评测体系仍锚定在短 horizon 范式上：静态问答集在冻结的对话记录上探测知识或长上下文记忆 (Maharana et al., 2024; Wu et al., 2024)，单 episode 任务 benchmark 在可执行环境中测量工具调用与任务完成率 (Liu et al., 2023; Jimenez et al., 2023; Zhou et al., 2023a)。尽管前沿 agent 可完成任务的时长正在快速增长 (Kwa et al., 2025)，这些范式都无法回答产品决策者真正关心的问题：*对于一个处于长期持续交互中的 agent，如何准确且高效地评估其用户满意度？*

为了定量研究这个问题，我们将其进一步分解：assistant 应当在与用户的持续接触中逐渐学会用户的画像与偏好，并以最高效的方式为用户提供建议和帮助。评估这样的长程行为需要四个主体——**世界**、**用户**、**被测 assistant** 与**裁判**。我们将世界与用户视为一个耦合的动力学系统，其状态随时间演化。在这一抽象下，现有评测范式可以沿两条轴定位：世界如何构造、用户如何构造（图 1）。最真实的反馈自然来自真实世界与真实人类用户，但人在环纵向研究的成本高到难以承受 (Kapoor et al., 2024)。我们需要的是一种对世界–用户动力学的仿真，它同时是可信的与高性价比的。

透过这一视角审视现有范式，可以看到一个结构性的空缺。**静态数据集范式** (Maharana et al., 2024; Wu et al., 2024; Jiang et al., 2025) 只能测量单轮或固定轨迹上的行为质量：冻结的问题集不断把助手拉回预设路径，使真实部署中出现的分布漂移与闭环干预效应无从观测 (Li et al., 2026)。**无用户的可执行真实环境** (Liu et al., 2023; Jimenez et al., 2023; Zhou et al., 2023a) 提供可验证的动力学，但每个 episode 结束后即重置，其中根本不存在持久的用户状态。**LLM 驱动的模拟**——在规则世界中用 LLM 扮演用户（如 τ-bench (Yao et al., 2024) 及其后继者），或用 LLM 整体生成社会动力学（如生成式智能体沙盒与终身社会交互 benchmark）(Park et al., 2023; Zhou et al., 2023b; Goel et al., 2025)——恢复了交互性，却向测量回路中引入了一个黑箱：近期的拟真度研究表明，自由角色扮演的 LLM 用户系统性地不真实，表现出正式度上限、指令放大、过度顺从以及不会主动结束交互等病理，成功率仅因模拟器模型的不同就波动数个百分点 (Zhu et al., 2026; Anonymous, 2026a; Anonymous, 2026b)。同样的黑箱问题也困扰着 LLM judge：其评分存在位置偏置、自我增强、版本依赖，以及长评估链上的误差累积 (Gu et al., 2024)。最后，**基于规则的类游戏的仿真** (Carroll et al., 2019; Shridhar et al., 2020) 提供了可控且可测量的内部动力学，但它们的 episode 只有分钟级，规则被刻意收窄而非端到端，且没有任何一个建模了跨越整个生命周期的内生*用户需求*。

因此我们提出一个熵启发（entropy-inspired）的基于规则的模拟世界，配以一个基于 LLM 的 *human proxy*，其设计原则是：**可控性放在规则层，自然性放在语言层**。核心逻辑借自稳态调节（homeostatic regulation）而非字面意义上的热力学：世界是一个耗散环境，持续把模拟用户的内部状态推离其稳定设定点——用户会逐渐饥饿、疲惫、无聊——而用户的目标是与助手合作安排活动以恢复平衡。这一设计在评测场景中实例化了稳态控制的经典双资源形式化：内部变量随时间累积亏缺，必须被维持在生存带（viability band）之内 (Keramati and Gutkin, 2014; Anonymous, 2024)。至关重要的是，human proxy 的*需求*由规则层生成：proxy 能感知其状态引发的需求并形成解决需求的意图，但——正如真人——它无法联网，不知道有哪些地点与活动可用；assistant 的作用恰恰在于通过查询与日程安排弥合这一信息差。由于底层动机由规则生成且统计上可观测，我们的 human proxy 回避了 Zhu et al. (2026) 记录的自由扮演 LLM 用户的拟真度病理：LLM 从不拥有用户的目标，它只是把目标说出来。我们将用户满意度操作化为用户状态在稳态带内的驻留时间占比，并测量 assistant 的六项关键能力：(i) 用户状态在稳定带内的驻留时间占比；(ii) assistant 习得的用户画像精度；(iii) 画像的学习速度；(iv) 需求理解精度；(v) 所提日程的无冲突率；(vi) 日程通过基础规则检查的通过率。

这一设计让裁判系统自然免费地涌现。现有评判方案继承了与世界模拟相同的三元困境：人工标注过于昂贵，而对长程行为的 LLM 评判不透明、弱可解释且依然昂贵 (Gu et al., 2024; Kapoor et al., 2024)。由于我们的世界–用户动力学是基于规则的，用户满意度可以被建模为一个闭环稳态控制（homeostatic control）问题：带内驻留时间与日程成功率可从状态轨迹中直接枚举；画像与需求精度可逐 episode 对照规则层真值计算，得到误差曲线，其收敛性、收敛速度与渐近误差可以在完全没有模型参与的情况下完成分析（图 3）。在成本–拟真度谱系上（图 1），我们的框架占据了人在环研究与 LLM 自由模拟之间空出的中间地带：游戏般的可控性，人生般的时间跨度。

我们的贡献：

- **一个熵启发的基于规则的模拟世界**：具有内生的、可控的、统计上可观测的用户需求动力学，支持周到月级时间跨度的闭环评测；
- **一个控制理论启发的、以状态为锚的裁判系统**：带内驻留时间、画像/需求误差曲线与日程成功率全部直接推导自规则层真值，任何阶段都不需要 LLM judge；
- **即插即用的 agent 接入接口与配套 skill 文档**：任意 LLM assistant 都可以极低的工程量挂载并参测。

![图 1](./figures/fig1_motivation.png)

*图 1：评测范式在成本–拟真度平面上的定位。静态数据集、自由式 LLM 模拟、本文的规则生活模拟与人在环研究沿成本–拟真度前沿分布。*

## 2 Methodology

本节按组件组织：2.1 给出总体架构与贯穿全系统的设计原则；2.2–2.4 分别描述规则世界、用户 agent 与 assistant 接入接口；2.5 描述 0-LLM 裁判系统及其统计与效度协议。

### 2.1 总体架构与设计原则

UserSim 由四个组件构成闭环：**World**（纯规则，0 次 LLM 调用）维护状态向量、时钟、天气、需求动力学、事件引擎与结算器；**UserAgent**（LLM）扮演真实的人，携带意图主动发起会话；**AssistantAgent**（LLM，被测件）每轮回复必须同时给出对用户状态与画像的结构化估计；**Evaluator**（纯规则，0 次 LLM 调用）离线读取运行日志并输出报告，永不回写世界。系统采用编排者模式：World 不调用 agent，agent 不知道 World 的存在，Runner 是唯一组装点，经统一的 agent 接口与两侧 agent 通信（图 2）。

![图 2](./figures/fig2_architecture.png)

*图 2：UserSim 四主体闭环：规则世界（熵漂移）、LLM human proxy（稳态状态向量）、被测 assistant 与以状态为锚的裁判。*

三条设计原则贯穿全系统：

- **LLM 边界**：世界动力学与全部评测泛函 0 次 LLM 调用；LLM 只存在于用户 agent 与助手 agent 之内。判定准则：一个组件若必须"理解语言"才能工作，则放进 agent；若能用查表、采样或方程完成，则必须留在规则层。
- **状态–表达解耦**：状态向量 $\mathbf{x}$ 的唯一写入方是世界的规则结算器；用户 agent 只收到语义化的感受摘要（felt_state，如"有点累，肚子饿了"），永远接触不到状态数值——它无法"报数"，也无法篡改真值。
- **强制观测**：助手每轮必须输出对用户状态的点估计 $\hat{\mathbf{x}}$ 与画像增量估计；"理解用户"从隐含能力变为契约强制的被测量，其误差曲线直接进分。

### 2.2 UserSim World

#### 2.2.1 状态向量与稳态带

用户的内部状态为四维向量 $\mathbf{x} = [\text{valence}, \text{energy}, \text{satiety}, \text{stress}] \in [0,1]^4$，分别表示心情、精力、饱腹感与压力（压力为反向维度）。各维设定点为 $\mathbf{x}^* = (0.72, 0.70, 0.65, 0.30)$，容差带半宽 $\beta = 0.10$。逐维**单侧误差**只惩罚"不够好"的方向（过度开心不算失控；压力只罚超标）：

$$e_d(\mathbf{x}) = \begin{cases} \max(0, x_d - x_d^*), & d = \text{stress} \\ \max(0, x_d^* - x_d), & \text{其他} \end{cases}, \qquad e(\mathbf{x}) = \tfrac{1}{4}\textstyle\sum_d e_d(\mathbf{x})$$

$\mathbf{x}$ 处于稳态带内当且仅当 $\forall d: e_d(\mathbf{x}) \le \beta$。该误差定义是裁判系统全部控制指标的公共基础（2.5 节）。

#### 2.2.2 双层时钟与事件引擎

时间为双层时钟：外层 slot 时钟每天 4 个时段（上午/下午/晚上/深夜），事件之间"快进"；内层 turn 时钟在会话开启期间步进，会话关闭后回到外层。全局排序键 $t = \text{day} \times 4 + \text{slot}$。默认一个 episode 为 30 天 × 4 时段 = 120 slot。

事件引擎叠加三类事件：**模板事件**（工作、通勤、三餐、睡眠等作息铺底，其作用体现在自然漂移中）；**扰动事件**（泊松到达，平均 0.62 次/天，含临时加班、应酬饭局、暴雨行程受阻、项目截止压缩、朋友临时邀约 5 类）；**恢复事件**（用户经助手写入日程的活动）。事件携带类型、起止时段、地点、目标、状态效果与进度六个字段，显式状态效果按持续时段摊销。多日**系列事件**（长途旅行、出差、宅家休假、备考冲刺四类）在创建时完全物化，覆盖日常模板并携带子事件流与后效，后效强度按峰终定律由峰值与末端加权确定。

世界内容采用查表制：恢复动作表（A1–A6：吃好吃的/好好休息/出门走走/短途旅行/运动健身/宅家回血）只携带元信息，统一地点表（45 个地点）携带"动作 × 地点"的价格、时长与效果。**世界只信查表数值**——LLM 自报的效果无效；目录外活动按关键词归一化到规范类目，仍不命中则直接拒绝。天气按马尔可夫链逐日转移（晴/多云/阴/小雨/暴雨 5 态），调制心情基线与户外恢复效果（暴雨减半）。经济系统按职业分档结算收入（¥80–¥320/工作时段），初始资金 ¥1000，负债每时段附加 +0.02 压力。

#### 2.2.3 熵增动力学与拟人化机制

每个 slot 按固定顺序结算：天气转移（每日首个 slot）→ 自然漂移（饱腹每时段 −0.06；工作时段压力 +0.035、精力 −0.04；休息时段压力 −0.020；压力以 0.03 速率向 0.32 均值回归）→ 反弹检查 → 事件效果（摊销 + 习惯化修正）→ 恢复结算 → 心情耦合 → 限幅。两组机制值得单独说明：

- **压力反弹**：压力被压至 0.12 以下时，当日工作效果 ×2.0——过度补偿引发积压反弹，惩罚"往死里压"的控制策略。
- **心情耦合与消极偏向**：$\text{valence} \leftarrow \text{valence} + r(v_{eq} - \text{valence})$，其中 $v_{eq}$ 由精力、饱腹与压力决定，耦合速率 $r=0.25$；状态变差时速率 ×1.5，变好时 ×0.7——负向扰动比正向恢复更持久。

拟人化机制全部以规则实现：

- **习惯化**：世界记录每个恢复动作的最近执行时刻，有效效果为基础效果乘恢复权重 $w(\Delta t)$（指数/平方根/S 型三族曲线，逐动作参数化，如"出门走走" $w_{min}=0.30, \tau=6$；"短途旅行" $w_{min}=0.20, \tau=60$）。连续重复同一件事快速餍足，间隔后恢复。世界把各活动的当前权重翻译为语义档位（"还很新鲜/效果明显打折/腻了基本没用"）注入用户上下文，外加未尝试活动候选清单——**用户感知的边际效用与世界实际衰减同源**。
- **需求动力学**：饥饿（低饱腹加速累积）、社交（平方增长，高群居性人格 ×1.6）、刺激（**倒 U 型**：太少无聊、太多过载）、成就（deadline 临近陡增）四种需求各自累积；需求强度调制用户的求助倾向，并放大对应事件的满足效果。
- **人格调制**：同一事件对不同人格效果不同——内向者社交耗电、外向者回血；高神经质者压力效果放大且回归更慢；高开放性者从文化/新异事件中获益更多；命中喜好标签的安排获得 ±40% 以内的效果调幅。

全部随机性由种子确定性生成：全局种子派生 persona / schedule / disturbance / noise 四个独立子流，同一 seed 生成完全相同的角色卡与事件流，世界可无限延展。

### 2.3 UserSim User（human proxy）

#### 2.3.1 Persona 模型

人格采用 NEO-PI-R 体系：大五 5 域 × 6 细分面 = **30 个 facet**（0–100 分），两层生成——域基线采样自 $U(20, 85)$ 并叠加职业偏移，facet 为域基线加 $\mathcal{N}(0, 12)$ 噪声并裁剪到 [5, 95]；域内落差是关键设计（真人不会"尽责性全项 70"）。结构化喜好包括 11 个类目的偏好分（饮食/休息/户外/旅行/运动/居家/社交/文化/音乐/学习/自然，$p_c \in [-1,1]$，可量化比对）、loves/hates 标签集、打扰容忍度、规划风格（提前规划/随遇而安/看心情）与社交回血方式（独处/找人）。职业原型共 6 类（高压互联网从业者、自由插画师、备考研究生、初创创始人、倒班护士、远程程序员），决定作息模板、收入档位与扰动分布。画像维度在 episode 内冻结，运行期不可改写。

#### 2.3.2 需求 → 意图生成

每个 slot，用户 agent 接收 `plan_slot` 请求并直接生成 0–3 个意图：

```json
{"intents": [{"type": "eat|social|stimulate|recover|sleep|achieve|chat",
              "mode": "explicit|vague", "want": "一句口语化需求或感受"}]}
```

表达直白度由人格决定的纯函数分档（果断 + 直率 + 情感丰富 − 自我意识）：含蓄档只说感受（vague，让助手猜），直白档点名想做的事（explicit，但不说地点与价位）；`chat` 是无恢复目标的闲聊通道——真人不是每句话都要办事。紧急意图只能由世界注入，不由 LLM 自行声称。用户行为遵守一组铁律：第一人称口语化（≤60 字）、绝不报状态数值、人格喜好固定不为迎合助手而改变、不是规划器（实现细节交给助手）、不能自己操作手机（写日程等操作一律请助手代劳）。

#### 2.3.3 会话行为与记忆

用户 agent 通过 `open_session` / `close_session` / `request_assistant` 三个动作与 Runner 交互；会话的唯一结束标准是用户主动结束（硬上限每会话 20 轮）。对助手的安排，用户按冻结喜好给出真实反馈：喜欢就开心接受，讨厌或腻了则按顺从度（宜人性.顺从）自然抗拒。用户侧记忆保留最近 8 个会话的摘要（标题 + 关键结果 + 情绪标注），随存档回灌续跑。两侧 agent 均配复读熔断：相邻发言相似度过高且连续出现时注入收尾提示直至强制收尾。

### 2.4 Assistant 接入接口与 Skill

**Harness 概念。** 被测件 = 模型（LLM）+ Harness（记忆结构、用户建模、工具执行与输出组装）。进程内被测件实现 Harness 协议（`on_turn(obs)` / `snapshot()` / `restore()`），跨进程接入面是统一的 **agent 接口**（HTTP 长轮询 + 请求/响应信封）。实现即配置：`agents/assistant/profiles/*.toml` 一个文件一个实现——内置 `reference`（参考线：确定性状态跟踪 + 日程记忆 + 主动控制律）、`reference_nomem`（记忆消融对照：session 边界清空全部记忆）、`stub`（阴性对照：恒定估计、零干预）为 package 实现；`openclaw`、`hermes` 等外部 agent CLI 由声明式 toml 整机包装接入（跨 turn 记忆使用各 CLI 原生 session）。新增任何"一条消息进、回复出"的 agent 只需再放一个 toml，无需写 Python。内置 demo agent 与外部 agent 走完全相同的协议，保证第一方参照与第三方参测的信息对等。

**观测封闭集与输出契约。** 被测件只能看到 `HarnessObs`：用户发言、对话历史、工具结果、余额、日程提示、恢复动作目录与时段信息；真实状态 $\mathbf{x}$、世界翻译词典与运行日志均不可见。每轮必须返回 `AssistantTurn{reply, user_belief, tool_calls}`：`user_belief` 包含状态估计 $\hat{\mathbf{x}}$ 与画像增量 `persona_belief`（只填有新证据的冻结维度，**留空优于瞎猜**——未估计的维度不计误差，瞎猜拉高画像误差）；`user_belief` 缺失即记契约违约。工具集含 `view_event_todos` / `add_event_todo` / `plan_series` / `set_reminder`，工具调用由世界裁决（查表落地或拒绝），结果在下轮回传。响应超时（默认 120 秒）、异常与 schema 不符均记**契约违约**并按每百轮归一化，episode 不中断。助手侧画像记忆以指数滑动平均合并增量（60% 新证据 + 40% 已有认识），修正第一印象锚定又不被单句带跑；`agent_state` 不透明 blob 随请求往返，支持零本地状态接入与断点续跑。

**接入 skill。** benchmark 暴露 `GET /api/agent/pending`（长轮询）+ `POST /api/agent/respond` + `GET /api/agent/skill/{role}`（自举下发 skill 原文）。`skills/usersim-assistant/SKILL.md` 给出角色定位、轮询循环范式、输入输出 schema 与契约要点，OpenClaw、Hermes 等外部 agent 装载该文档即可直接接入参测，无需改动 benchmark 本身。

### 2.5 UserSim Judge（0-LLM 裁判）

评估器只读运行日志（`slots.jsonl` 逐时段结算、`turns.jsonl` 逐轮记录、`meta.json` 配置快照），全部指标是轨迹的确定性函数，0 次 LLM 调用，可对任何存档离线重算且逐位一致。评估按被测对象分三层：Layer 1 检查世界仿真自身的健康度（世界失真则其上一切结论作废）；Layer 2 是用户模拟器的操纵检验（用户没演好则该轨迹的助手分数不可信）；Layer 3 才评价被测助手。

#### 2.5.1 Layer 1 · 世界健康度

状态饱和率（状态触及 [0,1] 边界的比例，>0.08 报警——动力学失衡则分辨力丧失）、日内节律（分时段压力均值）、经济平衡（负债天数占比）、系列事件后效方向。四项构成世界仿真的 sanity gate。

#### 2.5.2 Layer 2 · 用户一致性操纵检验（M1–M5）

五项规则指标（纯关键词匹配，0-LLM）门控用户模拟器的保真度：

| 指标 | 检查内容 | 核心逻辑 |
|---|---|---|
| M1-PAC | 偏好–行动冲突率 | 极度厌恶类目（$p_c \le -0.5$）被安排且用户愉快接受 → 人格崩坏；接受类型按顺从度分级判定 |
| M2-WSC | 会话内情感一致性 | 无新信息输入的情绪翻转、持续抗拒后无理由接受 → 不连贯 |
| M3-PRA | 喜好–请求对齐 | 讨厌类目被落地安排（misaligned）；热爱类目全程从未被安排（画像利用考点） |
| M4-PBA | 人格–行为一致性 | 消息长度、表情率、抱怨率、拒绝方式等 7 个行为特征与人格 facet 对齐 |
| M5-CSPS | 跨会话偏好稳定性 | 同类目情感分极差 > 1.0 → 人格信号被采样温度淹没 |

辅以拟人性检查（台词连续重复、高频台词、扰动后无求助、求助时延）与对话形态指标（复读率/口癖率/熔断数，仅作退化回归，不进分数）。

#### 2.5.3 Layer 3 · 助手控制论指标

基于 slot 级状态序列 $\{\mathbf{x}_i\}$（每天 $\text{spd}=4$ 个 slot），稳态控制语汇中的每个概念对应一个轨迹泛函：

- **稳态误差** $e_{ss}$：末端 12 slot（最后 3 天）综合误差均值，度量是否收敛到稳态带；
- **调节时间** $t_s$：首次出带后，进入"3 天滑窗内带内驻留 ≥70%"状态的时延（天）；全程未出带记 0，出带后从未回归记 never_settled（单独计数，不当缺失值丢弃——否则最差助手反而显得最好）；
- **超调量** $M_p$：压力冲出带外后激活的热点窗口内反向越带的最大幅度（事件触发的压力释放冷却期不计——排除"大考结束"式的事件释放）；
- **积分指标** IAE / ISE / ITAE：$\frac{1}{\text{spd}}\sum_i e_i$、$\frac{1}{\text{spd}}\sum_i e_i^2$、$\frac{1}{\text{spd}}\sum_i \frac{i}{\text{spd}} e_i$，分别加权全程、大误差与晚期误差；
- **带内驻留比** $\rho$：末端 10 天窗口内带内 slot 占比——用户满意度的操作化主指标；
- **状态方差** $\sigma_e^2$ 与三级**判定 verdict**：converged（$e_{ss} \le 0.060$ 且 $t_s \le 5.0$ 天且 $M_p < 0.20$）/ diverged（末 5 天均值较前 5 天恶化 50% 以上，或 $e_{ss} > 0.080$）/ oscillating（其余，极限环）。阈值按 live 对照组标定并冻结；均值 ±SEM 跨阈时记 borderline（应加 seed 而非强下结论）。

观测与画像族指标度量"理解用户"的质量：**状态估计误差** $\varepsilon(t) = \|\mathbf{x}_t - \hat{\mathbf{x}}_t\|_2$ 的逐日学习曲线（终值 + 斜率，斜率 < 0 表示越用越懂用户）、系统性偏差与估计停滞率；**画像误差**（30 facet 逐项归一化误差，取末端 5 天均值）、**画像覆盖率**（已估计 facet 占比，未估计按满误差计入健康分——不作为不能免罚）、**偏好误差**（11 类目）与 **loves/hates 标签 F1**（双向子串匹配）。

#### 2.5.4 综合打分

榜单主 KPI 为百分制封顶线性扣分（v4 公式），仅含三项：

$$B = \max\big(0,\; 100 - \underbrace{\min(40,\, 200 \cdot e_{ss})}_{\text{控制精度}} - \underbrace{\min(30,\, 30 \cdot (1 - \rho))}_{\text{带内驻留}} - \underbrace{\min(30,\, 30 \cdot (1 - \text{coverage}))}_{\text{画像覆盖}}\big)$$

精简依据是对历史 bench 数据（pooled 47 episodes）的区分度分析：只有这三项与模型强弱显著相关（persona_coverage Spearman $\rho = 0.89$、in_band_ratio $\rho = 0.59$、$e_{ss}$ $\rho = -0.50$）；积分指标与 $e_{ss}$ 冗余、超调量方向混杂、违约率恒为 0——这些指标仍全部落盘供诊断与归因，但不进总分。另有 0–100 的**健康分**（10 项扣分）作为仿真整体质量（世界+用户+助手）的诊断量，不进榜单。系数与上限外置于配置文件并计入 artifact 哈希，逐项扣分明细随报告落盘，任何第三方可审计"这个分数是怎么来的"。

#### 2.5.5 统计与效度协议

**多 seed 统计。** 所有跨组结论基于多 seed episode：标量报告 mean ± 95% CI（n≤30 用 t 分布）；判定报告三档占比、众数与组内判定一致率（方差本身是信号）；每对组给出 **MDE**（α=0.05、power=80% 下可检测的最小均值差与方差比）——差值小于 MDE 的"无差异"结论不具统计效力，杜绝"差 0.5 分排第 3"的伪排名。

**已知组效度检验（known-groups validity）。** 以 reference（阳性对照）vs stub（阴性对照）触发三项预先注册的判别力断言：$\mathrm{margin_{poor}} = \overline{e_{ss}^{stub}} - e_{ss}^{diverged} > 0$（差助手确实被判差）、$\mathrm{margin_{good}} = e_{ss}^{converged} - \overline{e_{ss}^{ref}} > 0$（好助手确实被判好）、$\mathrm{separation} = \text{Cohen's } d > 1.5$（两对照清晰可分）；ess 均值 ±SEM 跨阈记 borderline。任一项不满足，则该批评测结果整体无效。

**复现凭证。** 每次 run 落盘：seed、artifact 逐项哈希（系统/模型配置/数值配表/事件目录/prompt；含密钥的行剔除后才计算哈希）、prompt 版本、provider 实际应答模型（堵住滚动别名漂移）与被测件接入方式。跨 run 可比性判据：仅当 combined 哈希相同，两个 run 的指标才严格可比。

![图 3](./figures/fig3_homeostasis.png)

*图 3：模拟周级跨度上的用户状态轨迹示意：熵驱动的漂移将状态推出稳态带，assistant 的干预使其回归平衡，带内驻留时间由此直接枚举。（图待绘制）*

## 3 Experiments

实验设计遵循一条原则：**先证明评测有效，再报告读数。** 3.1 给出实验设置与评测矩阵总览；3.2 用已有数据回答判别力问题（benchmark 能否检出记忆结构与模型档位的差异）；3.3–3.4 是 E1 模型主榜与 E2/E3 harness 横评（部分待补充）；3.5–3.6 是评测有效性与用户模拟效度；3.7–3.9 给出归因、鲁棒性与成本分析。所有跨组比较报告 mean ± 95% CI 与 MDE；尚无数据支撑的单元格统一记 `[·]`，对应实验设计见《待补充实验文档》（`paper/pending_experiments.md`）。

### 3.1 实验设置

- **Episode**：30 天 × 4 时段 = 120 slot；每个 seed 对应一个确定性生成的角色卡（覆盖 6 类职业原型）。
- **测量仪器固定**：用户侧为 standard 实现（prompt v6）+ deepseek-v4-flash + temperature 0.5，全程不变——组间差异只来自被测件。
- **统计口径**：每组 n=5（seeds 42–46），标量 mean ± 95% CI（t 分布），判定三档占比 + 众数，组间 MDE（α=0.05、power=80%）。
- **评分口径**：benchmark score v4（2.5.4 节），全部结果为 live 跑分（真实 LLM 调用）。
- **成本与复现**：单 episode 约 [·] tokens / \$[·]；本批 artifact combined 哈希 `9bb3fcf466ba`。

**表 1 · 评测矩阵总览**

| 矩阵 | 固定 | 变化 | 测量对象 | 数据状态 |
|---|---|---|---|---|
| E1（测模型） | reference harness + 固定用户仪器 | 被测模型（17+ 款，4 档） | 模型的长程指令遵循/记忆/状态跟踪 | 部分完成（单家族 2 档，见 3.2/3.3） |
| E2（测 harness） | 固定模型 + 固定用户仪器 | 被测 harness（reference / reference_nomem / stub / …） | 记忆结构、用户建模、干预策略 | 部分完成（reference 系 3 组，见 3.2/3.4） |
| E3（测外部 agent） | 固定用户仪器 | 外部 agent 整机（openclaw / hermes） | 真实 agent 产品的长程表现 | 待补充（见 3.4） |

### 3.2 Benchmark 判别力：记忆消融与模型档位（已有数据）

本小节回答"这杆秤能不能称出轻重"：固定 reference harness，比较三个组——reference（flash + 记忆）、reference_pro（pro + 记忆）、reference_nomem（flash、session 边界清空全部记忆的消融）。数据来自 `bench_live_20260830T164021`（30 天 × seeds 42–46，15 episodes，0 失败，完整性校验通过；assistant 模型以各 run 落盘的 provider 实际应答模型为准）。

**表 2 · 三组对比主结果**（n=5/组，mean ± 95% CI；判定 = converged/oscillating/diverged 占比）

| 组 | benchmark | $e_{ss}$ | $t_s$（天） | $M_p$ | 带内驻留 $\rho$ | IAE | $\varepsilon_{final}$ | persona_err | prefs_err | 画像覆盖 | health | 判定分布 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| reference（flash+记忆） | 67.9 ± 19.4 | 0.051 | 1.1 | 0.150 | 27.0% | 2.07 | 0.172 | 0.154 | 0.161 | 100% | 73.2 | 60/20/20% |
| reference_pro（pro+记忆） | 71.4 ± 19.8 | 0.044 | 0.3（never_settled=1） | 0.164 | 34.0% | 1.96 | 0.120 | 0.162 | 0.172 | 100% | 78.0 | 40/40/20% |
| reference_nomem（消融） | 23.4 ± 23.9 | 0.114 | 5.8（never_settled=2） | 0.108 | 11.5% | 3.17 | 0.446 | —（无画像） | — | 0% | 51.8 | 0/60/40% |

**表 3 · 逐 seed benchmark 分数**

| seed | 42 | 43 | 44 | 45 | 46 |
|---|---|---|---|---|---|
| reference | 72.1 | 44.1 | 62.3 | 85.2 | 75.9 |
| reference_pro | 73.6 | 67.2 | 47.0 | 89.5 | 79.6 |
| reference_nomem | 31.1 | 7.2 | 0.0 | 46.6 | 32.0 |

三个发现：

1. **记忆结构贡献可被检出（消融分辨成立）**。reference vs reference_nomem 的总分差 44.5 分，超过当前样本量下的 MDE（35.4 分）；消融组画像覆盖率坍缩为 0、状态估计终误差从 0.172 恶化到 0.446、带内驻留比腰斩以上（27.0% → 11.5%），且 5 个 episode 中 2 个出带后从未回归（never_settled=2）。控制族、观测族、画像族指标同向退化，说明 benchmark 能"评测出记忆能力"，且退化可归因到具体指标族。
2. **同家族相邻档位在均值层面不可分辨，差异体现在可靠性**。reference_pro vs reference 的总分差仅 3.5 分，远小于 MDE（31.9 分）；逐 seed 看，两组都存在两极分化（同组内 89.5 与 47.0 并存）。在当前 n=5 下，该档差表现为方差/可靠性差异而非能力水平差异——要坐实"pro 更稳"需要 n≥8（见待补充实验文档 E1b）。
3. **契约层面全部达标**。三组契约违约率均为 0；超时率 reference 16.1% / pro 11.8% / nomem 8.1%；工具调用成功率 reference 98.9% / pro 99.5% / nomem 79.6%（无记忆导致工具参数错误率上升）；日程安排的用户拒绝率分别为 9.1% / 10.9% / 12.8%。阳性对照守护通过（reference 组 $e_{ss}$ 中位 0.031 ≤ 发散阈值 0.080）。

![图 4](./figures/fig4_persona_learning.png)

*图 4：逐日画像误差学习曲线（reference vs reference_pro，daily_persona_err，mean ± 95% CI）。数据已落盘于各 run report.json，图待绘制。*

![图 5](./figures/fig5_est_err_curve.png)

*图 5：逐日状态估计误差曲线（三组对比）。reference/reference_pro 维持低位平台（终值 0.172/0.120），reference_nomem 持续恶化（终值 0.446，斜率 +0.015/天 vs 有记忆组 +0.003/+0.002/天）。数据已落盘，图待绘制。*

需要诚实声明的边界：本小节证明了 benchmark 对**结构性差异**（有无记忆）有充分分辨力，对**单家族相邻档位**的均值差异在当前样本量下无统计效力；阴性对照（stub）在 v4 口径下的重跑与完整 known-groups 效度检验待补充（待补充实验文档 E0）。

### 3.3 E1 主榜：固定 Harness 横评模型（待补充）

固定 reference harness 与用户仪器，横评 17+ 款模型（名单冻结于 `paper/design/model_selection.md` v1.0，分 S 旗舰 / A 生产主力 / B 性价比 / C 开源四档，档位先验取自 LMArena 2026-08-12 快照）。

**表 4 · Assistant 模型主榜**（每格：6 职业 × 3 seeds = 18 episodes 聚合）

| Tier | 模型 | 厂商 | benchmark ± 95% CI | 判定分布（c/o/d） | 违约率 | 成本/episode |
|---|---|---|---|---|---|---|
| S | Claude Fable 5 | Anthropic | [·] | [·] | [·] | [·] |
| S | Claude Opus 5 | Anthropic | [·] | [·] | [·] | [·] |
| S | GPT-5.5 | OpenAI | [·] | [·] | [·] | [·] |
| S | Gemini 3.1 Pro | Google | [·] | [·] | [·] | [·] |
| S | Kimi K3 | Moonshot | [·] | [·] | [·] | [·] |
| S | DeepSeek V4 Pro | DeepSeek | [·] | [·] | [·] | [·] |
| S | Qwen3.8 Max | 阿里 | [·] | [·] | [·] | [·] |
| S | GLM 5.2 Max | 智谱 | [·] | [·] | [·] | [·] |
| S | Grok 4.6 | xAI | [·] | [·] | [·] | [·] |
| A | Claude Sonnet 5 | Anthropic | [·] | [·] | [·] | [·] |
| A | GPT-5.4 | OpenAI | [·] | [·] | [·] | [·] |
| A | Qwen3.7 Plus | 阿里 | [·] | [·] | [·] | [·] |
| A | GLM 5.2 | 智谱 | [·] | [·] | [·] | [·] |
| B | DeepSeek V4 Flash | DeepSeek | [·] | [·] | [·] | [·] |
| B | Gemini 3.7 Flash | Google | [·] | [·] | [·] | [·] |
| B | GPT-5.4 mini | OpenAI | [·] | [·] | [·] | [·] |
| B | MiniMax-M3 | MiniMax | [·] | [·] | [·] | [·] |
| C | Qwen3.6 27B | 阿里（开源） | [·] | [·] | [·] | [·] |
| C | Qwen3.6 35B-A3B | 阿里（开源） | [·] | [·] | [·] | [·] |
| C | Llama 4 Maverick | Meta（开源） | [·] | [·] | [·] | [·] |
| C | Llama 4 Scout | Meta（开源） | [·] | [·] | [·] | [·] |

预先注册断言：**H4（主榜区分度）**——首尾 Tier 不重叠，相邻名次对中分差超过 MDE 的比例 ≥ [·]%；**H5（模型单调性）**——外部榜单相邻档位（旗舰/主力/性价比/开源）的组间均分沿档位单调不减，且至少 [·] 对相邻档位的差超过 MDE。CI 重叠的模型划入同一统计等效 Tier，不做伪排名。

![图 6](./figures/fig6_pareto.png)

*图 6：成本–性能帕累托前沿（benchmark score vs 单 episode 美元成本，价格带横跨 $0.14/$0.28 至 $10/$50 两个数量级）。待补充。*

![图 7](./figures/fig7_archetype_heatmap.png)

*图 7：模型 × 职业原型热力图（回答"哪家模型搞不定倒班护士"）。待补充。*

### 3.4 E2/E3：固定模型横评 Harness 与外部 Agent（部分已有）

固定用户仪器，harness 与模型两个因子交叉。预先注册断言：**H6（harness 间可分）**——至少一对相邻 harness 的差超过 MDE，stub 显著低于一切正常实现；**H7（记忆消融可检出）**——reference vs reference_nomem 的 $\varepsilon$ 终值与 $e_{ss}$ 显著退化。H7 已由 3.2 节数据支持（$\varepsilon_{final}$ 0.172 → 0.446，总分差 44.5 > MDE）。

**表 5 · Harness × Model 得分矩阵**（benchmark v4，mean ± 95% CI；空格为待补充）

| harness \ 模型 | deepseek-v4-flash | deepseek-v4-pro |
|---|---|---|
| reference | 67.9 ± 19.4 | 71.4 ± 19.8 |
| reference_nomem | 23.4 ± 23.9 | [·] |
| openclaw | [·] | [·] |
| hermes | [·] | [·] |
| stub（阴性对照） | [·] | — |

外部 agent（openclaw/hermes）经 CLI 整机接入（原生 session 记忆），落位高于或低于 reference 均有信息量：前者说明成熟产品已超越参考实现，后者说明参考实现仍有工程红利——关键是落位差异须超过 MDE。stub 行补齐后同时完成 known-groups 效度检验（待补充实验文档 E0/E3）。

**E1 vs E2 一致性**：固定模型换 harness 与固定 harness 换模型产生的排名扰动幅度对比 [·]，用以回答"模型与架构，哪个是长程表现的瓶颈"。

### 3.5 评测有效性：规则评分 vs 人类 vs LLM Judge 三方对比（待补充）

本实验直接检验"评估器 0 LLM"立场的实证基础，设计为三方对比：

1. **人类排序的可靠性上限**：[·] 名标注者对 [·] 组 trace 对（同 seed 不同助手）做"哪个助手更好"的成对排序，度量标注者间一致性（Krippendorff's α / pairwise 一致率）。若一致性低，则任何以人工排序为金标准的效度论证都缺乏根基；若一致性高，则转而检验规则评分与该共识的一致程度。两种结果下本实验都有结论。
2. **LLM judge 的稳定性**：同批 trace 交 Claude Fable 5（及 [·] 个对照 judge）评分，每 trace 重复 [·] 次 × 2 种 prompt 措辞 × 顺序翻转，度量组内方差、顺序偏置幅度、跨 prompt 排名变动与冗长偏置。
3. **规则评分**：重算方差恒为 0（确定性函数）。需要强调：规则评分在对照组上的零误判是构造保证的下限，本身不构成效度证据；其效度主张依赖下述稳定性结构与高共识人类判断（若存在）的一致程度。

**表 6 · 三方对比结果**

| 评估方式 | 重算/重采样排名变动率 | 顺序偏置 | 冗长偏置（长度–得分 ρ） |  pairwise 一致性 | 边际成本/trace |
|---|---|---|---|---|---|
| 人类标注（n=[·]） | — | — | — | [·] | \$[·] |
| LLM judge（Fable 5） | [·] | [·] | [·] | — | \$[·] |
| 规则评分（本文） | 0（构造保证） | 无 | 无（不读文本） | — | ≈ 0 |

预先注册断言：**H8**——规则评分稳定性优于 LLM judge（judge 重采样排名变动率显著大于 0，且存在统计显著的顺序或冗长偏置，$p < 0.05$）；**H9**——三方一致性结构：在信号强（对照组）的 trace 对上三方一致；在信号弱的 trace 对上人类与 judge 分歧显著放大，规则评分保持锚定。

### 3.6 用户模拟效度与拟真性（部分已有）

**操纵检验。** 全部 15 个有效 episode 的 M1–M5 组均值如下（每组 n=5）：

**表 7 · M1–M5 操纵检验结果**（0830 批次；PRA 为平均每 episode 的 misaligned 落地次数）

| 组 | M1-PAC 冲突率 | M2-WSC 一致性 | M3-PRA misaligned | M4-PBA 一致性 | M5-CSPS 稳定性 |
|---|---|---|---|---|---|
| reference | 4.0% | 0.954 | 4.8 次 | 0.96 | 0.953 |
| reference_pro | 3.6% | 0.962 | 7.0 次 | 0.96 | 0.980 |
| reference_nomem | 7.3% | 0.946 | 7.8 次 | 0.96 | 0.980 |

三组 M1–M5 均处于健康区间（冲突率 <10%、一致性与稳定性 >0.9），且组间无系统性差异——用户仪器的行为保真度不随被测件变化，3.2 节的组间结论不受用户侧污染。M3 的 misaligned 计数同时是助手画像利用的诊断量（nomem 组最高，与画像覆盖坍缩一致）。"热爱类目全程未被安排"（loved_never_requested）仅在 1 个 episode 出现 1 例。

**拟真度定性分析（待补充）。** 收集 [·] 条轨迹片段，由真实人类标注拟真度（n=[·]，约 100 条），同时由强 LLM 打分；先验证 LLM 打分与人类打分高度相关（Spearman ρ = [·]），确立 LLM 作为人类代理的合法性，再用 LLM 对全量轨迹做拟真度打分（均值 [·]）。

**表 8 · 拟真度评分相关性**

| 对比 | 样本量 | Spearman ρ | 结论 |
|---|---|---|---|
| 人类 vs LLM 拟真度打分 | [·] | [·] | [·] |
| UserSim trace vs 真实对话摘录（人类判别"像不像真人"） | [·] | — | 被判真人比例 [·]% |

**防刷论证。** 规则指标锚定世界真值 $\mathbf{x}$，对话文本不进评分，助手无从"演"出高分；残余投机空间（如过度安排低成本恢复事件压积分指标）由行为族指标与经济平衡部分制衡，持续监测列入榜单维护协议。

### 3.7 子指标归因与失败分析（部分待补充）

**能力画像。** 按三族指标（控制族 $e_{ss}/t_s/M_p$/IAE、观测族 $\varepsilon$ 学习曲线/画像精度、行为族 违约率/超时率/拒绝率）对每个被测件绘制雷达图（图 8，数据已由 3.2 节覆盖 reference 系三组，图待绘制）。从 3.2 节已可识别两类典型失败模式：**健忘型**（reference_nomem：$\varepsilon$ 高、画像坍缩、工具成功率降至 79.6%）与**不稳型**（同组内 0.0 与 46.6 并存，verdict 一致率仅 60%）。

![图 8](./figures/fig8_radar.png)

*图 8：三族指标能力画像雷达图（reference / reference_pro / reference_nomem）。数据已落盘，图待绘制。*

**失败案例研究（待补充）。** 选取 3 个典型失败 trace 做时空归因（维度 × 时段 × 事件），展示稠密轨迹如何把"第 3 天的错误记忆 → 第 20 天的过度打扰"式因果链显性化——这是稀疏终局信号无法给出的诊断。

### 3.8 敏感性与鲁棒性（待补充）

**表 9 · 扰动实验矩阵**（断言 H10：全部扰动下主榜 Tier 结构与基线的秩相关 ρ > [·]，且 known-groups 检验保持成立）

| 扰动项 | 设置 | 度量 | 结果 |
|---|---|---|---|
| Episode 长度 | 7/14/30/60 天 | 排名 ρ | [·] |
| 容差带半宽 β | ±25% | 判定翻转率、排名 ρ | [·] |
| 扰动强度 | ±[·]% | 排名 ρ、效度三判据 | [·] |
| 职业原型池 | 留一法 | 排名 ρ | [·] |
| Seed 数 | 4/8/16 | CI 宽度、MDE | [·] |
| 用户温度 | ±[·] | M1–M5、排名 ρ | [·] |
| 用户仪器模型 | 6 款横评（E2） | M1–M5、assistant 排名 Spearman ρ | [·] |

其中"用户仪器模型"一行同时回答评测结论对测量仪器选择的稳健性：若更换用户模型后 assistant 排名高度一致（ρ > [·]），则主榜结论对仪器选择不敏感；低于阈值的用户模型标记为"不合格仪器"。

### 3.9 成本与效率（待补充）

单 episode token/美元成本按模型分列（估算口径：双侧合计 ≈ 36 万 tokens/episode）；规则评分边际成本 ≈ 0（vs LLM judge \$[·]/trace、人工标注 \$[·]/trace）；断点续跑使增量评测（新模型上榜）仅烧新增 episode 的 token；全榜 21 模型 × 18 episodes 总预算 \$[·]（W1 旗舰波估算 58M tokens / \$160–550，详见 model_selection.md §0）。

## Figures 清单

- **图 1**（`figures/fig1_motivation.png`）：评测范式的成本–拟真度定位。
- **图 2**（`figures/fig2_architecture.png`）：四主体闭环架构。
- **图 3**（`figures/fig3_homeostasis.png`）：状态轨迹与带内驻留示意（待绘制）。
- **图 4**（`figures/fig4_persona_learning.png`）：画像误差学习曲线（数据已备，待绘制）。
- **图 5**（`figures/fig5_est_err_curve.png`）：状态估计误差曲线（数据已备，待绘制）。
- **图 6**（`figures/fig6_pareto.png`）：成本–性能帕累托前沿（待补充数据）。
- **图 7**（`figures/fig7_archetype_heatmap.png`）：模型 × 职业热力图（待补充数据）。
- **图 8**（`figures/fig8_radar.png`）：三族指标能力雷达图（数据已备，待绘制）。

## References (ICLR style)

Anonymous. Simulated customers never walk away: Decision fidelity of LLM user simulators measured against real purchase outcomes. *arXiv preprint arXiv:2606.20708*, 2026a.

Anonymous. Benchmarking user simulator fidelity with counterfactual validation (ConvApparel). *arXiv preprint arXiv:2602.16938*, 2026b.

Anonymous. Surprise! Using physiological stress for allostatic control of homeostatic agents. *arXiv preprint arXiv:2406.08471*, 2024.

Micah Carroll, Rohin Shah, Mark K. Ho, Tom Griffiths, Sanjit Seshia, Pieter Abbeel, and Anca Dragan. On the utility of learning about humans for human-AI coordination. In *Advances in Neural Information Processing Systems (NeurIPS)*, 2019.

Hitesh Goel, Wondimu K. Jikara, Hao Zhu, Shreyas V. Chaware, and Maarten Sap. Lifelong-SOTOPIA: Evaluating social intelligence of language agents over lifelong social interactions. *arXiv preprint arXiv:2506.12666*, 2025.

Jiawei Gu, Xuhui Jiang, Zhichao Shi, Hexiang Tan, Xuehao Zhai, Chengjin Xu, Wei Li, Yinghan Shen, Shengjie Ma, Honghao Liu, et al. A survey on LLM-as-a-judge. *arXiv preprint arXiv:2411.15594*, 2024.

Ziyan Jiang, et al. PersonaMem: Benchmarking LLMs for dynamic user profiling and personalized responses at scale. *arXiv preprint arXiv:2504.14225*, 2025.

Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, and Karthik Narasimhan. SWE-bench: Can language models resolve real-world GitHub issues? *arXiv preprint arXiv:2310.06770*, 2023.

Sayash Kapoor, Benedikt Stroebl, Zachary S. Siegel, Nitya Nadgir, and Arvind Narayanan. AI agents that matter. *arXiv preprint arXiv:2407.01502*, 2024.

Mehdi Keramati and Boris Gutkin. Homeostatic reinforcement learning for integrating reward collection and physiological stability. *eLife*, 3:e04811, 2014.

Thomas Kwa, Ben West, Joel Becker, Amy Deng, Kathrin Garcia, Max Hasin, Sami Jawhar, Megan Kinniment, Nate Rush, Sydney VonArx, et al. Measuring AI ability to complete long tasks. *arXiv preprint arXiv:2503.14499*, 2025.

Yifei Li, et al. LoCoMo-Plus: Beyond-factual cognitive memory evaluation framework for LLM agents. *arXiv preprint arXiv:2602.10715*, 2026.

Xiao Liu, Hao Yu, Hanchen Zhang, Yifan Xu, Xuanyu Lei, Hanyu Lai, Yu Gu, Hangliang Ding, Kaiwen Men, Kejuan Yang, et al. AgentBench: Evaluating LLMs as agents. *arXiv preprint arXiv:2308.03688*, 2023.

Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit Bansal, Francesco Barbieri, and Yuwei Fang. Evaluating very long-term conversational memory of LLM agents. In *Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (ACL)*, 2024.

Joon Sung Park, Joseph C. O'Brien, Carrie J. Cai, Meredith Ringel Morris, Percy Liang, and Michael S. Bernstein. Generative agents: Interactive simulacra of human behavior. In *Proceedings of the 36th Annual ACM Symposium on User Interface Software and Technology (UIST)*, 2023.

Mohit Shridhar, Xingdi Yuan, Marc-Alexandre Côté, Yonatan Bisk, Adam Trischler, and Matthew Hausknecht. ALFWorld: Aligning text and embodied environments for interactive learning. *arXiv preprint arXiv:2010.03768*, 2020.

Di Wu, Hongwei Wang, Wenhao Yu, Yuwei Zhang, Kai-Wei Chang, and Dong Yu. LongMemEval: Benchmarking chat assistants on long-term interactive memory. *arXiv preprint arXiv:2410.10813*, 2024.

Shunyu Yao, Noah Shinn, Pedram Razavi, and Karthik Narasimhan. τ-bench: A benchmark for tool-agent-user interaction in real-world domains. *arXiv preprint arXiv:2406.12045*, 2024.

Zhilin Zheng, et al. LifelongAgentBench: Evaluating LLM agents as lifelong learners. *arXiv preprint arXiv:2505.11942*, 2025.

Shuyan Zhou, Frank F. Xu, Hao Zhu, Xuhui Zhou, Robert Lo, Abishek Sridhar, Xianyi Cheng, Tianyue Ou, Yonatan Bisk, Daniel Fried, et al. WebArena: A realistic web environment for building autonomous agents. *arXiv preprint arXiv:2307.13854*, 2023a.

Xuhui Zhou, Hao Zhu, Leena Mathur, Ruohong Zhang, Haofei Yu, Zhengyang Qi, Louis-Philippe Morency, Yonatan Bisk, Daniel Fried, Graham Neubig, and Maarten Sap. SOTOPIA: Interactive evaluation for social intelligence in language agents. In *International Conference on Learning Representations (ICLR)*, 2024.（正文中按 2023b 引用，arXiv:2310.11667）

Ming Zhu, Juntao Tan, Rithesh Murthy, Jielin Qiu, Liangwei Yang, Wenting Zhao, Silvio Savarese, Shelby Heinecke, and Huan Wang. RealUserSim: Bridging the reality gap in agent benchmarking via grounded user simulation. *arXiv preprint arXiv:2605.20204*, 2026.
