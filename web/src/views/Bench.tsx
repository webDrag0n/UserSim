import { useEffect, useState } from 'react'
import {
  api,
  type BenchAggregate, type BenchEpisode, type BenchJob, type BenchRunningEp,
  type BenchListItem, type Discriminability, type MetricStat,
} from '../api'
import { VERDICTS, cssVar, useThemeVersion } from '../components/theme'

// 聚合表展示的指标（顺序即重要性）
const SHOWN: { key: string; label: string; fmt: (v: number) => string; lowerBetter: boolean }[] = [
  { key: 'ess', label: 'e_ss 稳态误差', fmt: (v) => v.toFixed(4), lowerBetter: true },
  { key: 'in_band_ratio', label: '带内驻留比', fmt: (v) => `${(v * 100).toFixed(1)}%`, lowerBetter: false },
  { key: 'overshoot', label: 'M_p 超调', fmt: (v) => v.toFixed(4), lowerBetter: true },
  { key: 'est_err_final', label: '‖x−x̂‖ 终值', fmt: (v) => v.toFixed(4), lowerBetter: true },
  { key: 'est_err_slope_per_day', label: '学习曲线斜率', fmt: (v) => v.toFixed(5), lowerBetter: true },
  { key: 'health_score', label: '健康分', fmt: (v) => v.toFixed(1), lowerBetter: false },
]

function Stat({ s, fmt }: { s: MetricStat | undefined; fmt: (v: number) => string }) {
  if (!s || s.mean === null) return <span className="text-t3">—</span>
  return (
    <span className="font-num">
      {fmt(s.mean)}
      {s.ci95 !== null && <span className="text-t3 text-[10px] ml-1">±{fmt(s.ci95)}</span>}
    </span>
  )
}

