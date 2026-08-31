// API 与类型
export interface StateVec { valence: number; energy: number; satiety: number; stress: number }

// 结构化喜好（角色卡真值，冻结）
export interface Preferences {
  categories: Record<string, number>
  loves: string[]; hates: string[]
  interruption_tolerance: number
  planning_style: string
  social_recharge: string
}
// 助手对冻结维度（人格 + 喜好）的累积估计
export interface PersonaBelief {
  facets: Record<string, number>
  categories: Record<string, number>
  loves: string[]; hates: string[]
  interruption_tolerance: number | null
  planning_style: string | null
  social_recharge: string | null
  confidence: number
  notes: string
}
export interface Persona {
  name: string; archetype: string
  big5: Record<string, number>
  facets: Record<string, number>
  likes: string
  prefs: Preferences
  routine: string; income_per_slot: number
}
export interface Turn {
  run_id: string; t_logical: number; session_id: string | null; turn_id: number
  speaker: 'user' | 'assistant' | 'system'; text: string
  tool_calls: { name: string; args: any }[]; tool_results: { name: string; ok: boolean; payload: any }[]
  x_true: StateVec; x_hat: StateVec | null
  persona_hat?: PersonaBelief | null
  felt_state?: string | null
}
export interface Slot {
  t_logical: number; x_before: StateVec; x_after: StateVec
  natural_drift: Record<string, number>; event_effects: Record<string, number>
  control_effects: Record<string, number>; active_event_ids: string[]
  money_before: number; money_after: number; active_series?: string | null
  weather?: string | null  // 当前天气（晴/多云/阴/小雨/暴雨）
}
export interface RunEvent {
  id: string; kind: 'template' | 'disturbance' | 'recovery' | 'series'; name: string
  start_slot: number; span_slots: number; location: string; goal: string
  effect: Record<string, any>; cost: number; income: number
  caused_by_session_id?: string | null; series_id?: string | null; note?: string
}
export interface SeriesInfo {
  id: string; type: string; name: string; icon: string; start_day: number; end_day: number
}
export interface RunItem {
  run_id: string; seed?: number; days?: number; mode?: string | null
  assistant_quality?: string | null; status: string; verdict: string | null; persona_name?: string
  archetype?: string; income_per_slot?: number; started_at?: string
  progress?: { slot: number; total: number }
  benchmark_score?: number | null
  profiles?: { user?: string; assistant?: string } | null
}
// bench 分组文件夹：runs/_bench/<bench_id>/runs/ 下的各 episode run
export interface RunGroup {
  bench_id: string; n_runs: number; harnesses: string[]
  runs: RunItem[]
}
// benchmark 百分制扣分（report.json 的 benchmark 块；terms 固定按 control→belief→contract 排序）
export interface BenchmarkTerm {
  key: string; group: string; label: string
  obs: number; coef: number; cap: number; deduct: number
}
export interface Benchmark {
  version: string; formula: string; score: number
  groups: Record<string, { label: string; deduct: number }>
  terms: BenchmarkTerm[]
}
export interface Report {
  ess: number; settling_time_days: number | null; overshoot: number
  iae: number; ise: number; itae: number; variance: number; in_band_ratio: number
  est_err_final: number; est_err_slope_per_day: number
  daily_est_err: { day: number; err: number }[]; daily_err: { day: number; e: number }[]
  verdict: string; verdict_label: string; run_id: string; mode?: string; assistant_quality?: string
  // 画像精度（冻结维度）
  persona_err_final: number; persona_err_slope_per_day: number; persona_coverage: number
  prefs_err_final: number; prefs_tag_f1: number
  daily_persona_err: { day: number; err: number }[]
  // 行为一致性（用户 Agent reward 信号可信度）
  pac_conflict_rate?: number | null
  pac_conflict_count?: number
  pac_severity?: string
  wsc_coherence_score?: number | null
  wsc_incoherent_sessions?: number
  pra_misaligned_requests?: number
  pba_correlation?: number | null
  csps_stability_score?: number | null
  // benchmark 百分制扣分（新版报告；旧 run 无此字段）
  benchmark?: Benchmark
}
export interface MetricStat { n: number; mean: number | null; std: number | null; ci95: number | null; lo: number | null; hi: number | null }
export interface BenchGroup {
  n: number
  // 键见 aggregate.METRIC_KEYS；含 contract_violations（契约违约次数均值）
  metrics: Record<string, MetricStat>
  verdict_share: Record<string, number>
  verdict_mode: string
  never_settled: number
  verdict_consistency?: number  // 与众数一致的 episode 占比
}
export interface MdePair {
  a: string; b: string
  metrics: Record<string, { mde_mean: number | null; mde_var_ratio: number | null; n_a: number; n_b: number }>
}
export interface BenchAggregate {
  bench_id: string; mode: string; days: number; seeds: number[]
  n_episodes: number
  groups: Record<string, BenchGroup>
  artifact_hashes?: Record<string, string>
  mde?: { alpha: number; power: number; pairs: MdePair[] }
}
export interface Discriminability {
  // 锚点对组名（新版存档，如 {good: "reference", poor: "stub"}；旧 bench 无此字段，前端回退 good/poor 字样）
  groups?: { good: string; poor: string }
  thresholds: { diverged_ess_min: number; converged_ess_max: number }
  ess_good_mean: number | null; ess_poor_mean: number | null
  ess_good_sem?: number | null; ess_poor_sem?: number | null
  margin_poor: number | null; margin_good: number | null; separation: number | null
  checks: Record<string, boolean>; ok: boolean
  // 黄灯：ess 均值±SEM 跨阈 → borderline（旧存档无此字段，回退 ok/fail 二值）
  check_status?: Record<string, 'pass' | 'borderline' | 'fail'>
  status?: 'ok' | 'borderline' | 'fail'
}
export interface BenchEpisode {
  group: string; seed: number; archetype: string | null; label: string; run_id: string
  metrics: Record<string, any>
}
export interface BenchListItem {
  bench_id: string; mode: string; days: number | null; n_episodes: number
  groups: string[]; has_guard: boolean
  status?: string; episodes_done?: number
}
export interface BenchJob { bench_id: string; status: string; done: number; total: number; error: string | null }
// 进行中 episode（report.json 未出，进度由 slots.jsonl 推导）
export interface BenchRunningEp { run_id: string; status: string; progress?: { slot: number; total: number }; days?: number; seed?: number }

