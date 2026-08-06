import { CartesianGrid, Tooltip, XAxis, YAxis } from 'recharts'
import { cssVar, useThemeVersion } from './theme'

// 统一图表主题：网格/轴/tooltip 都读 CSS 变量，浅深自适应。
// useChartTheme 依赖 useThemeVersion → 主题切换后重新解析变量。

export function useChartTheme() {
  useThemeVersion() // 订阅主题变化，触发重算
  return {
    grid: cssVar('--grid'),
    axis: cssVar('--axis'),
    tick: cssVar('--text-3'),
    text: cssVar('--text-2'),
    surface: cssVar('--surface'),
    border: cssVar('--border'),
    color: (v: string) => cssVar(v),
  }
}

export function ChartGrid() {
  const t = useChartTheme()
  return <CartesianGrid stroke={t.grid} strokeOpacity={0.7} vertical={false} />
}

export function ThemedXAxis(props: any) {
  const t = useChartTheme()
  return <XAxis tick={{ fill: t.tick, fontSize: 10 }} stroke={t.axis} tickLine={false} {...props} />
}

export function ThemedYAxis(props: any) {
  const t = useChartTheme()
  return <YAxis tick={{ fill: t.tick, fontSize: 10 }} stroke={t.axis} tickLine={false} {...props} />
}

function TooltipRow({ color, name, value }: { color: string; name: string; value: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, lineHeight: 1.6 }}>
      <span style={{
        display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
        background: color, flexShrink: 0,
      }} />
      <span style={{ color: 'var(--text-2)', flex: 1 }}>{name}</span>
      <span style={{ color: 'var(--text-1)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

export function ThemedTooltipContent(props: any) {
  const { payload, label, labelFormatter, formatter } = props
  if (!payload || !payload.length) return null

  const displayLabel = labelFormatter ? labelFormatter(label, payload) : label

  return (
    <div style={{
      background: 'var(--toolbar-bg)',
      backdropFilter: 'blur(20px) saturate(180%)',
      border: '1px solid var(--border)',
      borderRadius: 12,
      boxShadow: 'var(--shadow-lg)',
      padding: '10px 12px',
      minWidth: 140,
    }}>
      {displayLabel != null && (
        <div style={{
          color: 'var(--text-1)', fontWeight: 600, fontSize: 12,
          marginBottom: payload.length > 1 ? 6 : 2,
        }}>
          {displayLabel}
        </div>
      )}
      {payload.map((entry: any, idx: number) => {
        const color = entry.color ?? entry.stroke ?? 'var(--text-3)'
        const name = entry.name ?? entry.dataKey ?? `series-${idx}`
        let value = entry.value
        if (formatter) {
          const formatted = formatter(value, name, entry, idx, payload)
          if (Array.isArray(formatted)) value = formatted[0]
          else if (typeof formatted === 'string') value = formatted
        }
        return <TooltipRow key={idx} color={color} name={name} value={String(value)} />
      })}
    </div>
  )
}

export function ThemedTooltip(props: any) {
  const t = useChartTheme()
  const { content, cursor, ...rest } = props
  return (
    <Tooltip
      content={content ?? ThemedTooltipContent}
      cursor={cursor ?? { stroke: t.color('--accent'), strokeWidth: 2, strokeOpacity: 0.55, strokeDasharray: '6 3' }}
      {...rest} />
  )
}