function GuardCard({ d }: { d: Discriminability }) {
  // 新版存档带锚点对组名（如 reference vs stub）；旧存档无 groups 字段，回退 good/poor 字样
  const good = d.groups?.good ?? 'good'
  const poor = d.groups?.poor ?? 'poor'
  // 三态：ok / borderline（均值±SEM 跨阈，黄灯）/ fail；旧存档无 status 字段回退二值
  const status = d.status ?? (d.ok ? 'ok' : 'fail')
  const tone = status === 'ok' ? '--good' : status === 'borderline' ? '--warning' : '--critical'
  const label = status === 'ok' ? '通过' : status === 'borderline' ? '通过（边缘）' : '未通过'
  const rows: [string, string][] = [
    [d.groups ? `margin_good（${good}）` : 'margin_good', d.margin_good === null ? '—' : d.margin_good.toFixed(4)],
    [d.groups ? `margin_poor（${poor}）` : 'margin_poor', d.margin_poor === null ? '—' : d.margin_poor.toFixed(4)],
    ['separation (Cohen’s d)', d.separation === null ? '—' : d.separation.toFixed(2)],
  ]
  return (
    <div className="rounded-xl border p-4" style={{ borderColor: `color-mix(in srgb, var(${tone}) 40%, transparent)`, background: `color-mix(in srgb, var(${tone}) 8%, transparent)` }}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-semibold text-t1">量程守护</span>
        <span className="text-xs px-2 py-0.5 rounded-full font-semibold"
          style={{ background: `color-mix(in srgb, var(${tone}) 18%, transparent)`, color: `var(${tone})` }}>
          {label}
        </span>
      </div>
      <p className="text-[11px] text-t2 mb-3 leading-relaxed">
        世界能否分辨好助手与差助手{d.groups && <>（锚点对：{good} vs {poor}）</>}。
        {good} 需低于收敛阈值 {d.thresholds.converged_ess_max}，
        {poor} 需高于发散阈值 {d.thresholds.diverged_ess_min}，两档需清晰分离（d&gt;1.5）。
        {status === 'borderline' && <span style={{ color: 'var(--warning)' }}>ess 均值 ±SEM 跨阈：结论在统计噪声刀沿上，建议加 seed。</span>}
      </p>
      <div className="grid grid-cols-3 gap-3 mb-3">
        {rows.map(([k, v]) => (
          <div key={k}>
            <div className="text-[10px] text-t3">{k}</div>
            <div className="font-num text-sm text-t1">{v}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {Object.entries(d.checks).map(([k, ok]) => {
          const stKey = k === 'margin_poor_positive' ? 'margin_poor'
            : k === 'margin_good_positive' ? 'margin_good' : 'separation'
          const st = d.check_status?.[stKey]
          const color = st === 'borderline' ? 'var(--warning)' : ok ? 'var(--good)' : 'var(--critical)'
          const mark = st === 'borderline' ? '⚠' : ok ? '✓' : '✗'
          return (
            <span key={k} className="text-[11px]" style={{ color }}>
              {mark} {k}
            </span>
          )
        })}
      </div>
    </div>
  )
}

// 解析 seeds 表达式（"1-8" 或 "1,4,7"）得到个数，非法则返回 null
function countSeeds(expr: string): number | null {
  const parts = expr.split(',').map((s) => s.trim()).filter(Boolean)
  if (!parts.length) return null
  let n = 0
  for (const p of parts) {
    const m = p.match(/^(\d+)(?:-(\d+))?$/)
    if (!m) return null
    const [a, b] = [parseInt(m[1], 10), m[2] ? parseInt(m[2], 10) : undefined]
    n += b === undefined ? 1 : Math.max(0, b - a + 1)
  }
  return n
}

// 模型天梯实验默认 5 组（存在则默认勾选）
const DEFAULT_GROUPS = ['reference', 'reference_pro', 'reference_nomem', 'reference_nomem_pro', 'stub']

function StartForm({ onStarted }: { onStarted: (id: string) => void }) {
  const [harnesses, setHarnesses] = useState<string[]>([])
  const [groups, setGroups] = useState<Set<string>>(new Set())
  const [seeds, setSeeds] = useState('42-46')
  const [days, setDays] = useState(30)
  const [concurrency, setConcurrency] = useState(5)
  const [maxEp, setMaxEp] = useState(25)
  const [benchId, setBenchId] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.harnesses().then((r) => {
      const names = r.items.map((i) => i.name)
      setHarnesses(names)
      const wanted = DEFAULT_GROUPS.filter((w) => names.includes(w))
      setGroups(new Set(wanted.length ? wanted : [r.default]))
    }).catch(() => setErr('无法获取 harness 清单'))
  }, [])

  const nSeeds = countSeeds(seeds)
  const nEp = nSeeds === null ? null : nSeeds * groups.size

  const toggle = (g: string) => {
    const next = new Set(groups)
    if (next.has(g)) next.delete(g); else next.add(g)
    setGroups(next)
  }

  const submit = () => {
    setErr(null)
    if (!groups.size) { setErr('至少勾选一个组'); return }
    if (nEp === null) { setErr('seeds 表达式非法（如 42-46 或 1,4,7）'); return }
    if (nEp > maxEp) { setErr(`episode 数 ${nEp} 超过 max_episodes ${maxEp}——调高确认上限或减少组合`); return }
    setBusy(true)
    api.startBench({
      seeds, days, groups: [...groups], max_episodes: maxEp, concurrency,
      bench_id: benchId.trim() || undefined,
    }).then((r) => {
      setBusy(false)
      if (r.started && r.bench_id) onStarted(r.bench_id)
      else setErr(r.error || '启动失败')
    }).catch((e) => { setBusy(false); setErr(String(e)) })
  }

  const inputCls = 'w-full rounded-lg border border-edge bg-surface-2 px-2.5 py-1.5 text-xs font-num text-t1 outline-none focus:border-[color-mix(in_srgb,var(--accent)_50%,transparent)]'
  return (
    <div className="rounded-xl border border-edge bg-surface p-4 space-y-3">
      <div className="flex items-baseline gap-3">
        <span className="text-sm font-semibold text-t1">启动批量评测</span>
        <span className="text-[10.5px] text-t3">恒为 live（烧真 token）；并发执行，已完成 episode 自动跳过</span>
      </div>
      <div>
        <div className="text-[11px] text-t2 mb-1.5">评测组（harness，{groups.size} 组）</div>
        <div className="flex flex-wrap gap-1.5">
          {harnesses.map((h) => (
            <button key={h} type="button" onClick={() => toggle(h)}
              className={`rounded-lg border px-2.5 py-1 text-[11px] font-num transition-colors ${
                groups.has(h)
                  ? 'border-[color-mix(in_srgb,var(--accent)_50%,transparent)] bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-[var(--accent)]'
                  : 'border-edge text-t2 hover:text-t1'}`}>
              {h}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        <label className="block">
          <span className="text-[10.5px] text-t3">seeds</span>
          <input className={inputCls} value={seeds} onChange={(e) => setSeeds(e.target.value)} />
        </label>
        <label className="block">
          <span className="text-[10.5px] text-t3">天数/episode</span>
          <input type="number" min={1} className={inputCls} value={days}
            onChange={(e) => setDays(parseInt(e.target.value, 10) || 1)} />
        </label>
        <label className="block">
          <span className="text-[10.5px] text-t3">并发数</span>
          <input type="number" min={1} max={10} className={inputCls} value={concurrency}
            onChange={(e) => setConcurrency(parseInt(e.target.value, 10) || 1)} />
        </label>
        <label className="block">
          <span className="text-[10.5px] text-t3">max_episodes（成本确认）</span>
          <input type="number" min={1} className={inputCls} value={maxEp}
            onChange={(e) => setMaxEp(parseInt(e.target.value, 10) || 1)} />
        </label>
        <label className="block col-span-2">
          <span className="text-[10.5px] text-t3">续跑 bench_id（留空 = 新建）</span>
          <input className={inputCls} placeholder="bench_live_…" value={benchId}
            onChange={(e) => setBenchId(e.target.value)} />
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button onClick={submit} disabled={busy}
          className="rounded-lg px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
          style={{ background: 'var(--accent)' }}>
          {busy ? '启动中…' : `开始评测${nEp !== null ? `（${nEp} episodes）` : ''}`}
        </button>
        {nEp !== null && (
          <span className="text-[10.5px] text-t3 font-num">
            ≈ {(nEp * days * 12000).toLocaleString()} tokens 上限（续跑部分不计）
          </span>
        )}
      </div>
      {err && <div className="text-[11px] rounded-lg px-3 py-2" style={{ color: 'var(--critical)', background: 'color-mix(in srgb, var(--critical) 8%, transparent)' }}>{err}</div>}
    </div>
  )
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0
  return (
    <div className="relative h-2 rounded-full bg-[var(--hover)] overflow-hidden">
      <div className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, background: 'var(--accent)' }} />
    </div>
  )
}


// 分组均值柱状对比：三档并排，一眼看出分离度
function GroupBars({ agg, groupNames }: { agg: BenchAggregate; groupNames: string[] }) {
  useThemeVersion()
  const groupColor = (g: string) =>
    g.includes('good') || g.includes('优') ? 'var(--good)'
    : g.includes('poor') || g.includes('差') || g.includes('失') ? 'var(--critical)'
    : 'var(--warning)'
  return (
    <div className="rounded-xl border border-edge bg-surface p-4">
      <div className="text-sm font-semibold text-t1 mb-4">分档均值对比</div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
        {SHOWN.map((m) => {
          const vals = groupNames.map((g) => ({ g, v: agg.groups[g].metrics[m.key]?.mean ?? null }))
          const max = Math.max(1e-9, ...vals.map((x) => (x.v === null ? 0 : Math.abs(x.v))))
          return (
            <div key={m.key}>
              <div className="text-[11px] text-t2 mb-1.5">{m.label}</div>
              <div className="space-y-1">
                {vals.map(({ g, v }) => (
                  <div key={g} className="flex items-center gap-2 text-[10.5px]">
                    <span className="w-10 text-t3 truncate shrink-0">{g}</span>
                    <div className="relative flex-1 h-2.5 rounded-full bg-[var(--hover)] overflow-hidden">
                      <div className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                        style={{ width: v === null ? '0%' : `${(Math.abs(v) / max) * 100}%`, background: groupColor(g), opacity: 0.85 }} />
                    </div>
                    <span className="w-14 text-right font-num text-t2 shrink-0">{v === null ? '—' : m.fmt(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function Bench() {
  useThemeVersion()
  const [list, setList] = useState<BenchListItem[]>([])
  const [jobs, setJobs] = useState<BenchJob[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [agg, setAgg] = useState<BenchAggregate | null>(null)
  const [guard, setGuard] = useState<Discriminability | null>(null)
  const [eps, setEps] = useState<BenchEpisode[]>([])
  const [runningEps, setRunningEps] = useState<BenchRunningEp[]>([])

  const refresh = () =>
    api.listBench().then((r) => {
      setList(r.items)
      setJobs(r.jobs)
      if (!sel && r.items.length) setSel(r.items[0].bench_id)
    })

  useEffect(() => { refresh() }, [])

  // 有运行中任务时轮询进度
  useEffect(() => {
    if (!jobs.some((j) => j.status === 'running')) return
    const t = setInterval(refresh, 1500)
    return () => clearInterval(t)
  }, [jobs])

  useEffect(() => {
    if (!sel) return
    api.benchDetail(sel).then((r) => {
      setAgg(r.aggregate ?? null)
      setGuard(r.discriminability ?? null)
      setEps(r.episodes ?? [])
      setRunningEps(r.running ?? [])
    })
  }, [sel, jobs])

  const groupNames = agg ? Object.keys(agg.groups) : []
  const selJob = jobs.find((j) => j.bench_id === sel)

  return (
    <div className="space-y-5">
      <StartForm onStarted={(id) => { setSel(id); refresh() }} />

      {/* 运行中任务：总进度 */}
      {jobs.filter((jb) => jb.status === 'running').map((jb) => (
        <div key={jb.bench_id} className="rounded-xl border border-edge bg-surface p-4">
          <div className="flex items-baseline justify-between mb-2">
            <button onClick={() => setSel(jb.bench_id)}
              className="text-xs font-num text-t1 hover:text-[var(--accent)]">
              {jb.bench_id}
            </button>
            <span className="text-[11px] font-num text-t2">{jb.done}/{jb.total} episodes</span>
          </div>
          <ProgressBar done={jb.done} total={jb.total} />
        </div>
      ))}
      {jobs.filter((jb) => jb.status === 'failed').map((jb) => (
        <div key={jb.bench_id} className="rounded-xl border p-3 text-[11px]"
          style={{ borderColor: 'color-mix(in srgb, var(--critical) 40%, transparent)', color: 'var(--critical)' }}>
          {jb.bench_id} 失败：{jb.error}
        </div>
      ))}

      {/* 批量选择 */}
      {list.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {list.map((b) => (
            <button key={b.bench_id} onClick={() => setSel(b.bench_id)}
              className={`rounded-lg border px-3 py-1.5 text-[11px] font-num transition-colors ${
                sel === b.bench_id ? 'border-[color-mix(in_srgb,var(--accent)_50%,transparent)] bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-[var(--accent)]' : 'border-edge text-t2 hover:text-t1'}`}>
              {b.status === 'running' && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: 'var(--warning)' }} />}
              {b.bench_id.replace('bench_', '')} · {b.episodes_done ?? b.n_episodes}/{b.n_episodes}ep{b.days ? ` · ${b.days}d` : ''}
            </button>
          ))}
        </div>
      )}

      {/* 选中 bench 的进行中 episode（逐个进度） */}
      {selJob?.status === 'running' && runningEps.length > 0 && (
        <div className="rounded-xl border border-edge bg-surface p-4">
          <div className="text-sm font-semibold text-t1 mb-3">正在运行的 episode（{runningEps.length}）</div>
          <div className="space-y-2">
            {runningEps.map((e) => (
              <div key={e.run_id}>
                <div className="flex justify-between text-[11px] font-num text-t2 mb-1">
                  <span>{e.run_id}</span>
                  <span>{e.progress ? `${Math.floor(e.progress.slot / 4)}/${(e.progress.total || 0) / 4} 天` : '启动中'}</span>
                </div>
                <ProgressBar done={e.progress?.slot ?? 0} total={e.progress?.total ?? 1} />
              </div>
            ))}
          </div>
        </div>
      )}

      {guard && <GuardCard d={guard} />}

      {agg && groupNames.length > 0 && <GroupBars agg={agg} groupNames={groupNames} />}

      {/* 聚合表 */}
      {agg && (
        <div className="rounded-xl border border-edge bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-edge flex items-baseline gap-3">
            <span className="text-sm font-semibold text-t1">分组聚合</span>
            <span className="text-[10.5px] text-t3 font-num">
              n={agg.n_episodes} · {agg.days} 天 · mean ± 95% CI
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-t3 border-b border-edge">
                  <th className="text-left px-4 py-2 font-medium">指标</th>
                  {groupNames.map((g) => (
                    <th key={g} className="text-right px-4 py-2 font-medium">{g}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-edge">
                  <td className="px-4 py-2 text-t2">判定众数</td>
                  {groupNames.map((g) => {
                    const v = agg.groups[g].verdict_mode
                    const meta = VERDICTS[v]
                    return (
                      <td key={g} className="text-right px-4 py-2">
                        <span style={{ color: meta ? cssVar(meta.cssVar) : cssVar('--text-3') }}>{meta?.label ?? v}</span>
                      </td>
                    )
                  })}
                </tr>
                <tr className="border-b border-edge">
                  <td className="px-4 py-2 text-t2">从未回带</td>
                  {groupNames.map((g) => (
                    <td key={g} className="text-right px-4 py-2 font-num text-t2">
                      {agg.groups[g].never_settled}/{agg.groups[g].n}
                    </td>
                  ))}
                </tr>
                <tr className="border-b border-edge">
                  <td className="px-4 py-2 text-t2">判定一致率</td>
                  {groupNames.map((g) => (
                    <td key={g} className="text-right px-4 py-2 font-num text-t2">
                      {agg.groups[g].verdict_consistency !== undefined
                        ? `${(agg.groups[g].verdict_consistency! * 100).toFixed(0)}%` : '—'}
                    </td>
                  ))}
                </tr>
                <tr className="border-b border-edge">
                  <td className="px-4 py-2 text-t2">benchmark 组内 sd</td>
                  {groupNames.map((g) => {
                    const sd = agg.groups[g].metrics.benchmark_score?.std
                    return (
                      <td key={g} className="text-right px-4 py-2 font-num text-t2">
                        {sd !== null && sd !== undefined ? sd.toFixed(1) : '—'}
                      </td>
                    )
                  })}
                </tr>
                <tr className="border-b border-edge">
                  <td className="px-4 py-2 text-t2">协议违约（次数）</td>
                  {groupNames.map((g) => (
                    <td key={g} className="text-right px-4 py-2 text-t1">
                      <Stat s={agg.groups[g].metrics.contract_violations} fmt={(v) => v.toFixed(1)} />
                    </td>
                  ))}
                </tr>
                <tr className="border-b border-edge">
                  <td className="px-4 py-2 text-t2">协议违约率（每助手 turn）</td>
                  {groupNames.map((g) => (
                    <td key={g} className="text-right px-4 py-2 text-t1">
                      <Stat s={agg.groups[g].metrics.contract_violation_rate} fmt={(v) => `${(v * 100).toFixed(1)}%`} />
                    </td>
                  ))}
                </tr>
                <tr className="border-b border-edge">
                  <td className="px-4 py-2 text-t2">超时率（provider 侧，不计分）</td>
                  {groupNames.map((g) => (
                    <td key={g} className="text-right px-4 py-2 text-t2">
                      <Stat s={agg.groups[g].metrics.contract_timeout_rate} fmt={(v) => `${(v * 100).toFixed(1)}%`} />
                    </td>
                  ))}
                </tr>
                {SHOWN.map((m) => (
                  <tr key={m.key} className="border-b border-edge last:border-0">
                    <td className="px-4 py-2 text-t2">{m.label}</td>
                    {groupNames.map((g) => (
                      <td key={g} className="text-right px-4 py-2 text-t1">
                        <Stat s={agg.groups[g].metrics[m.key]} fmt={m.fmt} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {agg.mde && agg.mde.pairs.length > 0 && (
            <div className="px-4 py-3 border-t border-edge">
              <div className="text-[10.5px] text-t3 leading-relaxed">
                统计效力脚注（α={agg.mde.alpha}，power={agg.mde.power}）：当前 n 下两组间可检测的最小效应——
                benchmark 均值差 / 方差比。差值小于 MDE 的"无差异"结论不具统计效力。
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5">
                {agg.mde.pairs.map((p) => {
                  const bs = p.metrics.benchmark_score
                  if (!bs) return null
                  return (
                    <span key={`${p.a}-${p.b}`} className="text-[10.5px] font-num text-t3">
                      {p.a} vs {p.b}：{bs.mde_mean !== null ? `Δ≥${bs.mde_mean.toFixed(1)}` : 'n 不足'}
                      {bs.mde_var_ratio !== null ? ` · 方差比≥${bs.mde_var_ratio.toFixed(1)}` : ''}
                    </span>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* episode 明细 */}
      {eps.length > 0 && (
        <div className="rounded-xl border border-edge bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-edge text-sm font-semibold text-t1">
            episode 明细（{eps.length}）
          </div>
          <div className="max-h-[340px] overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0" style={{ background: 'var(--surface-2)' }}>
                <tr className="text-t3">
                  <th className="text-left px-4 py-2 font-medium">episode</th>
                  <th className="text-left px-3 py-2 font-medium">判定</th>
                  <th className="text-right px-3 py-2 font-medium">e_ss</th>
                  <th className="text-right px-3 py-2 font-medium">带内</th>
                  <th className="text-right px-4 py-2 font-medium">健康分</th>
                </tr>
              </thead>
              <tbody>
                {eps.map((e) => {
                  const meta = VERDICTS[e.metrics.verdict]
                  return (
                    <tr key={e.run_id} className="border-t border-edge">
                      <td className="px-4 py-1.5 font-num text-t2">{e.label}</td>
                      <td className="px-3 py-1.5" style={{ color: meta ? cssVar(meta.cssVar) : cssVar('--text-3') }}>
                        {meta?.label ?? e.metrics.verdict}
                      </td>
                      <td className="text-right px-3 py-1.5 font-num text-t2">
                        {typeof e.metrics.ess === 'number' ? e.metrics.ess.toFixed(4) : '—'}
                      </td>
                      <td className="text-right px-3 py-1.5 font-num text-t2">
                        {typeof e.metrics.in_band_ratio === 'number' ? `${(e.metrics.in_band_ratio * 100).toFixed(0)}%` : '—'}
                      </td>
                      <td className="text-right px-4 py-1.5 font-num text-t2">
                        {e.metrics.health_score ?? '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!list.length && (
        <p className="text-xs text-t3">还没有批量结果。在上方表单勾选组与种子后点击"开始评测"即可发起（烧 token，需确认 max_episodes）。</p>
      )}
    </div>
  )
}
