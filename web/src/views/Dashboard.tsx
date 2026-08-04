import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { api, Catalog, RunItem } from '../api'
import { VERDICTS, cssVar, useReducedMotion } from '../components/theme'
import { Badge, Button } from '../components/ui'

export default function Dashboard({ onOpen }: { onOpen: (runId: string) => void }) {
  const reduced = useReducedMotion()
  const [runs, setRuns] = useState<RunItem[]>([])
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [form, setForm] = useState({ seed: 42, days: 30, archetype: '', harness: '' })
  const [harnesses, setHarnesses] = useState<{ name: string; doc: string }[]>([])
  const [starting, setStarting] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)

  const refresh = () => api.listRuns().then((d) => setRuns(d.runs))
  useEffect(() => {
    refresh()
    api.catalog().then(setCatalog).catch(() => {})
    api.harnesses().then((r) => {
      setHarnesses(r.items)
      setForm((f) => ({ ...f, harness: f.harness || r.default }))
    }).catch(() => {})
    const id = setInterval(refresh, 4000)
    return () => clearInterval(id)
  }, [])

  const start = async () => {
    setStarting(true)
    const res = await api.startRun({
      mode: 'live', quality: 'good', ...form,
      archetype: form.archetype || null, harness: form.harness || null,
    })
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

  const field = 'mt-1 block rounded-xl bg-surface-2 border border-edge px-3 py-2 text-sm text-t1'
  return (
    <div className="space-y-6">
      {/* 新建运行 */}
      <div className="rounded-2xl border border-edge bg-surface shadow-card p-5">
        <div className="text-sm font-semibold text-t1 mb-4">启动新运行</div>
        <div className="flex flex-wrap items-end gap-4">
          <div className="text-xs text-t2">
            模式
            <div className="mt-1 rounded-xl border px-3 py-2 text-sm"
              style={{ borderColor: 'color-mix(in srgb, var(--good) 40%, transparent)', background: 'color-mix(in srgb, var(--good) 8%, transparent)', color: 'var(--good)' }}>
              真实 LLM（用户 Agent + 助手 Agent）
            </div>
          </div>
          <label className="text-xs text-t2">
            职业
            <select value={form.archetype} onChange={(e) => setForm({ ...form, archetype: e.target.value })} className={field}>
              <option value="">随机（seed 决定）</option>
              {catalog?.professions.map((p) => (
                <option key={p.archetype} value={p.archetype}>{p.archetype}（¥{p.income_per_slot}/时段）</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-t2">
            被测 Harness
            <select value={form.harness} onChange={(e) => setForm({ ...form, harness: e.target.value })} className={field}>
              {harnesses.map((h) => (
                <option key={h.name} value={h.name} title={h.doc}>{h.name}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-t2">
            seed
            <input type="number" value={form.seed} onChange={(e) => setForm({ ...form, seed: +e.target.value })}
              className={`${field} w-24 font-num`} />
          </label>
          <label className="text-xs text-t2">
            天数
            <input type="number" value={form.days} onChange={(e) => setForm({ ...form, days: +e.target.value })}
              className={`${field} w-24 font-num`} />
          </label>
          <Button onClick={start} disabled={starting} className="!px-5 !py-2">
            {starting ? '启动中…' : '▶ 启动'}
          </Button>
        </div>
      </div>

      {/* 运行列表 + 删除模式 */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-t1">存档记录（{runs.length}）</span>
        {!selecting ? (
          <Button variant="danger" className="!py-1.5 !text-xs" onClick={() => setSelecting(true)} disabled={runs.length === 0}>
            🗑 删除存档
          </Button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-t2">已选 <span className="font-num text-[var(--critical)]">{selected.size}</span> 个</span>
            <Button variant="ghost" className="!py-1 !text-xs" onClick={() => setSelected(new Set(deletableRuns.map((r) => r.run_id)))}>全选</Button>
            <Button variant="ghost" className="!py-1 !text-xs" onClick={() => { setSelecting(false); setSelected(new Set()) }}>取消</Button>
            <Button variant="danger" className="!py-1 !text-xs" onClick={doDelete} disabled={selected.size === 0 || deleting}>
              {deleting ? '删除中…' : `确认删除 ${selected.size} 个`}
            </Button>
          </div>
        )}
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {runs.map((r, idx) => {
          const v = r.verdict ? VERDICTS[r.verdict] : null
          const isSelected = selected.has(r.run_id)
          const disabled = selecting && r.status === 'running'
          const pct = r.progress && r.progress.total > 0 ? Math.min(100, Math.round((r.progress.slot / r.progress.total) * 100)) : null
          return (
            <motion.button key={r.run_id}
              initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: Math.min(0.2, idx * 0.02) }}
              whileHover={reduced ? undefined : { y: -2 }}
              onClick={() => (selecting ? !disabled && toggleSelect(r.run_id) : onOpen(r.run_id))}
              className={`relative rounded-2xl border p-4 text-left transition-colors min-h-[128px] shadow-card ${
                isSelected ? 'bg-[color-mix(in_srgb,var(--critical)_8%,transparent)]' : 'bg-surface hover:bg-surface-2'
              } ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
              style={{ borderColor: isSelected ? 'color-mix(in srgb, var(--critical) 60%, transparent)' : 'var(--border)' }}>
              {selecting && (
                <span className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-md border text-[11px]"
                  style={isSelected
                    ? { borderColor: 'var(--critical)', background: 'var(--critical)', color: '#fff' }
                    : { borderColor: 'var(--axis)', color: 'transparent' }}>
                  ✓
                </span>
              )}
              <div className="flex items-center justify-between gap-2 pr-6">
                <span className="font-num text-[13px] text-t1 truncate">{r.run_id}</span>
                <div className="flex gap-1.5 shrink-0">
                  {r.status === 'running' && (
                    <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium"
                      style={{ color: 'var(--accent)', background: 'color-mix(in srgb, var(--accent) 12%, transparent)' }}>
                      <span className="relative flex h-2 w-2">
                        {!reduced && <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60" style={{ background: 'var(--accent)' }} />}
                        <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: 'var(--accent)' }} />
                      </span>
                      运行中
                    </span>
                  )}
                  {v && <Badge label={v.label} color={cssVar(v.cssVar)} icon={v.icon} />}
                </div>
              </div>
              {r.status === 'running' && pct !== null && (
                <div className="mt-2.5">
                  <div className="flex justify-between text-[10px] mb-1" style={{ color: 'var(--accent)' }}>
                    <span>模拟进行中</span>
                    <span className="font-num">{r.progress!.slot}/{r.progress!.total} 时段 · {pct}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-[var(--hover)] overflow-hidden">
                    <motion.div className="h-full rounded-full" style={{ background: 'var(--accent)' }}
                      initial={false} animate={{ width: `${pct}%` }}
                      transition={reduced ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.5 }} />
                  </div>
                </div>
              )}
              <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                <span className="text-t3">模式 <span className="text-t2">{r.mode === 'live' ? '真实 LLM' : '规则回放'}</span></span>
                {r.assistant_quality && <span className="text-t3">档位 <span className="text-t2">{{ good: '优秀助手', mid: '普通助手', poor: '失能助手' }[r.assistant_quality] ?? r.assistant_quality}</span></span>}
                {r.seed !== undefined && <span className="text-t3">seed <span className="font-num text-t2">{r.seed}</span></span>}
                {r.days !== undefined && <span className="text-t3">时长 <span className="font-num text-t2">{r.days} 天</span></span>}
                {r.persona_name && <span className="text-t3">角色 <span className="text-t2">{r.persona_name}</span></span>}
                {r.archetype && (
                  <span className="text-t3">职业 <span className="text-t2">{r.archetype}</span>
                    {r.income_per_slot !== undefined && <span className="font-num" style={{ color: 'var(--satiety)' }}> ¥{r.income_per_slot}/时段</span>}
                  </span>
                )}
                {r.started_at && <span className="text-t3 col-span-2">启动 <span className="font-num text-t2">{new Date(r.started_at).toLocaleString('zh-CN', { hour12: false })}</span></span>}
              </div>
            </motion.button>
          )
        })}
        {runs.length === 0 && <p className="text-sm text-t3">还没有运行记录，先在上方启动一个。</p>}
      </div>
    </div>
  )
}
