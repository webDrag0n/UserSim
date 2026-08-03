// API 与类型
export interface StateVec { valence: number; energy: number; satiety: number; stress: number }
export interface Turn {
  run_id: string; t_logical: number; session_id: string | null; turn_id: number
  speaker: 'user' | 'assistant' | 'system'; text: string
  tool_calls: { name: string; args: any }[]; tool_results: { name: string; ok: boolean; payload: any }[]
  x_true: StateVec; x_hat: StateVec | null
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
}
export interface Catalog {
  professions: { archetype: string; income_per_slot: number; note: string }[]
  recovery_actions: { id: string; action: string; category: string; variants: { vid: string; location: string; tier: string; cost: number; span: number }[] }[]
  meal_tiers: { vid: string; name: string; cost: number }[]
  sleep_tiers: { vid: string; name: string; cost: number }[]
}

const j = (r: Response) => r.json()
export const api = {
  listRuns: (): Promise<{ runs: RunItem[] }> => fetch('/api/runs').then(j),
  startRun: (body: { mode: string; seed: number; days: number; quality: string; archetype?: string | null }) =>
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
}

export const DIMS = [
  { key: 'valence' as const, label: '心情', target: 0.72, color: '#34d399', good: 'high' as const },
  { key: 'energy' as const, label: '精力', target: 0.70, color: '#38bdf8', good: 'high' as const },
  { key: 'satiety' as const, label: '饱腹', target: 0.65, color: '#fbbf24', good: 'high' as const },
  { key: 'stress' as const, label: '压力', target: 0.30, color: '#f87171', good: 'low' as const },
]
export const BAND = 0.10
export const VERDICTS: Record<string, { label: string; color: string }> = {
  converged: { label: '收敛稳定', color: '#34d399' },
  oscillating: { label: '欠阻尼振荡', color: '#fbbf24' },
  diverged: { label: '发散失控', color: '#f87171' },
}
export const KIND_META: Record<string, { label: string; color: string }> = {
  template: { label: '模板', color: '#38bdf8' },
  disturbance: { label: '扰动', color: '#f87171' },
  recovery: { label: '恢复', color: '#34d399' },
  series: { label: '系列', color: '#f472b6' },
}
export const SLOT_NAMES = ['上午', '下午', '晚上', '深夜']
