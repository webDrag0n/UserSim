import { useState } from 'react'
import Console from './views/Console'
import Dashboard from './views/Dashboard'
import BalancePage from './views/Balance'

export default function App() {
  const [runId, setRunId] = useState<string | null>(null)
  const [page, setPage] = useState<'runs' | 'balance'>('runs')

  return (
    <div className="min-h-screen" style={{ background: '#0a0b10' }}>
      <nav className="sticky top-0 z-50 border-b border-white/10 backdrop-blur-md" style={{ background: 'rgba(10,11,16,0.8)' }}>
        <div className="mx-auto max-w-[1400px] px-6 h-14 flex items-center gap-4">
          <button onClick={() => { setRunId(null); setPage('runs') }} className="font-bold text-white text-sm">
            UserSim<span className="text-cyan-400">.</span>
          </button>
          <div className="flex gap-1">
            {([['runs', '运行控制台'], ['balance', '配表编辑器']] as const).map(([k, l]) => (
              <button key={k} onClick={() => { setPage(k); if (k === 'balance') setRunId(null) }}
                className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${page === k ? 'bg-white/10 text-white font-semibold' : 'text-zinc-400 hover:text-zinc-200'}`}>
                {l}
              </button>
            ))}
          </div>
          <span className="text-[10.5px] font-num text-zinc-600 hidden md:inline ml-2">rule-based world · 2×LLM · control-theoretic eval</span>
        </div>
      </nav>

      <main className="mx-auto max-w-[1400px] px-6 py-6">
        {page === 'balance' ? <BalancePage /> : !runId ? <Dashboard onOpen={setRunId} /> : <Console runId={runId} onBack={() => setRunId(null)} />}
      </main>
    </div>
  )
}
