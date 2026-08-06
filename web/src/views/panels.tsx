import { useEffect, useMemo, useState } from 'react'
import {
  ComposedChart, Line, Bar, ReferenceLine, ReferenceArea, ResponsiveContainer, Legend,
} from 'recharts'
import { api, Report, RunEvent, SeriesInfo, Slot, Turn } from '../api'
import { DIMS, BAND, VERDICTS, cssVar, useThemeVersion } from '../components/theme'
import { ChartGrid, ThemedXAxis, ThemedYAxis, ThemedTooltip } from '../components/charts'
import { PlainCard as Card, Stat } from '../components/ui'

// ---------- 轨迹面板：状态轨迹 + 金钱 ----------
export function TrajectoryPanel({ slots, series = [] }: { slots: Slot[]; series?: SeriesInfo[] }) {
  useThemeVersion()
  const [view, setView] = useState<'valence' | 'energy' | 'satiety' | 'stress' | 'money'>('stress')
  const dim = DIMS.find((d) => d.key === (view === 'money' ? 'stress' : view))!
  const dimColor = cssVar(dim.cssVar)
  const chartData = useMemo(() => slots.map((s) => ({
    day: +(s.t_logical / 4).toFixed(2),
    value: view === 'money' ? +s.money_after.toFixed(0) : +s.x_after[view as 'stress'].toFixed(4),
  })), [slots, view])
  const disturbDays = useMemo(() => {
    const days = new Set<number>()
    slots.forEach((s) => {
      if (Object.entries(s.event_effects).some(([k, v]) => k !== 'energy' && Math.abs(v) > 0.005)) days.add(Math.floor(s.t_logical / 4))
    })
    return [...days]
  }, [slots])

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <span className="text-sm font-semibold text-t1 mr-2">状态轨迹 vs 设定点</span>
        {[...DIMS.map((d) => d.key), 'money' as const].map((k) => (
          <button key={k} onClick={() => setView(k as any)}
            className={`rounded-lg px-3 py-1 text-xs transition-colors ${view === k ? 'bg-[var(--hover)] text-t1' : 'text-t3 hover:text-t2'}`}>
            {k === 'money' ? '金钱' : DIMS.find((d) => d.key === k)!.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-t3 font-num">虚线 = 事件效果日</span>
      </div>
      <div className="h-[300px]">
        <ResponsiveContainer>
          <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
            <ChartGrid />
            <ThemedXAxis dataKey="day" type="number" domain={[0, 'dataMax']} tickFormatter={(x: number) => `${Math.floor(x)}`} />
            <ThemedYAxis domain={view === 'money' ? ['auto', 'auto'] : [0, 1]} />
            <ThemedTooltip labelFormatter={(x: number) => `第 ${Math.floor(Number(x)) + 1} 天`}
              formatter={(val: number) => [view === 'money' ? `¥${val}` : val.toFixed(3), view === 'money' ? '金钱' : dim.label]} />
            {view !== 'money' && (
              <>
                <ReferenceLine y={dim.target} stroke={dimColor} strokeDasharray="6 4"
                  label={{ value: `目标 ${dim.target}`, fill: dimColor, fontSize: 10, position: 'right' }} />
                <ReferenceArea
                  y1={dim.good === 'high' ? dim.target - BAND : dim.target}
                  y2={dim.good === 'high' ? dim.target : dim.target + BAND}
                  fill={dimColor} fillOpacity={0.07} />
              </>
            )}
            {disturbDays.map((d, i) => <ReferenceLine key={i} x={d} stroke="var(--critical)" strokeOpacity={0.3} strokeDasharray="3 4" />)}
            {series.map((s) => (
              <ReferenceArea key={s.id} x1={s.start_day} x2={s.end_day} fill={cssVar('--series')} fillOpacity={0.08}
                label={{ value: `${s.icon}${s.name}`, fill: cssVar('--series'), fontSize: 10, position: 'insideTop' }} />
            ))}
            <Line type="monotone" dataKey="value" stroke={view === 'money' ? cssVar('--satiety') : dimColor} strokeWidth={1.8} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

// ---------- 经济面板 ----------
export function EconomyPanel({ slots, events }: { slots: Slot[]; events: RunEvent[] }) {
  const daily = useMemo(() => {
    const days = Math.ceil(slots.length / 4)
    return Array.from({ length: days }, (_, d) => {
      const daySlots = slots.slice(d * 4, (d + 1) * 4)
      const m0 = daySlots[0]?.money_before ?? 0
      const m1 = daySlots[daySlots.length - 1]?.money_after ?? m0
      const spend = events.filter((e) => Math.floor(e.start_slot / 4) === d && e.cost > 0).reduce((s, e) => s + e.cost, 0)
      return { day: d, money: +m1.toFixed(0), delta: +(m1 - m0).toFixed(0), spend }
    })
  }, [slots, events])
  const totalCost = events.reduce((s, e) => s + e.cost, 0)
  const totalIncome = events.reduce((s, e) => s + e.income, 0)

  if (!slots.length) return <p className="text-sm text-t3 py-10 text-center">等待第一个时段结算…</p>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="期末余额" value={slots.length ? Math.round(slots[slots.length - 1].money_after) : 0} prefix="¥" color="var(--satiety)" />
        <Stat label="事件总消费" value={totalCost} prefix="¥" color="var(--critical)" />
        <Stat label="事件总收入（加班）" value={totalIncome} prefix="¥" color="var(--good)" />
      </div>
      <Card className="p-5">
        <div className="text-sm font-semibold text-t1 mb-4">每日收支（柱：日净变动 · 消费 · 线：余额）</div>
        <div className="h-[280px]">
          <ResponsiveContainer>
            <ComposedChart data={daily} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
              <ChartGrid />
              <ThemedXAxis dataKey="day" tickFormatter={(x: number) => `${x + 1}`} />
              <ThemedYAxis yAxisId="left" />
              <ThemedYAxis yAxisId="right" orientation="right" />
              <ThemedTooltip labelFormatter={(x: number) => `第 ${Number(x) + 1} 天`} />
              <Legend wrapperStyle={{ fontSize: 11, color: cssVar('--text-2') }} />
              <Bar yAxisId="left" dataKey="delta" name="日净变动" fill={cssVar('--energy')} radius={[3, 3, 0, 0]} />
              <Bar yAxisId="left" dataKey="spend" name="事件消费" fill={cssVar('--critical')} radius={[3, 3, 0, 0]} />
              <Line yAxisId="right" type="monotone" dataKey="money" name="余额" stroke={cssVar('--satiety')} strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  )
}

// ---------- 估计误差面板 ----------
export function EstErrPanel({ report, turns }: { report: Report | null; turns: Turn[] }) {
  useThemeVersion()
  const perTurn = useMemo(() => turns.filter((t) => t.x_hat).map((t) => ({
    idx: t.turn_id,
    err: +Math.sqrt(
      (t.x_true.valence - t.x_hat!.valence) ** 2 + (t.x_true.energy - t.x_hat!.energy) ** 2 +
      (t.x_true.satiety - t.x_hat!.satiety) ** 2 + (t.x_true.stress - t.x_hat!.stress) ** 2,
    ).toFixed(4),
  })), [turns])
  if (!report) return <p className="text-sm text-t3">报告计算中…</p>
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Card className="p-5">
        <div className="text-sm font-semibold text-t1 mb-1">每日估计误差 ‖x−x̂‖₂</div>
        <p className="text-xs text-t3 mb-4">终值 {report.est_err_final.toFixed(3)} · 斜率 {report.est_err_slope_per_day.toFixed(5)}/天</p>
        <div className="h-[240px]">
          <ResponsiveContainer>
            <ComposedChart data={report.daily_est_err} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
              <ChartGrid />
              <ThemedXAxis dataKey="day" />
              <ThemedYAxis />
              <ThemedTooltip />
              <Line type="monotone" dataKey="err" stroke={cssVar('--persona')} strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card className="p-5">
        <div className="text-sm font-semibold text-t1 mb-1">逐 turn 估计误差</div>
        <p className="text-xs text-t3 mb-4">每个助手 turn 的 x̂ 与真实 x 的距离（{perTurn.length} 个样本）</p>
        <div className="h-[240px]">
          <ResponsiveContainer>
            <ComposedChart data={perTurn} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
              <ChartGrid />
              <ThemedXAxis dataKey="idx" />
              <ThemedYAxis />
              <ThemedTooltip />
              <Line type="monotone" dataKey="err" stroke={cssVar('--accent')} strokeWidth={1.5} dot={{ r: 1.5, fill: cssVar('--accent') }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  )
}

// ---------- 指标面板 ----------
export function MetricsPanel({ report }: { report: Report | null }) {
  useThemeVersion()
  if (!report) return <p className="text-sm text-t3">报告计算中…</p>
  const v = VERDICTS[report.verdict]
  const vColor = cssVar(v.cssVar)
  const metrics = [
    { label: '稳态误差', sym: 'e_ss', val: report.ess.toFixed(3), hint: '窗口末端 mean |x−r|，越小越收敛' },
    { label: '调节时间', sym: 't_s', val: report.settling_time_days === null ? '未稳定' : `${report.settling_time_days.toFixed(2)} 天`, hint: '扰动后重新入带并保持的天数' },
    { label: '超调量', sym: 'M_p', val: report.overshoot.toFixed(3), hint: '校正过猛把状态反向压出目标的深度' },
    { label: '带内驻留比', sym: 'ρ', val: `${Math.round(report.in_band_ratio * 100)}%`, hint: '后 10 天处于平和带的时段占比' },
    { label: 'IAE', sym: '∫|e|', val: report.iae.toFixed(2), hint: '全程误差总量' },
    { label: 'ISE', sym: '∫e²', val: report.ise.toFixed(2), hint: '惩罚大偏差' },
    { label: 'ITAE', sym: '∫t|e|', val: report.itae.toFixed(2), hint: '惩罚迟迟不恢复' },
    { label: '状态方差', sym: 'σ²', val: report.variance.toFixed(4), hint: '情绪波动剧烈程度' },
  ]
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border p-5" style={{ borderColor: `color-mix(in srgb, ${vColor} 30%, transparent)`, background: `color-mix(in srgb, ${vColor} 6%, transparent)` }}>
        <span className="text-lg font-bold" style={{ color: vColor }}>{v.icon} 判定：{v.label}</span>
        <span className="ml-3 text-xs text-t2">
          {report.verdict === 'converged' ? '扰动后快速回到平和带并保持' :
           report.verdict === 'oscillating' ? '能回稳但反复过冲，存在极限环' : '状态持续偏离，无法恢复'}
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {metrics.map((m) => (
          <Card key={m.sym} className="p-4">
            <div className="text-[11px] text-t3">{m.label} <span className="font-num text-t3">{m.sym}</span></div>
            <div className="mt-1.5 text-xl font-bold font-num text-t1">{m.val}</div>
            <div className="mt-1 text-[10.5px] text-t3 leading-snug">{m.hint}</div>
          </Card>
        ))}
      </div>
    </div>
  )
}

// ---------- 洞察面板：免读轨迹的完整优化报告 ----------
const SEV_META: Record<string, { icon: string; color: string; label: string }> = {
  error: { icon: '✖', color: 'var(--critical)', label: '故障' },
  warn: { icon: '⚠', color: 'var(--warning)', label: '警告' },
  info: { icon: 'ℹ', color: 'var(--energy)', label: '信息' },
}

function MiniTable({ cols, rows, note }: { cols: string[]; rows: (string | number | null)[][]; note?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-t3 border-b border-edge">
            {cols.map((c, i) => <th key={i} className="pb-1.5 pr-3 font-medium whitespace-nowrap">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-edge">
              {r.map((v, j) => <td key={j} className="py-1.5 pr-3 text-t2 whitespace-nowrap">{v ?? '—'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {note && <p className="text-[10px] text-t3 mt-1.5">{note}</p>}
    </div>
  )
}

export function InsightsPanel({ runId }: { runId: string }) {
  const [data, setData] = useState<any>(null)
  useEffect(() => { api.insights(runId).then(setData).catch(() => {}) }, [runId])
  if (!data) return <p className="text-sm text-t3">诊断计算中…</p>

  const score = data.health_score
  const scoreColor = score >= 80 ? 'var(--good)' : score >= 60 ? 'var(--warning)' : 'var(--critical)'
  const grouped: Record<string, any[]> = { error: [], warn: [], info: [] }
  data.findings.forEach((f: any) => (grouped[f.severity] ?? grouped.info).push(f))
  const eco = data.stats.economy ?? {}
  const rep = data.stats.repetition ?? { user_top: [], assistant_top: [] }

  return (
    <div className="space-y-4">
      {/* 摘要 + 健康分 */}
      <Card className="p-5 flex items-start gap-5">
        <div className="shrink-0 text-center">
          <div className="relative w-20 h-20">
            <svg viewBox="0 0 80 80" className="w-20 h-20 -rotate-90">
              <circle cx="40" cy="40" r="34" fill="none" stroke="var(--hover)" strokeWidth="7" />
              <circle cx="40" cy="40" r="34" fill="none" stroke={scoreColor} strokeWidth="7"
                strokeDasharray={`${(score / 100) * 213.6} 213.6`} strokeLinecap="round" />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-xl font-bold font-num" style={{ color: scoreColor }}>{score}</span>
            </div>
          </div>
          <div className="text-[10px] text-t3 mt-1">健康分 / 100</div>
        </div>
        <p className="text-[13px] text-t2 leading-relaxed flex-1">{data.summary}</p>
      </Card>

      {/* 行为一致性摘要 */}
      {data.consistency && (
        <Card className="p-4">
          <div className="text-sm font-semibold text-t1 mb-2">
            🧠 行为一致性（用户 Agent Reward 信号可信度）
          </div>
          <div className="grid grid-cols-5 gap-3 text-center">
            <div className="rounded-lg bg-surface-2 p-2">
              <div className={`text-lg font-bold font-num ${
                (data.consistency.pac_conflict_rate ?? 0) > 0.2 ? 'text-[var(--critical)]' :
                (data.consistency.pac_conflict_rate ?? 0) > 0 ? 'text-[var(--warning)]' : 'text-[var(--good)]'
              }`}>
                {data.consistency.pac_conflict_count ?? 0}
              </div>
              <div className="text-[10px] text-t3">偏好冲突 (PAC)</div>
            </div>
            <div className="rounded-lg bg-surface-2 p-2">
              <div className={`text-lg font-bold font-num ${
                (data.consistency.wsc_coherence_score ?? 1) < 0.7 ? 'text-[var(--critical)]' :
                (data.consistency.wsc_coherence_score ?? 1) < 0.9 ? 'text-[var(--warning)]' : 'text-[var(--good)]'
              }`}>
                {((data.consistency.wsc_coherence_score ?? 1) * 100).toFixed(0)}%
              </div>
              <div className="text-[10px] text-t3">情感一致性 (WSC)</div>
            </div>
            <div className="rounded-lg bg-surface-2 p-2">
              <div className={`text-lg font-bold font-num ${
                (data.consistency.pra_misaligned_requests ?? 0) > 0 ? 'text-[var(--warning)]' : 'text-[var(--good)]'
              }`}>
                {data.consistency.pra_misaligned_requests ?? 0}
              </div>
              <div className="text-[10px] text-t3">请求不对齐 (PRA)</div>
            </div>
            <div className="rounded-lg bg-surface-2 p-2">
              <div className={`text-lg font-bold font-num ${
                (data.consistency.pba_correlation ?? 1) < 0.5 ? 'text-[var(--warning)]' : 'text-[var(--good)]'
              }`}>
                {data.consistency.pba_correlation != null ? (data.consistency.pba_correlation * 100).toFixed(0) + '%' : '—'}
              </div>
              <div className="text-[10px] text-t3">人格行为相关 (PBA)</div>
            </div>
            <div className="rounded-lg bg-surface-2 p-2">
              <div className={`text-lg font-bold font-num ${
                (data.consistency.csps_stability_score ?? 1) < 0.7 ? 'text-[var(--warning)]' : 'text-[var(--good)]'
              }`}>
                {((data.consistency.csps_stability_score ?? 1) * 100).toFixed(0)}%
              </div>
              <div className="text-[10px] text-t3">偏好稳定性 (CSPS)</div>
            </div>
          </div>
        </Card>
      )}

      {/* 发现（含建议） */}
      <div className="grid md:grid-cols-3 gap-3">
        {(['error', 'warn', 'info'] as const).map((sev) => (
          <Card key={sev} className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <span style={{ color: SEV_META[sev].color }}>{SEV_META[sev].icon}</span>
              <span className="text-sm font-semibold" style={{ color: SEV_META[sev].color }}>
                {SEV_META[sev].label} ×{grouped[sev].length}
              </span>
            </div>
            <div className="space-y-2.5">
              {grouped[sev].map((f: any, i: number) => (
                <div key={i} className="rounded-lg bg-surface-2 border border-edge p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] ${
                      f.category === '一致性' ? 'bg-[var(--accent)]/15 text-[var(--accent)]' : 'bg-[var(--hover)] text-t2'
                    }`}>{f.category}</span>
                    <span className="text-[12px] font-semibold text-t1">{f.title}</span>
                  </div>
                  <p className="text-[11px] text-t2 leading-relaxed">{f.detail}</p>
                  {f.suggestion && (
                    <p className="text-[11px] text-[var(--accent)] leading-relaxed mt-1.5 border-t border-edge pt-1.5">
                      💡 {f.suggestion}
                    </p>
                  )}
                </div>
              ))}
              {grouped[sev].length === 0 && <p className="text-[11px] text-t3">无</p>}
            </div>
          </Card>
        ))}
      </div>

      {/* 逐维控制指标 */}
      <Card className="p-5">
        <div className="text-sm font-semibold text-t1 mb-3">逐维控制指标（哪个维度失衡 / 估计偏差在哪）</div>
        <MiniTable
          cols={['维度', '目标', '均值', '平均误差', '带内驻留', 'min~max', 'x̂ 平均误差', 'x̂ 偏差']}
          rows={data.dims.map((d: any) => [
            d.label, d.target, d.mean,
            <span className={`font-num ${d.mean_err > 0.06 ? 'text-[var(--critical)]' : 'text-[var(--good)]'}`}>{d.mean_err}</span>,
            <span className={`font-num ${d.in_band < 0.5 ? 'text-[var(--critical)]' : ''}`}>{(d.in_band * 100).toFixed(0)}%</span>,
            `${d.min}~${d.max}`,
            d.xhat_mae ?? '—',
            d.xhat_bias === null ? '—' : <span className={`font-num ${Math.abs(d.xhat_bias) > 0.08 ? 'text-[var(--warning)]' : ''}`}>{d.xhat_bias > 0 ? '+' : ''}{d.xhat_bias}</span>,
          ])}
          note="平均误差为单侧偏差（健康维低于目标/压力高于目标）；x̂ 偏差 >0.08 说明估计器存在系统性偏移。"
        />
      </Card>

      <div className="grid lg:grid-cols-2 gap-4">
        {/* 扰动-恢复配对 */}
        <Card className="p-5">
          <div className="text-sm font-semibold text-t1 mb-3">
            扰动–恢复配对（{data.disturbances.length} 次扰动的控制回路表现）
          </div>
          <MiniTable
            cols={['日', '事件', '压力冲击', '恢复响应', '回带用时']}
            rows={data.disturbances.slice(0, 12).map((d: any) => [
              `d${d.day}`, d.event,
              <span className={`font-num ${d.stress_jump > 0.1 ? 'text-[var(--critical)]' : ''}`}>{d.stress_jump > 0 ? '+' : ''}{d.stress_jump}</span>,
              d.recover_in_slots === null ? <span className="text-[var(--critical)]">未响应</span> : `${d.recover_in_slots} 时段`,
              d.time_to_band_slots === null ? <span className="text-[var(--warning)]">未回带</span> : `${d.time_to_band_slots} 时段`,
            ])}
            note={data.disturbances.length > 12 ? `仅显示前 12 条，共 ${data.disturbances.length} 条。` : '压力冲击为扰动后一时段的压力变化。'}
          />
        </Card>

        {/* session 分析 */}
        <Card className="p-5">
          <div className="text-sm font-semibold text-t1 mb-3">
            Session 分析（{data.sessions_total} 个 · 估计是否在对话中变好）
          </div>
          <MiniTable
            cols={['ID', '日', '轮数', '工具', 'x̂误差 始→末', '有行动']}
            rows={data.sessions.slice(0, 10).map((s: any) => [
              s.id, `d${s.day}`, s.turns,
              <span className="text-[10px] text-[var(--persona)]">{s.tools.filter((t: string) => !['open_session', 'close_session'].includes(t)).join(', ') || '—'}</span>,
              s.belief_err_start === null ? '—' : (
                <span className={`font-num ${s.belief_err_end < s.belief_err_start ? 'text-[var(--good)]' : 'text-[var(--warning)]'}`}>
                  {s.belief_err_start}→{s.belief_err_end}
                </span>
              ),
              s.added_recovery ? '✓' : '✗',
            ])}
            note="x̂误差末<始（绿）= 对话让助手更懂用户；变差的 session 说明估计器被带偏。"
          />
        </Card>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        {/* 时段画像 */}
        <Card className="p-5">
          <div className="text-sm font-semibold text-t1 mb-3">时段画像（日内节律）</div>
          <div className="space-y-3">
            {data.slot_profile.map((p: any) => (
              <div key={p.slot}>
                <div className="flex justify-between text-[11px] mb-1">
                  <span className="text-t2">{p.name}</span>
                  <span className="font-num text-t3">压 {p.stress} · 精 {p.energy} · 情 {p.valence}</span>
                </div>
                <div className="flex h-2 rounded-full overflow-hidden bg-[var(--hover)]">
                  <div style={{ width: `${p.stress * 100}%`, background: 'var(--stress)' }} />
                </div>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-t3 mt-2">条形为平均压力；异常高峰提示该时段是干预重点。</p>
        </Card>

        {/* 经济 */}
        <Card className="p-5">
          <div className="text-sm font-semibold text-t1 mb-3">经济分析</div>
          <div className="grid grid-cols-2 gap-2 mb-3 text-[11px]">
            {[['期初', `¥${eco.money_start}`], ['期末', `¥${eco.money_end}`], ['最低', `¥${eco.money_min}`], ['最高', `¥${eco.money_max}`], ['负债', `${eco.debt_days} 天`], ['工具成功率', data.stats.tool_success_rate === null ? '—' : `${(data.stats.tool_success_rate * 100).toFixed(0)}%`]].map(([k, v]) => (
              <div key={k as string} className="rounded-lg bg-surface-2 px-2.5 py-1.5 flex justify-between">
                <span className="text-t3">{k}</span><span className="font-num text-[var(--satiety)]">{v}</span>
              </div>
            ))}
          </div>
          <div className="text-[10.5px] text-t3 mb-1.5">恢复消费构成</div>
          <div className="space-y-1.5">
            {(() => {
              const spendEntries = Object.entries(eco.recovery_spend_by_action ?? {}) as [string, number][]
              const maxSpend = Math.max(1, ...spendEntries.map(([, v]) => v))
              return spendEntries.map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-[11px]">
                  <span className="w-20 text-t2 truncate">{k}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-[var(--hover)]">
                    <div className="h-full rounded-full bg-[var(--critical)] opacity-70"
                      style={{ width: `${Math.min(100, (v / maxSpend) * 100)}%` }} />
                  </div>
                  <span className="font-num text-t2 w-12 text-right">¥{v}</span>
                </div>
              ))
            })()}
          </div>
        </Card>

        {/* 重复文本 */}
        <Card className="p-5">
          <div className="text-sm font-semibold text-t1 mb-3">表演同质化（重复台词榜）</div>
          {rep.user_top.length === 0 && rep.assistant_top.length === 0 && (
            <p className="text-[11px] text-[var(--good)]">✓ 无明显重复表达</p>
          )}
          {([
            { who: '用户', list: rep.user_top },
            { who: '助手', list: rep.assistant_top },
          ]).map(({ who, list }: any) => (
            list.length > 0 && (
              <div key={who} className="mb-3">
                <div className="text-[10.5px] text-t3 mb-1.5">{who}</div>
                <div className="space-y-1.5">
                  {list.slice(0, 4).map((r: any, i: number) => (
                    <div key={i} className="rounded bg-surface-2 px-2.5 py-1.5 text-[11px] flex items-center gap-2">
                      <span className="font-num text-[var(--warning)] shrink-0">×{r.count}</span>
                      <span className="text-t2 truncate">「{r.text}」</span>
                    </div>
                  ))}
                </div>
              </div>
            )
          ))}
          <div className="text-[10px] text-t3 border-t border-edge pt-2 mt-2">
            平均句长：用户 {rep.avg_user_len} 字 · 助手 {rep.avg_asst_len} 字 · 连续重复 ×{rep.user_dup_consecutive}
          </div>
        </Card>
      </div>

      {/* 系列事件分析 */}
      {data.series_analysis.length > 0 && (
        <Card className="p-5">
          <div className="text-sm font-semibold text-t1 mb-3">系列事件效果（前→中→后心情变化）</div>
          <MiniTable
            cols={['系列', '区间', '开始前心情', '期间心情', '结束后心情']}
            rows={data.series_analysis.map((s: any) => [
              s.name, s.days, s.valence_before ?? '—', s.valence_during,
              s.valence_after === null ? '—' : (
                <span className={`font-num ${s.valence_after < (s.valence_before ?? 0) ? 'text-[var(--warning)]' : 'text-[var(--good)]'}`}>{s.valence_after}</span>
              ),
            ])}
          />
        </Card>
      )}
    </div>
  )
}

export function EventStatsPanel({ events, turns }: { events: RunEvent[]; turns: Turn[] }) {
  const stats = useMemo(() => {
    const byKind: Record<string, number> = { template: 0, disturbance: 0, recovery: 0, series: 0 }
    events.forEach((e) => { byKind[e.kind] = (byKind[e.kind] ?? 0) + 1 })
    const topCost = [...events].filter((e) => e.cost > 0).sort((a, b) => b.cost - a.cost).slice(0, 5)
    const sessions = new Map<string, { turns: number; tools: string[] }>()
    turns.forEach((t) => {
      if (!t.session_id) return
      const s = sessions.get(t.session_id) ?? { turns: 0, tools: [] }
      s.turns += 1
      t.tool_calls.forEach((c) => s.tools.push(c.name))
      sessions.set(t.session_id, s)
    })
    const toolCount: Record<string, number> = {}
    sessions.forEach((s) => s.tools.forEach((t) => { toolCount[t] = (toolCount[t] ?? 0) + 1 }))
    const recovSpend = events.filter((e) => e.kind === 'recovery').reduce((s, e) => s + e.cost, 0)
    return { byKind, topCost, sessions, toolCount, recovSpend }
  }, [events, turns])

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <Card className="p-5">
        <div className="text-sm font-semibold text-t1 mb-4">事件构成</div>
        <div className="space-y-3">
          {(['disturbance', 'recovery', 'series', 'template'] as const).map((k) => {
            const meta = { disturbance: ['扰动事件', 'var(--critical)'], recovery: ['恢复事件', 'var(--good)'], series: ['系列子事件', 'var(--series)'], template: ['模板事件', 'var(--energy)'] }[k]
            const total = events.length || 1
            return (
              <div key={k}>
                <div className="flex justify-between text-xs mb-1">
                  <span style={{ color: meta[1] }}>{meta[0]}</span>
                  <span className="font-num text-t2">{stats.byKind[k]}</span>
                </div>
                <div className="h-2 rounded-full bg-[var(--hover)]">
                  <div className="h-full rounded-full" style={{ width: `${(stats.byKind[k] / total) * 100}%`, background: meta[1] }} />
                </div>
              </div>
            )
          })}
        </div>
        <div className="mt-5 pt-4 border-t border-edge text-xs text-t2 space-y-1.5">
          <div>恢复事件总花费：<span className="font-num text-[var(--critical)]">¥{stats.recovSpend}</span></div>
          <div>Session 数：<span className="font-num text-t1">{stats.sessions.size}</span></div>
          <div>平均轮数/session：<span className="font-num text-t1">
            {stats.sessions.size ? (turns.filter((t) => t.session_id).length / stats.sessions.size).toFixed(1) : 0}</span></div>
        </div>
      </Card>
      <Card className="p-5">
        <div className="text-sm font-semibold text-t1 mb-4">工具调用 & 高额事件</div>
        <div className="flex flex-wrap gap-2 mb-4">
          {Object.entries(stats.toolCount).sort((a, b) => b[1] - a[1]).map(([name, n]) => (
            <span key={name} className="rounded-md bg-violet-400/15 border border-violet-400/40 px-2 py-1 text-[11px] font-num text-[var(--persona)]">
              ƒ {name} ×{n}
            </span>
          ))}
          {Object.keys(stats.toolCount).length === 0 && <span className="text-xs text-t3">无工具调用</span>}
        </div>
        <div className="space-y-2">
          {stats.topCost.map((e) => (
            <div key={e.id} className="flex items-center justify-between text-xs rounded-lg bg-surface-2 px-3 py-2">
              <span className="text-t2">{e.name}</span>
              <span className="font-num text-[var(--critical)]">¥{e.cost}</span>
            </div>
          ))}
          {stats.topCost.length === 0 && <span className="text-xs text-t3">本次运行没有付费事件</span>}
        </div>
      </Card>
    </div>
  )
}
