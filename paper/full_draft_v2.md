# UserSim: Efficient Lifelong Assistant Agent Benchmark Via Rule-Based World Model and Control Theory Inspired Metrics.

keywords: LLM, long-term evaluation, user simulation, rule-based simulation, human proxy, entropy, control theory
针对长程、针对日常生活assistant，相对general范围

## Introduction

LLM 驱动的个人助手正在从"一次性问答工具"转变为"长期伴随式智能体"：它需要在数周乃至数月的跨度里记住用户、理解用户、在恰当的时机介入、在不该打扰时保持安静。然而主流评测体系仍停留在短 horizon 范式——静态问答集测知识，单 episode 任务 benchmark 工具调用与任务完成率——它们都无法回答产品决策者真正关心的问题：这个 agent 在长期的持续交互中如何准确且高效地评估用户满意度？

为了进行定量研究，我们将这个问题进一步分解为：衡量agent能否随着和用户的接触逐渐学会用户性格和喜好，并以最高效的方式为用户提供建议和帮助。衡量这样的长程任务下agent的表现需要有四个主体：世界、用户、被测assistant、裁判（打分器），我们将世界+用户看作一个整体动力学系统，随时间推进不断迭代状态，可以对现有的benchmark范式进行分析，最真实的反馈自然是来自于真实世界和人类用户，但是成本过高，因此我们需要一种能够对世界+人类用户动力学进行可信又同时性价比高的仿真模拟。

目前常用的数据集范式 (Maharana et al., 2024; Wu et al., 2024; Jiang et al., 2025) 只能衡量单轮或固定轨迹行为质量，因为固定的问题集会不断将助手拉回预设轨迹，无法观测到现实世界中可能会出现的漂移问题 (Li et al., 2026)；而大模型模拟世界动力学/世界模型τ-bench (Yao et al., 2024)，AgentBench、SWE-bench 等多步任务评测 (Park et al., 2023; Zhou et al., 2023b; Goel et al., 2025) 存在黑箱和大模型本身幻觉问题 (Zhu et al., 2026; Anonymous, 2026a; Anonymous, 2026b)，无法进行可靠的长程世界模拟 (Gu et al., 2024)；也有工作提出通过类游戏的范式对世界进行基于规则的仿真 (Liu et al., 2023; Jimenez et al., 2023; Zhou et al., 2023a)，此类仿真有更可控且可衡量的内部动力学，但是目前的规则仿真大部分没有long life，还有的系统规则过于简单没有用户需求 (Carroll et al., 2019; Shridhar et al., 2020)。

因此我们提出了受热力学定律启发的基于规则的模拟世界和基于大模型agent的human proxy模拟人类用户，核心逻辑是：世界作为一个封闭系统整体是熵增的，而模拟人类用户在该系统中也受到影响，随着时间推进，世界会不断将模拟人类用户的状态推离稳定值，例如逐渐饥饿、疲惫、无聊，而模拟人类用户的目标是和助手合作安排日程活动，降低自身熵维持自身状态稳定。模拟人类用户可以感知自身状态引发的需求，并产生解决需求的意图，但是和现实世界中一样，模拟人类用户也不能联网，不知道具体可以去哪些地方，而assistant的作用就在于帮助人类用户完成查询和活动安排，模拟人类用户在稳定区间停留时间越长我们认为代表用户满意度越高。综上所述，我们衡量assistant的6个关键能力：用户状态在稳定带内的驻留时间占比，对用户画像认知的精确度和学习速度，对用户需求的理解精确度，日程安排成功率（是否有时间冲突、能否通过基础规则检查等）。



基于此可以自然设计出裁判系统，现有裁判系统存在和世界仿真类似的问题，人类标注成本过高，大模型对长程任务的标注是个黑盒，可解释性弱且成本依然较高，而基于热力学定律的模拟世界-用户天然可以衡量状态波动曲线，建模为闭环稳态控制（homeostatic control）问题，稳定带内驻留时间和日程安排成功率可以自然完成统计，用户画像和需求精确度逐episode计算误差得到误差曲线，可以分析误差收敛性、收敛速度以及最终误差。

我们的贡献：

- Entropy inspired rule-based simulation world
- Control theory inspired state-based judge system
- 便捷的通用agent接入接口和配套skill文档

## Methodology

## Experiments

### 证明我们的benchmark的可用性

#### 世界模拟拟真度定性分析

大模型对轨迹拟真度打分，收集少量真实人类打分（100个），证明大模型打分和人类打分高度相关，大模型可以作为人类的代理进行轨迹真实性评估，然后用大模型进行全量轨迹拟真度打分。

#### 固定Assistant Harness下衡量出模型差异

以reference、reference no memory、openclaw、hermes四个harness，分别切换不同的assistant model，得到Model-Harness得分矩阵

分析不同model条件下，用户状态在稳定带内的驻留时间占比，对用户画像认知的精确度和学习速度，对用户需求的理解精确度，日程安排成功率（是否有时间冲突、能否通过基础规则检查等）

#### 固定Assistant Model

##### 不同Harnessss和不同记忆系统组合评测

使用DeepSeek Pro/Flash两个模型，分别进行以下实验

以reference harness为例，分别切换不同的memory system，得到Memory-Harness得分矩阵

分析不同harness条件下，用户状态在稳定带内的驻留时间占比，对用户画像认知的精确度和学习速度，对用户需求的理解精确度，日程安排成功率（是否有时间冲突、能否通过基础规则检查等）