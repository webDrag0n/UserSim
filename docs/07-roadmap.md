# 07 · 路线图（Roadmap）

> ⚠️ 注：replay 模式已于 R4 下线（已知组效度检验 known-groups validity 迁移至 live 对照组 reference vs stub），文中 replay/脚本三档内容为历史记录。

状态: 草稿

> 原则：每个里程碑端到端可用，验收标准可机器检查。

## M0 · 骨架与契约（0.5 周）

- [x] 两份配置文件 + AGENT.md + docs 初稿（本轮）
- [x] `contracts/` 全部 pydantic 模型 + golden JSON 测试
- [x] 配置加载器（TOML + 环境变量覆盖 + 校验与友好报错）
- **验收**：`pytest tests/contracts` 全绿；缺密钥时错误信息指明环境变量名 ✅

## M1 · 世界模拟器（1 周）

- [x] clock / persona / events / dynamics / settlement / streams
- [x] 规则回放模式（无 LLM 的三档脚本用户+脚本助手）
- [x] 同 seed 确定性测试、单调性与边界测试
- **验收**：规则回放 30 天，good/mid/poor 三档分别产出 收敛/振荡/发散 轨迹 ✅（集成测试锁定）

## M2 · 两个 Agent 与 Runner（1.5 周）

- [x] llm 客户端（OpenAI 兼容、重试、JSON 模式、密钥环境变量覆盖）
- [x] user_agent（prompt v1 模板 + felt_state 翻译器对接）
- [x] 参考 Harness（naive memory + user_belief + 工具执行）
- [x] Runner 编排 + turns.jsonl/slots.jsonl 落盘 + CLI `run`（replay/live 双模式）
- **验收**：`run --mode live --days 7` 端到端跑通 ✅；日志 schema 校验通过 ✅（断点重放待补）

## M3 · 评估器（1 周）

- [x] 指标库 + 三级判定
- [x] report.json + CLI `eval`（report.html 由 web 报告视图承担）
- [x] 合成轨迹对拍（收敛/振荡/发散必中）
- **验收**：对 M1 三档规则回放轨迹判定全对 ✅；对 M2 真实运行产出报告 ✅

## M4 · 服务与前端（2 周）

- [x] FastAPI（REST + WebSocket；pause/resume 待补）
- [x] web 三视图（控制台 / 实时 / 报告；事件时间线与配置页合并简化）
- [x] 生产模式：后端托管 `web/dist`
- **验收**：浏览器启动 run → 实时观看对话与状态 → 报告页可见全部指标 ✅；`npm run build` 产物由后端直接服务 ✅

## 里程碑之后（候选方向）

- 多 persona 并行 episode（进程池 + seed 递增）与跨 run 排行榜
- 扰动注入器：在指定日注入"黑天鹅"事件做压力测试
- 评测矩阵自动化：E1/E2 批量跑 + 显著性检验
- 轨迹导出为公开数据集格式

## 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 不遵守结构化输出 | AssistantTurn 校验失败率高 | schema 重试 + 违约计入指标；优先选支持 structured output 的 provider |
| 用户 Agent 表演同质化 | 轨迹多样性不足 | persona 池扩容 + 温度分层 + felt_state 分档词典随机化 |
| 长程运行成本 | 30 天 episode token 消耗大 | 规则回放先调参；报告离线重算；`log_prompts=false` |
| 指标对对话质量无感 | "会说漂亮话但估计差"的助手被低估 | 指标全部锚定结构化信号正是设计意图；文档中明确声明该立场 |
