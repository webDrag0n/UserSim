import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BalanceConfig, BalanceFiles, RecoveryAction, Disturbance, MealTier, SleepTier,
  CustomActivity, Profession, TemplateEvent, HabituationEntry, NeedsEntry, PersonaModEntry,
  EffectDict, EffectDim, EFFECT_DIMS, WeatherConfig, Venue,
  api,
} from '../api'
import { PlainCard as Card, Badge } from '../components/ui'
import { cssVar } from '../components/theme'

// ── 配表编辑器：单页滚动 + 左侧悬浮目录，JSON 配置直接编辑，自动保存热加载 ──

const FILE_LABELS: Record<string, string> = {
  events:             '事件配置',
  venues:             '地点表',
  weather:            '天气系统',
  professions:        '职业收入',
  economy:            '经济参数',
  dynamics:           '动力学参数',
  needs:              '需求参数',
  persona_modulation: '人格调节',
  template_events:    '模板事件',
}

const FILE_ORDER = Object.keys(FILE_LABELS)

const RESETABLE = new Set([
  'events', 'venues', 'professions', 'economy', 'habituation',
])

const DIM_LABEL: Record<EffectDim, string> = {
  valence: '心情', energy: '精力', satiety: '饱腹', stress: '压力',
}

function normalizeEffect(d: Partial<EffectDict> | undefined): EffectDict {
  const out: any = {}
  for (const dim of EFFECT_DIMS) {
    const v = d?.[dim]
    if (v && typeof v === 'object' && 'pull' in v) {
      out[dim] = { pull: [Number(v.pull[0]), Number(v.pull[1])] }
    } else {
      const n = Number(v ?? 0)
      out[dim] = Number.isFinite(n) ? n : 0
    }
  }
  return out as EffectDict
}

