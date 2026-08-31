import { useMemo } from 'react'
import { Persona, PersonaBelief, Report, Turn } from '../api'
import { BIG5_FACETS, PREF_CATEGORIES, cssVar, useThemeVersion } from '../components/theme'
import { PlainCard as Card } from '../components/ui'
import { ChartGrid, ThemedXAxis, ThemedYAxis, ThemedTooltip, useChartAnimation } from '../components/charts'
import { ComposedChart, Line, ResponsiveContainer } from 'recharts'

/** 真值 vs 估计的双游标条：真值填充，估计用白色游标（与 StateBars 视觉语言一致）。 */
function FacetRow({ label, truth, est }: { label: string; truth: number; est?: number; }) {
  const color = cssVar('--text-3')
  const gap = est === undefined ? null : Math.abs(truth - est)
  const gapColor = gap === null ? '' : gap <= 10 ? 'text-[var(--good)]' : gap <= 25 ? 'text-[var(--warning)]' : 'text-[var(--critical)]'
  return (
    <div>
      <div className="flex justify-between text-[10.5px] mb-0.5">
        <span className="text-t2">{label}</span>
        <span className="font-num text-t2">
          {truth}
          {est !== undefined ? <><span className="text-t3"> / 估 </span><span className={gapColor}>{est}</span></> : <span className="text-t3"> / 未估</span>}
        </span>
      </div>
      <div className="relative h-1.5 rounded-full bg-[var(--hover)] overflow-hidden">
        <div className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
          style={{ width: `${truth}%`, background: color, opacity: 0.9 }} />
        {est !== undefined && (
          <div className="absolute top-1/2 -translate-y-1/2 h-2.5 w-[3px] rounded-full bg-[var(--text-1)] transition-all duration-500"
            style={{ left: `calc(${est}% - 1px)` }} />
        )}
      </div>
    </div>
  )
}

/** 一个大五域：域内 6 个 facet 的真值/估计对照。 */
function DomainBlock({ domain, color, facets, truth, est }: {
  domain: string; color: string; facets: string[]
  truth: Record<string, number>; est: Record<string, number>
}) {
  const rows = facets.map((f) => {
    const key = `${domain}.${f}`
    return { f, key, truth: truth[key], est: est[key] }
  }).filter((r) => r.truth !== undefined)
  if (!rows.length) return null
  const domainTruth = Math.round(rows.reduce((s, r) => s + r.truth, 0) / rows.length)
  const estRows = rows.filter((r) => r.est !== undefined)
  const domainEst = estRows.length ? Math.round(estRows.reduce((s, r) => s + (r.est as number), 0) / estRows.length) : null

  return (
    <div className="rounded-lg border p-2.5" style={{ borderColor: `${color}33`, background: `${color}0a` }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[12px] font-semibold" style={{ color }}>{domain}</span>
        <span className="font-num text-[10.5px] text-t2">
          域分 {domainTruth}{domainEst !== null && <span className="text-t3"> / 估 {domainEst}</span>}
        </span>
      </div>
      <div className="space-y-1.5">
        {rows.map((r) => <FacetRow key={r.key} label={r.f} truth={r.truth} est={r.est} />)}
      </div>
    </div>
  )
}

/** 喜好类目对照条：真值与估计都在 [-1,1]，中线为 0。 */
function PrefRow({ label, truth, est }: { label: string; truth?: number; est?: number }) {
  const t = truth ?? 0
  const pos = (v: number) => 50 + v * 50
  return (
    <div>
      <div className="flex justify-between text-[10.5px] mb-0.5">
        <span className="text-t2">{label}</span>
        <span className="font-num">
          <span className={t >= 0 ? 'text-[var(--good)]' : 'text-[var(--critical)]'}>{t.toFixed(2)}</span>
          {est !== undefined ? <span className="text-t3"> / 估 {est.toFixed(2)}</span> : <span className="text-t3"> / 未估</span>}
        </span>
      </div>
      <div className="relative h-1.5 rounded-full bg-[var(--hover)] overflow-hidden">
        <div className="absolute inset-y-0 w-px bg-[var(--axis)]" style={{ left: '50%' }} />
        <div className="absolute inset-y-0 rounded-full transition-all duration-500"
          style={{
            left: `${Math.min(50, pos(t))}%`, width: `${Math.abs(t) * 50}%`,
            background: t >= 0 ? 'var(--good)' : 'var(--critical)', opacity: 0.85,
          }} />
        {est !== undefined && (
          <div className="absolute top-1/2 -translate-y-1/2 h-2.5 w-[3px] rounded-full bg-[var(--text-1)] transition-all duration-500"
            style={{ left: `calc(${pos(est)}% - 1px)` }} />
        )}
      </div>
    </div>
  )
}

/** 标签命中对照：命中绿、漏报灰、瞎猜黄。 */
function TagCompare({ title, truth, est }: { title: string; truth: string[]; est: string[] }) {
  const hit = (a: string, list: string[]) => list.some((b) => a.includes(b) || b.includes(a))
  return (
    <div>
      <div className="text-[10.5px] text-t3 mb-1">{title}</div>
      <div className="flex flex-wrap gap-1">
        {truth.map((t) => (
          <span key={`t-${t}`} className={`rounded px-1.5 py-0.5 text-[10px] border ${
            hit(t, est) ? 'border-[color-mix(in_srgb,var(--good)_50%,transparent)] bg-[color-mix(in_srgb,var(--good)_10%,transparent)] text-[var(--good)]'
                        : 'border-edge bg-surface-2 text-t3'}`}>
            {t}{hit(t, est) ? ' ✓' : ''}
          </span>
        ))}
        {est.filter((e) => !hit(e, truth)).map((e) => (
          <span key={`e-${e}`} className="rounded px-1.5 py-0.5 text-[10px] border border-[color-mix(in_srgb,var(--warning)_40%,transparent)] bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] text-[var(--warning)]">
            {e} ?
          </span>
        ))}
        {!truth.length && !est.length && <span className="text-[10px] text-t3">（无）</span>}
      </div>
    </div>
  )
}

/** 取当前时刻（curT）之前最后一个有画像估计的助手 turn。 */
export function usePersonaHat(turns: Turn[], curT: number): { hat: PersonaBelief | null; turnId: number | null } {
  return useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      if (turns[i].persona_hat && turns[i].t_logical <= curT) {
        return { hat: turns[i].persona_hat as PersonaBelief, turnId: turns[i].turn_id }
      }
    }
    return { hat: null, turnId: null }
  }, [turns, curT])
}

