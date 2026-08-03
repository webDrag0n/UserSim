import { useEffect, useState } from 'react'
import { api, Catalog, RunItem, VERDICTS } from '../api'
import { Badge, Card } from '../components/StateBars'

export default function Dashboard({ onOpen }: { onOpen: (runId: string) => void }) {
  const [runs, setRuns] = useState<RunItem[]>([])
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [form, setForm] = useState({ seed: 42, days: 30, archetype: '' })
  const [starting, setStarting] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)

  const refresh = () => api.listRuns().then((d) => setRuns(d.runs))
  useEffect(() => {
    refresh()
    api.catalog().then(setCatalog).catch(() => {})
    const id = setInterval(refresh, 4000)
    return () => clearInterval(id)
  }, [])

  const start = async () => {
    setStarting(true)
    const res = await api.startRun({ mode: 'live', quality: 'good', ...form, archetype: form.archetype || null })
    setStarting(false)
    refresh()
    if (res?.run_id) onOpen(res.run_id)  // 启动后立即进入实时视图
  }

  const toggleSelect = (id: string) => {
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id); else n.add(id)
      return n
    })
  }
  const deletableRuns = runs.filter((r) => r.status !== 'running')
  const doDelete = async () => {
    if (selected.size === 0) return
    setDeleting(true)
    await api.deleteRuns([...selected])
    setDeleting(false)
    setSelected(new Set())
    setSelecting(false)
    refresh()
  }

  return (
    <div className="space-y-6">
      {/* 新建运行 */}
      <Card className="p-5">
        <div className="text-sm font-semibold text-zinc-200 mb-4">启动新运行</div>
        <div className="flex flex-wrap items-end gap-4">
          <div className="text-xs text-zinc-400">
            模式
            <div className="mt-1 rounded-lg border border-emerald-400/40 bg-emerald-400/[0.08] px-3 py-2 text-sm text-emerald-300">
              真实 LLM（用户 Agent + 助手 Agent）
            </div>
          </div>
          <label className="text-xs text-zinc-400">
            职业
            <select value={form.archetype} onChange={(e) => setForm({ ...form, archetype: e.target.value })}
              className="mt-1 block rounded-lg bg-white/5 border border-white/15 px-3 py-2 text-sm text-white">
              <option value="">随机（seed 决定）</option>
              {catalog?.professions.map((p) => (
                <option key={p.archetype} value={p.archetype}>{p.archetype}（¥{p.income_per_slot}/时段）</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-zinc-400">
            seed
            <input type="number" value={form.seed} onChange={(e) => setForm({ ...form, seed: +e.target.value })}
              className="mt-1 block w-24 rounded-lg bg-white/5 border border-white/15 px-3 py-2 text-sm text-white font-num" />
          </label>
          <label className="text-xs text-zinc-400">
            天数
            <input type="number" value={form.days} onChange={(e) => setForm({ ...form, days: +e.target.value })}
              className="mt-1 block w-24 rounded-lg bg-white/5 border border-white/15 px-3 py-2 text-sm text-white font-num" />
          </label>
          <button onClick={start} disabled={starting}
            className="rounded-lg bg-cyan-500/90 hover:bg-cyan-400 px-5 py-2 text-sm font-semibold text-black transition-colors disabled:opacity-40">
            {starting ? '启动中…' : '▶ 启动'}
          </button>
        </div>
      </Card>

      {/* 运行列表 + 删除模式 */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-zinc-200">存档记录（{runs.length}）</span>
        {!selecting ? (
          <button onClick={() => setSelecting(true)} disabled={runs.length === 0}
            className="rounded-lg border border-red-400/40 px-3 py-1.5 text-xs text-red-300 hover:bg-red-400/10 transition-colors disabled:opacity-30">
            🗑 删除存档
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400">已选 <span className="font-num text-red-300">{selected.size}</span> 个</span>
            <button onClick={() => setSelected(new Set(deletableRuns.map((r) => r.run_id)))}
              className="rounded-lg border border-white/15 px-2.5 py-1 text-xs text-zinc-300 hover:bg-white/5">全选</button>
            <button onClick={() => { setSelecting(false); setSelected(new Set()) }}
              className="rounded-lg border border-white/15 px-2.5 py-1 text-xs text-zinc-300 hover:bg-white/5">取消</button>
            <button onClick={doDelete} disabled={selected.size === 0 || deleting}
              className="rounded-lg bg-red-500/90 hover:bg-red-400 px-3 py-1 text-xs font-semibold text-black transition-colors disabled:opacity-40">
              {deleting ? '删除中…' : `确认删除 ${selected.size} 个`}
            </button>
          </div>
        )}
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {runs.map((r) => {
          const v = r.verdict ? VERDICTS[r.verdict] : null
          const isSelected = selected.has(r.run_id)
          const disabled = selecting && r.status === 'running'
          const pct = r.progress && r.progress.total > 0 ? Math.min(100, Math.round((r.progress.slot / r.progress.total) * 100)) : null
          return (
            <button key={r.run_id}
              onClick={() => (selecting ? !disabled && toggleSelect(r.run_id) : onOpen(r.run_id))}
              className={`relative rounded-xl border p-4 text-left transition-colors min-h-[128px] ${
                isSelected ? 'border-red-400/70 bg-red-400/[0.08]' : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]'
              } ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}>
              {selecting && (
                <span className={`absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded border text-[11px] ${
                  isSelected ? 'border-red-400 bg-red-400 text-black' : 'border-white/30 text-transparent'}`}>
                  ✓
                </span>
              )}
              {/* 标题行 */}
              <div className="flex items-center justify-between gap-2 pr-6">
                <span className="font-num text-[13px] text-zinc-200 truncate">{r.run_id}</span>
                <div className="flex gap-1.5 shrink-0">
                  {r.status === 'running' && (
                    <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium text-cyan-300"
                      style={{ background: 'rgba(34,211,238,0.1)', border: '1px solid rgba(34,211,238,0.4)' }}>
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-60" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400" />
                      </span>
                      运行中
                    </span>
                  )}
                  {v && <Badge label={v.label} color={v.color} />}
                </div>
              </div>
              {/* 运行进度条 */}
              {r.status === 'running' && pct !== null && (
                <div className="mt-2.5">
                  <div className="flex justify-between text-[10px] text-cyan-300/90 mb-1">
                    <span>模拟进行中</span>
                    <span className="font-num">{r.progress!.slot}/{r.progress!.total} 时段 · {pct}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                    <div className="h-full rounded-full bg-cyan-400 transition-all duration-500" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )}
              {/* 配置信息网格 */}
              <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                <span className="text-zinc-500">模式 <span className="text-zinc-300">{r.mode === 'live' ? '真实 LLM' : '规则回放'}</span></span>
                {r.assistant_quality && <span className="text-zinc-500">档位 <span className="text-zinc-300">{{ good: '优秀助手', mid: '普通助手', poor: '失能助手' }[r.assistant_quality] ?? r.assistant_quality}</span></span>}
                {r.seed !== undefined && <span className="text-zinc-500">seed <span className="font-num text-zinc-300">{r.seed}</span></span>}
                {r.days !== undefined && <span className="text-zinc-500">时长 <span className="font-num text-zinc-300">{r.days} 天</span></span>}
                {r.persona_name && <span className="text-zinc-500">角色 <span className="text-zinc-300">{r.persona_name}</span></span>}
                {r.archetype && (
                  <span className="text-zinc-500">职业 <span className="text-zinc-300">{r.archetype}</span>
                    {r.income_per_slot !== undefined && <span className="font-num text-amber-300/90"> ¥{r.income_per_slot}/时段</span>}
                  </span>
                )}
                {r.started_at && <span className="text-zinc-500 col-span-2">启动 <span className="font-num text-zinc-400">{new Date(r.started_at).toLocaleString('zh-CN', { hour12: false })}</span></span>}
              </div>
            </button>
          )
        })}
        {runs.length === 0 && <p className="text-sm text-zinc-500">还没有运行记录，先在上方启动一个。</p>}
      </div>
    </div>
  )
}
