import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, KIND_META, RunEvent, SeriesInfo, Slot, SLOT_NAMES, Turn, VERDICTS } from '../api'
import { Badge, Card, StateBars } from '../components/StateBars'
import ScheduleGantt, { SessionInfo } from './gantt'
import UnifiedTrajectory from './trajectory'
import WorldGraph from './worldgraph'
import { EconomyPanel, EstErrPanel, EventStatsPanel, InsightsPanel, MetricsPanel } from './panels'

type Mode = 'live' | 'replay'
const PANELS = ['经济', '估计误差', '指标', '事件统计', '洞察', '世界图谱'] as const

const ACTION_META: Record<string, { icon: string; label: string; color: string }> = {
  add_event_todo: { icon: '🍽', label: '写入日程', color: '#34d399' },
  plan_series: { icon: '🗺', label: '规划系列事件', color: '#f472b6' },
  set_reminder: { icon: '🔔', label: '设置提醒', color: '#fbbf24' },
  view_event_todos: { icon: '🔍', label: '查看日程', color: '#38bdf8' },
}

function ActionCard({ call, result }: { call: Turn['tool_calls'][number]; result?: Turn['tool_results'][number] }) {
  const m = ACTION_META[call.name] ?? { icon: '⚡', label: call.name, color: '#a78bfa' }
  const arg = call.args?.name ?? call.args?.series_type ?? call.args?.message ?? call.args?.content ?? ''
  const failed = result && !result.ok
  return (
    <div className="rounded-lg border px-2.5 py-1.5 text-[11px] leading-tight"
      style={{ borderColor: `${failed ? '#f87171' : m.color}66`, background: `${failed ? '#f87171' : m.color}0d` }}>
      <span className="mr-1">{m.icon}</span>
      <span style={{ color: failed ? '#f87171' : m.color }} className="font-medium">{m.label}</span>
      {arg && <span className="text-zinc-300">：{String(arg)}</span>}
      {result && (
        <span className={`ml-1.5 font-num ${failed ? 'text-red-400' : 'text-emerald-400'}`}>
          {failed ? `✗ ${result.payload?.error ?? '失败'}` : '✓'}
        </span>
      )}
    </div>
  )
}

function EventRow({ e, curT, activeEventIds }: { e: RunEvent; curT: number; activeEventIds: Set<string> }) {
  const active = activeEventIds.has(e.id)
  const km = KIND_META[e.kind]
  return (
    <div className={`rounded border px-2 py-1 text-[10.5px] leading-tight ${
      active ? 'border-cyan-400/50 bg-cyan-400/[0.07]' : 'border-white/10 opacity-60'}`}>
      <div className="flex items-center justify-between gap-1">
        <span className="text-zinc-300 truncate">{e.name}</span>
        <span className="font-num shrink-0" style={{ color: km.color }}>{km.label}</span>
      </div>
      <div className="text-zinc-600 font-num">{e.location}{e.cost > 0 && ` · -¥${e.cost}`}{e.income > 0 && ` · +¥${e.income}`}</div>
    </div>
  )
}

