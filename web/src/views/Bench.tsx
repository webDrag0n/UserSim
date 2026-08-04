import { useEffect, useState } from 'react'
import {
  api,
  type BenchAggregate, type BenchEpisode, type BenchJob,
  type BenchListItem, type Discriminability, type MetricStat,
} from '../api'
import { VERDICTS, cssVar, useThemeVersion } from '../components/theme'
import { Button, Segmented } from '../components/ui'

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
  const rows: [string, string][] = [
    ['margin_good', d.margin_good === null ? '—' : d.margin_good.toFixed(4)],
    ['margin_poor', d.margin_poor === null ? '—' : d.margin_poor.toFixed(4)],
    ['separation (Cohen’s d)', d.separation === null ? '—' : d.separation.toFixed(2)],
  ]
  return (
    <div className="rounded-xl border p-4" style={{ borderColor: d.ok ? 'color-mix(in srgb, var(--good) 40%, transparent)' : 'color-mix(in srgb, var(--critical) 40%, transparent)', background: d.ok ? 'color-mix(in srgb, var(--good) 8%, transparent)' : 'color-mix(in srgb, var(--critical) 8%, transparent)' }}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-semibold text-t1">量程守护</span>
        <span className="text-xs px-2 py-0.5 rounded-full font-semibold"
          style={{ background: d.ok ? 'color-mix(in srgb, var(--good) 18%, transparent)' : 'color-mix(in srgb, var(--critical) 18%, transparent)', color: d.ok ? 'var(--good)' : 'var(--critical)' }}>
          {d.ok ? '通过' : '未通过'}
        </span>
      </div>
      <p className="text-[11px] text-t2 mb-3 leading-relaxed">
        世界能否分辨好助手与差助手。good 需低于收敛阈值 {d.thresholds.converged_ess_max}，
        poor 需高于发散阈值 {d.thresholds.diverged_ess_min}，两档需清晰分离（d&gt;1.5）。
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
        {Object.entries(d.checks).map(([k, ok]) => (
          <span key={k} className="text-[11px]" style={{ color: ok ? 'var(--good)' : 'var(--critical)' }}>
            {ok ? '✓' : '✗'} {k}
          </span>
        ))}
      </div>
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
  const [seeds, setSeeds] = useState('1-8')
  const [days, setDays] = useState(30)
  const [busy, setBusy] = useState(false)

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
    })
  }, [sel, jobs])

  const start = async () => {
    setBusy(true)
    try {
      await api.startBench({ seeds, days, mode: 'replay' })
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const groupNames = agg ? Object.keys(agg.groups) : []

  return (
    <div className="space-y-5">
      {/* 启动栏 */}
      <div className="rounded-xl border border-edge bg-surface p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-[10px] text-t3 mb-1">seeds</label>
            <input value={seeds} onChange={(e) => setSeeds(e.target.value)}
              className="w-28 rounded-lg bg-surface-2 border border-edge px-2 py-1.5 text-xs font-num text-t1" />
          </div>
          <div>
            <label className="block text-[10px] text-t3 mb-1">天数</label>
            <input type="number" value={days} onChange={(e) => setDays(+e.target.value)}
              className="w-20 rounded-lg bg-surface-2 border border-edge px-2 py-1.5 text-xs font-num text-t1" />
          </div>
          <Button onClick={start} disabled={busy} className="!py-1.5 !text-xs">
            {busy ? '启动中…' : '跑三档批量（replay · 0 token）'}
          </Button>
          <span className="text-[10.5px] text-t3">
            live 批量需用 CLI 显式确认成本：<code className="text-t2">bench --mode live --max-episodes N</code>
          </span>
        </div>
        {jobs.filter((jb) => jb.status === 'running').map((jb) => (
          <div key={jb.bench_id} className="mt-3 text-xs font-num">
            {jb.bench_id} · {jb.done}/{jb.total}
          </div>
        ))}
      </div>

      {/* 批量选择 */}
      {list.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {list.map((b) => (
            <button key={b.bench_id} onClick={() => setSel(b.bench_id)}
              className={`rounded-lg border px-3 py-1.5 text-[11px] font-num transition-colors ${
                sel === b.bench_id ? 'border-[color-mix(in_srgb,var(--accent)_50%,transparent)] bg-[color-mix(in_srgb,var(--accent)_15%,transparent)] text-[var(--accent)]' : 'border-edge text-t2 hover:text-t1'}`}>
              {b.bench_id.replace('bench_', '')} · {b.n_episodes}ep · {b.days}d
            </button>
          ))}
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
        <p className="text-xs text-t3">还没有批量结果。点上面的按钮跑一次三档回放（零 token）。</p>
      )}
    </div>
  )
}
