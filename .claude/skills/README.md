# 项目级 Skills（vendor 来源记录）

本目录下的 skill 全部**从外部仓库拷贝（vendor）而来**，未做任何内容修改，与上游逐字节一致。
不走 plugin marketplace，因此随本仓库提交、离线可用、队友 clone 即得。

重新拉取上游： `bash scripts/update-skills.sh`

## 来源

### multica-ai/andrej-karpathy-skills

- 仓库： https://github.com/multica-ai/andrej-karpathy-skills
- 安装时 commit： `2c606141936f1eeef17fa3043a72095b4765b9c2`
- License： MIT
- 上游路径： `skills/<name>/`

| 目录 | 说明 |
| --- | --- |
| `karpathy-guidelines/` | 减少 LLM 编码常见错误的行为约束：先思考再编码、简单优先、外科手术式改动、目标驱动执行 |

上游那份是完整 plugin（含 `.claude-plugin/`），vendor 时只取了 `skills/` 下的 skill 目录，
清单文件与 `CLAUDE.md` / `CURSOR.md` / `.cursor/` / `EXAMPLES.md` 均未拷入。
内容与原作 `forrestchang/andrej-karpathy-skills` 逐字节相同。

### emilkowalski/skills

- 仓库： https://github.com/emilkowalski/skills
- 安装时 commit： `da80201b64de7d608a6dc5f723797ce6c65b692b`
- License： MIT（Copyright (c) 2026 Emil Kowalski）
- 上游路径： `skills/<name>/`
- 该仓库**没有** `.claude-plugin/` 清单，本就只能 vendor

| 目录 | 附带文件 | 自动触发 | 说明 |
| --- | --- | --- | --- |
| `apple-design/` | — | 是 | Apple 的界面设计与流体物理动效，translated 到 Web（CSS / Pointer Events / spring） |
| `emil-design-eng/` | — | 是 | UI 打磨、组件设计、动画决策的整体哲学 |
| `animation-vocabulary/` | — | 是 | 反查词表：把"弹一下那个效果"翻译成准确术语 |
| `find-animation-opportunities/` | — | 是 | 只读扫描：找出该加动效的地方并给精确参数 |
| `improve-animations/` | `AUDIT.md` `PLAN-TEMPLATE.md` | 是 | 审计现有动效并产出可交给其他 agent 执行的实施计划 |
| `pick-ui-library/` | — | 否（仅手动） | 按任务挑前端库（数字、OTP、图表、虚拟列表、拖拽、toast 等） |
| `prototype/` | `PICKER.md` | 否（仅手动） | 同一 UI 做多个差异化版本，放进可视 picker 里逐个试 |
| `review-animations/` | `STANDARDS.md` | 否（仅手动） | 按高标准评审动效代码，默认倾向挑问题 |

带附带文件的 3 个 skill 用**相对同级链接**互指（如 `[AUDIT.md](AUDIT.md)`），
因此必须整目录一起拷贝，不能只取 `SKILL.md`。

"仅手动"= frontmatter 带 `disable-model-invocation: true`，只能用 `/<skill-name>` 显式调用。

## 维护约定

- **不要就地编辑这些文件。** 任何本地修改都会被 `scripts/update-skills.sh` 覆盖，
  也会让上游 diff 失去意义。需要项目专属规约请写进 `AGENT.md`。
- 同步后请一并更新上面两处 commit SHA。
- `scripts/update-skills.sh` 里显式列出 9 个目录，上游新增的 skill 不会被自动拉进来；
  要新增请同时改脚本里的数组和本文件的表格。
