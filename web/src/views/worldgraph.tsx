import { useMemo } from 'react'
import { RunEvent, SeriesInfo, Slot } from '../api'
import { cssVar, useThemeVersion, useReducedMotion } from '../components/theme'
import { PlainCard as Card } from '../components/ui'

// 知识图谱世界状态：实体-关系随时间动态演化
// 节点：用户/助手/地点/系列/事件；边：位置在/进行/位于/经历/观测

interface Props {
  events: RunEvent[]
  series: SeriesInfo[]
  slots: Slot[]
  curT: number
  personaName?: string
}

const CX = 310, CY = 200, R = 155

function locationAt(curT: number, slots: Slot[], activeEvents: RunEvent[], activeSeriesName: string | null): string {
  if (activeSeriesName) {
    if (activeSeriesName.includes('旅行')) return '旅途中'
    if (activeSeriesName.includes('出差')) return '出差城市'
    return '家'
  }
  const nonTpl = activeEvents.filter((e) => e.kind !== 'template')
  if (nonTpl.length) return nonTpl[0].location
  const slot = curT % 4
  const workday = Math.floor(curT / 4) % 7 < 5
  if (slot === 3) return '家'
  if (workday && slot <= 1) return '公司'
  return '家'
}

export default function WorldGraph({ events, series, slots, curT, personaName }: Props) {
  useThemeVersion()
  const reduced = useReducedMotion()
  const curSlot = slots[curT] ?? null
  const activeSeriesName = curSlot?.active_series ?? null
  const activeEvents = useMemo(
    () => events.filter((e) => e.start_slot <= curT && curT < e.start_slot + e.span_slots),
    [events, curT],
  )

  // 地点节点集合：家/公司/旅途中 + 事件高频地点
  const locations = useMemo(() => {
    const freq = new Map<string, number>()
    events.forEach((e) => {
      if (e.kind !== 'template' && e.location) freq.set(e.location, (freq.get(e.location) ?? 0) + 1)
    })
    const top = [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([n]) => n)
    return ['家', '公司', '旅途中', ...top.filter((n) => !['家', '公司', '旅途中'].includes(n))]
  }, [events])

  const userLoc = locationAt(curT, slots, activeEvents, activeSeriesName)

  // 布局：用户中心；助手左；地点右侧半圆；系列上方；事件下方
  const locPos = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>()
    locations.forEach((n, i) => {
      const a = (-70 + (140 * i) / Math.max(1, locations.length - 1)) * (Math.PI / 180)
      m.set(n, { x: CX + Math.cos(a) * R * 1.15, y: CY - Math.sin(a) * R })
    })
    return m
  }, [locations])

  const seriesPos = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>()
    series.forEach((s, i) => {
      const a = (-160 + (60 * i) / Math.max(1, series.length - 1 || 1) + (series.length === 1 ? 30 : 0)) * (Math.PI / 180)
      m.set(s.id, { x: CX + Math.cos(a) * R * 0.9, y: CY + Math.sin(a) * R * 0.9 })
    })
    return m
  }, [series])

  const eventPos = useMemo(() => {
    const evs = activeEvents.slice(0, 4)
    return evs.map((e, i) => ({ e, x: CX - 60 + i * 45, y: CY + 120 }))
  }, [activeEvents])

  const assistantPos = { x: 70, y: CY }

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold text-t1">世界状态知识图谱 · t={curT}</span>
        <div className="flex gap-3 text-[10px] text-t3">
          <span>━━ 位置在（当前）</span>
          <span className="text-[var(--series)]">━━ 经历系列</span>
          <span className="text-t3">┅ 位于/观测</span>
        </div>
      </div>
      <svg viewBox="0 0 620 420" className="w-full">
        <defs>
          <style>{`
            .flow { stroke-dasharray: 6 4; animation: dashmove 1.2s linear infinite; }
            @keyframes dashmove { to { stroke-dashoffset: -20; } }
            .edge { transition: opacity .5s, stroke .5s; }
            .node { transition: all .5s; }
          `}</style>
        </defs>

        {/* 助手 —观测→ 用户（常驻虚线） */}
        <line x1={assistantPos.x + 30} y1={assistantPos.y} x2={CX - 34} y2={CY}
          stroke={cssVar('--text-3')} strokeWidth={1.2} strokeDasharray="4 4" className="edge" opacity={0.6} />
        <text x={(assistantPos.x + CX) / 2 - 10} y={CY - 8} fill={cssVar('--text-3')} fontSize={9}>观测/辅助</text>

        {/* 用户 —位置在→ 各地点（当前高亮，其余淡） */}
        {locations.map((n) => {
          const p = locPos.get(n)!
          const active = n === userLoc
          return (
            <g key={n}>
              <line x1={CX} y1={CY} x2={p.x} y2={p.y}
                stroke={active ? cssVar('--accent') : cssVar('--axis')} strokeWidth={active ? 2.5 : 1}
                className={`edge ${active && !reduced ? 'flow' : ''}`} opacity={active ? 1 : 0.35} />
              {active && (
                <text x={(CX + p.x) / 2} y={(CY + p.y) / 2 - 6} fill={cssVar('--accent')} fontSize={10} textAnchor="middle">位置在</text>
              )}
            </g>
          )
        })}

        {/* 用户 —经历→ 活跃系列 */}
        {series.filter((s) => s.start_day * 4 <= curT && curT < s.end_day * 4).map((s) => {
          const p = seriesPos.get(s.id)!
          return (
            <g key={s.id}>
              <line x1={CX} y1={CY} x2={p.x} y2={p.y} stroke={cssVar('--series')} strokeWidth={2}
                className={`edge ${reduced ? '' : 'flow'}`} opacity={0.9} />
              <text x={(CX + p.x) / 2} y={(CY + p.y) / 2 - 6} fill={cssVar('--series')} fontSize={9} textAnchor="middle">经历中</text>
            </g>
          )
        })}

        {/* 活跃事件：用户—进行→事件，事件—位于→地点 */}
        {eventPos.map(({ e, x, y }) => {
          const lp = locPos.get(e.location) ?? (e.location === userLoc ? locPos.get(userLoc)! : null)
          return (
            <g key={e.id}>
              <line x1={CX} y1={CY} x2={x} y2={y} stroke={cssVar('--persona')} strokeWidth={1.5} className="edge" opacity={0.8} />
              {lp && <line x1={x} y1={y} x2={lp.x} y2={lp.y} stroke={cssVar('--axis')} strokeWidth={1} strokeDasharray="3 3" className="edge" opacity={0.5} />}
              <circle cx={x} cy={y} r={7} fill={`color-mix(in srgb, ${cssVar('--persona')} 20%, transparent)`} stroke={cssVar('--persona')} className="node" />
              <text x={x} y={y + 18} fill={cssVar('--persona')} fontSize={8.5} textAnchor="middle">{e.name.slice(0, 6)}</text>
            </g>
          )
        })}

        {/* 地点节点 */}
        {locations.map((n) => {
          const p = locPos.get(n)!
          const active = n === userLoc
          return (
            <g key={n} className="node">
              <circle cx={p.x} cy={p.y} r={active ? 16 : 11}
                fill={active ? `color-mix(in srgb, ${cssVar('--accent')} 15%, transparent)` : 'var(--hover)'}
                stroke={active ? cssVar('--accent') : cssVar('--axis')} strokeWidth={active ? 2 : 1} className="node" />
              <text x={p.x} y={p.y + 3.5} fill={active ? cssVar('--accent') : cssVar('--text-3')} fontSize={active ? 11 : 9.5}
                textAnchor="middle" fontWeight={active ? 700 : 400}>{n}</text>
            </g>
          )
        })}

        {/* 系列节点 */}
        {series.map((s) => {
          const p = seriesPos.get(s.id)!
          const activeS = s.start_day * 4 <= curT && curT < s.end_day * 4
          return (
            <g key={s.id} className="node">
              <rect x={p.x - 26} y={p.y - 13} width={52} height={26} rx={8}
                fill={activeS ? `color-mix(in srgb, ${cssVar('--series')} 15%, transparent)` : 'var(--hover)'}
                stroke={activeS ? cssVar('--series') : cssVar('--axis')} strokeWidth={activeS ? 1.5 : 1} className="node" />
              <text x={p.x} y={p.y + 3.5} fill={activeS ? cssVar('--series') : cssVar('--text-3')} fontSize={9} textAnchor="middle">
                {s.icon}{s.name}
              </text>
            </g>
          )
        })}

        {/* 助手节点 */}
        <g className="node">
          <circle cx={assistantPos.x} cy={assistantPos.y} r={22} fill={`color-mix(in srgb, ${cssVar('--good')} 10%, transparent)`} stroke={cssVar('--good')} strokeWidth={1.5} />
          <text x={assistantPos.x} y={assistantPos.y - 2} fill={cssVar('--good')} fontSize={10} textAnchor="middle">助手</text>
          <text x={assistantPos.x} y={assistantPos.y + 11} fill={cssVar('--good')} fontSize={7.5} textAnchor="middle">Harness</text>
        </g>

        {/* 用户节点 */}
        <g className="node">
          <circle cx={CX} cy={CY} r={28} fill={`color-mix(in srgb, ${cssVar('--accent')} 12%, transparent)`} stroke={cssVar('--accent')} strokeWidth={2} />
          <text x={CX} y={CY - 2} fill={cssVar('--text-1')} fontSize={11.5} textAnchor="middle" fontWeight={700}>
            {personaName ?? '用户'}
          </text>
          <text x={CX} y={CY + 12} fill={cssVar('--accent')} fontSize={8.5} textAnchor="middle">{userLoc}</text>
        </g>
      </svg>
      <p className="text-[10.5px] text-t3 mt-1">
        随回放/实时推进动态演化：「位置在」边随用户移动在地点节点间切换（如 家→旅途中），系列激活时出现粉色「经历中」边。
      </p>
    </Card>
  )
}
