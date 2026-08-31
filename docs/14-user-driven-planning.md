# 14 · 用户主动规划系统（User-Driven Planning）

> ⚠️ 注：replay 模式已于 R4 下线（量程守护迁移至 live 锚点对 reference vs stub），文中 replay/脚本三档内容为历史记录。

状态: 设计中

> **历史备注**：本文是"用户主动规划"特性的早期设计稿（其中的规则版 `UserPlanner`
> 曾落地，现已在 prompt v3 中**废除**——意图改由用户侧 LLM 生成，数值不进 prompt，
> 见 docs/02-user-agent.md"LLM 意图规划"）。文中规划器代码示例仅作历史参考。

## 0. 当前系统与目标设计的差异

### 目标设计（理想流程）

每个时间段执行周期：
1. **天气系统**：确定天气，天气转换有概率关系（晴天→多云概率大于晴天→暴雨）
2. **环境持续改变生理状态**：熵增（持续饥饿、疲劳、无聊），心理状态周期性起落（生物钟叠加）
3. **根据生理状态+生物钟计算需求**
4. **用户主动规划事件**：用户 agent 结合所有需求状态进行多目标优化，从"主动事件库"中根据"预期效果"通过规则匹配创建多个事件（不同用户有不同的主动事件库）
5. **逐个进入事件，开启对话 session**：用户 agent 结合意图、当前状态、过去经历与助手对话，没有固定结束标准，可以任意长度对话，唯一结束标准是用户主动调用"结束对话"
6. **推进时间**：所有事件结束后进入下一时段

### 当前实现的问题

| 目标设计 | 当前实现 | 差异 |
|---|---|---|
| 天气系统 | **完全缺失** | 无天气状态、无马尔可夫转移矩阵 |
| 熵增 + 生物钟 | **部分实现** | 熵增已实现（饥饿/疲劳/无聊），生物钟叠加不完善（只有饭点，无昼夜节律） |
| 需求计算 | **已实现** | 4 个需求 + 驱动力曲线 + 满足曲线 |
| 用户主动规划 | **完全缺失** | 用户是**被动响应**，助手创建事件；无"主动事件库"；无用户侧规划器 |
| 意图驱动 session | **设计偏差** | 当前是世界驱动（`assist_prompt`），非用户意图驱动；session 与事件无一一对应 |
| 任意长度对话 | **部分实现** | 用户可主动结束，但有 `max_turns_per_session=20` 强制截断 |
| 过去经历 | **完全缺失** | 用户无跨 session 记忆 |

**核心架构问题**：
- **触发方向反了**：目标是"用户根据需求主动规划 → 进入事件 → 开 session"，当前是"世界概率性生成 `assist_prompt` → 用户被动响应"
- **能力倒置**：目标是"用户有主动事件库、自己规划"，当前是"助手有候选清单、助手创建事件"

## 1. 实现规划总览

### 阶段 1：天气系统（1-2 天，独立模块）

**World 层**：
- 新建 `world/weather.py`：天气枚举 + 马尔可夫转移矩阵
- `World.__init__` 初始化天气流，`step_slot` 开头转移天气
- `EventContext` 增加 `weather` 字段

**前端**：
- 天气图标显示（时间轴顶部）
- 天气转换动画（云飘过、雨滴等）

### 阶段 2：生物钟叠加（1 天，dynamics 改进）

**World 层**：
- `dynamics.settle_slot` 增加昼夜节律项（valence/energy 的周期性起伏）
- `Needs.update` 接收 slot，饭点前饥饿陡增、晚间社交加速

**前端**：
- 生物钟可视化（时段背景色渐变：清晨亮 → 深夜暗）

### 阶段 3：用户主动规划（5-7 天，**核心重构**）

#### 3.1 个性化事件库

**World 层**（`world/persona.py`）：
```python
def generate_persona(...):
    # 现有逻辑...
    
    # 新增：按 archetype/prefs 从全局 catalog 抽取个性化事件库
    event_library = _build_event_library(archetype, prefs, facets)
    persona.event_library = event_library  # List[EventTemplate]
```

