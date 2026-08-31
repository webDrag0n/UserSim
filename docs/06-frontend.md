# 06 · 前端与后端服务（server + web）

状态: 草稿

## 1. 定位

前端是 benchmark 的**观察窗与控制台**：启动/监控运行、实时观看事件生成与对话处理、浏览结算报告。设计语言沿用已验证的 `usersim-demo`（深色、等宽数字、控制论仪表盘）。

## 2. 技术栈

- `server/`：FastAPI + WebSocket（uvicorn），生产模式托管 `web/dist`；
- `web/`：React + TypeScript + Vite + Tailwind + Recharts；dev 模式代理到 `[server].port`。

## 3. 页面结构（五个视图）

| 路由 | 视图 | 内容 |
|---|---|---|
| `/` | 总览 Dashboard | run 列表、当前 run 状态卡、最新 verdict 徽章、快速进入 |
| `/run/:id/live` | 实时运行 | 三栏：事件轨道（播放中游标推进）/ 对话流（WebSocket 逐 turn 到达）/ 状态面板（x 与 x̂ 实时对照） |
| `/run/:id/events` | 事件时间线 | 全 episode 事件轨道 + 事件卡片 + 因果链箭头 |
| `/run/:id/report` | 结算报告 | 轨迹图（四维切换 + 扰动标注 + 设定点容差带）、指标卡、学习曲线、行为指标 |
| `/settings` | 配置 | 两个配置文件的只读展示与校验状态（密钥脱敏显示 `sk-****`） |

### 关键交互

- 实时运行页：WebSocket 推送 `turn` / `slot_settlement` 事件，前端按 `t_logical` 排序渲染；支持暂停世界的推进（Runner 支持 pause/resume）；
- 报告页：四维切换 tabs、滑窗选择器（窗口指标序列）、三档 verdict 对比（若有多 run）；
- 事件卡：点击显示六字段 + Δx 条形 + 关联 session。

## 4. 后端 API 草案

```
POST   /api/runs                 启动 run {days, episodes, assistant_quality?}
GET    /api/runs                 run 列表（含 verdict 摘要）
GET    /api/runs/{id}            run 元信息 + 进度
POST   /api/runs/{id}/pause      暂停 / resume / stop
WS     /ws/runs/{id}             实时事件流：turn / slot / settlement
GET    /api/runs/{id}/report     report.json（HTML 报告内嵌数据）
GET    /api/config/validation    两个配置文件的加载与校验状态（脱敏）
```

## 5. 前端数据流

- 实时：`WS /ws/runs/{id}` → reducer 追加 → 三个面板分别订阅；
- 历史：REST 拉取 `turns.jsonl` 分页 + `slots.jsonl`（轻量，全量）；
- 图表数据在前端聚合（每日估计误差、窗口指标），与服务端 `report.json` 对拍一致。

## 6. 与非技术读者的接口

- 每个指标卡带 `?` 悬浮解释（人话版："调节时间 = 出事后几天能缓过来"）；
- 报告页顶部一句话结论："该助手让用户在 30 天内保持了内心平和（收敛）"。

## 7. 实现备注

- 后端 `server/app.py`：REST（runs 启动/列表/详情/turns/slots/report/events/config 校验）+ WebSocket `/ws/runs/{id}`（先补发积压再实时推送）+ 静态托管 `web/dist`（SPA 回退）。
- 前端 `web/`（React+Vite+Tailwind+Recharts）实现为三视图：控制台（启动运行 + run 列表 + verdict 徽章）、实时视图（对话流 + x vs x̂ 状态面板 + 时段结算流水）、结算报告（四维轨迹图 + 8 指标卡 + 学习曲线）。
- 事件时间线视图暂合并进实时视图的结算流水；设置页以 `/api/config/validation` 提供（密钥脱敏）。
- 生产模式：`python -m usersim serve` 直接托管 `web/dist`（端口 8610）；开发模式：`cd web && npm run dev`（7100，代理到后端）。