/** 逐 facet 平均绝对误差（归一到 0-1），与后端 contracts.persona.facet_error 同定义。 */
function facetErr(truth: Record<string, number>, est: Record<string, number>): number | null {
  const keys = Object.keys(est).filter((k) => truth[k] !== undefined)
  if (!keys.length) return null
  return keys.reduce((s, k) => s + Math.abs(truth[k] - est[k]), 0) / keys.length / 100
}

/** 侧栏紧凑版：当前 turn 的画像估计概览（覆盖率 / 误差 / 置信度）。 */
export function PersonaSummary({ persona, hat }: { persona?: Persona | null; hat: PersonaBelief | null }) {
  useThemeVersion()
  if (!persona) return null
  const truth = persona.facets ?? {}
  const nTruth = Object.keys(truth).length
  if (!nTruth) return <p className="text-[11px] text-t3">该存档未记录人格细分特质（旧版本）</p>
  const cov = hat ? Object.keys(hat.facets).length / nTruth : 0
  const err = hat ? facetErr(truth, hat.facets) : null
  return (
    <div className="rounded-lg bg-surface-2 p-2.5 text-[11px] space-y-1">
      <div className="flex justify-between"><span className="text-t3">画像覆盖</span>
        <span className="font-num text-t1">{(cov * 100).toFixed(0)}% · {hat ? Object.keys(hat.facets).length : 0}/{nTruth}</span></div>
      <div className="flex justify-between"><span className="text-t3">人格误差</span>
        <span className={`font-num ${err === null ? 'text-t3' : err <= 0.12 ? 'text-[var(--good)]' : err <= 0.25 ? 'text-[var(--warning)]' : 'text-[var(--critical)]'}`}>
          {err === null ? '未估计' : err.toFixed(3)}</span></div>
      <div className="flex justify-between"><span className="text-t3">助手置信度</span>
        <span className="font-num text-t2">{hat ? hat.confidence.toFixed(2) : '—'}</span></div>
      {hat?.notes && <div className="text-[10px] text-t3 leading-snug pt-1 border-t border-edge">{hat.notes}</div>}
    </div>
  )
}

