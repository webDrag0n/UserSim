import { useMemo } from 'react'
import {
  ComposedChart, Line, ReferenceLine, ReferenceArea, ResponsiveContainer, Legend,
} from 'recharts'
import { SeriesInfo, Slot } from '../api'
import { DIMS, cssVar, useThemeVersion } from '../components/theme'
import { ChartGrid, ThemedXAxis, ThemedYAxis, ThemedTooltip } from '../components/charts'
import { seriesColor } from './gantt'

// 统一状态轨迹：四维曲线共一张图（左轴 0-1），金钱独立右轴；
// 与日程记录图共享同一时间游标（点击图表反向同步定位）。
export default function UnifiedTrajectory({ slots, series, curT, onSeek }: {
  slots: Slot[]
  series: SeriesInfo[]
  curT: number
  onSeek: (t: number) => void
}) {
  const data = useMemo(() => slots.map((s) => ({
    day: +(s.t_logical / 4).toFixed(2),
    valence: +s.x_after.valence.toFixed(3),
    energy: +s.x_after.energy.toFixed(3),
    satiety: +s.x_after.satiety.toFixed(3),
    stress: +s.x_after.stress.toFixed(3),
    money: Math.round(s.money_after),
  })), [slots])

  useThemeVersion()
  const cur = slots[curT] ?? null
  const curDay = +(curT / 4).toFixed(2)

  const disturbDays = useMemo(() => {
    const days = new Set<number>()
    slots.forEach((s) => {
      if (Object.values(s.event_effects).some((v) => Math.abs(v) > 0.005)) days.add(Math.floor(s.t_logical / 4))
    })
    return [...days]
  }, [slots])

  // 空数据防护：recharts 在空数组 + dataMax 域下会抛 Invariant
  if (!slots.length) {
    return (
      <div>
        <div className="text-sm font-semibold text-t1 mb-2">状态轨迹</div>
        <p className="text-sm text-t3 py-10 text-center">等待第一个时段结算…</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold text-t1">状态轨迹</span>
        <span className="text-[10px] text-t3 font-num">左轴 0~1 · 金钱右轴 · 点击图表同步定位 · 虚线 = 事件效果日</span>
      </div>
      <div className="h-[240px]">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 2, left: -16 }}
            onClick={(st: any) => {
              const x = st?.activeLabel
              if (x !== undefined && x !== null) {
                onSeek(Math.max(0, Math.min(slots.length - 1, Math.round(Number(x) * 4))))
              }
            }}>
            <ChartGrid />
            <ThemedXAxis dataKey="day" type="number" domain={[0, 'dataMax']} tickFormatter={(x: number) => `${Math.floor(x)}`} />
            <ThemedYAxis yAxisId="left" domain={[0, 1]} />
            <ThemedYAxis yAxisId="right" orientation="right" tick={{ fill: cssVar('--satiety'), fontSize: 10 }}
              tickFormatter={(x: number) => `¥${x}`} />
            <Legend wrapperStyle={{ fontSize: 11, color: cssVar('--text-2') }} />
            {series.map((s, i) => (
              <ReferenceArea key={s.id} x1={s.start_day} x2={s.end_day} yAxisId="left"
                fill={seriesColor(s, i)} fillOpacity={0.08} />
            ))}
            {disturbDays.map((d, i) => (
              <ReferenceLine key={i} x={d} yAxisId="left" stroke="var(--critical)" strokeOpacity={0.25} strokeDasharray="3 4" />
            ))}
            <ReferenceLine x={curDay} yAxisId="left" stroke={cssVar('--accent')} strokeWidth={1.5} />
            {DIMS.map((d) => (
              <Line key={d.key} yAxisId="left" type="monotone" dataKey={d.key} name={d.label}
                stroke={cssVar(d.cssVar)} strokeWidth={1.8} dot={false} />
            ))}
            <Line yAxisId="right" type="monotone" dataKey="money" name="金钱（右轴）"
              stroke={cssVar('--satiety')} strokeWidth={1.5} strokeDasharray="5 3" dot={false} />
            <ThemedTooltip labelFormatter={(x: number) => `第 ${Math.floor(Number(x)) + 1} 天`} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {cur && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 mt-2 text-[11px]">
          <span className="text-t3 font-num">t={curT} · 第 {Math.floor(curT / 4) + 1} 天{['上午', '下午', '晚上', '深夜'][curT % 4]}</span>
          {DIMS.map((d) => (
            <span key={d.key} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: cssVar(d.cssVar) }} />
              <span className="text-t2">{d.label}</span>
              <span className="font-num text-t1">{cur.x_after[d.key].toFixed(3)}</span>
              <span className="text-t3 font-num">/ {d.target}</span>
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: cssVar('--satiety') }} />
            <span className="text-t2">金钱</span>
            <span className="font-num" style={{ color: cssVar('--satiety') }}>¥{Math.round(cur.money_after)}</span>
          </span>
        </div>
      )}
    </div>
  )
}
