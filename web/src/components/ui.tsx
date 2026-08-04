import { motion, useMotionValue, useSpring, useTransform, animate } from 'motion/react'
import { ReactNode, useEffect, useRef, useState } from 'react'
import { SPRING, useReducedMotion } from './theme'

// ============================================================
// Card — 白卡 + 细描边 + 上下文阴影；入场时材质化（blur+scale+opacity）
// ============================================================
export function Card({ children, className = '', hover = false, delay = 0 }: {
  children: ReactNode; className?: string; hover?: boolean; delay?: number
}) {
  const reduced = useReducedMotion()
  return (
    <motion.div
      initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.985, filter: 'blur(6px)' }}
      animate={reduced ? { opacity: 1 } : { opacity: 1, scale: 1, filter: 'blur(0px)' }}
      transition={{ ...SPRING, delay }}
      whileHover={hover && !reduced ? { y: -2, boxShadow: 'var(--shadow-lg)' } : undefined}
      className={`rounded-2xl border border-edge bg-surface shadow-card ${className}`}>
      {children}
    </motion.div>
  )
}

// 静态卡片（无入场动画；用于列表大量渲染避免抖动）
export function PlainCard({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-edge bg-surface shadow-card ${className}`}>{children}</div>
}

// ============================================================
// Badge — 状态徽章（颜色用 CSS 变量或直接色）
// ============================================================
export function Badge({ label, color, icon }: { label: string; color: string; icon?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium"
      style={{ color, background: `color-mix(in srgb, ${color} 12%, transparent)`, border: `1px solid color-mix(in srgb, ${color} 35%, transparent)` }}>
      {icon && <span>{icon}</span>}{label}
    </span>
  )
}

// ============================================================
// Button — 主/次/危险
// ============================================================
export function Button({ children, onClick, variant = 'primary', disabled, className = '', title }: {
  children: ReactNode; onClick?: () => void; variant?: 'primary' | 'ghost' | 'danger'
  disabled?: boolean; className?: string; title?: string
}) {
  const reduced = useReducedMotion()
  const base = 'rounded-xl px-4 py-2 text-[13px] font-semibold transition-colors disabled:opacity-40 disabled:pointer-events-none'
  const styles = {
    primary: 'bg-accent text-white hover:brightness-110',
    ghost: 'border border-edge text-t2 hover:bg-[var(--hover)]',
    danger: 'text-critical border hover:bg-[color-mix(in_srgb,var(--critical)_10%,transparent)]',
  }[variant]
  return (
    <motion.button title={title} onClick={onClick} disabled={disabled}
      whileTap={reduced ? undefined : { scale: 0.97 }}
      style={variant === 'danger' ? { borderColor: 'color-mix(in srgb, var(--critical) 40%, transparent)' } : undefined}
      className={`${base} ${styles} ${className}`}>
      {children}
    </motion.button>
  )
}

// ============================================================
// Segmented — 分段控件（Tab / 模式选择），选中态用弹簧滑块
// ============================================================
export function Segmented<T extends string>({ options, value, onChange, size = 'md' }: {
  options: readonly (readonly [T, string])[] | readonly T[]
  value: T; onChange: (v: T) => void; size?: 'sm' | 'md'
}) {
  const reduced = useReducedMotion()
  const opts = options.map((o) => (Array.isArray(o) ? o : [o, o]) as [T, string])
  const pad = size === 'sm' ? 'px-3 py-1 text-[12px]' : 'px-4 py-1.5 text-[13px]'
  return (
    <div className="inline-flex rounded-xl border border-edge bg-surface-2 p-0.5">
      {opts.map(([k, label]) => {
        const active = k === value
        return (
          <button key={k} onClick={() => onChange(k)}
            className={`relative rounded-[10px] ${pad} font-medium transition-colors ${active ? 'text-t1' : 'text-t3 hover:text-t2'}`}>
            {active && (
              <motion.span layoutId="seg-active" transition={reduced ? { duration: 0 } : SPRING}
                className="absolute inset-0 rounded-[10px] bg-surface shadow-card border border-edge" />
            )}
            <span className="relative z-10 whitespace-nowrap">{label}</span>
          </button>
        )
      })}
    </div>
  )
}

// ============================================================
// AnimatedNumber — 滚动计数（状态数值/余额/健康分）
// ============================================================
export function AnimatedNumber({ value, decimals = 0, prefix = '', suffix = '', className = '' }: {
  value: number; decimals?: number; prefix?: string; suffix?: string; className?: string
}) {
  const reduced = useReducedMotion()
  const [display, setDisplay] = useState(value)
  useEffect(() => {
    if (reduced) { setDisplay(value); return }
    const controls = animate(display, value, {
      duration: 0.5, ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setDisplay(v),
    })
    return () => controls.stop()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, reduced])
  return <span className={`font-num ${className}`}>{prefix}{display.toFixed(decimals)}{suffix}</span>
}

// ============================================================
// Stat — KPI 数字块
// ============================================================
export function Stat({ label, value, hint, color, decimals = 0, prefix = '', suffix = '' }: {
  label: string; value: number | string; hint?: string; color?: string
  decimals?: number; prefix?: string; suffix?: string
}) {
  return (
    <PlainCard className="p-4">
      <div className="text-[11px] text-t3">{label}</div>
      <div className="mt-1.5 text-2xl font-bold display" style={{ color: color ?? 'var(--text-1)' }}>
        {typeof value === 'number'
          ? <AnimatedNumber value={value} decimals={decimals} prefix={prefix} suffix={suffix} />
          : <span className="font-num">{value}</span>}
      </div>
      {hint && <div className="mt-1 text-[10.5px] text-t3 leading-snug">{hint}</div>}
    </PlainCard>
  )
}

// re-export motion 常用件，视图统一从这里取
export { motion, useMotionValue, useSpring, useTransform }
