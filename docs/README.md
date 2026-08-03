# UserSim 实现方案文档地图

> 规约：先设计后编码。每篇文档头部标注状态；实现完成后回填"实现备注"。

| # | 文档 | 内容 | 状态 |
|---|------|------|------|
| 00 | [architecture](00-architecture.md) | 总体架构、四组件解耦、依赖规则、技术选型 | 已实现 |
| 01 | [world](01-world.md) | 世界模拟器：双层时钟、事件引擎、状态动力学、结算器、无限生成 | 已实现 |
| 02 | [user-agent](02-user-agent.md) | 用户模拟 Agent：人格注入、状态→表达、求助决策、工具集 | 已实现 |
| 03 | [assistant-agent](03-assistant-agent.md) | 助手 Agent / Harness 契约、user_belief 输出、记忆抽象、接入规范 | 已实现 |
| 04 | [evaluator](04-evaluator.md) | 评估器：控制论指标、滑窗、判定规则、报告产物 | 已实现（report.json；HTML 报告由 web 前端承担） |
| 05 | [contracts](05-contracts.md) | 跨组件数据契约（消息 schema 全集） | 已实现 |
| 06 | [frontend](06-frontend.md) | 前端页面结构、后端 API / WebSocket、可视化设计 | 已实现（三视图：控制台/实时/报告） |
| 07 | [roadmap](07-roadmap.md) | 里程碑 M0–M4 与验收标准 | M0–M4 已完成 |
| 08 | [event-catalog](08-event-catalog.md) | 事件配表（动作×地点×时长）与经济系统、Excel 导出 | 已实现 |
| 09 | [series-events](09-series-events.md) | 长时间系列事件（旅行/出差/休假/备考）：行程单物化、日程覆盖、后效 | 已实现 |

## 撰写计划

- **第一轮（本轮）**：两份配置 + AGENT.md + 本目录全部方案草稿。
- 第二轮：contracts + world 实现，回填 01/05 实现备注。
- 第三轮：两个 Agent + 端到端冒烟，回填 02/03。
- 第四轮：evaluator + 报告，回填 04。
- 第五轮：server + web 前端联调，回填 06。
