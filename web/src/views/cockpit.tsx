import { useMemo } from 'react'
import { motion } from 'motion/react'
import { Persona, RunEvent, Slot, StateVec, Turn } from '../api'
import { PersonaBelief } from '../api'
import { DIMS, KIND_META, SLOT_NAMES, cssVar, useThemeVersion, useReducedMotion, SPRING } from '../components/theme'
import { StateBars } from '../components/StateBars'
import { AnimatedNumber, PlainCard } from '../components/ui'

// ============================================================
// Cockpit — 同时刻全景：系统(世界) · 用户 Agent · 助手 Agent
// 由单一时间游标 curT 驱动，三栏同步，因果链高亮。
// ============================================================

// 天气图标映射
const WEATHER_ICONS: Record<string, { icon: string; color: string }> = {
  '晴': { icon: '☀️', color: '#f59e0b' },
  '多云': { icon: '⛅', color: '#94a3b8' },
  '阴': { icon: '☁️', color: '#64748b' },
  '小雨': { icon: '🌧️', color: '#3b82f6' },
  '暴雨': { icon: '⛈️', color: '#6366f1' },
}

// 意图类型映射
const INTENT_META: Record<string, { label: string; color: string }> = {
  eat: { label: '🍽️ 进餐', color: 'var(--satiety)' },
  social: { label: '👥 社交', color: 'var(--energy)' },
  stimulate: { label: '✨ 找乐子', color: 'var(--valence)' },
  recover: { label: '😌 恢复', color: 'var(--good)' },
  sleep: { label: '😴 睡觉', color: 'var(--series)' },
  achieve: { label: '📚 做正事', color: 'var(--stress)' },
  emergency: { label: '🚨 紧急', color: 'var(--critical)' },
}

function WeatherBadge({ weather }: { weather?: string | null }) {
  if (!weather) return null
  const meta = WEATHER_ICONS[weather] ?? { icon: '🌤️', color: '#94a3b8' }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{ background: 'var(--hover)', color: meta.color }}>
      {meta.icon} {weather}
    </span>
  )
}

function IntentBadge({ intentType }: { intentType?: string | null }) {
  if (!intentType) return null
  const meta = INTENT_META[intentType] ?? { label: intentType, color: 'var(--text-2)' }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{ background: 'var(--hover)', color: meta.color }}>
      {meta.label}
    </span>
  )
}

const ACTION_META: Record<string, { icon: string; label: string; cssVar: string }> = {
  add_event_todo: { icon: '🍽', label: '写入日程', cssVar: '--good' },
  plan_series: { icon: '🗺', label: '规划系列', cssVar: '--series' },
  set_reminder: { icon: '🔔', label: '设置提醒', cssVar: '--satiety' },
  view_event_todos: { icon: '🔍', label: '查看日程', cssVar: '--energy' },
}

function SectionTitle({ dot, children, sub }: { dot: string; children: React.ReactNode; sub?: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: dot }} />
      <span className="text-[13px] font-semibold text-t1">{children}</span>
      {sub && <span className="text-[10.5px] text-t3 ml-auto font-num">{sub}</span>}
    </div>
  )
}

// 结算分解微条（带符号，正负分色）
function EffectBars({ slot }: { slot: Slot }) {
  useThemeVersion()
  const rows = (['natural_drift', 'event_effects', 'control_effects'] as const).flatMap((k) => {
    const label = { natural_drift: '自然漂移', event_effects: '事件效果', control_effects: '控制回血' }[k]
    return Object.entries(slot[k])
      .filter(([, v]) => Math.abs(v as number) > 0.005)
      .map(([dim, v]) => ({ group: label, dim, v: v as number }))
  })
  if (!rows.length) return <p className="text-[11px] text-t3">本时段无显著状态变化</p>
  const max = Math.max(0.02, ...rows.map((r) => Math.abs(r.v)))
  const dimColor = (dim: string) => {
    const d = DIMS.find((x) => x.key === dim)
    return d ? cssVar(d.cssVar) : cssVar('--text-3')
  }
  const dimLabel = (dim: string) => DIMS.find((x) => x.key === dim)?.label ?? dim
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2 text-[10.5px]">
          <span className="w-14 text-t3 shrink-0">{r.group}</span>
          <span className="w-7 text-t2 shrink-0">{dimLabel(r.dim)}</span>
          <div className="relative flex-1 h-2 rounded-full bg-[var(--hover)]">
            <div className="absolute top-0 bottom-0 w-px bg-[var(--axis)]" style={{ left: '50%' }} />
            <div className="absolute inset-y-0 rounded-full"
              style={{
                left: r.v >= 0 ? '50%' : `${50 - (Math.abs(r.v) / max) * 50}%`,
                width: `${(Math.abs(r.v) / max) * 50}%`,
                background: r.v >= 0 ? dimColor(r.dim) : 'var(--critical)', opacity: 0.85,
              }} />
          </div>
          <span className="w-10 text-right font-num shrink-0" style={{ color: r.v >= 0 ? dimColor(r.dim) : 'var(--critical)' }}>
            {r.v > 0 ? '+' : ''}{r.v.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  )
}