**事件库差异化规则**：
- 内向者（外向性.群居性 < 35）：移除"朋友小聚"，增加"独处"类事件权重
- 高开放性（开放性.尝新 > 70）：增加"文化看展""短途旅行"权重
- 备考型角色：增加"学习充电"类，减少娱乐类
- 低收入角色：只保留低价/免费档事件

#### 3.2 用户规划器（规则版）

**新建 `agents/user/planner.py`**：
```python
class UserPlanner:
    """用户侧事件规划器（规则版）：多目标优化选择意图事件。"""
    
    def plan_slot(self, needs: Needs, state: StateVec, slot: int, 
                  event_library: List[EventTemplate], money: float) -> List[Intent]:
        """返回本 slot 的意图事件列表（0~N 个）。"""
        urges = needs.urges()
        
        # 生物钟门控：睡眠时段不规划，饭点增加进餐意图
        if slot == 3:  # 深夜，只想睡觉
            return [Intent(type="sleep", priority=1.0)]
        
        intents = []
        
        # 饥饿驱动
        if urges['hunger'] > 0.6 or (slot == 1 and urges['hunger'] > 0.3):
            candidates = [e for e in event_library if '吃' in e.name]
            best = self._match_effect(candidates, {'satiety': urges['hunger']}, money)
            if best:
                intents.append(Intent(type="eat", event=best, priority=urges['hunger']))
        
        # 社交驱动
        if urges['social'] > 0.5:
            candidates = [e for e in event_library if any(k in e.name for k in SOCIAL_EVENTS)]
            best = self._match_effect(candidates, {'valence': 0.3, 'energy': -0.1}, money)
            if best:
                intents.append(Intent(type="social", event=best, priority=urges['social']))
        
        # 刺激驱动（倒 U：太低或太高都有意图）
        stim_urge = needs.n['stimulation']
        if stim_urge < 0.3:  # 太无聊
            candidates = [e for e in event_library if any(k in e.name for k in STIM_EVENTS)]
            best = self._match_effect(candidates, {'valence': 0.2}, money)
            if best:
                intents.append(Intent(type="stimulate", event=best, priority=1.0 - stim_urge))
        
        # 压力驱动（恢复）
        if state.stress > 0.6:
            candidates = [e for e in event_library if '休息' in e.name or '放松' in e.name]
            best = self._match_effect(candidates, {'stress': -state.stress * 0.5}, money)
            if best:
                intents.append(Intent(type="recover", event=best, priority=state.stress))
        
        # 按优先级排序，取前 N 个（防止一个 slot 塞太多）
        intents.sort(key=lambda i: i.priority, reverse=True)
        return intents[:3]
    
    def _match_effect(self, candidates, target_effect, money):
        """按预期效果匹配最佳事件（买得起 + 效果覆盖度最高）。"""
        affordable = [e for e in candidates if e.cost <= money]
        if not affordable:
            return None
        
        def score(event):
            effect_match = sum(
                abs(event.effect.get(k, 0)) * v 
                for k, v in target_effect.items()
            )
            return effect_match - event.cost * 0.001  # 轻微偏好便宜的
        
        return max(affordable, key=score)
```

#### 3.3 Runner 主循环重构

**当前流程**（`runner.py:318-445`）：
```python
while not world.done:
    ctx = world.current_context()  # 世界驱动
    if ctx.assist_prompt or assistant.should_intervene():  # 被动响应
        # 单个 session
        pass
    world.step_slot()
```

