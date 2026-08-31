import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { api, Persona, RunEvent, SeriesInfo, Slot, Turn } from '../api'
import { KIND_META, SLOT_NAMES, VERDICTS, cssVar, useReducedMotion, SPRING } from '../components/theme'
import { Badge, Button, Segmented, PlainCard } from '../components/ui'
import Cockpit from './cockpit'
import ScheduleGantt, { SessionInfo } from './gantt'
import UnifiedTrajectory from './trajectory'
import WorldGraph from './worldgraph'
import { EconomyPanel, EstErrPanel, EventStatsPanel, InsightsPanel, MetricsPanel } from './panels'
import { PersonaPanel, PersonaSummary, usePersonaHat } from './persona'

type Mode = 'live' | 'replay'
const PANELS = ['经济', '人格画像', '估计误差', '指标', '事件统计', '洞察', '世界图谱'] as const

const ACTION_META: Record<string, { icon: string; label: string; cssVar: string }> = {
  add_event_todo: { icon: '🍽', label: '写入日程', cssVar: '--good' },
  plan_series: { icon: '🗺', label: '规划系列事件', cssVar: '--series' },
  set_reminder: { icon: '🔔', label: '设置提醒', cssVar: '--satiety' },
  view_event_todos: { icon: '🔍', label: '查看日程', cssVar: '--energy' },
}

