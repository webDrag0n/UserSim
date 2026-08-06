# 配置系统迁移说明

## 概述

已将配置系统从单一 Excel 文件迁移到 JSON 配置文件，支持前端实时编辑和热加载。

## 架构变更

### 之前：Excel 配置
- 单一文件：`config/balance.xlsx`
- 手动编辑 Excel，重启后生效
- 公式为文档字符串，不可执行

### 之后：JSON 配置
- 分散文件：`config/balance/*.json`（12个配置文件）
- 前端可视化编辑器，自动保存并热加载
- 公式为可执行 Python 表达式，实时预览

## 配置文件列表

| 文件名 | 说明 | 可重置 |
|--------|------|--------|
| `recovery_actions.json` | 恢复事件（运动、社交、娱乐） | ✓ |
| `disturbances.json` | 扰动事件（加班、生病） | ✓ |
| `meal_tiers.json` | 进餐档位 | ✓ |
| `sleep_tiers.json` | 睡眠档位 | ✓ |
| `custom_activities.json` | 自定义活动 | ✓ |
| `professions.json` | 职业收入 | ✓ |
| `economy.json` | 经济参数 | ✓ |
| `dynamics.json` | 动力学参数 | — |
| `habituation.json` | 习惯化曲线 | ✓ |
| `needs.json` | 需求参数（公式可编辑） | — |
| `persona_modulation.json` | 人格调节规则 | — |
| `template_events.json` | 模板事件 | — |

## 公式编辑功能

### 需求曲线（needs.json）

**驱动力曲线 `urge_curve`**：控制需求未满足时的驱动强度
- 语法：Python 数学表达式，变量为 `x`（需求缺失度，0-1）
- 函数：`x**n`, `sqrt(x)`, `exp(x)`, `log(x)`, `sin(x)`, `cos(x)`, `max()`, `min()`
- 示例：
  - `x**2`：二次增长（社交需求）
  - `min(1, (x/0.6)**1.5)`：饥饿急迫曲线
  - `1 - (2*x - 1)**2`：倒U型（刺激需求，过少无聊，过多过载）

**满足曲线 `satisfy_curve`**：控制事件对需求的满足程度
- 同样支持数学表达式
- 实时预览：编辑后立即显示曲线图

### 人格调节规则（persona_modulation.json）

**规则 `rule`**：控制人格特质如何影响行为偏好
- 语法：Python 条件表达式
- 可访问：
  - `persona.big5`：字典，键为 `openness`/`conscientiousness`/`extraversion`/`agreeableness`/`neuroticism`，值为 0-1
  - `persona.facets`：字典，键为 `sociable`/`dutiful`/`anxious`/`impulsive`/`assertive`/`optimistic`，值为 0-1
- 示例：
  ```python
  persona.big5['extraversion'] > 0.7 and persona.facets['sociable'] > 0.6
  ```

**规则验证**：
- 前端自动检测规则是否包含实际逻辑（访问 persona、条件判断）
- 纯文档字符串会显示 ⚠ 未实现警告

## API 接口

### 获取配置
```
GET /api/balance/config
返回：{ source: 'json' | 'default', files: {...} }
```

### 保存配置文件
```
POST /api/balance/save
Body: { file: string, content: object }
返回：{ ok: true, source: 'json', file: string }
```

### 重置配置
```
POST /api/balance/reset
Body: { file: string | null }  # null 重置全部
返回：{ ok: true, reset: string[], source: string }
```

### 公式评估（实时预览）
```
POST /api/balance/eval_formula
Body: { formula: string, var_name: string, points: number }
返回：{ ok: boolean, points?: {x, y}[], error?: string }
```

## 前端编辑器

### 位置
- URL：`/balance`
- 组件：`web/src/views/Balance.tsx`

### 功能
1. **分页编辑**：顶部 tab 切换配置文件
2. **内联编辑**：点击单元格直接编辑
3. **自动保存**：2秒无修改后自动保存（可关闭）
4. **实时预览**：
   - 习惯化曲线：w(Δt) 图形
   - 需求公式：u(x) 和 s(x) 曲线，显示值域
5. **重置功能**：恢复到代码默认值
6. **热加载**：保存后新 run 立即使用新配置

### 验证
- 数值字段自动类型检查
- 公式字段实时语法验证
- 规则字段逻辑完整性检查

## 安全措施

### 公式沙箱
- 白名单模式：只允许数学函数和运算符
- 禁止：`import`, `eval`, `exec`, `__`, 文件操作
- AST 静态分析：拒绝不安全节点

### 示例被拒绝的输入
```python
import os; os.system('ls')  # ✗ 拒绝
__import__('os')            # ✗ 拒绝
open('/etc/passwd')         # ✗ 拒绝
```

## 迁移脚本

迁移工具：`usersim/world/balance.py::migrate_excel_to_json()`
- 自动将 Excel 转换为 12 个 JSON 文件
- 保留所有数值、公式和文档
- 运行一次后可删除 Excel 文件

## 使用示例

### 修改饥饿曲线
1. 前端进入 `/balance`
2. 切换到「需求参数」tab
3. 找到「饥饿」→「驱动力曲线 u(x)」
4. 修改公式为 `x**3`（更陡峭的曲线）
5. 观察实时预览变化
6. 保存后新 run 立即应用

### 添加人格规则
1. 切换到「人格调节」tab
2. 找到需要修改的规则
3. 编辑为：`persona.big5['conscientiousness'] > 0.8`
4. 保存后高尽责性用户行为会受影响

## 测试

```bash
# 测试公式解析器
python -c "from usersim.world.anthro import parse_formula; print(parse_formula('x**2', 'x')(0.5))"

# 测试 API
python -m pytest tests/test_server.py -v -k balance

# 启动服务器验证前端
python -m usersim.server
```

## 注意事项

1. **向后兼容**：如果 JSON 文件不存在，自动回退到代码默认值
2. **配置热加载**：只对新启动的 run 生效，运行中的 run 使用启动时配置
3. **公式性能**：每次计算都会执行 Python 表达式，已优化缓存
4. **规则限制**：persona_modulation 规则暂未完全集成到决策流程（设计中）