export interface Catalog {
  professions: { archetype: string; income_per_slot: number; note: string }[]
  recovery_actions: { id: string; action: string; category: string; design_intent: string; default_span: number }[]
  venues: { id: string; name: string; category: string; cuisine: string; supports: { event: string; cost: number; span: number }[] }[]
  meal_tiers: { vid: string; name: string; cost: number }[]
  sleep_tiers: { vid: string; name: string; cost: number }[]
}

// ── Balance config types ────────────────────────────────────────────────────

export const EFFECT_DIMS = ['valence', 'energy', 'satiety', 'stress'] as const
export type EffectDim = typeof EFFECT_DIMS[number]

export interface EffectDict { valence: number | { pull: [number, number] }; energy: number | { pull: [number, number] }; satiety: number | { pull: [number, number] }; stress: number | { pull: [number, number] } }

export interface RecoveryAction {
  id: string; action: string; category: string
  design_intent: string; default_span: number
}

// 统一地点表：价格/效果在 supports 条目上逐项覆盖事件定义
export interface VenueSupport {
  event: string; label?: string; cost: number; span: number; effect: EffectDict
}

export interface Venue {
  id: string; name: string; category: string; cuisine: string
  aliases: string[]; replaces_meal?: boolean
  supports: VenueSupport[]; design_intent: string
}

export interface MealTier {
  vid: string; name: string; tier: string; cost: number; effect: EffectDict; design_intent: string
}

export interface SleepTier {
  vid: string; name: string; tier: string; cost: number; effect: EffectDict; design_intent: string
}

export interface CustomActivity {
  id: string; name: string; cost: number; keywords: string[]
  effect: EffectDict; design_intent: string
}

export interface Profession {
  archetype: string; income_per_slot: number; note: string
}

export interface Disturbance {
  id: string; name: string; location: string; cost: number; income: number
  effect: EffectDict; design_intent: string
}

export interface TemplateEvent {
  id: string; name: string; slot: string; location: string
  implicit_effect: EffectDict
  note?: string
}

export interface HabituationEntry { w_min: number; tau: number; curve: string }
export interface NeedsEntry {
  accumulate: string; satisfy_events: string; urge_curve: string; satisfy_curve: string
}
export interface PersonaModEntry { formula: string; var: string; intent: string; rule?: string }

export interface WeatherConfig {
  states: string[]
  initial_weights: number[]
  transition_matrix: number[][]
  state_effects: Record<string, Partial<Record<EffectDim, number>>>
  outdoor_modifiers: Record<string, number>
}

