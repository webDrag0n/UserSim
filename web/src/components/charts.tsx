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
  return <YAxis tick={{ fill: t.tick, fontSize: 10 }} stroke={t.axis} tickLine={false} axisLine={false} {...props} />
}

export function ThemedTooltip(props: any) {
  const t = useChartTheme()
  return (
    <Tooltip
      contentStyle={{
        background: 'var(--toolbar-bg)', backdropFilter: 'blur(20px) saturate(180%)',
        border: `1px solid ${t.border}`, borderRadius: 12, fontSize: 12,
        boxShadow: 'var(--shadow-lg)', color: t.text,
      }}
      labelStyle={{ color: 'var(--text-1)', fontWeight: 600 }}
      cursor={{ stroke: t.axis, strokeWidth: 1 }}
      {...props} />
  )
}
