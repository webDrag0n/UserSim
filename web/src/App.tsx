import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import Console from './views/Console'
import Dashboard from './views/Dashboard'
import BalancePage from './views/Balance'
import Bench from './views/Bench'
import { ThemeCtx, Theme, readInitialTheme, applyTheme, SPRING, useReducedMotion } from './components/theme'

type Page = 'runs' | 'bench' | 'balance'
const NAV: [Page, string][] = [['runs', '运行控制台'], ['bench', '批量评测'], ['balance', '配表编辑器']]

function ThemeToggle({ theme, toggle }: { theme: Theme; toggle: () => void }) {
  const reduced = useReducedMotion()
  return (
    <motion.button onClick={toggle} title={theme === 'dark' ? '切到浅色' : '切到深色'}
      whileTap={reduced ? undefined : { scale: 0.9 }}
      className="ml-auto flex h-9 w-9 items-center justify-center rounded-full border border-edge text-t2 hover:bg-[var(--hover)] transition-colors">
      <motion.span key={theme} initial={reduced ? false : { rotate: -30, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} transition={SPRING}>
        {theme === 'dark' ? '☾' : '☀'}
      </motion.span>
    </motion.button>
  )
}

export default function App() {
  const [runId, setRunId] = useState<string | null>(null)
  const [page, setPage] = useState<Page>('runs')
  const [theme, setTheme] = useState<Theme>(() => (typeof window !== 'undefined' ? readInitialTheme() : 'light'))
  const reduced = useReducedMotion()

  useEffect(() => { applyTheme(theme) }, [theme])
  const toggle = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  return (
    <ThemeCtx.Provider value={{ theme, toggle }}>
      <div className="min-h-screen bg-plane">
        <nav className="sticky top-0 z-50 border-b border-edge"
          style={{ background: 'var(--toolbar-bg)', backdropFilter: 'blur(20px) saturate(180%)' }}>
          <div className="mx-auto max-w-[1480px] px-6 h-14 flex items-center gap-4">
            <button onClick={() => { setRunId(null); setPage('runs') }} className="font-bold text-t1 text-sm display">
              UserSim<span className="text-accent">.</span>
            </button>
            <div className="relative flex gap-0.5 rounded-xl bg-surface-2 border border-edge p-0.5">
              {NAV.map(([k, l]) => {
                const active = page === k
                return (
                  <button key={k} onClick={() => { setPage(k); if (k !== 'runs') setRunId(null) }}
                    className={`relative rounded-[10px] px-3.5 py-1.5 text-xs font-medium transition-colors ${active ? 'text-t1' : 'text-t3 hover:text-t2'}`}>
                    {active && (
                      <motion.span layoutId="nav-active" transition={reduced ? { duration: 0 } : SPRING}
                        className="absolute inset-0 rounded-[10px] bg-surface shadow-card border border-edge" />
                    )}
                    <span className="relative z-10">{l}</span>
                  </button>
                )
              })}
            </div>
            <span className="text-[10.5px] font-num text-t3 hidden md:inline ml-2">rule-based world · 2×LLM · control-theoretic eval</span>
            <ThemeToggle theme={theme} toggle={toggle} />
          </div>
        </nav>

        <main className="mx-auto max-w-[1480px] px-6 pt-6 pb-24">
          {page === 'balance' ? <BalancePage />
            : page === 'bench' ? <Bench />
            : !runId ? <Dashboard onOpen={setRunId} />
            : <Console runId={runId} onBack={() => setRunId(null)} />}
        </main>
      </div>
    </ThemeCtx.Provider>
  )
}
