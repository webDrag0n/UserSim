import { CartesianGrid, Tooltip, XAxis, YAxis } from 'recharts'
import { cssVar, useReducedMotion, useThemeVersion } from './theme'

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

// 统一曲线动画（apple-design §4：ease-out 快速起步、平缓收尾，无过冲；
// 尊重系统「减弱动态效果」辅助设置）
export function useChartAnimation() {
  const reduced = useReducedMotion()
  return {
    isAnimationActive: !reduced,
    animationDuration: 700,
    animationEasing: 'ease-out' as const,
  }
}

export function ChartGrid() {
  const t = useChartTheme()
  // Apple 风格：网格只做衬托，hairline 淡线、不要喧宾夺主
  return <CartesianGrid stroke={t.grid} strokeOpacity={0.55} vertical={false} />
}
// recharts 通过 child.type.displayName 识别子组件，
// 包装组件必须声明与原生组件相同的 displayName，否则会被静默丢弃不渲染。
ChartGrid.displayName = 'CartesianGrid'

export function ThemedXAxis(props: any) {
  return <XAxis {...props} />
}
ThemedXAxis.displayName = 'XAxis'
// recharts 从 element.type.defaultProps 读取 axisId 建 axisMap（键缺省为 0），
// 缺了它 Line/Bar 的默认 xAxisId=0 匹配不到轴，渲染时抛 Invariant。
// 轴的最终样式同样取自元素 props（经 axisMap 传给 CartesianAxis），
// 所以主题默认值必须放 defaultProps；颜色用 CSS 变量引用，浅深主题切换自动跟随。
// Apple 风格：轴线细到近乎隐形（hairline），刻度文字静音、与轴线留白充足。
ThemedXAxis.defaultProps = {
  ...XAxis.defaultProps,
  stroke: 'var(--axis)',
  strokeWidth: 1,
  tickLine: false,
  tickMargin: 8,
  tick: { fill: 'var(--text-3)', fontSize: 10 },
}

export function ThemedYAxis(props: any) {
  return <YAxis {...props} />
}
ThemedYAxis.displayName = 'YAxis'
ThemedYAxis.defaultProps = {
  ...YAxis.defaultProps,
  stroke: 'var(--axis)',
  strokeWidth: 1,
  tickLine: false,
  tickMargin: 6,
  tick: { fill: 'var(--text-3)', fontSize: 10 },
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
        } else if (typeof value === 'number') {
          value = +value.toFixed(4) // 缺省数值保留 4 位小数，避免长浮点刷屏
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
ThemedTooltip.displayName = 'Tooltip'
