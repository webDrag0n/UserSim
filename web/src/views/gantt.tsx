import { useMemo, useRef, useState, useEffect } from 'react'
import { KIND_META, RunEvent, SeriesInfo, SLOT_NAMES } from '../api'

export interface SessionInfo { id: string; t: number; nTurns: number }

const CELL = 26 // 每时段像素宽
const LABEL_W = 150

const SERIES_COLORS: Record<string, string> = {
  grand_trip: '#f472b6',
  business_trip: '#38bdf8',
  staycation: '#34d399',
  exam_crunch: '#fbbf24',
}
const SERIES_PALETTE = ['#f472b6', '#38bdf8', '#34d399', '#fbbf24', '#a78bfa']
export const seriesColor = (s: SeriesInfo, i: number) => SERIES_COLORS[s.type] ?? SERIES_PALETTE[i % SERIES_PALETTE.length]

interface GanttProps {
  events: RunEvent[]
  series: SeriesInfo[]
  sessions: SessionInfo[]
  days: number
  curT: number
  onSeek: (t: number) => void
  onSelectSession: (id: string) => void
  selectedSession: string | null
}

interface Row {
  key: string
  label: string
  color: string
  bars: { start: number; span: number; label?: string }[]
  sessions: SessionInfo[]
}

export default function ScheduleGantt({ events, series, sessions, days, curT, onSeek, onSelectSession, selectedSession }: GanttProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState({ left: 0, top: 0, width: 1, height: 1 })
  const totalSlots = days * 4
  const width = LABEL_W + totalSlots * CELL

  // minimap 视口同步（横纵双向）
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const sync = () => setViewport({ left: el.scrollLeft, top: el.scrollTop, width: el.clientWidth, height: el.clientHeight })
    sync()
    el.addEventListener('scroll', sync)
    window.addEventListener('resize', sync)
    return () => { el.removeEventListener('scroll', sync); window.removeEventListener('resize', sync) }
  }, [])

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = []
    const usedSessions = new Set<string>()
    const takeSessions = (bars: { start: number; span: number }[]) =>
      sessions.filter((s) => {
        if (usedSessions.has(s.id)) return false
        if (bars.some((b) => s.t >= b.start && s.t < b.start + b.span)) {
          usedSessions.add(s.id)
          return true
        }
        return false
      })

    // 逻辑事件归组键：系列内外统一（系列餐/宿/工作与普通餐/宿/工作同行）
    const groupKey = (e: RunEvent): string => {
      const n = e.name.replace(/^(上午|下午|晚间|晚上)/, '')
      if (n.includes('工作')) return '工作'
      if (n.includes('特色')) return '异地特色餐'
      if (/^(早餐|午餐|晚餐)$/.test(n) || n.includes('早餐') || n.endsWith('餐') || n.endsWith('餐食') || n.startsWith('家常') || n.startsWith('备考')) return '三餐'
      if (n.includes('睡眠') || n.includes('懒觉')) return '睡眠'
      if (n.includes('交通')) return '交通'
      return n
    }

    // 同一逻辑事件的连续发生（如 上午+下午）合并为一个条
    const mergeBars = (evs: RunEvent[]) => {
      const sorted = [...evs].sort((a, b) => a.start_slot - b.start_slot)
      const bars: { start: number; span: number }[] = []
      for (const e of sorted) {
        const last = bars[bars.length - 1]
        const eEnd = e.start_slot + e.span_slots
        if (last && e.start_slot <= last.start + last.span) {
          last.span = Math.max(last.start + last.span, eEnd) - last.start
        } else {
          bars.push({ start: e.start_slot, span: e.span_slots })
        }
      }
      return bars
    }

    // 全事件统一归组（模板 + 独立 + 系列子事件）
    const groups = new Map<string, RunEvent[]>()
    for (const e of events) {
      const k = groupKey(e)
      const arr = groups.get(k) ?? []
      arr.push(e)
      groups.set(k, arr)
    }
    const sortedGroups = [...groups.entries()].sort((a, b) =>
      Math.min(...a[1].map((e) => e.start_slot)) - Math.min(...b[1].map((e) => e.start_slot)))

    for (const [k, evs] of sortedGroups) {
      const bars = mergeBars(evs)
      const color = KIND_META[evs[0].kind]?.color ?? '#71717a'
      out.push({ key: `g-${k}`, label: k, color, bars, sessions: takeSessions(bars) })
    }
    // 未归属 session 行
    const free = sessions.filter((s) => !usedSessions.has(s.id))
    if (free.length) {
      out.push({ key: 'free-sessions', label: '自由会话', color: '#a78bfa', bars: [], sessions: free })
    }
    return out
  }, [events, sessions])

  const cursorX = LABEL_W + curT * CELL + CELL / 2

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-zinc-200">日程记录图</span>
        <div className="flex gap-3 text-[10px] text-zinc-500 flex-wrap">
          {series.map((s, si) => (
            <span key={s.id} className="flex items-center gap-1">
              <span className="h-2 w-3 rounded-sm" style={{ background: `${seriesColor(s, si)}66` }} />
              {s.icon}{s.name}
            </span>
          ))}
          <span className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-red-400/70" /> 扰动</span>
          <span className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-emerald-400/70" /> 恢复</span>
          <span className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-violet-400" style={{ borderRadius: '50%', width: 10, height: 10 }} /> Session（点击看对话）</span>
          <span className="text-zinc-600">点击空白处跳转回放</span>
        </div>
      </div>
      <div ref={scrollRef} className="overflow-x-auto pb-2" style={{ maxHeight: 340, overflowY: 'auto' }}>
        <div className="relative" style={{ width, minWidth: width }}>
          {/* 天表头 */}
          <div className="flex sticky top-0 z-20 bg-[#0d0e14]">
            <div className="shrink-0" style={{ width: LABEL_W }} />
            {Array.from({ length: days }, (_, d) => (
              <div key={d} className="shrink-0 text-center text-[10px] font-semibold text-zinc-400 border-l border-white/10 py-1"
                style={{ width: CELL * 4 }}>
                d{d + 1}
              </div>
            ))}
          </div>
          {/* 时段表头 */}
          <div className="flex sticky top-[22px] z-20 bg-[#0d0e14]">
            <div className="shrink-0" style={{ width: LABEL_W }} />
            {Array.from({ length: totalSlots }, (_, i) => (
              <div key={i} className="shrink-0 text-center text-[8.5px] text-zinc-600 py-0.5" style={{ width: CELL }}>
                {SLOT_NAMES[i % 4][0]}
            </div>
            ))}
          </div>
          {/* 系列背景色带（每类系列不同颜色，半透明） */}
          {series.map((s, si) => {
            const c = seriesColor(s, si)
            const start = s.start_day * 4
            const span = (s.end_day - s.start_day) * 4
            return (
              <div key={s.id} className="absolute pointer-events-none z-0"
                style={{
                  left: LABEL_W + start * CELL, top: 48, width: span * CELL, bottom: 0,
                  background: `${c}0f`, borderLeft: `2px solid ${c}66`, borderRight: `1px solid ${c}33`,
                }}>
                <span className="sticky top-12 inline-block text-[9px] font-medium px-1.5 py-0.5 rounded-br-md"
                  style={{ color: c, background: `${c}1f` }}>
                  {s.icon}{s.name}
                </span>
              </div>
            )
          })}
          {/* 行 */}
          {rows.map((row) => (
            <div key={row.key} className="flex items-center border-t border-white/5 hover:bg-white/[0.02]"
              style={{ height: 26 }}
              onClick={(e) => {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                const x = (e as unknown as MouseEvent).clientX - rect.left - LABEL_W
                if (x >= 0) onSeek(Math.min(totalSlots - 1, Math.max(0, Math.floor(x / CELL))))
              }}>
              <div className="shrink-0 px-2 text-[10px] text-zinc-400 truncate sticky left-0 bg-[#0c0d12] z-10"
                style={{ width: LABEL_W }}>
                {row.label}
              </div>
              <div className="relative flex-1 h-full">
                {row.bars.map((b, i) => (
                  <div key={i}
                    className="absolute top-1/2 -translate-y-1/2 rounded-sm"
                    style={{
                      left: b.start * CELL, width: Math.max(4, b.span * CELL - 2), height: 14,
                      background: `${row.color}55`, border: `1px solid ${row.color}88`,
                    }}
                    title={b.label} />
                ))}
                {row.sessions.map((s) => (
                  <button key={s.id}
                    onClick={(e) => { e.stopPropagation(); onSelectSession(s.id) }}
                    className={`absolute top-1/2 -translate-y-1/2 rounded-full transition-all ${
                      selectedSession === s.id ? 'ring-2 ring-violet-300 scale-125' : 'hover:scale-125'}`}
                    style={{
                      left: s.t * CELL + CELL / 2 - 5, width: 10, height: 10,
                      background: '#a78bfa',
                    }}
                    title={`${s.id} · ${s.nTurns} turns · 点击查看对话`} />
                ))}
              </div>
            </div>
          ))}
          {/* 当前时间游标 */}
          <div className="absolute top-0 bottom-0 w-px bg-cyan-400/80 z-10 pointer-events-none" style={{ left: cursorX }}>
            <div className="absolute -top-0 -translate-x-1/2 h-2 w-2 rounded-full bg-cyan-400" />
          </div>
        </div>
      </div>

      {/* minimap 2D 缩略导航 */}
      <div className="mt-3">
        <div className="text-[10px] text-zinc-600 mb-1 font-num">全局缩略（2D）· 点击/拖动跳转横纵位置</div>
        {(() => {
          const contentH = 48 + rows.length * 26
          const miniRowH = Math.min(3.5, 140 / Math.max(1, rows.length))
          const miniH = Math.max(28, Math.ceil(rows.length * miniRowH))
          const seek = (clientX: number, clientY: number, el: HTMLElement) => {
            const rect = el.getBoundingClientRect()
            const rx = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
            const ry = Math.min(1, Math.max(0, (clientY - rect.top) / rect.height))
            if (scrollRef.current) {
              scrollRef.current.scrollLeft = rx * (width - scrollRef.current.clientWidth)
              scrollRef.current.scrollTop = ry * (contentH - scrollRef.current.clientHeight)
            }
          }
          return (
            <div className="relative select-none cursor-crosshair rounded border border-white/10 overflow-hidden"
              style={{ height: miniH, background: 'rgba(255,255,255,0.02)' }}
              onClick={(e) => seek(e.clientX, e.clientY, e.currentTarget)}
              onMouseMove={(e) => { if (e.buttons === 1) seek(e.clientX, e.clientY, e.currentTarget) }}>
              {/* 系列背景色带 */}
              {series.map((s, si) => {
                const c = seriesColor(s, si)
                return (
                  <div key={s.id} className="absolute top-0 bottom-0 pointer-events-none"
                    style={{
                      left: `${(s.start_day / days) * 100}%`,
                      width: `${((s.end_day - s.start_day) / days) * 100}%`,
                      background: `${c}1f`, borderLeft: `1px solid ${c}66`,
                    }} />
                )
              })}
              {/* 每行的事件横条（起点-终点） */}
              {rows.map((row, ri) => (
                <div key={row.key} className="absolute left-0 right-0" style={{ top: ri * miniRowH, height: miniRowH }}>
                  {row.bars.map((b, i) => (
                    <div key={i} className="absolute rounded-[1px]"
                      style={{
                        left: `${(b.start / totalSlots) * 100}%`,
                        width: `${Math.max(0.4, (b.span / totalSlots) * 100)}%`,
                        top: miniRowH * 0.2, height: Math.max(1, miniRowH * 0.6),
                        background: row.color,
                      }} />
                  ))}
                  {row.sessions.map((s) => (
                    <div key={s.id} className="absolute rounded-full bg-violet-400"
                      style={{
                        left: `${(s.t / totalSlots) * 100}%`,
                        top: miniRowH * 0.2, width: Math.max(1.5, miniRowH * 0.6), height: Math.max(1.5, miniRowH * 0.6),
                      }} />
                  ))}
                </div>
              ))}
              {/* 当前时间线 */}
              <div className="absolute top-0 bottom-0 w-px bg-cyan-300" style={{ left: `${(curT / totalSlots) * 100}%` }} />
              {/* 2D 视口矩形 */}
              <div className="absolute rounded border border-cyan-300/70 bg-cyan-300/10 pointer-events-none"
                style={{
                  left: `${(viewport.left / width) * 100}%`,
                  top: `${(viewport.top / contentH) * 100}%`,
                  width: `${(viewport.width / width) * 100}%`,
                  height: `${(viewport.height / contentH) * 100}%`,
                }} />
            </div>
          )
        })()}
      </div>
    </div>
  )
}
