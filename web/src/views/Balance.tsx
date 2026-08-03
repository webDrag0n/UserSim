import { useEffect, useMemo, useState } from 'react'
import { Card, Badge } from '../components/StateBars'

// 配表编辑器：查看/编辑所有事件与需求参数、效果、边际效益函数（Excel 单一数据源）

interface Sheet { name: string; headers: (string | number | null)[]; rows: (string | number | null)[][] }

const api = {
  balance: (): Promise<{ source: string; sheets: Sheet[] }> => fetch('/api/balance').then((r) => r.json()),
  setCell: (sheet: string, row: number, col: number, value: string) =>
    fetch('/api/balance/cell', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sheet, row, col, value }),
    }).then((r) => r.json()),
}

// 与后端 anthro.hab_weight 同式
function habW(dt: number, wMin: number, tau: number, curve: string): number {
  dt = Math.max(0, dt)
  if (tau <= 0) return 1
  let c: number
  if (curve === 'sqrt') c = Math.pow(tau / (dt + tau), 0.5)
  else if (curve === 's') c = (tau * tau) / (tau * tau + dt * dt)
  else c = Math.exp(-dt / tau)
  return 1 - (1 - wMin) * c
}

function CurvePreview({ wMin, tau, curve, color = '#22d3ee' }: { wMin: number; tau: number; curve: string; color?: string }) {
  const W = 120, H = 36
  const maxT = Math.max(4, tau * 3)
  const pts = Array.from({ length: 41 }, (_, i) => {
    const dt = (i / 40) * maxT
    const x = (i / 40) * W
    const y = H - habW(dt, wMin, tau, curve) * H
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg width={W} height={H} className="inline-block align-middle">
      <line x1="0" y1={H - wMin * H} x2={W} y2={H - wMin * H} stroke="rgba(255,255,255,0.15)" strokeDasharray="3 3" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  )
}

function UrgePreview({ kind }: { kind: string }) {
  const W = 110, H = 34
  const f = (x: number) =>
    kind === '饥饿' ? Math.min(1, Math.pow(x / 0.6, 1.5))
    : kind === '社交' ? x * x
    : kind === '刺激' ? 1 - Math.pow(2 * x - 1, 2)
    : Math.pow(x, 2.5)
  const pts = Array.from({ length: 41 }, (_, i) => {
    const x = i / 40
    return `${(x * W).toFixed(1)},${(H - Math.max(0, Math.min(1, f(x))) * H).toFixed(1)}`
  }).join(' ')
  return (
    <svg width={W} height={H} className="inline-block align-middle">
      <polyline points={pts} fill="none" stroke="#a78bfa" strokeWidth="1.5" />
    </svg>
  )
}

function EditableCell({ value, onSave }: { value: any; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState(String(value ?? ''))
  if (!editing) {
    return (
      <span onClick={() => { setV(String(value ?? '')); setEditing(true) }}
        className="cursor-text rounded px-1 -mx-1 hover:bg-cyan-400/10 hover:text-cyan-200 transition-colors"
        title="点击编辑">
        {value === null || value === '' ? '—' : String(value)}
      </span>
    )
  }
  return (
    <input autoFocus value={v} onChange={(e) => setV(e.target.value)}
      onBlur={() => { setEditing(false); if (v !== String(value ?? '')) onSave(v) }}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setEditing(false) }}
      className="w-full min-w-[60px] rounded bg-cyan-400/10 border border-cyan-400/50 px-1 text-inherit outline-none font-num" />
  )
}

export default function BalancePage() {
  const [data, setData] = useState<{ source: string; sheets: Sheet[] } | null>(null)
  const [tab, setTab] = useState('习惯化曲线')
  const [savedAt, setSavedAt] = useState('')

  const refresh = () => api.balance().then(setData)
  useEffect(() => { refresh() }, [])

  const save = async (sheet: string, row: number, col: number, value: string) => {
    await api.setCell(sheet, row, col, value)
    setSavedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
    refresh()
  }

  const sheets = data?.sheets ?? []
  const cur = sheets.find((s) => s.name === tab)

  const contentRows = useMemo(() => {
    if (!cur) return []
    return cur.rows.map((r) => {
      const [rowNum, ...cells] = r
      return { rowNum: rowNum as number, cells }
    })
  }, [cur])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-lg font-bold text-white">配表编辑器</h2>
        <Badge label={data?.source === 'excel' ? '数据源：Excel 实时生效' : '数据源：代码默认'} color={data?.source === 'excel' ? '#34d399' : '#fbbf24'} />
        {savedAt && <span className="text-[11px] text-emerald-400">✓ 已保存并热加载 {savedAt}</span>}
        <span className="text-[11px] text-zinc-500">balance-sheet/UserSim数值配表.xlsx · 点击单元格直接编辑，回车保存</span>
      </div>

      <div className="flex gap-2 flex-wrap">
        {sheets.map((s) => (
          <button key={s.name} onClick={() => setTab(s.name)}
            className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${tab === s.name ? 'bg-white/10 text-white font-semibold' : 'text-zinc-400 hover:text-zinc-200'}`}>
            {s.name}
          </button>
        ))}
      </div>

      {cur && (
        <Card className="p-4 overflow-x-auto">
          <table className="text-[11.5px] border-collapse">
            <thead>
              <tr>
                {cur.headers.map((h, i) => (
                  <th key={i} className="text-left text-zinc-500 font-medium border-b border-white/10 px-2 py-1.5 whitespace-nowrap">
                    {h}{tab === '习惯化曲线' && i === cur.headers.length ? ' · 曲线' : ''}
                  </th>
                ))}
                {tab === '习惯化曲线' && <th className="text-left text-zinc-500 font-medium border-b border-white/10 px-2 py-1.5">w(Δt) 预览</th>}
                {tab === '需求参数' && <th className="text-left text-zinc-500 font-medium border-b border-white/10 px-2 py-1.5">u(x) 预览</th>}
              </tr>
            </thead>
            <tbody>
              {contentRows.map(({ rowNum, cells }) => (
                <tr key={rowNum} className="border-b border-white/5 hover:bg-white/[0.02]">
                  {cells.map((v, ci) => (
                    <td key={ci} className="px-2 py-1.5 text-zinc-300 whitespace-nowrap max-w-[260px] truncate">
                      <EditableCell value={v} onSave={(nv) => save(cur.name, rowNum, ci + 1, nv)} />
                    </td>
                  ))}
                  {tab === '习惯化曲线' && (
                    <td className="px-2 py-1">
                      <CurvePreview wMin={Number(cells[1]) || 0.4} tau={Number(cells[2]) || 8} curve={String(cells[3] || 'exp')} />
                    </td>
                  )}
                  {tab === '需求参数' && (
                    <td className="px-2 py-1"><UrgePreview kind={String(cells[0])} /></td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === '需求参数' && (
        <Card className="p-4 text-[11px] text-zinc-400 leading-relaxed">
          <span className="text-zinc-200 font-semibold">认知动力学曲线说明：</span>
          饥饿 u=((1-x)/0.6)^1.5（越饿越急）；社交 u=x²；<span className="text-violet-300">刺激 u=1-(2x-1)² 为倒 U</span>（太少无聊、太多过载，曲线顶点在中等刺激）；成就 u=x^2.5（deadline 后期陡增）。
        </Card>
      )}
    </div>
  )
}
