# UserSim 论文评测模型选型（2026-08，v1.0 冻结候选）

> 方法论与准入/退出机制见 `model_comparison.md`；本文档是根据 `paper/draft.md`
> 敲定的**最终名单 + 波次 + 预算口径**。draft 贡献 3 要求三类实验：
> ① assistant 模型横评（主榜）；② user 模型横评（测量仪器研究）；
> ③ 固定模型评测多种 assistant 智能体（harness 对比）。
>
> 名单版本依据：[DataLearner / LMArena 文本生成榜 2026-08-12 快照](
> https://www.datalearner.com/leaderboards/external/text-generation)
> 及同期厂商发布（DeepSeek V4 Pro 0813 GA、Kimi K3 开源权重、Qwen3.8-Max、
> Grok 4.6 等）。

## 0. 口径与预算基线

- 单 episode = 30 天 × 6 职业 archetype（`usersim/world/catalog.py: PROFESSIONS`）
  × N seeds；实测 token 量级 ≈ 12k tokens/天（`usersim/bench/suite.py:
  TOKENS_PER_DAY_ESTIMATE`），即单 episode ≈ 36 万 tokens（双侧合计）。
- W1 旗舰波：9 模型 × 6 职业 × 3 seeds = 162 episodes ≈ 58M tokens；
  Grok 4.6 单价低（$2/$6），总额仍控制在 $160–550 区间（draft §5 口径
  $150–500 的上沿，扩军 1 席的代价可接受）。
- 3 seeds 是 95% CI 的下限；CI 重叠归入同一 tier（T1/T2/T3），不做伪排名。
- 所有模型统一：temperature 按 `config/llm.toml` 默认（assistant 0.7 /
  user 0.5），推理档统一用各家**默认档**，钉具体快照版本并记录 system
  fingerprint / 快照日期，写入 meta 供复现（呼应 draft「预先注册协议」）。
  固定版本（pinned）示例：`deepseek-v4-pro-0813`、`deepseek-v4-flash-0731`（$0.14/$0.28
  每 M tokens，价格带下沿）。

## 1. Assistant 模型横评（主榜，17+ 模型 / 10–11 厂商 / 4 档）

协议：harness 固定 `reference`（benchmark 参考线），只换模型 —— 用
`agents/assistant/profiles/*.toml` 的 `[llm] provider` 覆盖实现。

### S 档 · 旗舰标杆层（W1，全量：6 职业 × 3 seeds）

| # | 模型 | 厂商 | 开源 | 第三方位次* | 选型理由 |
|---|------|------|------|------------|----------|
| 1 | Claude Fable 5 | Anthropic | 否 | Arena #1 (1506) | 能力上限锚点（$10/$50 价格带上沿） |
| 2 | Claude Opus 5 | Anthropic | 否 | Arena #7 (1493) | Opus 线现役旗舰（4.8 已降至 #18，换代） |
| 3 | GPT-5.5 | OpenAI | 否 | Arena #17/#21 | 海外闭源主力天花板，headline 对比锚 |
| 4 | Gemini 3.1 Pro | Google | 否 | Arena #14 (1486) | 1M 上下文 + 多模态阵营代表 |
| 5 | Kimi K3 | Moonshot | 权重开放 | Arena #12 (1489) | 2.8T MoE + 1M 上下文，2026-07 发布即进前 12；成本约旗舰一半，长程任务主场选手 |
| 6 | DeepSeek V4 Pro（0813） | DeepSeek | 权重开放 | 前排 | 1.6T MoE，0813 正式版 Agent 能力大涨；开源阵营天花板锚 |
| 7 | Qwen3.8 Max | 阿里 | 权重开放中 | Arena #8 (1491) | Arena 国产最高位（仅次于 Claude 系）；替换 Qwen3.7 Max |
| 8 | GLM 5.2 Max | 智谱 | 见 C 档 | 前排 | 工具幻觉率低，契约违约率列的有力竞争者 |
| 9 | Grok 4.6 | xAI | 否 | AA 指数 61（追平 GPT-5.6 Sol） | 2026-08-12 发布，主打长程 Agent 回合效率——与 UserSim「30 天不出错」定位直接对口；$2/$6 旗舰最低价；TTFT 慢、agentic coding 回退等传闻正好由本榜验证 |

\* 第三方位次（LMArena 2026-08-12 快照 / Artificial Analysis）仅作选型依据，不进论文结果；
Grok 4.6 部分数据尚属厂商自报，按准入规则标注。

候补（准入规则：公开 API 稳定可调后补测上榜）：Muse Spark 1.2（Meta，Arena #4，
xHigh 档，API 可用性待验证）、GPT-5.6 Sol（OpenAI，#19 xHigh 档）。
前代锚点（可选，用于展示代际进步）：Kimi K2.7、Qwen3.7 Max、Claude Opus 4.8、Grok 4.5。

### A 档 · 生产主力层（W2，全量：6 职业 × 3 seeds）

| # | 模型 | 厂商 | 选型理由 |
|---|------|------|----------|
| 10 | Claude Sonnet 5 | Anthropic | 真实部署量最大的档位，选型参考价值最高 |
| 11 | GPT-5.4 | OpenAI | 同上，OpenAI 生产主力（Arena #22 high 档） |
| 12 | Qwen3.7 Plus | 阿里 | 国产主力价位带 |
| 13 | GLM 5.2 | 智谱 | 主力档国产第二席（工具调用稳定性） |

### B 档 · 性价比层（W2/W3，全量同上）

| # | 模型 | 厂商 | 选型理由 |
|---|------|------|----------|
| 14 | DeepSeek V4 Flash（0731） | DeepSeek | $0.14/$0.28 价格带下沿，Pareto 成本锚；98% 缓存折扣 |
| 15 | Gemini 3.7 Flash | Google | Flash 线现役最强（Arena #9，超越多家旗舰），性价比之王候选 |
| 16 | GPT-5.4 mini | OpenAI | OpenAI 性价比档 |
| 17 | MiniMax-M3 / MiMo-V2.5-Pro | MiniMax / 小米 | 国产性价比新势力两个代表（M3 为开源权重；取其一上榜，另一个替补，视 W2 预算） |

### C 档 · 开源层（W3，托管 API，OpenAI 兼容端点；不自部署）

旗舰级开源已由 S 档直接覆盖（Kimi K3 / DeepSeek V4 Pro / Qwen3.8 Max 权重均开放），
C 档聚焦中小尺寸开源基线（经托管平台调用，无需自建 vLLM）：

| # | 模型 | 级别 | 选型理由 |
|---|------|------|----------|
| 18 | Qwen3.6 27B（dense） | 中档开源 | 中坚尺寸，私有化选型基线 |
| 19 | Qwen3.6 35B-A3B（MoE） | 小档开源 | 激活 3B 的效率档，检验「小模型能否维持稳态」 |
| 20 | Llama 4 Maverick（400B MoE / 17B 激活，1M 上下文） | 中档开源 | Meta 开源主力版本，补 Meta 一席 |
| 21 | Llama 4 Scout（109B MoE / 17B 激活，10M 上下文，约 $0.08/$0.30） | 小档开源 | Meta 效率版本，超长上下文卖点可验证 |
| — | Gemma 4 31B（可选） | 小档开源 | 美国阵营最强真开源（Apache 系），与国产第一梯队差 20+ 分——这个落差本身是论文素材 |
| — | Nemotron 3 Ultra（可选替补） | 大档开源 | NVIDIA 550B；仅当需要 NVIDIA 厂商覆盖时启用 |

注：Llama 4 Behemoth 尚未正式发布，不入选；GLM-5.2 开源权重（753B）
的能力面由 A 档 GLM 5.2 覆盖，不再单设自部署行。
开源层面不建议再扩：C 档每加一个模型 = 18 episodes 的托管成本，
4–6 个已足够覆盖中/小两级（旗舰级开源见 S 档）。

覆盖核对：11 家厂商（OpenAI / Anthropic / Google / xAI / Moonshot /
DeepSeek / 阿里 / 智谱 / MiniMax / 小米 / Meta [+NVIDIA 可选]）；价格带从
$0.14/$0.28（V4 Flash）到 $10/$50（Fable 5）跨两个数量级（Pareto 图核心产出）；
开源覆盖旗舰（S 档）/ 中 / 小（C 档）三级。

## 2. User 模型横评（测量仪器研究，6 模型）

协议：user impl 固定 `standard`，assistant 固定 `reference` harness +
DeepSeek V4 Flash（当前固定版本的仪器对面），只换 user 模型；抽样 2 职业
（高压互联网从业者、倒班护士）× 3 seeds，≈ 36 episodes ≈ 13M tokens。

| 模型 | 档位 | 作用 |
|------|------|------|
| DeepSeek V4 Flash（当前固定版本，`agents/user/config.toml`） | B | 现任仪器基线 |
| Qwen3.7 Plus | A | 国产中档仪器候选 |
| GPT-5.4 mini | B | 海外中档仪器候选 |
| Kimi K3-256k | A | 长程一致性候选（K3 经济变体，256K 窗口约半价的配额成本） |
| Claude Sonnet 5 | A | 海外高质量仪器参照 |
| Qwen3.6 27B | C（开源） | 开源仪器可行性 |

产出：① 各 user 模型的真人对齐度 + 长期喜好一致性；② 关键有效性证据 ——
**更换 user 模型后 assistant 排名的 Spearman 相关**，若高度一致则证明
benchmark 结论对仪器选择不敏感（draft §8「规则评测相关性」的配套论证）。

## 3. Harness 对比的固定模型（draft 贡献 3 后半句）

- user 模型：DeepSeek V4 Flash（已钉具体版本，跨天可比）。
- assistant 模型：DeepSeek V4 Flash（成本敏感 + 契约稳定；harness 对比
  需要反复跑，不能用旗舰烧钱）。
- 被评 harness：`reference` / `reference_nomem` / `openclaw` / `hermes` /
  `stub`（阴性对照，`suite.py: GUARD_POOR_GROUP`）。

## 4. 落地映射（开跑前的工程动作）

1. `config/llm.toml` 为每个入选模型加 `[providers.<name>]`（全部
   OpenAI 兼容；开源档走托管平台的兼容端点，不自部署），密钥用环境变量。
2. 主榜每模型一个 profile：复制 `reference.toml` 为
   `reference_<model>.toml`，内写 `[llm] provider = "<name>"` + 固定版本号
   `model = "<具体快照>"`。
3. 榜单元数据（家族/档位/价格带/上下文/开源/快照日期）在冻结配置时
   一次性登记，与 seeds、artifact_hashes 一起公开。
4. 价格以冻结日厂商官网为准重新核算 —— 本文只锁名单与口径，不锁价格。

## 5. 名单维护

- 新旗舰发布 1 周内补测上榜（draft §4）；补测走同一冻结协议，榜单 bump
  版本号 + changelog。本名单以 LMArena 文本榜月度快照为复查节奏
  （最近复查：2026-08-12 快照 + Grok 4.6 / V4 Pro 0813 发布）。
- 下线模型移入历史档案区，保持时间序列可比。
- 厂商自报数据未获第三方验证的（如 Grok 4.6 的 AA 指数），标「厂商自报」
  暂作标注，进主榜前以自家跑分为准。