function formatEffectValue(v: EffectDict[EffectDim]): string {
  if (v && typeof v === 'object' && 'pull' in v) return `→${v.pull[0]}(×${v.pull[1]})`
  const n = Number(v ?? 0)
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`
}

function isPullValue(v: EffectDict[EffectDim]): v is { pull: [number, number] } {
  return !!v && typeof v === 'object' && 'pull' in v
}

function addEffects(a: EffectDict, b: EffectDict): EffectDict {
  const out: any = {}
  for (const dim of EFFECT_DIMS) {
    const av = a[dim], bv = b[dim]
    if (isPullValue(av) || isPullValue(bv)) {
      out[dim] = isPullValue(av) ? av : bv
    } else {
      out[dim] = Number(av ?? 0) + Number(bv ?? 0)
    }
  }
  return out as EffectDict
}

// ── 内联可编辑单元格 ──────────────────────────────────────────────────────────
function Cell({ value, onSave, numeric, mono }: { value: any; onSave: (v: string) => void; numeric?: boolean; mono?: boolean }) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState(String(value ?? ''))
  const [err, setErr] = useState(false)

  const validate = (raw: string) => {
    if (!numeric) return true
    if (raw === '' || raw === '-') return true
    return !isNaN(Number(raw))
  }

  if (!editing) return (
    <span
      onClick={() => { setV(String(value ?? '')); setErr(false); setEditing(true) }}
      className={`cursor-text rounded px-0.5 -mx-0.5 hover:bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] hover:text-[var(--accent)] transition-colors ${mono ? 'font-mono text-[10px]' : ''}`}
      title="点击编辑">
      {value === null || value === '' ? '—' : String(value)}
    </span>
  )

  return (
    <input
      autoFocus value={v}
      onChange={e => { setV(e.target.value); setErr(!validate(e.target.value)) }}
      onBlur={() => {
        if (numeric && !validate(v)) return
        setEditing(false)
        if (v !== String(value ?? '')) onSave(v)
      }}
      onKeyDown={e => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        if (e.key === 'Escape') setEditing(false)
      }}
      className={`w-full min-w-[48px] rounded bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] border ${
        err ? 'border-[var(--critical)]' : 'border-[color-mix(in_srgb,var(--accent)_50%,transparent)]'
      } px-1 text-inherit outline-none ${numeric ? 'font-num' : ''} ${mono ? 'font-mono text-[10px]' : ''}`}
    />
  )
}

// ── 下拉选择单元格（必须从可选项中选择）─────────────────────────────────────────
function SelectCell({ value, options, onSave, mono }: { value: string; options: string[]; onSave: (v: string) => void; mono?: boolean }) {
  const [open, setOpen] = useState(false)

  if (open) return (
    <select
      autoFocus
      value={value}
      onChange={e => { onSave(e.target.value); setOpen(false) }}
      onBlur={() => setOpen(false)}
      className={`w-full min-w-[80px] rounded bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] border border-[color-mix(in_srgb,var(--accent)_50%,transparent)] px-1 text-inherit outline-none text-[11px] ${mono ? 'font-mono' : ''}`}
    >
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  )

  return (
    <span
      onClick={() => setOpen(true)}
      className={`cursor-pointer rounded px-1 -mx-0.5 border border-transparent hover:border-[color-mix(in_srgb,var(--accent)_50%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] transition-colors ${mono ? 'font-mono text-[10px]' : ''}`}
      title="点击选择"
    >
      {value || '—'}
    </span>
  )
}

// ── 统一效果值表格（1 行 × 4 维，缺失显示 0，支持 pull 模式）───────────────────
function EffectGrid({ effect, onChange, readOnly }: { effect: EffectDict; onChange?: (dim: EffectDim, v: EffectDict[EffectDim]) => void; readOnly?: boolean }) {
  return (
    <div className={`grid grid-cols-4 gap-1 text-[10.5px] ${readOnly ? 'opacity-80' : ''}`}>
      {EFFECT_DIMS.map(dim => {
        const v = effect[dim]
        const isPull = isPullValue(v)
        return (
          <div
            key={dim}
            onContextMenu={e => {
              if (readOnly || !onChange) return
              e.preventDefault()
              onChange(dim, isPull ? 0 : { pull: [0.5, 0.1] })
            }}
            className="group relative rounded border border-edge bg-surface-2 px-1 py-0.5"
            title={readOnly ? `${DIM_LABEL[dim]}: ${formatEffectValue(v)}` : `右键切换 pull 模式`}
          >
            <div className="text-[9px] text-t3 leading-none mb-0.5">{DIM_LABEL[dim]}</div>
            {isPull ? (
              <div className="flex items-center gap-0.5">
                <span className="text-t3 text-[9px]">→</span>
                <Cell
                  value={v.pull[0]}
                  numeric
                  mono
                  onSave={raw => onChange?.(dim, { pull: [Number(raw), v.pull[1]] })}
                />
                <span className="text-t3 text-[9px]">×</span>
                <Cell
                  value={v.pull[1]}
                  numeric
                  mono
                  onSave={raw => onChange?.(dim, { pull: [v.pull[0], Number(raw)] })}
                />
              </div>
            ) : (
              <Cell
                value={Number(v ?? 0)}
                numeric
                mono
                onSave={raw => onChange?.(dim, Number(raw))}
              />
            )}
            {!readOnly && (
              <span className="absolute -top-1 -right-1 hidden group-hover:flex h-3 w-3 items-center justify-center rounded-full bg-accent text-[7px] text-white cursor-pointer"
                onClick={e => {
                  e.stopPropagation()
                  onChange?.(dim, isPull ? 0 : { pull: [0.5, 0.1] })
                }}
              >
                {isPull ? 'N' : 'P'}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── 习惯化曲线预览 ────────────────────────────────────────────────────────────
function habW(dt: number, wMin: number, tau: number, curve: string): number {
  dt = Math.max(0, dt)
  if (tau <= 0) return 1
  let c: number
  if (curve === 'sqrt') c = Math.pow(tau / (dt + tau), 0.5)
  else if (curve === 's') c = (tau * tau) / (tau * tau + dt * dt)
  else c = Math.exp(-dt / tau)
  return 1 - (1 - wMin) * c
}

function CurvePreview({ wMin, tau, curve }: { wMin: number; tau: number; curve: string }) {
  const W = 100, H = 28
  const maxT = Math.max(4, tau * 3)
  const pts = Array.from({ length: 41 }, (_, i) => {
    const dt = (i / 40) * maxT
    return `${((i / 40) * W).toFixed(1)},${(H - habW(dt, wMin, tau, curve) * H).toFixed(1)}`
  }).join(' ')
  return (
    <svg width={W} height={H} className="inline-block align-middle">
      <line x1="0" y1={H - wMin * H} x2={W} y2={H - wMin * H} stroke="var(--axis)" strokeDasharray="3 3" />
      <polyline points={pts} fill="none" stroke={cssVar('--accent')} strokeWidth="1.5" />
    </svg>
  )
}

// ── 实时公式预览（防抖调后端求值）────────────────────────────────────────────
function FormulaPreview({ formula, varName = 'x', color = 'var(--accent)', width = 200, height = 120 }: { formula: string; varName?: string; color?: string; width?: number; height?: number }) {
  const [points, setPoints] = useState<{ x: number; y: number }[] | null>(null)
  const [error, setError] = useState('')
  const [hover, setHover] = useState<{ x: number; y: number; px: number; py: number } | null>(null)

  useEffect(() => {
    if (!formula.trim()) { setPoints(null); setError(''); return }
    let cancelled = false
    const timer = setTimeout(() => {
      api.evalFormula(formula, varName, 60).then(res => {
        if (cancelled) return
        if (res.ok && res.points) { setPoints(res.points); setError('') }
        else { setPoints(null); setError(res.error ?? '未知错误') }
      }).catch(e => { if (!cancelled) { setPoints(null); setError(e.message) } })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [formula, varName])

  const W = width, H = height
  if (error) return <span className="text-[10px] text-[var(--critical)]">✗ {error}</span>
  if (!points) return <svg width={W} height={H} className="border border-edge rounded bg-surface" />

  const yMin = Math.min(...points.map(p => p.y))
  const yMax = Math.max(...points.map(p => p.y))
  const yRange = yMax - yMin || 1
  const pts = points.map(p =>
    `${(p.x * W).toFixed(1)},${(H - ((p.y - yMin) / yRange) * H).toFixed(1)}`
  ).join(' ')

  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = Math.max(0, Math.min(W, e.clientX - rect.left))
    const xRatio = px / W
    const nearest = points.reduce((best, p) => Math.abs(p.x - xRatio) < Math.abs(best.x - xRatio) ? p : best, points[0])
    const py = H - ((nearest.y - yMin) / yRange) * H
    setHover({ x: nearest.x, y: nearest.y, px, py })
  }

  return (
    <span className="inline-flex items-start gap-2">
      <svg
        width={W} height={H}
        className="border border-edge rounded bg-surface cursor-crosshair"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75].map(v => (
          <g key={v}>
            <line x1="0" y1={H - v * H} x2={W} y2={H - v * H} stroke="var(--edge)" strokeDasharray="3 3" opacity={0.5} />
            <line x1={v * W} y1="0" x2={v * W} y2={H} stroke="var(--edge)" strokeDasharray="3 3" opacity={0.5} />
          </g>
        ))}
        <line x1="0" y1={H} x2={W} y2={H} stroke="var(--text-3)" strokeWidth={1} />
        <line x1="0" y1="0" x2="0" y2={H} stroke="var(--text-3)" strokeWidth={1} />
        <polyline points={pts} fill="none" stroke={color} strokeWidth={2} />
        {hover && <circle cx={hover.px} cy={hover.py} r="4" fill={color} />}
      </svg>
      <span className="text-[10px] text-t3 font-num leading-tight pt-1">
        <div>min {yMin.toFixed(2)}</div>
        <div>max {yMax.toFixed(2)}</div>
        {hover && <div className="text-t2 mt-1">{varName}={hover.x.toFixed(2)}<br/>→ {hover.y.toFixed(3)}</div>}
      </span>
    </span>
  )
}

// ── 映射公式编辑器（输入 + 实时曲线 + 验证状态）────────────────────────────────
function FormulaEditor({ value, varName = 'x', onSave, label }: { value: string; varName?: string; onSave: (v: string) => void; label?: string }) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState(value)
  const [valid, setValid] = useState(true)

  useEffect(() => {
    if (!editing) setV(value)
  }, [value, editing])

  useEffect(() => {
    if (!editing || !v.trim()) { setValid(true); return }
    let cancelled = false
    const timer = setTimeout(() => {
      api.evalFormula(v, varName, 5).then(res => {
        if (!cancelled) setValid(res.ok)
      }).catch(() => { if (!cancelled) setValid(false) })
    }, 200)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [v, editing, varName])

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        {label && <span className="text-[10px] text-t3 whitespace-nowrap">{label}</span>}
        {!editing ? (
          <span
            onClick={() => setEditing(true)}
            className={`cursor-text font-mono text-[11px] rounded px-1.5 py-0.5 border transition-colors ${valid ? 'border-edge hover:border-accent hover:bg-[color-mix(in_srgb,var(--accent)_8%,transparent)]' : 'border-[var(--critical)]'}`}
          >
            {value || '—'}
          </span>
        ) : (
          <input
            autoFocus
            value={v}
            onChange={e => setV(e.target.value)}
            onBlur={() => {
              setEditing(false)
              if (v !== value) onSave(v)
            }}
            onKeyDown={e => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
              if (e.key === 'Escape') setEditing(false)
            }}
            className={`flex-1 min-w-[160px] font-mono text-[11px] rounded bg-[color-mix(in_srgb,var(--accent)_8%,transparent)] border px-1.5 py-0.5 outline-none ${valid ? 'border-[color-mix(in_srgb,var(--accent)_50%,transparent)]' : 'border-[var(--critical)]'}`}
          />
        )}
        <span className={`text-[10px] ${valid ? 'text-[var(--good)]' : 'text-[var(--critical)]'}`}>
          {valid ? '✓' : '✗'}
        </span>
      </div>
      <FormulaPreview formula={editing ? v : value} varName={varName} />
    </div>
  )
}

// ── 各配置编辑器（紧凑表格版）─────────────────────────────────────────────────

function Th({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <th className={`text-left text-t3 text-[10px] font-medium border-b border-edge px-1.5 py-1 whitespace-nowrap ${className}`}>{children}</th>
}
function Td({ children, className = '', rowSpan, colSpan }: { children: React.ReactNode; className?: string; rowSpan?: number; colSpan?: number }) {
  return <td rowSpan={rowSpan} colSpan={colSpan} className={`px-1.5 py-1 align-top ${className}`}>{children}</td>
}

type EventRow = {
  kind: 'recovery' | 'meal' | 'sleep' | 'custom' | 'disturbance'
  id: string
  name: string
  category?: string
  location?: string
  tier?: string
  span?: number
  cost?: number
  income?: number
  effect?: EffectDict
  intent?: string
  habitKey: string | null
  source: { file: 'recovery_actions' | 'disturbances' | 'meal_tiers' | 'sleep_tiers' | 'custom_activities'; path: (number | string)[] }
}

function buildEventRows(files: BalanceFiles): EventRow[] {
  const rows: EventRow[] = []

  // 恢复动作只剩定义：价格/效果由地点表（venues）逐项覆盖
  for (const action of (files.recovery_actions || []) as RecoveryAction[]) {
    rows.push({
      kind: 'recovery',
      id: action.id,
      name: action.action,
      category: action.category,
      span: action.default_span,
      intent: action.design_intent,
      habitKey: action.action,
      source: { file: 'recovery_actions', path: [action.id] },
    })
  }

  for (const t of (files.meal_tiers || []) as MealTier[]) {
    rows.push({
      kind: 'meal',
      id: t.vid,
      name: t.name,
      tier: t.tier,
      cost: t.cost,
      income: 0,
      effect: normalizeEffect(t.effect),
      habitKey: '三餐',
      source: { file: 'meal_tiers', path: [t.vid] },
    })
  }

  for (const t of (files.sleep_tiers || []) as SleepTier[]) {
    rows.push({
      kind: 'sleep',
      id: t.vid,
      name: t.name,
      tier: t.tier,
      cost: t.cost,
      income: 0,
      effect: normalizeEffect(t.effect),
      habitKey: '睡眠',
      source: { file: 'sleep_tiers', path: [t.vid] },
    })
  }

  for (const c of (files.custom_activities || []) as CustomActivity[]) {
    rows.push({
      kind: 'custom',
      id: c.id,
      name: c.name,
      cost: c.cost,
      income: 0,
      effect: normalizeEffect(c.effect),
      habitKey: '自定义活动',
      source: { file: 'custom_activities', path: [c.id] },
    })
  }

  for (const d of (files.disturbances || []) as Disturbance[]) {
    rows.push({
      kind: 'disturbance',
      id: d.id,
      name: d.name,
      location: d.location,
      cost: d.cost,
      income: d.income,
      effect: normalizeEffect(d.effect),
      habitKey: null,
      source: { file: 'disturbances', path: [d.id] },
    })
  }

  return rows
}

function collectLocations(files: BalanceFiles): string[] {
  const locs = new Set<string>()
  for (const v of (files.venues || []) as Venue[]) {
    if (v.name) locs.add(v.name)
  }
  for (const d of (files.disturbances || []) as Disturbance[]) {
    if (d.location) locs.add(d.location)
  }
  for (const t of (files.template_events || []) as TemplateEvent[]) {
    if (t.location) locs.add(t.location)
  }
  return Array.from(locs).sort()
}

const CURVE_OPTIONS = ['exp', 'sqrt', 's']
const SLOT_OPTIONS = ['上午', '下午', '晚上', '深夜']

function EventsEditor({
  files,
  onChange,
}: {
  files: Pick<BalanceFiles, 'recovery_actions' | 'disturbances' | 'meal_tiers' | 'sleep_tiers' | 'custom_activities' | 'habituation' | 'template_events' | 'venues'>
  onChange: (changed: Partial<BalanceFiles>) => void
}) {
  const [localFiles, setLocalFiles] = useState(files)
  useEffect(() => setLocalFiles(files), [files])

  const locations = collectLocations(localFiles)
  const habit = localFiles.habituation || {}

  const updateHabit = (key: string, field: keyof HabituationEntry, raw: string) => {
    const next = JSON.parse(JSON.stringify(localFiles)) as typeof localFiles
    if (!next.habituation) next.habituation = {}
    if (!next.habituation![key]) next.habituation![key] = { w_min: 0.4, tau: 8, curve: 'exp' }
    ;(next.habituation![key] as any)[field] = field === 'curve' ? raw : Number(raw)
    setLocalFiles(next)
    onChange({ habituation: next.habituation })
  }

  const updateEffect = (row: EventRow, dim: EffectDim, val: EffectDict[EffectDim]) => {
    const next = JSON.parse(JSON.stringify(localFiles)) as typeof localFiles
    const f = (next as any)[row.source.file]
    if (!f) return
    const item = f.find((x: any) => x.id === row.id || x.vid === row.id)
    if (item) item.effect[dim] = val as any
    setLocalFiles(next)
    onChange({ [row.source.file]: f })
  }

  const updateField = (row: EventRow, field: string, raw: string) => {
    const next = JSON.parse(JSON.stringify(localFiles)) as typeof localFiles
    const f = (next as any)[row.source.file]
    if (!f) return
    const item = f.find((x: any) => x.id === row.id || x.vid === row.id)
    if (!item) return
    if (field === 'span' && row.source.file === 'recovery_actions') {
      item.default_span = Number(raw)
    } else if (field === 'cost' || field === 'income' || field === 'span') {
      item[field] = Number(raw)
    } else if (field === 'intent') {
      item.design_intent = raw
    } else {
      item[field] = raw
    }
    setLocalFiles(next)
    onChange({ [row.source.file]: f })
  }

  const rows = buildEventRows(localFiles)
  const disturbanceIndex = rows.findIndex(r => r.kind === 'disturbance')

  return (
    <Card className="p-3 overflow-x-auto">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed space-y-1">
        <p><strong className="text-t1">事件配置表</strong>：统一管理所有对世界状态产生直接效果的事件。恢复动作（A1–A6）只保留定义（类别/默认时长/设计意图），价格与四维效果由「地点表」逐项覆盖；进餐/睡眠档位、自定义活动、扰动事件在此直接编辑。</p>
        <ul className="list-disc pl-4 space-y-0.5 text-[10.5px]">
          <li><span className="text-t3">合计效果</span>：心情/精力/饱腹/压力四个维度；0 表示无影响，右键单元格可切换 pull 模式（拉向准稳态）。恢复动作行此列改为编辑设计意图。</li>
          <li><span className="text-t3">边际效益曲线</span>：描述同一事件重复发生时效果递减/恢复的规律。w_min=最低权重，τ=恢复所需时段数，curve=曲线类型（exp 指数、sqrt 前快后慢、s 型）。</li>
          <li><span className="text-t3">扰动事件</span>：以红色分隔线区分，代表外部强加事件，不参与习惯化。</li>
        </ul>
      </div>
      <table className="text-[11px] border-collapse w-full">
        <thead>
          <tr>
            <Th>类别</Th>
            <Th>ID</Th>
            <Th>名称</Th>
            <Th>地点/档位</Th>
            <Th>时长</Th>
            <Th>¥</Th>
            <Th>收入¥</Th>
            <Th className="min-w-[220px]">合计效果 / 设计意图</Th>
            <Th className="min-w-[220px]">边际效益曲线（习惯化）</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <>
              {i === disturbanceIndex && (
                <tr key="divider" className="bg-[color-mix(in_srgb,var(--critical)_6%,transparent)]">
                  <Td colSpan={9} className="py-1 text-center text-[10px] text-[var(--critical)] font-medium">
                    — 扰动事件（不参与习惯化，与恢复/日常事件区分）—
                  </Td>
                </tr>
              )}
              <tr key={`${row.kind}-${row.id}`} className={`border-b border-edge hover:bg-[var(--hover)] ${row.kind === 'disturbance' ? 'bg-[color-mix(in_srgb,var(--critical)_3%,transparent)]' : ''}`}>
                <Td className="text-t2 whitespace-nowrap">
                  {row.kind === 'recovery' && row.category}
                  {row.kind === 'meal' && '进餐'}
                  {row.kind === 'sleep' && '睡眠'}
                  {row.kind === 'custom' && '自定义'}
                  {row.kind === 'disturbance' && '扰动'}
                </Td>
                <Td className="text-t3 font-num whitespace-nowrap">{row.id}</Td>
                <Td className="text-t1 font-medium whitespace-nowrap">{row.name}</Td>
                <Td>{
                  row.location !== undefined ? (
                    <SelectCell value={row.location} options={locations} onSave={v => updateField(row, 'location', v)} />
                  ) : row.tier ? (
                    <Cell value={row.tier} onSave={v => updateField(row, 'tier', v)} />
                  ) : (
                    '—'
                  )
                }
                </Td>
                <Td className="text-t3 font-num">{
                  row.span !== undefined
                    ? <Cell value={row.span} numeric onSave={v => updateField(row, 'span', v)} />
                    : '—'
                }</Td>
                <Td>{row.cost !== undefined ? <Cell value={row.cost} numeric onSave={v => updateField(row, 'cost', v)} /> : '—'}</Td>
                <Td>{row.income !== undefined ? <Cell value={row.income} numeric onSave={v => updateField(row, 'income', v)} /> : '—'}</Td>
                <Td>{
                  row.effect
                    ? <EffectGrid effect={row.effect} onChange={(dim, val) => updateEffect(row, dim, val)} />
                    : <span className="text-t2 text-[10.5px]"><Cell value={row.intent ?? ''} onSave={v => updateField(row, 'intent', v)} /></span>
                }</Td>
                <Td>
                  {(() => {
                    const key = row.habitKey
                    if (!key || !habit[key]) return <span className="text-t3 text-[10px]">—</span>
                    return (
                      <div className="flex items-center gap-2">
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1">
                            <span className="text-[9px] text-t3">w_min</span>
                            <Cell value={habit[key].w_min} numeric mono onSave={v => updateHabit(key, 'w_min', v)} />
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="text-[9px] text-t3">τ</span>
                            <Cell value={habit[key].tau} numeric mono onSave={v => updateHabit(key, 'tau', v)} />
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="text-[9px] text-t3">曲线</span>
                            <SelectCell value={habit[key].curve} options={CURVE_OPTIONS} onSave={v => updateHabit(key, 'curve', v)} />
                          </div>
                        </div>
                        <CurvePreview wMin={habit[key].w_min} tau={habit[key].tau} curve={habit[key].curve} />
                      </div>
                    )
                  })()}
                </Td>
              </tr>
            </>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

// ── 统一地点表：每个地点一行，supports 子行逐项覆盖事件价格/效果 ──────────────────
function VenuesEditor({ data, eventOptions, onChange }: { data: Venue[]; eventOptions: string[]; onChange: (v: Venue[]) => void }) {
  const mutate = (fn: (next: Venue[]) => void) => {
    const next = JSON.parse(JSON.stringify(data)) as Venue[]
    fn(next); onChange(next)
  }
  const newSupport = (): Venue['supports'][number] => ({
    event: eventOptions[0] ?? 'A1', cost: 0, span: 1,
    effect: { valence: 0, energy: 0, satiety: 0, stress: 0 },
  })
  const addVenue = () => mutate(n => {
    const maxId = n.reduce((m, v) => {
      const num = parseInt(v.id.replace(/^V/i, ''), 10)
      return Number.isFinite(num) ? Math.max(m, num) : m
    }, 0)
    n.push({
      id: `V${String(maxId + 1).padStart(3, '0')}`,
      name: '新地点', category: '', cuisine: '', aliases: [],
      supports: [newSupport()], design_intent: '',
    })
  })

  return (
    <Card className="p-3 overflow-x-auto">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed space-y-1">
        <p><strong className="text-t1">统一地点表</strong>：每个地点一行（跨子行合并），supports 子行逐项声明该地点可承载的事件及其价格、时长与四维效果——地点逐项覆盖事件定义（事件本身只剩 A1–A6 / C1–C6 的类别与设计意图）。</p>
        <ul className="list-disc pl-4 space-y-0.5 text-[10.5px]">
          <li><span className="text-t3">事件</span>：下拉选择（A1–A6 恢复动作、C1–C6 自定义活动）；标签可选，用于同一事件在同一地点的多种玩法（如「家」的补觉/看片/下厨）。</li>
          <li><span className="text-t3">效果</span>：心情/精力/饱腹/压力四维；0 表示无影响，右键单元格切换 pull 模式（拉向准稳态）。</li>
          <li><span className="text-t3">代餐</span>：勾选后该地点的进餐可替代三餐结算。</li>
          <li><span className="text-t3">别名</span>：顿号/逗号分隔，供对话文本匹配到该地点。</li>
        </ul>
      </div>
      <table className="text-[11px] border-collapse w-full">
        <thead>
          <tr>
            <Th>ID</Th>
            <Th>名称</Th>
            <Th>类别</Th>
            <Th>菜系</Th>
            <Th>别名</Th>
            <Th>代餐</Th>
            <Th>事件</Th>
            <Th>标签</Th>
            <Th>¥</Th>
            <Th>时长</Th>
            <Th className="min-w-[220px]">效果</Th>
            <Th>设计意图</Th>
            <Th>{''}</Th>
          </tr>
        </thead>
        <tbody>
          {data.map((v, vi) => {
            const supports = v.supports.length > 0 ? v.supports : [null]
            return supports.map((s, si) => (
              <tr key={`${v.id}-${si}`} className={`border-b border-edge hover:bg-[var(--hover)] ${si === 0 ? 'border-t-2 border-t-[var(--edge)]' : ''}`}>
                {si === 0 && (
                  <>
                    <Td rowSpan={supports.length} className="text-t3 font-num whitespace-nowrap">
                      <div>{v.id}</div>
                      <div className="flex flex-col gap-0.5 mt-1">
                        <button
                          onClick={() => mutate(n => { n[vi].supports.push(newSupport()) })}
                          className="text-[9.5px] text-t3 hover:text-[var(--accent)] text-left"
                        >＋子项</button>
                        <button
                          onClick={() => { if (confirm(`确定删除地点「${v.name}」及其全部支持条目？`)) mutate(n => { n.splice(vi, 1) }) }}
                          className="text-[9.5px] text-t3 hover:text-[var(--critical)] text-left"
                        >删地点</button>
                      </div>
                    </Td>
                    <Td rowSpan={supports.length} className="text-t1 font-medium whitespace-nowrap">
                      <Cell value={v.name} onSave={raw => mutate(n => { n[vi].name = raw })} />
                    </Td>
                    <Td rowSpan={supports.length}><Cell value={v.category} onSave={raw => mutate(n => { n[vi].category = raw })} /></Td>
                    <Td rowSpan={supports.length}><Cell value={v.cuisine} onSave={raw => mutate(n => { n[vi].cuisine = raw })} /></Td>
                    <Td rowSpan={supports.length} className="text-t2 max-w-[160px]">
                      <Cell
                        value={v.aliases.join('、')}
                        onSave={raw => mutate(n => { n[vi].aliases = raw.split(/[,，、;；]+/).map(x => x.trim()).filter(Boolean) })}
                      />
                    </Td>
                    <Td rowSpan={supports.length} className="text-center">
                      <input
                        type="checkbox"
                        checked={!!v.replaces_meal}
                        onChange={e => mutate(n => { if (e.target.checked) n[vi].replaces_meal = true; else delete n[vi].replaces_meal })}
                        className="accent-[var(--accent)] scale-90 cursor-pointer"
                        title="进餐可替代三餐结算"
                      />
                    </Td>
                  </>
                )}
                {s ? (
                  <>
                    <Td><SelectCell value={s.event} options={eventOptions} onSave={raw => mutate(n => { n[vi].supports[si].event = raw })} mono /></Td>
                    <Td className="text-t2 whitespace-nowrap"><Cell value={s.label ?? ''} onSave={raw => mutate(n => { if (raw) n[vi].supports[si].label = raw; else delete n[vi].supports[si].label })} /></Td>
                    <Td><Cell value={s.cost} numeric onSave={raw => mutate(n => { n[vi].supports[si].cost = Number(raw) })} /></Td>
                    <Td><Cell value={s.span} numeric onSave={raw => mutate(n => { n[vi].supports[si].span = Number(raw) })} /></Td>
                    <Td>
                      <EffectGrid
                        effect={normalizeEffect(s.effect)}
                        onChange={(dim, val) => mutate(n => {
                          const eff = n[vi].supports[si].effect as any
                          eff[dim] = val
                        })}
                      />
                    </Td>
                  </>
                ) : (
                  <Td colSpan={5} className="text-t3 text-[10px]">无支持条目——点 ID 列「＋子项」添加</Td>
                )}
                {si === 0 && (
                  <Td rowSpan={supports.length} className="text-t3 max-w-[220px]">
                    <Cell value={v.design_intent} onSave={raw => mutate(n => { n[vi].design_intent = raw })} />
                  </Td>
                )}
                <Td>
                  {s && (
                    <button
                      onClick={() => mutate(n => { n[vi].supports.splice(si, 1) })}
                      className="text-t3 hover:text-[var(--critical)] px-0.5"
                      title="删除该支持条目"
                    >×</button>
                  )}
                </Td>
              </tr>
            ))
          })}
        </tbody>
      </table>
      <button
        onClick={addVenue}
        className="mt-2 text-[11px] px-2 py-1 rounded-md border border-edge text-t2 hover:border-accent hover:text-[var(--accent)] transition-colors"
      >＋ 新增地点</button>
    </Card>
  )
}

function ProfessionEditor({ data, onChange }: { data: Profession[]; onChange: (v: Profession[]) => void }) {
  const mutate = (fn: (next: Profession[]) => void) => {
    const next = JSON.parse(JSON.stringify(data)) as Profession[]
    fn(next); onChange(next)
  }
  return (
    <Card className="p-3 overflow-x-auto">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed">
        <strong className="text-t1">职业收入表</strong>：定义不同职业每工作时段的收入。
        日收入按每天 2 个工作时段估算。职业会影响用户初始金钱与日常消费的紧张程度。
      </div>
      <table className="text-[11px] border-collapse w-full">
        <thead><tr><Th>职业</Th><Th>收入¥/时段</Th><Th>日收入¥</Th><Th>备注</Th></tr></thead>
        <tbody>
          {data.map((p, i) => (
            <tr key={p.archetype} className="border-b border-edge hover:bg-[var(--hover)]">
              <Td><Cell value={p.archetype} onSave={v => mutate(n => { n[i].archetype = v })} /></Td>
              <Td><Cell value={p.income_per_slot} numeric onSave={v => mutate(n => { n[i].income_per_slot = Number(v) })} /></Td>
              <Td className="text-t3 font-num">{p.income_per_slot * 2}</Td>
              <Td className="text-t3 max-w-[260px] truncate"><Cell value={p.note} onSave={v => mutate(n => { n[i].note = v })} /></Td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

const PARAM_LABELS: Record<string, string> = {
  initial_money: '初始金钱',
  overtime_income: '加班收入',
  debt_stress_per_slot: '负债压力/时段',
  satiety_drain_per_slot: '饱腹消耗/时段',
  work_stress_per_slot: '工作压力增速/时段',
  work_energy_drain: '工作精力消耗/时段',
  rest_stress_relief: '休息降压/时段',
  rebound_threshold: '反弹阈值',
  rebound_multiplier: '反弹倍率',
  valence_coupling_rate: '心情耦合速率',
  stress_mean_reversion: '压力均值回归速率',
  stress_reversion_target: '压力回归目标',
}

function KVEditor({ data, onChange, title, description }: { data: Record<string, number>; onChange: (v: Record<string, number>) => void; title: string; description: string }) {
  return (
    <Card className="p-3">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed">
        <strong className="text-t1">{title}</strong>：{description}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-0.5">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-2 py-1 border-b border-edge text-[11px]">
            <span className="text-t2">{PARAM_LABELS[k] ?? k}</span>
            <span className="font-num text-t1"><Cell value={v} numeric onSave={raw => onChange({ ...data, [k]: Number(raw) })} /></span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function NeedsEditor({ data, onChange }: { data: Record<string, NeedsEntry>; onChange: (v: Record<string, NeedsEntry>) => void }) {
  const update = (name: string, field: keyof NeedsEntry, raw: string) => {
    const next = JSON.parse(JSON.stringify(data)) as typeof data
    next[name][field] = raw
    onChange(next)
  }
  return (
    <Card className="p-3 overflow-x-auto">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed space-y-1">
        <p><strong className="text-t1">需求参数表</strong>：定义四种内在需求如何驱动用户行为以及如何被事件满足。</p>
        <ul className="list-disc pl-4 space-y-0.5 text-[10.5px]">
          <li><span className="text-t3">累积规则</span>：需求在未满足时如何随时间增长。</li>
          <li><span className="text-t3">满足事件</span>：哪些事件可以释放该需求。</li>
          <li><span className="text-t3">驱动力 u(x)</span>：x 为需求缺失度（0–1），输出 u 决定用户多想去寻求满足。</li>
          <li><span className="text-t3">满足 s(x/u)</span>：事件对需求的实际满足倍率；饥饿/社交/成就使用 u（当前驱动力），刺激使用 x（当前刺激水平）。</li>
        </ul>
      </div>
      <table className="text-[11px] border-collapse w-full">
        <thead><tr><Th>需求</Th><Th>累积规则</Th><Th>满足事件</Th><Th>驱动力 u(x)</Th><Th>满足 s(x)</Th></tr></thead>
        <tbody>
          {Object.entries(data).map(([name, row]) => (
            <tr key={name} className="border-b border-edge hover:bg-[var(--hover)]">
              <Td className="text-t1 font-medium whitespace-nowrap">{name}</Td>
              <Td className="max-w-[160px] text-t2"><Cell value={row.accumulate} onSave={v => update(name, 'accumulate', v)} /></Td>
              <Td className="max-w-[120px] text-t2"><Cell value={row.satisfy_events} onSave={v => update(name, 'satisfy_events', v)} /></Td>
              <Td className="min-w-[200px]"><FormulaEditor value={row.urge_curve} varName="x" label="u(x)=" onSave={v => update(name, 'urge_curve', v)} /></Td>
              <Td className="min-w-[200px]"><FormulaEditor value={row.satisfy_curve} varName={name === '刺激' ? 'x' : 'u'} label={name === '刺激' ? 's(x)=' : 's(u)='} onSave={v => update(name, 'satisfy_curve', v)} /></Td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-t3 mt-2">
        公式语法：x / u, + - * / **, sqrt/abs/min/max。编辑后 300ms 内实时渲染曲线；保存后新 run 立即生效（无效公式自动回退代码默认）。
      </p>
    </Card>
  )
}

const PERSONA_VAR: Record<string, string> = {
  '外向性': 'E',
  '神经质': 'N',
  '开放性': 'O',
  '尽责性': 'C',
  '宜人性': 'A',
}

function PersonaModEditor({ data, onChange }: { data: Record<string, PersonaModEntry>; onChange: (v: Record<string, PersonaModEntry>) => void }) {
  const update = (name: string, field: keyof PersonaModEntry, raw: string) => {
    const next = JSON.parse(JSON.stringify(data)) as typeof data
    next[name][field] = raw
    onChange(next)
  }
  return (
    <Card className="p-3 overflow-x-auto">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed space-y-1">
        <p><strong className="text-t1">人格调节表（大五人格）</strong>：按大五人格五个维度调节事件效果。
          每个公式返回一个效果倍率，变量为对应人格维度归一化到 0–1 后的值。
          公式非法时自动回退代码默认值。</p>
        <ul className="list-disc pl-4 space-y-0.5 text-[10.5px]">
          <li><span className="text-t3">外向性 E</span>：社交事件精力消耗/恢复倍率。</li>
          <li><span className="text-t3">神经质 N</span>：正向压力事件放大倍率。</li>
          <li><span className="text-t3">开放性 O</span>：新异/文化类事件收益倍率。</li>
          <li><span className="text-t3">尽责性 C</span>：工作/成就类负面压力缓冲倍率。</li>
          <li><span className="text-t3">宜人性 A</span>：社交事件正面心情加成倍率。</li>
        </ul>
      </div>
      <table className="text-[11px] border-collapse w-full">
        <thead><tr><Th>维度</Th><Th>映射公式</Th><Th>设计意图</Th></tr></thead>
        <tbody>
          {Object.entries(data).map(([name, row]) => (
            <tr key={name} className="border-b border-edge hover:bg-[var(--hover)]">
              <Td className="text-t1 font-medium whitespace-nowrap">{name}</Td>
              <Td className="min-w-[280px]">
                <FormulaEditor
                  value={row.formula || row.rule || ''}
                  varName={PERSONA_VAR[name] || 'x'}
                  onSave={v => update(name, 'formula', v)}
                />
              </Td>
              <Td className="text-t3 max-w-[220px]"><Cell value={row.intent} onSave={v => update(name, 'intent', v)} /></Td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

function TemplateEditor({ data, onChange, locations }: { data: TemplateEvent[]; onChange: (v: TemplateEvent[]) => void; locations: string[] }) {
  const mutate = (fn: (next: TemplateEvent[]) => void) => {
    const next = JSON.parse(JSON.stringify(data)) as TemplateEvent[]
    fn(next); onChange(next)
  }
  return (
    <Card className="p-3 overflow-x-auto">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed space-y-1">
        <p><strong className="text-t1">模板事件表</strong>：定义每天不同时段默认发生的基线事件（如工作、晚间休整、周末休闲）。
          这些事件的效果当前用于文档化各时段基线漂移，实际结算由 dynamics 参数控制。</p>
        <ul className="list-disc pl-4 space-y-0.5 text-[10.5px]">
          <li><span className="text-t3">时段</span>：上午/下午/晚上/深夜，必须从下拉列表选择。</li>
          <li><span className="text-t3">地点</span>：事件发生的地点，必须从下拉列表选择。</li>
          <li><span className="text-t3">隐含效果</span>：文档化的四维效果，0 表示无影响。</li>
        </ul>
      </div>
      <table className="text-[11px] border-collapse w-full">
        <thead><tr><Th>ID</Th><Th>名称</Th><Th>时段</Th><Th>地点</Th><Th>隐含效果</Th><Th>备注</Th></tr></thead>
        <tbody>
          {data.map((t, i) => (
            <tr key={t.id} className="border-b border-edge hover:bg-[var(--hover)]">
              <Td className="text-t3 font-num">{t.id}</Td>
              <Td><Cell value={t.name} onSave={v => mutate(n => { n[i].name = v })} /></Td>
              <Td><SelectCell value={t.slot} options={SLOT_OPTIONS} onSave={v => mutate(n => { n[i].slot = v })} /></Td>
              <Td><SelectCell value={t.location} options={locations} onSave={v => mutate(n => { n[i].location = v })} /></Td>
              <Td><EffectGrid effect={normalizeEffect(t.implicit_effect)} onChange={(dim, val) => mutate(n => { n[i].implicit_effect[dim] = val as any })} /></Td>
              <Td className="text-t3 max-w-[240px] truncate"><Cell value={t.note || ''} onSave={v => mutate(n => { n[i].note = v })} /></Td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

// ── 天气状态转移矩阵编辑器 ────────────────────────────────────────────────────
function WeatherEditor({ data, onChange }: { data: WeatherConfig | undefined; onChange: (v: WeatherConfig) => void }) {
  const mutate = (fn: (next: WeatherConfig) => void) => {
    const next = JSON.parse(JSON.stringify(data || {
      states: ["晴", "多云", "阴", "小雨", "暴雨"],
      initial_weights: [0.5, 0.25, 0.15, 0.08, 0.02],
      transition_matrix: [
        [0.6, 0.25, 0.1, 0.04, 0.01],
        [0.3, 0.4, 0.2, 0.08, 0.02],
        [0.15, 0.25, 0.35, 0.2, 0.05],
        [0.1, 0.2, 0.3, 0.3, 0.1],
        [0.05, 0.15, 0.25, 0.35, 0.2],
      ],
      state_effects: {
        "晴": { valence: 0.003 },
        "多云": {},
        "阴": {},
        "小雨": { valence: -0.002 },
        "暴雨": { valence: -0.003 },
      },
      outdoor_modifiers: { "晴": 1.1, "多云": 1.0, "阴": 0.9, "小雨": 0.6, "暴雨": 0.3 },
    })) as WeatherConfig
    fn(next)
    onChange(next)
  }

  const cfg = data || {
    states: ["晴", "多云", "阴", "小雨", "暴雨"],
    initial_weights: [0.5, 0.25, 0.15, 0.08, 0.02],
    transition_matrix: [
      [0.6, 0.25, 0.1, 0.04, 0.01],
      [0.3, 0.4, 0.2, 0.08, 0.02],
      [0.15, 0.25, 0.35, 0.2, 0.05],
      [0.1, 0.2, 0.3, 0.3, 0.1],
      [0.05, 0.15, 0.25, 0.35, 0.2],
    ],
    state_effects: {} as WeatherConfig['state_effects'],
    outdoor_modifiers: {} as WeatherConfig['outdoor_modifiers'],
  }
  const states = cfg.states || []

  return (
    <Card className="p-3">
      <div className="text-[11px] text-t2 mb-3 leading-relaxed space-y-1">
        <p><strong className="text-t1">天气状态转移矩阵</strong>：马尔可夫链驱动的天气系统，每天转移一次，影响心情基线和户外事件效果。</p>
        <ul className="list-disc pl-4 space-y-0.5 text-[10.5px]">
          <li><span className="text-t3">转移概率矩阵</span>：行=当前天气，列=下一天天气，每行概率之和自动归一化为 1（输入时无需恰好为 1，保存后前端显示将归一化值）。</li>
          <li><span className="text-t3">初始权重</span>：模拟开始时各天气状态的概率分布。</li>
          <li><span className="text-t3">状态效果</span>：天气对心情等维度的微小加成（每时段叠加，氛围调剂）。</li>
          <li><span className="text-t3">户外倍率</span>：天气对户外事件效果的修正倍率（晴天增强、雨天打折）。</li>
        </ul>
      </div>

      {/* 转移概率矩阵 */}
      <div className="mb-4">
        <h4 className="text-[11px] font-semibold text-t1 mb-1.5">转移概率矩阵（行 → 列）</h4>
        <div className="overflow-x-auto">
          <table className="text-[11px] border-collapse">
            <thead>
              <tr>
                <Th className="text-t3">当前 ↓ 下一天 →</Th>
                {states.map(s => <Th key={s} className="text-t3 text-center">{s}</Th>)}
              </tr>
            </thead>
            <tbody>
              {states.map((from, ri) => (
                <tr key={from} className="border-b border-edge hover:bg-[var(--hover)]">
                  <Td className="text-t2 font-medium">{from}</Td>
                  {states.map((_to, ci) => {
                    const val = (cfg.transition_matrix?.[ri]?.[ci] ?? 0)
                    return (
                      <Td key={ci}>
                        <Cell value={val.toFixed(3)} numeric mono onSave={raw => {
                          mutate(n => {
                            if (!n.transition_matrix) n.transition_matrix = states.map(() => states.map(() => 0))
                            if (!n.transition_matrix[ri]) n.transition_matrix[ri] = states.map(() => 0)
                            n.transition_matrix[ri][ci] = Number(raw)
                          })
                        }} />
                      </Td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 初始权重 */}
      <div className="mb-4">
        <h4 className="text-[11px] font-semibold text-t1 mb-1.5">初始权重</h4>
        <div className="flex items-center gap-3 flex-wrap">
          {states.map((s, i) => (
            <div key={s} className="flex items-center gap-1">
              <span className="text-[10px] text-t3">{s}</span>
              <Cell
                value={(cfg.initial_weights?.[i] ?? 0).toFixed(3)}
                numeric mono
                onSave={raw => {
                  mutate(n => {
                    if (!n.initial_weights) n.initial_weights = states.map(() => 0)
                    n.initial_weights[i] = Number(raw)
                  })
                }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* 状态效果 */}
      <div className="mb-4">
        <h4 className="text-[11px] font-semibold text-t1 mb-1.5">状态效果（每时段）</h4>
        <div className="overflow-x-auto">
          <table className="text-[11px] border-collapse">
            <thead>
              <tr>
                <Th>天气</Th>
                {EFFECT_DIMS.map(d => <Th key={d} className="text-center">{DIM_LABEL[d]}</Th>)}
              </tr>
            </thead>
            <tbody>
              {states.map(s => {
                const eff = cfg.state_effects?.[s] || {}
                return (
                  <tr key={s} className="border-b border-edge hover:bg-[var(--hover)]">
                    <Td className="text-t2 font-medium">{s}</Td>
                    {EFFECT_DIMS.map(dim => (
                      <Td key={dim}>
                        <Cell
                          value={Number(eff[dim] ?? 0).toFixed(4)}
                          numeric mono
                          onSave={raw => {
                            mutate(n => {
                              if (!n.state_effects) n.state_effects = {}
                              if (!n.state_effects[s]) n.state_effects[s] = {}
                              n.state_effects[s][dim] = Number(raw)
                            })
                          }}
                        />
                      </Td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 户外倍率 */}
      <div>
        <h4 className="text-[11px] font-semibold text-t1 mb-1.5">户外事件修正倍率</h4>
        <div className="flex items-center gap-3 flex-wrap">
          {states.map(s => (
            <div key={s} className="flex items-center gap-1">
              <span className="text-[10px] text-t3">{s}</span>
              <Cell
                value={(cfg.outdoor_modifiers?.[s] ?? 1.0).toFixed(2)}
                numeric mono
                onSave={raw => {
                  mutate(n => {
                    if (!n.outdoor_modifiers) n.outdoor_modifiers = {}
                    n.outdoor_modifiers[s] = Number(raw)
                  })
                }}
              />
            </div>
          ))}
        </div>
      </div>
    </Card>
  )
}

// ── 主页面：单页滚动 + 左侧悬浮目录 ──────────────────────────────────────────
export default function BalancePage() {
  const [config, setConfig] = useState<BalanceConfig | null>(null)
  const [localFiles, setLocalFiles] = useState<BalanceFiles>({})
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [savedAt, setSavedAt] = useState('')
  const [error, setError] = useState('')
  const [autoSave, setAutoSave] = useState(true)
  const [activeSection, setActiveSection] = useState(FILE_ORDER[0])
  const containerRef = useRef<HTMLDivElement>(null)

  const refresh = useCallback(() => {
    api.getBalanceConfig().then(c => {
      setConfig(c)
      setLocalFiles(c.files)
      setDirty(new Set())
    }).catch(e => setError('加载配置失败：' + e.message))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const save = useCallback(async (file: string) => {
    const content = (localFiles as any)[file]
    if (content === undefined) return
    setError('')
    try {
      await api.saveBalanceFile(file, content)
      setSavedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
      setDirty(prev => { const s = new Set(prev); s.delete(file); return s })
    } catch (e: any) {
      setError(`保存失败(${FILE_LABELS[file] ?? file})：${e.message ?? '请检查数据格式'}`)
    }
  }, [localFiles])

  const handleChange = useCallback((file: string, value: unknown) => {
    setLocalFiles(prev => ({ ...prev, [file]: value }))
    setDirty(prev => new Set(prev).add(file))
  }, [])

  const handleEventChanges = useCallback((changes: Partial<BalanceFiles>) => {
    setLocalFiles(prev => ({ ...prev, ...changes }))
    setDirty(prev => {
      const s = new Set(prev)
      Object.keys(changes).forEach(k => s.add(k))
      return s
    })
  }, [])

  // 自动保存：2s 无修改后保存所有脏文件
  useEffect(() => {
    if (!autoSave || dirty.size === 0) return
    const timer = setTimeout(() => { Array.from(dirty).forEach(f => save(f)) }, 2000)
    return () => clearTimeout(timer)
  }, [autoSave, dirty, save])

  const reset = async (file: string) => {
    if (!confirm(`确定重置「${FILE_LABELS[file] ?? file}」到代码默认值？此操作不可撤销。`)) return
    setError('')
    try {
      await api.resetBalanceFile(file)
      setSavedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
      refresh()
    } catch { setError('重置失败') }
  }

  // 滚动监听：高亮当前 section
  useEffect(() => {
    const observer = new IntersectionObserver(
      entries => {
        const visible = entries.filter(e => e.isIntersecting)
        if (visible.length > 0) {
          const top = visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
          setActiveSection(top.target.id.replace('sec-', ''))
        }
      },
      { rootMargin: '-10% 0px -70% 0px' }
    )
    const sections = containerRef.current?.querySelectorAll('section[id^="sec-"]')
    sections?.forEach(s => observer.observe(s))
    return () => observer.disconnect()
  }, [config])

  const jumpTo = (key: string) => {
    document.getElementById(`sec-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const availableFiles = FILE_ORDER.filter(f => {
    if (f === 'events') {
      return ['recovery_actions', 'disturbances', 'meal_tiers', 'sleep_tiers', 'custom_activities', 'habituation']
        .some(k => (localFiles as any)[k] !== undefined)
    }
    return (localFiles as any)[f] !== undefined
  })

  const eventLocations = collectLocations(localFiles)
  // 地点表 supports 的事件下拉选项：恢复动作 A1–A6 + 自定义活动 C0–C6
  const eventOptions = [
    ...(localFiles.recovery_actions ?? []).map(a => a.id),
    ...(localFiles.custom_activities ?? []).map(c => c.id),
  ]

  const renderEditor = (key: string) => {
    const files = localFiles as any
    switch (key) {
      case 'events': return (
        <EventsEditor
          files={{
            recovery_actions: files.recovery_actions,
            disturbances: files.disturbances,
            meal_tiers: files.meal_tiers,
            sleep_tiers: files.sleep_tiers,
            custom_activities: files.custom_activities,
            habituation: files.habituation,
            template_events: files.template_events,
            venues: files.venues,
          }}
          onChange={handleEventChanges}
        />
      )
      case 'venues':             return <VenuesEditor data={files.venues} eventOptions={eventOptions} onChange={v => handleChange(key, v)} />
      case 'professions':        return <ProfessionEditor data={files.professions} onChange={v => handleChange(key, v)} />
      case 'economy':            return <KVEditor data={files.economy} onChange={v => handleChange(key, v)} title="经济参数" description="初始金钱、加班收入、负债压力等全局经济设定。" />
      case 'dynamics':           return <KVEditor data={files.dynamics} onChange={v => handleChange(key, v)} title="动力学参数" description="状态自然漂移、工作消耗、反弹阈值等世界动力学系数。" />
      case 'needs':              return <NeedsEditor data={files.needs} onChange={v => handleChange(key, v)} />
      case 'persona_modulation': return <PersonaModEditor data={files.persona_modulation} onChange={v => handleChange(key, v)} />
      case 'weather': return <WeatherEditor data={files.weather} onChange={v => handleChange(key, v)} />
      case 'template_events':    return <TemplateEditor data={files.template_events} onChange={v => handleChange(key, v)} locations={eventLocations} />
      default: return null
    }
  }

  return (
    <div className="flex gap-5 items-start">
      {/* 左侧悬浮目录 */}
      <nav className="sticky top-20 z-10 shrink-0 hidden md:flex flex-col gap-0.5 w-[104px] py-1">
        {availableFiles.map(f => (
          <button
            key={f}
            onClick={() => jumpTo(f)}
            className={`text-left text-[11px] px-2 py-1 rounded transition-colors flex items-center gap-1.5 ${
              activeSection === f
                ? 'bg-[color-mix(in_srgb,var(--accent)_12%,transparent)] text-[var(--accent)] font-medium'
                : 'text-t3 hover:text-t1 hover:bg-[var(--hover)]'
            }`}
          >
            <span className="truncate">{FILE_LABELS[f]}</span>
            {dirty.has(f) && <span className="h-1 w-1 rounded-full bg-[var(--warning)] shrink-0" />}
          </button>
        ))}
        <div className="mt-2 px-2 space-y-1">
          <label className="flex items-center gap-1.5 text-[10px] text-t3 cursor-pointer">
            <input type="checkbox" checked={autoSave} onChange={e => setAutoSave(e.target.checked)} className="accent-[var(--accent)] scale-90" />
            自动保存
          </label>
          {!autoSave && dirty.size > 0 && (
            <button
              onClick={() => Array.from(dirty).forEach(f => save(f))}
              className="w-full text-[10px] px-2 py-1 rounded-md font-medium text-white"
              style={{ background: cssVar('--accent') }}
            >
              保存 {dirty.size} 项
            </button>
          )}
        </div>
      </nav>

      {/* 主内容：单页滚动 */}
      <div ref={containerRef} className="flex-1 min-w-0 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-lg font-bold text-t1 display">配表编辑器</h2>
          <Badge
            label={config?.source === 'json' ? 'JSON 实时生效' : config?.source === 'default' ? '代码默认' : '加载中…'}
            color={config?.source === 'json' ? cssVar('--good') : cssVar('--warning')}
          />
          {savedAt && <span className="text-[11px] text-[var(--good)]">✓ 已保存 {savedAt}</span>}
          {dirty.size > 0 && autoSave && <span className="text-[10.5px] text-[var(--warning)]">自动保存中…</span>}
          {error && <span className="text-[11px] text-[var(--critical)]">{error}</span>}
          <span className="text-[11px] text-t3 ml-auto">config/balance/ · 点击单元格编辑</span>
        </div>

        {config === null ? (
          <Card className="p-8 text-center text-t3 text-[12px]">加载配置中…</Card>
        ) : availableFiles.map(key => (
          <section key={key} id={`sec-${key}`} className="scroll-mt-20">
            <div className="flex items-center gap-2 mb-1.5">
              <h3 className="text-[13px] font-semibold text-t1">{FILE_LABELS[key]}</h3>
              <span className="text-[9.5px] text-t3 font-mono">{key === 'events' ? 'recovery_actions + meal_tiers + sleep_tiers + custom_activities + disturbances + habituation' : `${key}.json`}</span>
              {dirty.has(key) && <span className="h-1.5 w-1.5 rounded-full bg-[var(--warning)]" />}
              {RESETABLE.has(key) && (
                <button
                  onClick={() => reset(key)}
                  className="ml-auto text-[10px] text-t3 hover:text-[var(--critical)] px-1.5 py-0.5 rounded hover:bg-[color-mix(in_srgb,var(--critical)_8%,transparent)] transition-colors"
                >
                  重置
                </button>
              )}
            </div>
            {renderEditor(key)}
          </section>
        ))}
      </div>
    </div>
  )
}