/** 主面板：真实人格/喜好 vs 助手逐 turn 估计（随时间游标更新）。 */
export function PersonaPanel({ persona, turns, curT, report }: {
  persona?: Persona | null; turns: Turn[]; curT: number; report: Report | null
}) {
  useThemeVersion()
  const anim = useChartAnimation()
  const { hat, turnId } = usePersonaHat(turns, curT)
  if (!persona) return <p className="text-sm text-t3">加载角色卡…</p>
  const truth = persona.facets ?? {}
  if (!Object.keys(truth).length) {
    return <p className="text-sm text-t3">该存档未记录人格细分特质（在本功能上线前生成）。</p>
  }
  const est = hat?.facets ?? {}
  const err = facetErr(truth, est)
  const trueCats = persona.prefs?.categories ?? {}
  const estCats = hat?.categories ?? {}

  return (
    <div className="space-y-4">
      {/* 概览 */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div>
            <div className="text-sm font-semibold text-t1">{persona.name} · {persona.archetype}</div>
            <div className="text-[11px] text-t3 mt-0.5">{persona.likes}</div>
          </div>
          <div className="ml-auto flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
            <span className="text-t3">人格误差 <span className={`font-num ${err === null ? 'text-t3' : err <= 0.12 ? 'text-[var(--good)]' : 'text-[var(--warning)]'}`}>{err === null ? '—' : err.toFixed(3)}</span></span>
            <span className="text-t3">覆盖 <span className="font-num text-t1">{Object.keys(est).length}/{Object.keys(truth).length}</span></span>
            <span className="text-t3">置信度 <span className="font-num text-t1">{hat ? hat.confidence.toFixed(2) : '—'}</span></span>
            {turnId !== null && <span className="text-t3 font-num">来自 turn {turnId + 1}</span>}
          </div>
        </div>
      </Card>

      {/* 人格 30 facet 对照 */}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {BIG5_FACETS.map((d) => (
          <DomainBlock key={d.domain} domain={d.domain} color={cssVar(d.cssVar)} facets={d.facets}
            truth={truth} est={est} />
        ))}
      </div>

      {/* 喜好对照 + 学习曲线 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <div className="text-sm font-semibold text-t1 mb-1">喜好类目：真值 vs 估计</div>
          <p className="text-[11px] text-t3 mb-3">填充为角色卡真值，白色游标为助手估计</p>
          <div className="space-y-2">
            {PREF_CATEGORIES.map((c) => (
              <PrefRow key={c} label={c} truth={trueCats[c]} est={estCats[c]} />
            ))}
          </div>
          <div className="mt-4 space-y-2.5 pt-3 border-t border-edge">
            <TagCompare title="明确偏爱（loves）" truth={persona.prefs?.loves ?? []} est={hat?.loves ?? []} />
            <TagCompare title="明确反感（hates）" truth={persona.prefs?.hates ?? []} est={hat?.hates ?? []} />
            <div className="grid grid-cols-3 gap-2 text-[10.5px] pt-1">
              {([
                ['打扰容忍', persona.prefs?.interruption_tolerance?.toFixed(2), hat?.interruption_tolerance?.toFixed(2)],
                ['做事风格', persona.prefs?.planning_style, hat?.planning_style],
                ['回血方式', persona.prefs?.social_recharge, hat?.social_recharge],
              ] as [string, string | undefined | null, string | undefined | null][]).map(([label, t, e]) => (
                <div key={label} className="rounded bg-surface-2 p-1.5">
                  <div className="text-t3">{label}</div>
                  <div className="text-t1">{t ?? '—'}</div>
                  <div className={e && t && String(e) === String(t) ? 'text-[var(--good)]' : 'text-t3'}>
                    估 {e ?? '未估'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card className="p-4">
          <div className="text-sm font-semibold text-t1 mb-1">画像学习曲线</div>
          <p className="text-[11px] text-t3 mb-3">
            每日人格估计误差（越低越准）
            {report && Number.isFinite(report.persona_err_slope_per_day) &&
              ` · 斜率 ${report.persona_err_slope_per_day.toFixed(5)}/天`}
            {report && Number.isFinite(report.prefs_err_final) &&
              ` · 喜好误差 ${report.prefs_err_final.toFixed(3)} · 爱憎 F1 ${report.prefs_tag_f1.toFixed(2)}`}
          </p>
          <div className="h-[300px]">
            <ResponsiveContainer>
              <ComposedChart data={report?.daily_persona_err ?? []} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
                <ChartGrid />
                <ThemedXAxis dataKey="day" />
                <ThemedYAxis domain={[0, 'auto']} />
                <Line {...anim} type="monotone" dataKey="err" name="画像误差" stroke={cssVar('--series')} strokeWidth={2} dot={false} />
                <ThemedTooltip labelFormatter={(x: number) => `第 ${Number(x) + 1} 天`} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
    </div>
  )
}