**新流程**：
```python
while not world.done:
    ctx = world.current_context()  # 保留天气、active_events
    
    # ---- 用户主动规划 ----
    intents = user_planner.plan_slot(
        world.needs, world.x, world.slot, 
        world.persona.event_library, world.money
    )
    
    # ---- 世界补充触发（扰动/高压仍可触发额外 intent）----
    if ctx.assist_prompt and '扰动' in ctx.assist_prompt:
        intents.insert(0, Intent(type="emergency", priority=1.0))
    
    # ---- 逐个意图开 session ----
    for intent in intents:
        sess_counter += 1
        sid = f"S{sess_counter:04d}"
        
        # 用户 agent 带着意图进入 session
        user_context = UserContext(
            persona=world.persona,
            felt_state=world.felt_state(),
            active_events=ctx.active_events,
            schedule_view=ctx.schedule_view,
            intent=intent,  # 新增
            past_sessions=user_memory.recent_summary(),  # 新增
        )
        
        # session 内多轮对话（直到用户主动结束）
        turn_count = 0
        while turn_count < 60:  # 安全熔断
            user_out = user_agent.speak(user_context, history)
            emit("user", user_out['say'], ...)
            
            if user_out['end_session']:
                break
            
            assistant_out = assistant.on_turn(obs)
            emit("assistant", assistant_out.reply, ...)
            
            # 助手工具调用（创建事件）
            for tc in assistant_out.tool_calls:
                result = world.execute_tool(tc)
                tool_results.append(result)
            
            history.append(...)
            turn_count += 1
            
            # 软上限提示
            if turn_count >= 15:
                user_context.hint = "你们聊得有点久了，考虑收尾？"
        
        # session 结算
        user_memory.add_session_summary(sid, intent.type, turn_count)
    
    world.step_slot()
```

#### 3.4 用户记忆系统

**新建 `agents/user/memory.py`**：
```python
class UserMemory:
    """用户跨 session 记忆：滚动保留最近 N 个 session 的摘要。"""
    
    def __init__(self, capacity=10):
        self.sessions = deque(maxlen=capacity)
    
    def add_session_summary(self, session_id, intent_type, turn_count):
        """session 结束时记录一句话摘要。"""
        summary = f"刚和助手聊过{intent_type}，聊了 {turn_count} 轮"
        self.sessions.append({
            'sid': session_id,
            'intent': intent_type,
            'summary': summary,
        })
    
    def recent_summary(self) -> str:
        """格式化为 prompt 注入的文本。"""
        if not self.sessions:
            return "（这是你第一次和助手对话）"
        lines = [s['summary'] for s in list(self.sessions)[-5:]]
        return "；".join(lines)
```

### 阶段 4：session 结束语义改进（1 天）

**Runner 层**：
- `max_turns_per_session` 改为软上限：接近时在 `user_context.hint` 注入"聊得有点久了"
- 安全熔断提高到 60 轮（仅防死循环）
- `max_sessions_per_slot` 改为按意图数动态：`min(5, len(intents) + 2)`

**LLM User Agent**（`llm_user.py`）：
- `speak` 的 prompt 增加 `{hint}` 占位符，接近上限时暗示收尾

## 2. 契约与兼容性

### 2.1 快照兼容

**新增状态必须进快照**（`world.py:287-337`）：
- `weather_state: str`（天气）
- `event_library: List[dict]`（个性化事件库，存在 Persona 里）
- `user_memory: dict`（用户记忆）

**新增随机流必须命名**（`world/streams.py`）：
- `weather` 流：天气转移
- `planner` 流：用户规划器的随机决策（如同优先级意图的随机打破平局）

### 2.2 确定性回放

新流必须派生自 `seed`，保证"同一 seed 完全相同轨迹"（`world.py:3`）：
```python
def make_streams(seed: int) -> dict:
    seq = np.random.SeedSequence(seed)
    children = seq.spawn(6)  # 原 4 → 6
    return {
        "persona": np.random.default_rng(children[0]),
        "schedule": np.random.default_rng(children[1]),
        "disturbance": np.random.default_rng(children[2]),
        "noise": np.random.default_rng(children[3]),
        "weather": np.random.default_rng(children[4]),  # 新增
        "planner": np.random.default_rng(children[5]),  # 新增
    }
```

### 2.3 Replay 模式

