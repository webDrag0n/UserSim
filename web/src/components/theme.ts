import { createContext, useContext, useEffect, useState } from 'react'

// ============================================================
// 主题（浅色优先 + 深色可切换）
// ============================================================
export type Theme = 'light' | 'dark'

const KEY = 'usersim-theme'

export function readInitialTheme(): Theme {
  const saved = localStorage.getItem(KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(t: Theme) {
  document.documentElement.setAttribute('data-theme', t)
  localStorage.setItem(KEY, t)
}

export const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({
  theme: 'light',
  toggle: () => {},
})
export const useTheme = () => useContext(ThemeCtx)

// 读一个 CSS 变量当前解析值（图表把颜色喂给 recharts 时用；随主题变化重新读取）
export function cssVar(name: string): string {
  if (typeof window === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

// 让依赖 CSS 变量取色的组件在主题切换后重渲染
export function useThemeVersion(): Theme {
  const { theme } = useTheme()
  return theme
}

// ============================================================
// 尊重 prefers-reduced-motion
// ============================================================
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}

// 默认弹簧（apple-design §4：临界阻尼，无过冲）
export const SPRING = { type: 'spring', bounce: 0, duration: 0.4 } as const
// 动量弹簧（仅手势带速度时用）
export const SPRING_BOUNCE = { type: 'spring', bounce: 0.2, duration: 0.4 } as const

// ============================================================
// 领域常量（配色改为 CSS 变量，浅深自适应）
// ============================================================
export const DIMS = [
  { key: 'valence' as const, label: '心情', target: 0.72, cssVar: '--valence', good: 'high' as const },
  { key: 'energy' as const, label: '精力', target: 0.70, cssVar: '--energy', good: 'high' as const },
  { key: 'satiety' as const, label: '饱腹', target: 0.65, cssVar: '--satiety', good: 'high' as const },
  { key: 'stress' as const, label: '压力', target: 0.30, cssVar: '--stress', good: 'low' as const },
]
export const BAND = 0.10

export const VERDICTS: Record<string, { label: string; cssVar: string; icon: string }> = {
  converged: { label: '收敛稳定', cssVar: '--good', icon: '●' },
  oscillating: { label: '欠阻尼振荡', cssVar: '--warning', icon: '◐' },
  diverged: { label: '发散失控', cssVar: '--critical', icon: '▲' },
}

export const KIND_META: Record<string, { label: string; cssVar: string }> = {
  template: { label: '模板', cssVar: '--energy' },
  disturbance: { label: '扰动', cssVar: '--critical' },
  recovery: { label: '恢复', cssVar: '--good' },
  series: { label: '系列', cssVar: '--series' },
}

export const SLOT_NAMES = ['上午', '下午', '晚上', '深夜']

export const BIG5_FACETS: { domain: string; cssVar: string; facets: string[] }[] = [
  { domain: '开放性', cssVar: '--persona', facets: ['想象力', '审美', '情感丰富', '尝新', '思辨', '价值开放'] },
  { domain: '尽责性', cssVar: '--energy', facets: ['胜任感', '条理性', '尽职', '成就追求', '自律', '审慎'] },
  { domain: '外向性', cssVar: '--satiety', facets: ['热情', '群居性', '果断', '活跃', '寻求刺激', '积极情绪'] },
  { domain: '宜人性', cssVar: '--valence', facets: ['信任', '直率', '利他', '顺从', '谦逊', '同理心'] },
  { domain: '神经质', cssVar: '--stress', facets: ['焦虑', '愤怒敌意', '抑郁', '自我意识', '冲动性', '脆弱'] },
]
export const PREF_CATEGORIES = ['饮食', '休息', '户外', '旅行', '运动', '居家', '社交', '文化', '音乐', '学习', '自然']