function ActionCard({ call, result }: { call: Turn['tool_calls'][number]; result?: Turn['tool_results'][number] }) {
  const m = ACTION_META[call.name] ?? { icon: '⚡', label: call.name, cssVar: '--persona' }
  const arg = call.args?.name ?? call.args?.series_type ?? call.args?.message ?? call.args?.content ?? ''
  const failed = result && !result.ok
  const color = failed ? 'var(--critical)' : cssVar(m.cssVar)
  return (
    <div className="rounded-lg border px-2.5 py-1.5 text-[11px] leading-tight"
      style={{ borderColor: `color-mix(in srgb, ${color} 40%, transparent)`, background: `color-mix(in srgb, ${color} 6%, transparent)` }}>
      <span className="mr-1">{m.icon}</span>
      <span style={{ color }} className="font-medium">{m.label}</span>
      {arg && <span className="text-t2">：{String(arg)}</span>}
      {result && (
        <span className="ml-1.5 font-num" style={{ color: failed ? 'var(--critical)' : 'var(--good)' }}>
          {failed ? `✗ ${result.payload?.error ?? '失败'}` : '✓'}
        </span>
      )}
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
  const reduced = useReducedMotion()

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

  const curTurnId = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].t_logical <= curT) return turns[i].turn_id
    }
    return null
  }, [turns, curT])

  // 刻意不在实时/回放更新时自动定位对话记录：由用户自行滚动，避免游标跳动打断阅读。

  const curXhat = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].x_hat && turns[i].t_logical <= curT) return turns[i].x_hat
    }
    return null
  }, [turns, curT])

  const { hat: curPersonaHat } = usePersonaHat(turns, curT)

  // Cockpit：当前时刻最近的用户/助手 turn + felt_state
  const curUserTurn = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].speaker === 'user' && turns[i].t_logical <= curT) return turns[i]
    }
    return null
  }, [turns, curT])
  const curAssistantTurn = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].speaker === 'assistant' && turns[i].t_logical <= curT) return turns[i]
    }
    return null
  }, [turns, curT])
  const curFelt = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].t_logical <= curT && turns[i].felt_state) return turns[i].felt_state!
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
  const persona: Persona | null = detail?.meta?.persona ?? null

  return (
    <div className="space-y-4">
      {/* 头部 */}
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={onBack} className="text-[13px] text-t2 hover:text-t1 transition-colors">← 返回</button>
        <span className="font-num text-sm text-t1 truncate max-w-[300px]">{runId}</span>
        {status === 'running' && (
          <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium"
            style={{ color: 'var(--accent)', background: 'color-mix(in srgb, var(--accent) 12%, transparent)' }}>
            <span className="relative flex h-2 w-2">
              {!reduced && <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60" style={{ background: 'var(--accent)' }} />}
              <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: 'var(--accent)' }} />
            </span>
            运行中
          </span>
        )}
        {verdict && <Badge label={verdict.label} color={cssVar(verdict.cssVar)} icon={verdict.icon} />}
        {detail?.meta?.profiles && (
          <span className="rounded-full px-2.5 py-0.5 text-[11px] font-num text-t3 border border-edge bg-surface-2">
            助手 {detail.meta.profiles.assistant ?? '—'} · 用户 {detail.meta.profiles.user ?? '—'}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <input type="number" value={extraDays} min={1} onChange={(e) => setExtraDays(+e.target.value)}
            className="w-16 rounded-xl bg-surface-2 border border-edge px-2 py-1.5 text-xs text-t1 font-num" />
          <Button onClick={doContinue} disabled={continuing} variant="primary" className="!py-1.5">
            {continuing ? '续跑中…' : `⏩ 续跑 ${extraDays} 天`}
          </Button>
        </div>
      </div>

      {/* 同时刻全景 */}
      <Cockpit
        curT={curT} curSlot={curSlot} curXhat={curXhat} persona={persona}
        personaHat={curPersonaHat} activeEvents={activeEventsNow}
        userTurn={curUserTurn} assistantTurn={curAssistantTurn} feltState={curFelt} />

      {/* 统一时间线 */}
      <PlainCard className="p-4 space-y-5">
        <ScheduleGantt
          events={events} series={seriesList} sessions={sessions}
          days={detail?.meta?.days ?? Math.ceil((maxT + 1) / 4)} curT={curT}
          onSeek={(t) => { setMode('replay'); setReplayT(t) }}
          onSelectSession={(id) => setSelectedSession(id === selectedSession ? null : id)}
          selectedSession={selectedSession} />
        <div className="border-t border-edge" />
        <UnifiedTrajectory
          slots={slots} series={seriesList} curT={curT}
          onSeek={(t) => { setMode('replay'); setReplayT(t) }} />
      </PlainCard>

      <div className="grid grid-cols-12 gap-4">
        {/* 对话记录 */}
        <PlainCard className="col-span-12 lg:col-span-8 p-4 flex flex-col h-[560px]">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-t1">对话记录</span>
              {selectedSession && (
                <button onClick={() => setSelectedSession(null)}
                  className="rounded-full px-2 py-0.5 text-[11px]"
                  style={{ color: 'var(--persona)', background: 'color-mix(in srgb, var(--persona) 12%, transparent)', border: '1px solid color-mix(in srgb, var(--persona) 40%, transparent)' }}>
                  {selectedSession} · 第 {Math.floor((sessions.find((s) => s.id === selectedSession)?.t ?? 0) / 4) + 1} 天 ✕
                </button>
              )}
            </div>
            <span className="text-[10px] font-num text-t3">
              {selectedSession ? `${shownTurns.length} turns` : mode === 'replay' ? `回放至 t=${curT}` : '实时'}
            </span>
          </div>
          <div ref={chatRef} className="flex-1 overflow-y-auto space-y-3 pr-1">
            {shownTurns.map((t) => {
              const isCur = t.turn_id === curTurnId
              if (t.speaker === 'system') {
                return (
                  <div key={t.turn_id} ref={(el) => { if (el) turnRefs.current.set(t.turn_id, el) }}
                    className="rounded-xl border px-3 py-2 text-[11px]"
                    style={{ borderColor: 'color-mix(in srgb, var(--warning) 30%, transparent)', background: 'color-mix(in srgb, var(--warning) 8%, transparent)', color: 'var(--warning)' }}>
                    ⚙ {t.text}
                  </div>
                )
              }
              const isUser = t.speaker === 'user'
              return (
                <motion.div key={t.turn_id} ref={(el) => { if (el) turnRefs.current.set(t.turn_id, el) }}
                  animate={isCur && !reduced ? { scale: 1 } : {}}
                  className={isCur ? 'rounded-2xl p-1.5 -m-1.5' : ''}
                  style={isCur ? { boxShadow: '0 0 0 1.5px var(--accent)', background: 'color-mix(in srgb, var(--accent) 4%, transparent)' } : undefined}>
                  <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    <div className="max-w-[85%] rounded-2xl px-3.5 py-2 text-[13px] leading-relaxed border"
                      style={isUser
                        ? { background: 'color-mix(in srgb, var(--user) 12%, transparent)', borderColor: 'color-mix(in srgb, var(--user) 30%, transparent)', borderTopRightRadius: 4 }
                        : { background: 'var(--surface-2)', borderColor: 'var(--border)', borderTopLeftRadius: 4 }}>
                      <div className="text-[9px] text-t3 font-num mb-0.5">
                        {isUser ? '用户' : '助手'} · turn {t.turn_id + 1} · d{Math.floor(t.t_logical / 4) + 1} {SLOT_NAMES[t.t_logical % 4]}
                        {isCur && <span className="ml-1" style={{ color: 'var(--accent)' }}>● 当前</span>}
                      </div>
                      <div className="text-t1">{t.text}</div>
                      {isUser && t.felt_state && (
                        <div className="text-[10px] text-t3 mt-1 pt-1 border-t border-edge">感受：{t.felt_state}</div>
                      )}
                    </div>
                  </div>
                  {t.tool_calls.filter((c) => !['open_session', 'close_session'].includes(c.name)).length > 0 && (
                    <div className={`mt-1.5 space-y-1 ${isUser ? 'ml-auto w-fit' : ''}`}>
                      {t.tool_calls.filter((c) => !['open_session', 'close_session'].includes(c.name)).map((c, i) => (
                        <ActionCard key={i} call={c} result={t.tool_results.find((r) => r.name === c.name)} />
                      ))}
                    </div>
                  )}
                </motion.div>
              )
            })}
            {shownTurns.length === 0 && <p className="text-sm text-t3">该时刻之前还没有对话</p>}
          </div>
        </PlainCard>

        {/* 侧栏：人格画像缩略（状态全景已在 Cockpit） */}
        <div className="col-span-12 lg:col-span-4">
          <PlainCard className="p-4 sticky top-20 max-h-[560px] overflow-y-auto">
            <div className="text-sm font-semibold text-t1 mb-2">人格 / 喜好画像</div>
            {persona && <div className="text-[10.5px] text-t3 mb-3">{persona.name} · {persona.archetype}</div>}
            <PersonaSummary persona={persona} hat={curPersonaHat} />
            {curPersonaHat && (curPersonaHat.loves.length > 0 || curPersonaHat.hates.length > 0) && (
              <div className="mt-3 flex flex-wrap gap-1">
                {curPersonaHat.loves.slice(0, 5).map((t) => (
                  <span key={`l-${t}`} className="rounded-full px-1.5 py-0.5 text-[10px] border"
                    style={{ color: 'var(--good)', borderColor: 'color-mix(in srgb, var(--good) 40%, transparent)', background: 'color-mix(in srgb, var(--good) 10%, transparent)' }}>♥ {t}</span>
                ))}
                {curPersonaHat.hates.slice(0, 5).map((t) => (
                  <span key={`h-${t}`} className="rounded-full px-1.5 py-0.5 text-[10px] border"
                    style={{ color: 'var(--critical)', borderColor: 'color-mix(in srgb, var(--critical) 40%, transparent)', background: 'color-mix(in srgb, var(--critical) 10%, transparent)' }}>✗ {t}</span>
                ))}
              </div>
            )}
            {activeEventsNow.length > 0 && (
              <div className="mt-4">
                <div className="text-[10.5px] text-t3 mb-1.5">当前进行中的事件</div>
                <div className="space-y-1">
                  {activeEventsNow.slice(0, 6).map((e) => (
                    <div key={e.id} className="rounded-lg border border-edge px-2 py-1 text-[10.5px] flex items-center justify-between gap-1">
                      <span className="text-t2 truncate">{e.name}</span>
                      <span className="shrink-0 font-num" style={{ color: cssVar(KIND_META[e.kind].cssVar) }}>{KIND_META[e.kind].label}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </PlainCard>
        </div>
      </div>

      {/* 回放控制条 — 固定底部悬浮 */}
      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-edge pb-safe"
        style={{ background: 'var(--toolbar-bg)', backdropFilter: 'blur(20px) saturate(180%)' }}>
        <div className="mx-auto max-w-[1480px] px-6 py-3 flex flex-wrap items-center gap-3">
          <Button variant="primary" className="!py-1.5" onClick={() => { setMode('replay'); setPlaying(!playing) }}>
            {playing ? '⏸ 暂停' : '▶ 回放'}
          </Button>
          <Button variant="ghost" className="!px-2.5 !py-1.5" onClick={() => { setMode('replay'); setReplayT(Math.max(0, curT - 1)) }}>◀</Button>
          <Button variant="ghost" className="!px-2.5 !py-1.5" onClick={() => { setMode('replay'); setReplayT(Math.min(maxT, curT + 1)) }}>▶</Button>
          <input type="range" min={0} max={maxT} value={curT}
            onChange={(e) => { setMode('replay'); setReplayT(+e.target.value) }}
            className="flex-1 accent-[var(--accent)]" />
          <span className="text-[11px] font-num text-t2 whitespace-nowrap">t={curT} / {maxT}</span>
          <Segmented size="sm" value={String(speed)} options={['1', '2', '4'].map((s) => [s, `${s}×`] as const)}
            onChange={(s) => setSpeed(+s)} />
          {mode === 'replay' && (
            <button onClick={() => { setMode('live'); setPlaying(false) }}
              className="rounded-xl border px-3 py-1.5 text-xs transition-colors"
              style={{ color: 'var(--accent)', borderColor: 'color-mix(in srgb, var(--accent) 40%, transparent)' }}>
              ⏭ 回到最新
            </button>
          )}
        </div>
      </div>

      {/* 底部留白（防止内容被控制条遮挡） */}
      <div className="h-20" />

      {/* 分析面板 */}
      <div>
        <div className="mb-4 overflow-x-auto">
          <Segmented value={panel} options={PANELS.map((p) => [p, p] as const)} onChange={setPanel} />
        </div>
        {panel === '经济' && <EconomyPanel slots={slots} events={events} />}
        {panel === '人格画像' && <PersonaPanel persona={persona} turns={turns} curT={curT} report={report} />}
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