**保留脚本模式**（`run_replay`）：
- 脚本用户没有规划器，保持原逻辑（世界驱动 + 固定 3 轮 session）
- 作为 0-LLM 基线，不需要适配新流程

**新增 Live 模式变体**（`run_live_user_driven`）：
- 用户 LLM + 规划器，走新流程
- 助手可以是 LLM 或脚本

## 3. 前端改动

### 3.1 天气显示

**位置**：时间轴顶部，每个 slot 一个天气图标。

**组件**（`frontend/src/components/WeatherBar.tsx`）：
```tsx
export function WeatherBar({ slots }: { slots: Slot[] }) {
  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-sky-50 border-b">
      {slots.map(slot => (
        <div key={slot.t_logical} className="flex items-center gap-1">
          <WeatherIcon weather={slot.weather} />
          <span className="text-xs text-gray-500">{slot.slot_name}</span>
        </div>
      ))}
    </div>
  );
}

function WeatherIcon({ weather }: { weather: string }) {
  const icons = {
    '晴': '☀️', '多云': '⛅', '阴': '☁️', 
    '小雨': '🌧️', '暴雨': '⛈️'
  };
  return <span className="text-2xl">{icons[weather] || '❓'}</span>;
}
```

### 3.2 意图标签

**位置**：session 标题旁，显示用户发起此次对话的意图。

**修改**（`frontend/src/components/SessionCard.tsx`）：
```tsx
<div className="flex items-center gap-2">
  <h3>Session {session.id}</h3>
  {session.intent && (
    <span className={`px-2 py-0.5 text-xs rounded ${intentColors[session.intent.type]}`}>
      {intentLabels[session.intent.type]}
    </span>
  )}
</div>

const intentLabels = {
  eat: '🍽️ 进餐', social: '👥 社交', stimulate: '✨ 寻求刺激',
  recover: '😌 恢复', emergency: '🚨 紧急', sleep: '😴 睡眠'
};
```

### 3.3 用户记忆面板

**位置**：右侧边栏新增"用户记忆"折叠面板。

**组件**（`frontend/src/components/UserMemoryPanel.tsx`）：
```tsx
export function UserMemoryPanel({ memory }: { memory: UserMemory }) {
  return (
    <div className="p-4 bg-purple-50 rounded">
      <h4 className="font-semibold mb-2">🧠 过去经历</h4>
      <ul className="text-sm space-y-1">
        {memory.sessions.map(s => (
          <li key={s.sid} className="text-gray-700">
            <Link to={`/runs/${runId}/sessions/${s.sid}`} className="hover:underline">
              {s.sid}
            </Link>: {s.summary}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

### 3.4 生物钟可视化

**背景渐变**：时间轴的 slot 背景色按生物钟周期渐变。

**修改**（`frontend/src/components/Timeline.tsx`）：
```tsx
const circadianColors = {
  0: 'bg-amber-100',  // 上午：暖色
  1: 'bg-yellow-50',  // 下午：亮色
  2: 'bg-indigo-100', // 晚上：冷色
  3: 'bg-slate-200',  // 深夜：暗色
};

<div className={`slot-card ${circadianColors[slot.slot]}`}>
  {/* slot 内容 */}
</div>
```

## 4. 数据模型变更

### 4.1 Contracts 新增

**`contracts/models.py`**：
```python
class Intent(BaseModel):
    """用户意图。"""
    type: str  # eat/social/stimulate/recover/emergency/sleep
    priority: float  # 0-1
    event: dict | None = None  # 匹配到的事件模板
    description: str = ""  # 一句话描述

class UserContext(BaseModel):
    """用户 agent 输入（替换原 UserContext）。"""
    persona: Persona
    felt_state: str
    active_events: list[Event]
    schedule_view: list[Event]
    intent: Intent | None = None  # 新增
    past_sessions: str = ""  # 新增：过去经历摘要
    hint: str = ""  # 新增：系统提示（如"聊太久了"）

class SlotSettlement(BaseModel):
    # 原有字段...
    weather: str | None = None  # 新增