// 逐维估计误差微条
function EstErrBars({ x, xhat }: { x: StateVec; xhat: StateVec }) {
  useThemeVersion()
  return (
    <div className="space-y-1.5">
      {DIMS.map((d) => {
        const err = Math.abs(x[d.key] - xhat[d.key])
        const color = err > 0.15 ? 'var(--critical)' : err > 0.08 ? 'var(--warning)' : 'var(--good)'
        return (
          <div key={d.key} className="flex items-center gap-2 text-[10.5px]">
            <span className="w-7 text-t2 shrink-0">{d.label}</span>
            <div className="relative flex-1 h-2 rounded-full bg-[var(--hover)] overflow-hidden">
              <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, err * 300)}%`, background: color, opacity: 0.85 }} />
            </div>
            <span className="w-10 text-right font-num shrink-0" style={{ color }}>{err.toFixed(2)}</span>
          </div>
        )
      })}
    </div>
  )
}

function Bubble({ who, text, color }: { who: string; text: string; color: string }) {
  return (
    <div className="rounded-xl border border-edge bg-surface-2 p-2.5">
      <div className="text-[10px] font-num mb-1" style={{ color }}>{who}</div>
      <div className="text-[12.5px] leading-relaxed text-t1 line-clamp-4">{text}</div>
    </div>
  )
}

// 因果链箭头：世界 → 用户感受 → 用户台词 → 助手估计 → 助手行动
function CausalArrow({ active, label }: { active: boolean; label: string }) {
  useThemeVersion()
  const reduced = useReducedMotion()
  return (
    <div className="flex flex-col items-center justify-center px-1 py-2 lg:py-0">
      <svg width="40" height="24" viewBox="0 0 40 24" className="lg:rotate-0 rotate-90">
        <motion.line x1="2" y1="12" x2="30" y2="12"
          stroke={active ? 'var(--accent)' : 'var(--axis)'} strokeWidth={active ? 2 : 1.2}
          className={active && !reduced ? 'flow' : ''} opacity={active ? 1 : 0.5} />
        <path d="M30 7 L38 12 L30 17 Z" fill={active ? 'var(--accent)' : 'var(--axis)'} opacity={active ? 1 : 0.5} />
      </svg>
      <span className="text-[9px] text-t3 mt-0.5 whitespace-nowrap text-center">{label}</span>
    </div>
  )
}

interface CockpitProps {
  curT: number
  curSlot: Slot | null
  curXhat: StateVec | null
  persona: Persona | null
  personaHat: PersonaBelief | null
  activeEvents: RunEvent[]
  userTurn: Turn | null
  assistantTurn: Turn | null
  feltState: string | null
}

export default function Cockpit(p: CockpitProps) {
  useThemeVersion()
  const reduced = useReducedMotion()
  const { curT, curSlot, curXhat, persona, activeEvents, userTurn, assistantTurn, feltState } = p
  const day = Math.floor(curT / 4) + 1
  const isWorkday = (Math.floor(curT / 4)) % 7 < 5

  const actionCards = useMemo(
    () => (assistantTurn?.tool_calls ?? []).filter((c) => !['open_session', 'close_session'].includes(c.name)),
    [assistantTurn],
  )

  const cellAnim = reduced
    ? {}
    : { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: SPRING }

  return (
    <PlainCard className="p-4 md:p-5">
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm font-semibold text-t1">同时刻全景</span>
        <span className="text-[10.5px] text-t3 font-num">
          第 {day} 天 · {SLOT_NAMES[curT % 4]} · {isWorkday ? '工作日' : '周末'} · t={curT}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto_1fr_auto_1fr] gap-3 items-stretch">
        {/* ① 系统（世界） */}
        <motion.div {...cellAnim} className="rounded-2xl border border-edge bg-surface p-4">
          <SectionTitle dot="var(--satiety)">系统 · 世界</SectionTitle>
          <div className="space-y-1.5 text-[11px] mb-3">
            <div className="flex justify-between items-center">
              <span className="text-t3">天气</span>
              <WeatherBadge weather={curSlot?.weather} />
            </div>
            <div className="flex justify-between"><span className="text-t3">系列事件</span>
              <span style={{ color: 'var(--series)' }}>{curSlot?.active_series ?? '无'}</span></div>
            <div className="flex justify-between"><span className="text-t3">余额</span>
              <span style={{ color: curSlot && curSlot.money_after < 0 ? 'var(--critical)' : 'var(--satiety)' }}>
                ¥<AnimatedNumber value={curSlot ? Math.round(curSlot.money_after) : 0} /></span></div>
          </div>
          {activeEvents.length > 0 && (
            <div className="mb-3 space-y-1">
              <div className="text-[10px] text-t3">进行中</div>
              {activeEvents.slice(0, 4).map((e) => (
                <div key={e.id} className="rounded-lg border border-edge px-2 py-1 text-[10.5px] flex items-center justify-between gap-1"
                  style={{ borderColor: `color-mix(in srgb, ${cssVar(KIND_META[e.kind].cssVar)} 40%, transparent)` }}>
                  <span className="text-t2 truncate">{e.name}</span>
                  <span className="shrink-0 font-num" style={{ color: cssVar(KIND_META[e.kind].cssVar) }}>{KIND_META[e.kind].label}</span>
                </div>
              ))}
            </div>
          )}
          <div className="text-[10px] text-t3 mb-1.5">本时段状态结算</div>
          {curSlot ? <EffectBars slot={curSlot} /> : <p className="text-[11px] text-t3">等待结算…</p>}
        </motion.div>

        <CausalArrow active={!!feltState} label="翻译感受" />

        {/* ② 用户 Agent */}
        <motion.div {...cellAnim} transition={reduced ? undefined : { ...SPRING, delay: 0.05 }}
          className="rounded-2xl border border-edge bg-surface p-4">
          <SectionTitle dot="var(--user)">用户 Agent · 真实状态 x</SectionTitle>
          {curSlot ? <StateBars x={curSlot.x_after} /> : <p className="text-[11px] text-t3">等待数据…</p>}
          {feltState && (
            <div className="mt-3 rounded-xl px-3 py-2 text-[11.5px] leading-relaxed"
              style={{ background: 'color-mix(in srgb, var(--user) 8%, transparent)', color: 'var(--text-2)' }}>
              <span className="text-[9.5px] text-t3 block mb-0.5">世界翻译给用户的感受</span>
              “{feltState}”
            </div>
          )}
          {userTurn && <div className="mt-3"><Bubble who="用户说" text={userTurn.text} color="var(--user)" /></div>}
          {persona && (
            <div className="mt-3 text-[10.5px] text-t3">
              {persona.name} · {persona.archetype} · ¥{persona.income_per_slot}/时段
            </div>
          )}
        </motion.div>

        <CausalArrow active={!!curXhat} label="观测估计" />

        {/* ③ 助手 Agent */}
        <motion.div {...cellAnim} transition={reduced ? undefined : { ...SPRING, delay: 0.1 }}
          className="rounded-2xl border border-edge bg-surface p-4">
          <SectionTitle dot="var(--assistant)">助手 Agent · 估计 x̂ 与偏差</SectionTitle>
          {curSlot && curXhat ? (
            <>
              <StateBars x={curSlot.x_after} xhat={curXhat} />
              <div className="mt-3 text-[10px] text-t3 mb-1.5">逐维估计误差 |x − x̂|</div>
              <EstErrBars x={curSlot.x_after} xhat={curXhat} />
            </>
          ) : <p className="text-[11px] text-t3">助手尚未产生估计</p>}
          {assistantTurn && <div className="mt-3"><Bubble who="助手回复" text={assistantTurn.text} color="var(--assistant)" /></div>}
          {actionCards.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {actionCards.map((c, i) => {
                const m = ACTION_META[c.name] ?? { icon: '⚡', label: c.name, cssVar: '--persona' }
                const arg = c.args?.name ?? c.args?.series_type ?? c.args?.message ?? ''
                return (
                  <span key={i} className="rounded-lg border px-2 py-0.5 text-[10.5px]"
                    style={{ borderColor: `color-mix(in srgb, ${cssVar(m.cssVar)} 40%, transparent)`, color: cssVar(m.cssVar) }}>
                    {m.icon} {m.label}{arg ? `：${String(arg).slice(0, 8)}` : ''}
                  </span>
                )
              })}
            </div>
          )}
        </motion.div>
      </div>
    </PlainCard>
  )
}
