import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { api, Catalog, RunGroup, RunItem } from '../api'
import { VERDICTS, cssVar, useReducedMotion } from '../components/theme'
import { Badge, Button } from '../components/ui'

export default function Dashboard({ onOpen }: { onOpen: (runId: string) => void }) {
  const reduced = useReducedMotion()
  const [runs, setRuns] = useState<RunItem[]>([])
  const [groups, setGroups] = useState<RunGroup[]>([])
  const [openGroupId, setOpenGroupId] = useState<string | null>(null)  // 点进的分组文件夹
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [form, setForm] = useState({ seed: 42, days: 30, archetype: '', harness: '' })
  const [harnesses, setHarnesses] = useState<{ name: string; doc: string }[]>([])
  const [starting, setStarting] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set())  // 删除模式下选中的 bench 分组
  const [deleting, setDeleting] = useState(false)
  // 按两个 agent 实现筛选存档（'' = 全部）
  const [filterAssistant, setFilterAssistant] = useState('')
  const [filterUser, setFilterUser] = useState('')

  const refresh = () => api.listRuns().then((d) => { setRuns(d.runs); setGroups(d.groups ?? []) })
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
  const toggleSelectGroup = (id: string) => {
    setSelectedGroups((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id); else n.add(id)
      return n
    })
  }
  const deletableRuns = runs.filter((r) => r.status !== 'running')
  const assistantOptions = [...new Set(runs.map((r) => r.profiles?.assistant).filter((v): v is string => !!v))].sort()
  const userOptions = [...new Set(runs.map((r) => r.profiles?.user).filter((v): v is string => !!v))].sort()
  const visibleRuns = runs.filter((r) =>
    (!filterAssistant || r.profiles?.assistant === filterAssistant) &&
    (!filterUser || r.profiles?.user === filterUser))
  const filtering = filterAssistant !== '' || filterUser !== ''
  const exitSelecting = () => { setSelecting(false); setSelected(new Set()); setSelectedGroups(new Set()) }
  const doDelete = async () => {
    if (selected.size === 0 && selectedGroups.size === 0) return
    setDeleting(true)
    const skipped: string[] = []
    if (selected.size > 0) {
      const res = await api.deleteRuns([...selected])
      skipped.push(...res.skipped.map((s) => `${s.run_id}：${s.reason}`))
    }
    if (selectedGroups.size > 0) {
      const res = await api.deleteBench([...selectedGroups])
      skipped.push(...res.skipped.map((s) => `${s.bench_id}：${s.reason}`))
    }
    setDeleting(false)
    exitSelecting()
    refresh()
    if (skipped.length > 0) alert(`部分存档未删除：\n${skipped.join('\n')}`)
  }
  // 删除整个 bench 分组文件夹（runs/_bench/<bench_id>/ 整目录）
  const deleteWholeGroup = async () => {
    if (!openGroup || deleting) return
    if (!confirm(`确定删除整个分组文件夹「${openGroup.bench_id}」？\n其中 ${openGroup.n_runs} 个 run 会一并删除，不可撤销。`)) return
    setDeleting(true)
    const res = await api.deleteBench([openGroup.bench_id])
    setDeleting(false)
    if (res.skipped.length > 0) {
      alert(`无法删除「${openGroup.bench_id}」：${res.skipped.map((s) => s.reason).join('；')}`)
      return
    }
    setOpenGroupId(null)
    refresh()
  }

  const openGroup = groups.find((g) => g.bench_id === openGroupId) ?? null

  // 单个 run 卡片（顶层存档与分组内子 run 共用）
  const renderRunCard = (r: RunItem, idx: number) => {
    const v = r.verdict ? VERDICTS[r.verdict] : null
    const isSelected = selected.has(r.run_id)
    const disabled = selecting && r.status === 'running'  // 运行中的 run 不可删除
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
        {isSelected && selecting && (
          <span className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-md border text-[11px]"
            style={{ borderColor: 'var(--critical)', background: 'var(--critical)', color: '#fff' }}>
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
            {r.benchmark_score != null && (
              <Badge label={`分数 ${r.benchmark_score.toFixed(0)}`}
                color={r.benchmark_score >= 80 ? 'var(--good)' : r.benchmark_score >= 60 ? 'var(--warning)' : 'var(--critical)'} />
            )}
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
          {r.profiles && (r.profiles.assistant || r.profiles.user) && (
            <span className="text-t3 col-span-2">
              助手 <span className="font-num text-t2">{r.profiles.assistant ?? '—'}</span>
              <span className="mx-1">·</span>
              用户 <span className="font-num text-t2">{r.profiles.user ?? '—'}</span>
            </span>
          )}
          {r.archetype && (
            <span className="text-t3">职业 <span className="text-t2">{r.archetype}</span>
              {r.income_per_slot !== undefined && <span className="font-num" style={{ color: 'var(--satiety)' }}> ¥{r.income_per_slot}/时段</span>}
            </span>
          )}
          {r.started_at && <span className="text-t3 col-span-2">启动 <span className="font-num text-t2">{new Date(r.started_at).toLocaleString('zh-CN', { hour12: false })}</span></span>}
        </div>
      </motion.button>
    )
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

      {/* 分组文件夹下钻视图 */}
      {openGroup ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="ghost" className="!py-1 !text-xs" onClick={() => { setOpenGroupId(null); exitSelecting() }}>
              ← 返回存档列表
            </Button>
            <span className="text-sm font-semibold text-t1 font-num">📁 {openGroup.bench_id}</span>
            <span className="text-[11px] text-t3">
              {openGroup.n_runs} 个 run · 分组：{openGroup.harnesses.join('、')}
            </span>
            <div className="ml-auto flex items-center gap-2">
              {!selecting ? (
                <>
                  <Button variant="danger" className="!py-1.5 !text-xs" onClick={() => setSelecting(true)}
                    disabled={openGroup.runs.every((r) => r.status === 'running')}>
                    🗑 删除存档
                  </Button>
                  <Button variant="danger" className="!py-1.5 !text-xs" onClick={deleteWholeGroup} disabled={deleting}>
                    {deleting ? '删除中…' : '🗑 删除整个文件夹'}
                  </Button>
                </>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-t2">已选 <span className="font-num text-[var(--critical)]">{selected.size}</span> 个</span>
                  <Button variant="ghost" className="!py-1 !text-xs"
                    onClick={() => setSelected(new Set(openGroup.runs.filter((r) => r.status !== 'running').map((r) => r.run_id)))}>全选</Button>
                  <Button variant="ghost" className="!py-1 !text-xs" onClick={exitSelecting}>取消</Button>
                  <Button variant="danger" className="!py-1 !text-xs" onClick={doDelete} disabled={selected.size === 0 || deleting}>
                    {deleting ? '删除中…' : `确认删除 ${selected.size} 个`}
                  </Button>
                </div>
              )}
            </div>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            {openGroup.runs.map((r, idx) => renderRunCard(r, idx))}
          </div>
        </div>
      ) : (
      <>
      {/* 运行列表 + 筛选 + 删除模式 */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-semibold text-t1">
            存档记录（{filtering ? `${visibleRuns.length}/${runs.length}` : runs.length}{groups.length > 0 ? ` · ${groups.length} 个分组` : ''}）
          </span>
          <label className="text-[11px] text-t3 flex items-center gap-1.5">
            助手
            <select value={filterAssistant} onChange={(e) => setFilterAssistant(e.target.value)}
              className="rounded-lg bg-surface-2 border border-edge px-2 py-1 text-[12px] text-t1 font-num">
              <option value="">全部</option>
              {assistantOptions.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-t3 flex items-center gap-1.5">
            用户
            <select value={filterUser} onChange={(e) => setFilterUser(e.target.value)}
              className="rounded-lg bg-surface-2 border border-edge px-2 py-1 text-[12px] text-t1 font-num">
              <option value="">全部</option>
              {userOptions.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          {filtering && (
            <button onClick={() => { setFilterAssistant(''); setFilterUser('') }}
              className="text-[11px] text-t3 hover:text-t1 transition-colors">
              ✕ 清除筛选
            </button>
          )}
        </div>
        {!selecting ? (
          <Button variant="danger" className="!py-1.5 !text-xs" onClick={() => setSelecting(true)} disabled={runs.length === 0 && groups.length === 0}>
            🗑 删除存档
          </Button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-t2">已选 <span className="font-num text-[var(--critical)]">{selected.size + selectedGroups.size}</span> 个</span>
            <Button variant="ghost" className="!py-1 !text-xs" onClick={() => {
              setSelected(new Set(deletableRuns.map((r) => r.run_id)))
              setSelectedGroups(new Set(groups.map((g) => g.bench_id)))
            }}>全选</Button>
            <Button variant="ghost" className="!py-1 !text-xs" onClick={exitSelecting}>取消</Button>
            <Button variant="danger" className="!py-1 !text-xs" onClick={doDelete} disabled={(selected.size === 0 && selectedGroups.size === 0) || deleting}>
              {deleting ? '删除中…' : `确认删除 ${selected.size + selectedGroups.size} 个`}
            </Button>
          </div>
        )}
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {/* bench 分组文件夹卡片：点进查看组内 run；删除模式下可勾选整个分组 */}
        {groups.map((g) => {
          const scores = g.runs.map((r) => r.benchmark_score).filter((v): v is number => v != null)
          const mean = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null
          const isSelected = selectedGroups.has(g.bench_id)
          return (
            <motion.button key={g.bench_id}
              initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
              whileHover={reduced ? undefined : { y: -2 }}
              onClick={() => (selecting ? toggleSelectGroup(g.bench_id) : setOpenGroupId(g.bench_id))}
              className={`relative rounded-2xl border p-4 text-left transition-colors min-h-[128px] shadow-card ${
                isSelected ? 'bg-[color-mix(in_srgb,var(--critical)_8%,transparent)]' : 'bg-surface hover:bg-surface-2'
              }`}
              style={{ borderColor: isSelected ? 'color-mix(in srgb, var(--critical) 60%, transparent)' : 'var(--border)' }}>
              {isSelected && selecting && (
                <span className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-md border text-[11px]"
                  style={{ borderColor: 'var(--critical)', background: 'var(--critical)', color: '#fff' }}>
                  ✓
                </span>
              )}
              <div className="flex items-center justify-between gap-2 pr-6">
                <span className="font-num text-[13px] text-t1 truncate">📁 {g.bench_id}</span>
                {mean != null && (
                  <Badge label={`均分 ${mean.toFixed(0)}`}
                    color={mean >= 80 ? 'var(--good)' : mean >= 60 ? 'var(--warning)' : 'var(--critical)'} />
                )}
              </div>
              <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                <span className="text-t3">run 数 <span className="font-num text-t2">{g.n_runs}</span></span>
                <span className="text-t3 col-span-2">分组 <span className="font-num text-t2">{g.harnesses.join('、')}</span></span>
                <span className="text-t3 col-span-2">点进查看组内各 run 的回放与报告</span>
              </div>
            </motion.button>
          )
        })}
        {visibleRuns.map((r, idx) => renderRunCard(r, idx))}
        {runs.length === 0 && groups.length === 0 && <p className="text-sm text-t3">还没有运行记录，先在上方启动一个。</p>}
        {runs.length > 0 && visibleRuns.length === 0 && (
          <p className="text-sm text-t3">没有符合筛选条件的存档（助手: {filterAssistant || '全部'} · 用户: {filterUser || '全部'}）。</p>
        )}
      </div>
      </>
      )}
    </div>
  )
}
