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
}
export interface MetricStat { n: number; mean: number | null; std: number | null; ci95: number | null; lo: number | null; hi: number | null }
export interface BenchGroup {
  n: number
  metrics: Record<string, MetricStat>
  verdict_share: Record<string, number>
  verdict_mode: string
  never_settled: number
}
export interface BenchAggregate {
  bench_id: string; mode: string; days: number; seeds: number[]
  n_episodes: number
  groups: Record<string, BenchGroup>
  artifact_hashes?: Record<string, string>
}
export interface Discriminability {
  thresholds: { diverged_ess_min: number; converged_ess_max: number }
  ess_good_mean: number | null; ess_poor_mean: number | null
  margin_poor: number | null; margin_good: number | null; separation: number | null
  checks: Record<string, boolean>; ok: boolean
}
export interface BenchEpisode {
  group: string; seed: number; archetype: string | null; label: string; run_id: string
  metrics: Record<string, any>
}
export interface BenchListItem {
  bench_id: string; mode: string; days: number; n_episodes: number
  groups: string[]; has_guard: boolean
}
export interface BenchJob { bench_id: string; status: string; done: number; total: number; error: string | null }

export interface Catalog {
  professions: { archetype: string; income_per_slot: number; note: string }[]
  recovery_actions: { id: string; action: string; category: string; variants: { vid: string; location: string; tier: string; cost: number; span: number }[] }[]
  meal_tiers: { vid: string; name: string; cost: number }[]
  sleep_tiers: { vid: string; name: string; cost: number }[]
}

const j = (r: Response) => r.json()
export const api = {
  listRuns: (): Promise<{ runs: RunItem[] }> => fetch('/api/runs').then(j),
  startRun: (body: { mode: string; seed: number; days: number; quality: string; archetype?: string | null; harness?: string | null }) =>
    fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(j),
  continueRun: (id: string, extraDays: number) =>
    fetch(`/api/runs/${id}/continue`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ extra_days: extraDays }) }).then(j),
  deleteRuns: (ids: string[]): Promise<{ deleted: string[]; skipped: { run_id: string; reason: string }[] }> =>
    fetch('/api/runs/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_ids: ids }) }).then(j),
  runDetail: (id: string) => fetch(`/api/runs/${id}`).then(j),
  turns: (id: string, offset = 0, limit = 5000): Promise<{ total: number; items: Turn[] }> =>
    fetch(`/api/runs/${id}/turns?offset=${offset}&limit=${limit}`).then(j),
  slots: (id: string): Promise<{ items: Slot[] }> => fetch(`/api/runs/${id}/slots`).then(j),
  events: (id: string): Promise<{ items: RunEvent[]; series: SeriesInfo[] }> => fetch(`/api/runs/${id}/events`).then(j),
  report: (id: string): Promise<Report> => fetch(`/api/runs/${id}/report`).then(j),
  insights: (id: string): Promise<{ findings: { severity: string; category: string; title: string; detail: string; evidence: string }[]; stats: Record<string, any> }> =>
    fetch(`/api/runs/${id}/insights`).then(j),
  catalog: (): Promise<Catalog> => fetch('/api/catalog').then(j),
  harnesses: (): Promise<{ items: { name: string; doc: string }[]; default: string }> =>
    fetch('/api/harnesses').then(j),
  listBench: (): Promise<{ items: BenchListItem[]; jobs: BenchJob[] }> => fetch('/api/bench').then(j),
  benchDetail: (id: string): Promise<{ aggregate?: BenchAggregate; discriminability?: Discriminability; episodes?: BenchEpisode[]; job?: BenchJob; pending?: boolean }> =>
    fetch(`/api/bench/${id}`).then(j),
  startBench: (body: { seeds: string; days: number; mode: string; groups?: string[]; max_episodes?: number }) =>
    fetch('/api/bench', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(j),
}

// 领域常量（DIMS / BAND / VERDICTS / KIND_META / SLOT_NAMES / BIG5_FACETS / PREF_CATEGORIES）
// 迁移到 components/theme.ts（配色改为随主题的 CSS 变量）。此处 re-export 保持旧 import 兼容。
export {
  DIMS, BAND, VERDICTS, KIND_META, SLOT_NAMES, BIG5_FACETS, PREF_CATEGORIES,
} from './components/theme'