```

### 4.2 Persona 扩展

**`contracts/persona.py`**：
```python
class Persona(BaseModel):
    # 原有字段...
    event_library: list[dict] = Field(default_factory=list)  # 新增：个性化事件库
```

## 5. 测试策略

### 5.1 单元测试

**新增**（`tests/test_weather.py`）：
- 天气转移矩阵的概率和为 1
- 同 seed 产出相同天气序列
- 暴雨触发"行程受阻"扰动

**新增**（`tests/test_planner.py`）：
- 高饥饿 → 产生 eat 意图
- 高社交需求 → 产生 social 意图
- 刺激倒 U：过低或过高都产生 stimulate 意图
- 余额不足时只规划免费事件

### 5.2 集成测试

**新增**（`tests/test_user_driven_flow.py`）：
- 用户主动规划 → 创建意图 → 开 session → 助手创建事件 → 状态改善
- 多个意图在一个 slot 内依次执行
- 用户记忆跨 session 传递

### 5.3 回归测试

**确保兼容性**：
- `test_evaluator.py` 的三档回放（good/mid/poor）仍收敛/振荡/发散
- 旧 run 可续跑（快照向后兼容）

## 6. 实施顺序

### Week 1: 天气 + 生物钟（低风险）
- Day 1-2: 天气系统（`weather.py` + 前端图标）
- Day 3: 生物钟叠加（`dynamics.py` + 前端渐变）
- Day 4-5: 测试 + 文档更新

### Week 2: 用户规划（高风险，分步验证）
- Day 1-2: 个性化事件库（`persona.py` + catalog 抽取逻辑）
- Day 3-4: 规则规划器（`user/planner.py`，先写死优先级验证流程）
- Day 5: 前端意图标签 + 测试

### Week 3: Runner 重构（核心）
- Day 1-3: Runner 主循环改为意图驱动（`runner.py`）
- Day 4: 用户记忆系统（`user/memory.py` + 前端面板）
- Day 5: 集成测试 + 回归验证

### Week 4: 打磨 + 文档
- Day 1-2: Session 结束语义改进
- Day 3: LLM User Agent 适配新 prompt
- Day 4: 前端生物钟可视化 + UX 优化
- Day 5: 文档更新（本文档 + 00-architecture.md + 02-user-agent.md）

## 7. 风险与备选

**风险 1**：用户规划器产出过多意图，一个 slot 塞不下。
- **缓解**：优先级截断（只取前 3 个）+ `max_sessions_per_slot` 动态上限。

**风险 2**：LLM 用户不愿结束 session，导致死循环。
- **缓解**：软上限提示 + 60 轮安全熔断 + 监控 session 长度分布。

**风险 3**：个性化事件库差异不明显，所有用户规划趋同。
- **备选**：Phase 2 改为 LLM 规划器，完全动态生成意图。

**风险 4**：破坏确定性回放。
- **缓解**：所有新随机性走命名流 + CI 锁定 seed=42 的 30 天轨迹哈希。

## 8. 成功标准

### 定量指标

- 用户主动发起的 session 占比 > 60%（vs 当前 100% 被动）
- 平均 session 长度 > 5 轮（vs 当前固定 3 轮）
- 意图类型分布符合需求分布（高饥饿时段 eat 意图多、晚间 social 意图多）

### 定性验证

- 观察 10 个 episode，用户行为模式与人格一致（内向者少社交、高开放性者多文化活动）
- session 对话自然（带着明确意图进入，不是空泛的"我压力大"）
- 前端可读性：天气/意图/记忆 UI 清晰直观

## 9. 参考资料

- [00-architecture.md](00-architecture.md)：依赖规则、编排者模式
- [02-user-agent.md](02-user-agent.md)：用户 agent 驱动机制、图结构分析
- [11-anthropomorphism.md](11-anthropomorphism.md)：需求动力学、生物钟
- [13-persona-model.md](13-persona-model.md)：人格 30 facet、结构化喜好
