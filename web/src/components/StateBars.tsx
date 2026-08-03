import { DIMS, BAND, StateVec } from '../api'

export function StateBars({ x, xhat }: { x: StateVec; xhat?: StateVec | null }) {
  return (
    <div className="space-y-2.5">
      {DIMS.map((d) => {
        const v = x[d.key]
        const ve = xhat?.[d.key]
        const bad = d.good === 'high' ? d.target - v > BAND : v - d.target > BAND
        return (
          <div key={d.key}>
            <div className="flex justify-between text-[11px] mb-1">
              <span className="text-zinc-400">{d.label}<span className="text-zinc-600 ml-1 font-num">目标 {d.target}</span></span>
              <span className={`font-num ${bad ? 'text-red-400' : ''}`} style={bad ? {} : { color: d.color }}>
                {v.toFixed(2)}{ve !== undefined && ve !== null && <span className="text-zinc-500"> / 估 {ve.toFixed(2)}</span>}
              </span>
            </div>
            <div className="relative h-2 rounded-full bg-white/5 overflow-hidden">
              <div className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                style={{ width: `${v * 100}%`, background: d.color, opacity: 0.85 }} />
              <div className="absolute inset-y-0 w-px bg-white/50" style={{ left: `${d.target * 100}%` }} />
              {ve !== undefined && ve !== null && (
                <div className="absolute top-1/2 -translate-y-1/2 h-3 w-[3px] rounded-full bg-white transition-all duration-500"
                  style={{ left: `calc(${ve * 100}% - 1px)` }} />
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium"
      style={{ color, background: `${color}1a`, border: `1px solid ${color}40` }}>
      {label}
    </span>
  )
}

export function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-white/10 bg-white/[0.03] ${className}`}>{children}</div>
}
