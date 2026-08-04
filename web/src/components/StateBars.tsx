import { DIMS, BAND, useReducedMotion, cssVar, useThemeVersion } from './theme'
import { StateVec } from '../api'
import { motion } from 'motion/react'

// Apple 风双游标条：真值填充（弹簧宽度过渡）+ 估计白游标 + 目标刻度线。
export function StateBars({ x, xhat }: { x: StateVec; xhat?: StateVec | null }) {
  useThemeVersion()
  const reduced = useReducedMotion()
  return (
    <div className="space-y-3">
      {DIMS.map((d) => {
        const v = x[d.key]
        const ve = xhat?.[d.key]
        const color = cssVar(d.cssVar)
        const bad = d.good === 'high' ? d.target - v > BAND : v - d.target > BAND
        return (
          <div key={d.key}>
            <div className="flex justify-between text-[11px] mb-1">
              <span className="text-t2">{d.label}<span className="text-t3 ml-1 font-num">目标 {d.target}</span></span>
              <span className="font-num" style={{ color: bad ? 'var(--critical)' : color }}>
                {v.toFixed(2)}
                {ve !== undefined && ve !== null && <span className="text-t3"> / 估 {ve.toFixed(2)}</span>}
              </span>
            </div>
            <div className="relative h-2 rounded-full bg-[var(--hover)] overflow-hidden">
              <motion.div className="absolute inset-y-0 left-0 rounded-full"
                style={{ background: color, opacity: 0.9 }}
                initial={false}
                animate={{ width: `${v * 100}%` }}
                transition={reduced ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.5 }} />
              <div className="absolute inset-y-0 w-px bg-[var(--text-2)] opacity-50" style={{ left: `${d.target * 100}%` }} />
              {ve !== undefined && ve !== null && (
                <motion.div className="absolute top-1/2 h-3.5 w-[3px] rounded-full bg-[var(--text-1)] shadow-sm"
                  style={{ y: '-50%' }}
                  initial={false}
                  animate={{ left: `calc(${ve * 100}% - 1.5px)` }}
                  transition={reduced ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.5 }} />
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// 兼容旧 import：Card/Badge 现由 ui.tsx 提供
export { Card, Badge } from './ui'