export interface BalanceFiles {
  recovery_actions?: RecoveryAction[]
  venues?: Venue[]
  meal_tiers?: MealTier[]
  sleep_tiers?: SleepTier[]
  custom_activities?: CustomActivity[]
  professions?: Profession[]
  disturbances?: Disturbance[]
  template_events?: TemplateEvent[]
  economy?: Record<string, number>
  dynamics?: Record<string, number>
  habituation?: Record<string, HabituationEntry>
  needs?: Record<string, NeedsEntry>
  persona_modulation?: Record<string, PersonaModEntry>
  weather?: WeatherConfig
}

export interface BalanceConfig {
  source: 'json' | 'default' | 'default(error)'
  files: BalanceFiles
}

const j = (r: Response) => r.json()
export const api = {
  listRuns: (): Promise<{ runs: RunItem[]; groups: RunGroup[] }> => fetch('/api/runs').then(j),
  startRun: (body: { mode: string; seed: number; days: number; quality: string; archetype?: string | null; harness?: string | null }) =>
    fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(j),
  continueRun: (id: string, extraDays: number) =>
    fetch(`/api/runs/${id}/continue`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ extra_days: extraDays }) }).then(j),
  deleteRuns: (ids: string[]): Promise<{ deleted: string[]; skipped: { run_id: string; reason: string }[] }> =>
    fetch('/api/runs/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_ids: ids }) }).then(j),
  deleteBench: (ids: string[]): Promise<{ deleted: string[]; skipped: { bench_id: string; reason: string }[] }> =>
    fetch('/api/bench/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ bench_ids: ids }) }).then(j),
  runDetail: (id: string) => fetch(`/api/runs/${id}`).then(j),
  turns: (id: string, offset = 0, limit = 5000): Promise<{ total: number; items: Turn[] }> =>
    fetch(`/api/runs/${id}/turns?offset=${offset}&limit=${limit}`).then(j),
  slots: (id: string): Promise<{ items: Slot[] }> => fetch(`/api/runs/${id}/slots`).then(j),
  events: (id: string): Promise<{ items: RunEvent[]; series: SeriesInfo[] }> => fetch(`/api/runs/${id}/events`).then(j),
  report: (id: string): Promise<Report> => fetch(`/api/runs/${id}/report`).then(j),
  insights: (id: string): Promise<{ findings: { severity: string; category: string; title: string; detail: string; evidence: string }[]; stats: Record<string, any> }> =>
    fetch(`/api/runs/${id}/insights`).then(j),
  getBalanceConfig: (): Promise<BalanceConfig> => fetch('/api/balance/config').then(j),
  saveBalanceFile: (file: string, content: unknown): Promise<{ ok: boolean; source: string; file: string }> =>
    fetch('/api/balance/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file, content }) }).then(j),
  resetBalanceFile: (file?: string): Promise<{ ok: boolean; reset: string[]; source: string }> =>
    fetch('/api/balance/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file: file ?? null }) }).then(j),
  evalFormula: (formula: string, varName = 'x', points = 50): Promise<{ ok: boolean; points?: { x: number; y: number }[]; error?: string }> =>
    fetch('/api/balance/eval_formula', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ formula, var_name: varName, points }) }).then(j),
  catalog: (): Promise<Catalog> => fetch('/api/catalog').then(j),
  harnesses: (): Promise<{ items: { name: string; doc: string }[]; default: string }> =>
    fetch('/api/harnesses').then(j),
  listBench: (): Promise<{ items: BenchListItem[]; jobs: BenchJob[] }> => fetch('/api/bench').then(j),
  benchDetail: (id: string): Promise<{ aggregate?: BenchAggregate; discriminability?: Discriminability; episodes?: BenchEpisode[]; job?: BenchJob; pending?: boolean; running?: BenchRunningEp[] }> =>
    fetch(`/api/bench/${id}`).then(j),
  startBench: (body: { seeds: string; days: number; groups?: string[]; archetypes?: string[]; max_episodes?: number; concurrency?: number; bench_id?: string }): Promise<{ started: boolean; bench_id?: string; n_episodes?: number; estimated_tokens?: number; error?: string }> =>
    fetch('/api/bench', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(j),
}

// 领域常量（DIMS / BAND / VERDICTS / KIND_META / SLOT_NAMES / BIG5_FACETS / PREF_CATEGORIES）
// 迁移到 components/theme.ts（配色改为随主题的 CSS 变量）。此处 re-export 保持旧 import 兼容。
export {
  DIMS, BAND, VERDICTS, KIND_META, SLOT_NAMES, BIG5_FACETS, PREF_CATEGORIES,
} from './components/theme'