export default function Console({ runId, onBack }: { runId: string; onBack: () => void }) {
  const [detail, setDetail] = useState<any>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [slots, setSlots] = useState<Slot[]>([])
  const [events, setEvents] = useState<RunEvent[]>([])
  const [seriesList, setSeriesList] = useState<SeriesInfo[]>([])
  const [report, setReport] = useState<any>(null)
  const [status, setStatus] = useState('running')

  const [mode, setMode] = useState<Mode>('live')
  const [replayT, setReplayT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(2)
  const [panel, setPanel] = useState<(typeof PANELS)[number]>('经济')
  const [selectedSession, setSelectedSession] = useState<string | null>(null)
  const [extraDays, setExtraDays] = useState(10)
  const [continuing, setContinuing] = useState(false)
  const chatRef = useRef<HTMLDivElement>(null)
  const turnRefs = useRef(new Map<number, HTMLDivElement>())

  const maxT = Math.max(0, slots.length - 1)

  // ---------- 数据加载 ----------
  const loadStatic = useCallback(async () => {
    const [d, t, s, e, r] = await Promise.all([
      api.runDetail(runId), api.turns(runId), api.slots(runId), api.events(runId),
      api.report(runId).catch(() => null),
    ])
    setDetail(d); setStatus(d.status)
    setTurns(t.items); setSlots(s.items); setEvents(e.items); setSeriesList(e.series ?? []); setReport(r)
  }, [runId])

  useEffect(() => { loadStatic() }, [loadStatic])

  useEffect(() => {
    if (status !== 'running') return
    const id = setInterval(() => api.runDetail(runId).then(setDetail).catch(() => {}), 5000)
    return () => clearInterval(id)
  }, [runId, status])

  // ---------- WebSocket ----------
  useEffect(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/runs/${runId}`)
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data)
      if (ev.type === 'turn') {
        setTurns((ts) => (ts.some((x) => x.turn_id === ev.data.turn_id) ? ts : [...ts, ev.data]))
      } else if (ev.type === 'slot') {
        setSlots((ss) => (ss.some((x) => x.t_logical === ev.data.t_logical) ? ss : [...ss, ev.data]))
      } else if (ev.type === 'done') {
        setStatus('finished')
        api.events(runId).then((d) => { setEvents(d.items); setSeriesList(d.series ?? []) })
        api.report(runId).then(setReport).catch(() => {})
        api.runDetail(runId).then(setDetail)
      } else if (ev.type === 'error') {
        setStatus('failed')
      }
    }
    return () => ws.close()
  }, [runId])

  // ---------- 回放 ----------
  useEffect(() => {
    if (!playing || mode !== 'replay') return
    const id = setInterval(() => {
      setReplayT((t) => { if (t >= maxT) { setPlaying(false); return t } return t + 1 })
    }, 700 / speed)
    return () => clearInterval(id)
  }, [playing, mode, speed, maxT])

  useEffect(() => { if (mode === 'live') setReplayT(maxT) }, [maxT, mode])

  const curT = mode === 'live' ? maxT : replayT
  const curSlot = slots[curT] ?? null

  // ---------- sessions ----------
  const sessions = useMemo<SessionInfo[]>(() => {
    const m = new Map<string, Turn[]>()
    turns.forEach((t) => {
      if (!t.session_id) return
      const arr = m.get(t.session_id) ?? []
      arr.push(t)
      m.set(t.session_id, arr)
    })
    return [...m.entries()].map(([id, ts]) => ({ id, t: ts[0].t_logical, nTurns: ts.length }))
  }, [turns])

  const shownTurns = useMemo(() => {
    if (selectedSession) return turns.filter((t) => t.session_id === selectedSession)
    return turns.filter((t) => t.t_logical <= curT).slice(-100)
  }, [turns, curT, selectedSession])

  // 当前 turn（用于高亮与自动滚动）
  const curTurnId = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].t_logical <= curT) return turns[i].turn_id
    }
    return null
  }, [turns, curT])

  useEffect(() => {
    if (mode === 'live' && !selectedSession) {
      chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight })
    }
  }, [shownTurns.length, mode, selectedSession])

  useEffect(() => {
    if (mode === 'replay' && curTurnId !== null) {
      turnRefs.current.get(curTurnId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [curTurnId, mode])

  const curXhat = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].x_hat && turns[i].t_logical <= curT) return turns[i].x_hat
    }
    return null
  }, [turns, curT])

  const activeEventsNow = useMemo(
    () => events.filter((e) => e.start_slot <= curT && curT < e.start_slot + e.span_slots),
    [events, curT],
  )

  const doContinue = async () => {
    setContinuing(true)
    await api.continueRun(runId, extraDays)
    setStatus('running'); setMode('live')
    setContinuing(false)
  }

  const verdict = report?.verdict ? VERDICTS[report.verdict] : null
  const persona = detail?.meta?.persona
  const isWorkday = (d: number) => d % 7 < 5

  return (
    <div className="space-y-4">
      {/* 头部 */}
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={onBack} className="text-xs text-zinc-400 hover:text-white">← 返回</button>
        <span className="font-num text-sm text-zinc-200 truncate max-w-[300px]">{runId}</span>
        {status === 'running' && <Badge label="● 运行中" color="#22d3ee" />}
        {verdict && <Badge label={verdict.label} color={verdict.color} />}
        <div className="ml-auto flex items-center gap-2">
          <input type="number" value={extraDays} min={1} onChange={(e) => setExtraDays(+e.target.value)}
            className="w-16 rounded-lg bg-white/5 border border-white/15 px-2 py-1.5 text-xs text-white font-num" />
          <button onClick={doContinue} disabled={continuing}
            className="rounded-lg bg-emerald-500/90 hover:bg-emerald-400 px-3 py-1.5 text-xs font-semibold text-black transition-colors disabled:opacity-40">
            {continuing ? '续跑中…' : `⏩ 续跑 ${extraDays} 天`}
          </button>
        </div>
      </div>

      {/* 统一时间线：日程记录图 + 状态轨迹（共享同一时间游标 curT） */}
      <Card className="p-4 space-y-5">
        <ScheduleGantt
          events={events} series={seriesList} sessions={sessions}
          days={detail?.meta?.days ?? Math.ceil((maxT + 1) / 4)} curT={curT}
          onSeek={(t) => { setMode('replay'); setReplayT(t) }}
          onSelectSession={(id) => setSelectedSession(id === selectedSession ? null : id)}
          selectedSession={selectedSession} />
        <div className="border-t border-white/10" />
        <UnifiedTrajectory
          slots={slots} series={seriesList} curT={curT}
          onSeek={(t) => { setMode('replay'); setReplayT(t) }} />
      </Card>

      <div className="grid grid-cols-12 gap-4">
        {/* 对话记录 */}
        <Card className="col-span-12 lg:col-span-8 p-4 flex flex-col h-[560px]">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-zinc-200">对话记录</span>
              {selectedSession && (
                <button onClick={() => setSelectedSession(null)}
                  className="rounded-md bg-violet-400/15 border border-violet-400/40 px-2 py-0.5 text-[11px] text-violet-300 hover:bg-violet-400/25">
                  {selectedSession} · 第 {Math.floor((sessions.find((s) => s.id === selectedSession)?.t ?? 0) / 4) + 1} 天 ✕
                </button>
              )}
            </div>
            <span className="text-[10px] font-num text-zinc-500">
              {selectedSession ? `${shownTurns.length} turns` : mode === 'replay' ? `回放至 t=${curT}` : '实时'}
            </span>
          </div>
          <div ref={chatRef} className="flex-1 overflow-y-auto space-y-3 pr-1">
            {shownTurns.map((t) => {
              const isCur = t.turn_id === curTurnId
              const wrapCls = isCur ? 'rounded-xl ring-1 ring-cyan-400/70 bg-cyan-400/[0.04] p-1.5 -m-1.5' : ''
              if (t.speaker === 'system') {
                return (
                  <div key={t.turn_id} ref={(el) => { if (el) turnRefs.current.set(t.turn_id, el) }}
                    className={`rounded-lg border border-amber-400/25 bg-amber-400/[0.05] p-2.5 text-[11px] text-amber-200/80 ${wrapCls}`}>
                    ⚙ {t.text}
                  </div>
                )
              }
              const isUser = t.speaker === 'user'
              return (
                <div key={t.turn_id} ref={(el) => { if (el) turnRefs.current.set(t.turn_id, el) }} className={wrapCls}>
                  <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-[13px] leading-relaxed ${
                      isUser ? 'bg-emerald-500/15 border border-emerald-400/30 text-emerald-50 rounded-tr-sm'
                             : 'bg-white/[0.06] border border-white/10 text-zinc-100 rounded-tl-sm'}`}>
                      <div className="text-[9px] text-zinc-500 font-num mb-0.5">
                        {isUser ? '用户' : '助手'} · turn {t.turn_id + 1} · d{Math.floor(t.t_logical / 4) + 1} {SLOT_NAMES[t.t_logical % 4]}
                        {isCur && <span className="text-cyan-400 ml-1">● 当前</span>}
                      </div>
                      {t.text}
                    </div>
                  </div>
                  {/* 助手行为动作卡 */}
                  {t.tool_calls.filter((c) => !['open_session', 'close_session'].includes(c.name)).length > 0 && (
                    <div className={`mt-1.5 space-y-1 ${isUser ? 'ml-auto w-fit' : ''}`}>
                      {t.tool_calls.filter((c) => !['open_session', 'close_session'].includes(c.name)).map((c, i) => (
                        <ActionCard key={i} call={c}
                          result={t.tool_results.find((r) => r.name === c.name)} />
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            {shownTurns.length === 0 && <p className="text-sm text-zinc-500">该时刻之前还没有对话</p>}
          </div>
        </Card>

        {/* 常驻状态栏 */}
        <div className="col-span-12 lg:col-span-4">
          <Card className="p-4 sticky top-20 max-h-[560px] overflow-y-auto">
            {/* 环境状态 */}
            <div className="text-sm font-semibold text-zinc-200 mb-2">环境状态</div>
            <div className="rounded-lg bg-white/[0.04] p-2.5 text-[11px] space-y-1 mb-4">
              <div className="flex justify-between"><span className="text-zinc-500">时间</span>
                <span className="font-num text-zinc-200">第 {Math.floor(curT / 4) + 1} 天 · {SLOT_NAMES[curT % 4]}{isWorkday(Math.floor(curT / 4)) ? ' · 工作日' : ' · 周末'}</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">系列</span>
                <span className="text-pink-300">{curSlot?.active_series ?? '无'}</span></div>
              <div className="flex justify-between"><span className="text-zinc-500">余额</span>
                <span className={`font-num ${curSlot && curSlot.money_after < 0 ? 'text-red-400' : 'text-amber-300'}`}>
                  ¥{curSlot ? Math.round(curSlot.money_after) : 0}</span></div>
            </div>
            {activeEventsNow.length > 0 && (
              <div className="mb-4">
                <div className="text-[10.5px] text-zinc-500 mb-1.5">当前进行中的事件</div>
                <div className="space-y-1">
                  {activeEventsNow.slice(0, 6).map((e) => (
                    <EventRow key={e.id} e={e} curT={curT} activeEventIds={new Set([e.id])} />
                  ))}
                </div>
              </div>
            )}

            {/* 双状态 */}
            <div className="text-sm font-semibold text-zinc-200 mb-1">真实状态 x vs 估计 x̂</div>
            {persona && <div className="text-[10.5px] text-zinc-500 mb-3">{persona.name} · {persona.archetype} · ¥{persona.income_per_slot}/时段</div>}
            {curSlot ? <StateBars x={curSlot.x_after} xhat={curXhat} /> : <p className="text-sm text-zinc-500">等待数据…</p>}

            {curSlot && (
              <div className="mt-4 rounded-lg bg-black/30 p-3 text-[11px] font-num text-zinc-400 space-y-1">
                {(['natural_drift', 'event_effects', 'control_effects'] as const).map((k) => {
                  const fx = Object.entries(curSlot[k]).filter(([, v]) => Math.abs(v as number) > 0.005)
                  if (!fx.length) return null
                  const label = { natural_drift: '自然漂移', event_effects: '事件效果', control_effects: '控制回血' }[k]
                  return <div key={k}>▸ {label}: {fx.map(([kk, v]) => `${kk} ${(v as number) > 0 ? '+' : ''}${(v as number).toFixed(2)}`).join(' · ')}</div>
                })}
                {curSlot.money_after !== curSlot.money_before && (
                  <div>▸ 金钱: {curSlot.money_after - curSlot.money_before > 0 ? '+' : ''}{(curSlot.money_after - curSlot.money_before).toFixed(0)}</div>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* 回放控制条 */}
      <Card className="p-3 flex flex-wrap items-center gap-3">
        <button onClick={() => { setMode('replay'); setPlaying(!playing) }}
          className="rounded-lg bg-cyan-500/90 hover:bg-cyan-400 px-4 py-1.5 text-xs font-semibold text-black transition-colors">
          {playing ? '⏸ 暂停' : '▶ 回放'}
        </button>
        <button onClick={() => { setMode('replay'); setReplayT(Math.max(0, curT - 1)) }} className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-white/5">◀</button>
        <button onClick={() => { setMode('replay'); setReplayT(Math.min(maxT, curT + 1)) }} className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-white/5">▶</button>
        <input type="range" min={0} max={maxT} value={curT}
          onChange={(e) => { setMode('replay'); setReplayT(+e.target.value) }}
          className="flex-1 accent-cyan-400" />
        <span className="text-[11px] font-num text-zinc-400 whitespace-nowrap">t={curT} / {maxT}</span>
        {[1, 2, 4].map((s) => (
          <button key={s} onClick={() => setSpeed(s)}
            className={`rounded px-2 py-1 text-[11px] font-num ${speed === s ? 'bg-white/10 text-white' : 'text-zinc-500'}`}>{s}×</button>
        ))}
        {mode === 'replay' && (
          <button onClick={() => { setMode('live'); setPlaying(false) }}
            className="rounded-lg border border-cyan-400/40 px-3 py-1.5 text-xs text-cyan-300 hover:bg-cyan-400/10">
            ⏭ 回到最新
          </button>
        )}
      </Card>

      {/* 分析面板 */}
      <div>
        <div className="flex gap-2 mb-4">
          {PANELS.map((p) => (
            <button key={p} onClick={() => setPanel(p)}
              className={`rounded-lg px-4 py-2 text-sm transition-colors ${panel === p ? 'bg-white/10 text-white font-semibold' : 'text-zinc-400 hover:text-zinc-200'}`}>
              {p}
            </button>
          ))}
        </div>
        {panel === '经济' && <EconomyPanel slots={slots} events={events} />}
        {panel === '估计误差' && <EstErrPanel report={report} turns={turns} />}
        {panel === '指标' && <MetricsPanel report={report} />}
        {panel === '事件统计' && <EventStatsPanel events={events} turns={turns} />}
        {panel === '洞察' && <InsightsPanel runId={runId} />}
        {panel === '世界图谱' && (
          <WorldGraph events={events} series={seriesList} slots={slots} curT={curT}
            personaName={detail?.meta?.persona?.name} />
        )}
      </div>
    </div>
  )
}
