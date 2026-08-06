# Formula Editor Enhancement Plan

## Problem Analysis

### Current State
1. **Formulas are documentation-only** — `needs.json` and `persona_modulation.json` contain formula strings like `"u=((1-x)/0.6)^1.5"`, but these are never executed. The real logic is hardcoded in `anthro.py`.

2. **No live preview** — Habituation curve editor has preview charts, but needs/persona formulas don't show their curves when editing.

3. **No usage validation** — We can't verify which config rules are actually used vs which are dead documentation.

4. **Hard to test changes** — To test a formula change, you must edit Python code, restart the server, and run a full sim.

## Issues to Fix

### 1. Make formulas executable
**Current**: Formula strings like `"u=x²"` are pure documentation  
**Target**: Parse and evaluate formulas safely, replacing hardcoded logic

**Approach**:
- Add a safe expression evaluator (using `ast.parse` with whitelist)
- Support syntax: `x`, `u`, `E`, `N`, `O`, `+`, `-`, `*`, `/`, `^`, `**`, `abs()`, `min()`, `max()`, `sqrt()`
- Convert formula strings to Python callables at load time
- Fall back to hardcoded defaults if formula is invalid

### 2. Add live formula preview
**Current**: Needs editor shows static text, no visualization  
**Target**: Real-time curve preview updates as you type

**Components**:
- `FormulaCell` — editable text input with syntax highlighting
- `FormulaCurvePreview` — SVG line chart that re-renders on change
- Validation indicator (green checkmark / red error)

### 3. Validate formula usage
**Current**: No way to know if a config rule is actually applied  
**Target**: Mark unused rules with a warning badge

**Detection**:
- Habituation: Used if `habit_params()` is called with that key
- Needs: Used if event name matches `SOCIAL_EVENTS`, `STIM_EVENTS`, `ACHIEVE_EVENTS`
- Persona: Always used (hardcoded in `persona_modifiers()`)

**UI indicator**: 
- ✓ Green badge "已生效" if detected in code
- ⚠ Yellow badge "未检测到使用" if rule exists but no code references it

### 4. Better curve visualization
**Current**: 
- Habituation curves are tiny (120×36px), hard to read
- Needs curves are even smaller (110×34px), no axis labels
- No hover tooltip showing exact values

**Target**:
- Larger charts (200×120px) with axis labels
- Hover tooltip showing `x` and `y` values
- Grid lines for readability
- Toggle to expand to full-screen overlay

## Implementation Plan

### Phase 1: Backend — Make formulas executable

**File**: `usersim/world/anthro.py`

Add safe formula evaluator:
```python
import ast
import operator

SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

SAFE_FUNCS = {
    'abs': abs,
    'min': min,
    'max': max,
    'sqrt': math.sqrt,
}

def parse_formula(expr: str, var_name: str = 'x') -> callable | None:
    """Parse formula string like 'x²' or '1-(2x-1)²' into a Python function."""
    try:
        # Normalize: ² → **2, x → x
        expr = expr.replace('²', '**2').replace('³', '**3')
        expr = expr.replace('^', '**')
        
        tree = ast.parse(expr, mode='eval')
        # Validate: only safe operations allowed
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCS:
                    return None
            elif isinstance(node, (ast.Import, ast.ImportFrom, ast.Attribute)):
                return None  # No imports or attribute access
        
        code = compile(tree, '<formula>', 'eval')
        
        def eval_func(x: float) -> float:
            return eval(code, {"__builtins__": {}}, {var_name: x, **SAFE_FUNCS})
        
        return eval_func
    except:
        return None
```

Update `Needs.urges()` to use config formulas:
```python
def urges(self, overrides: dict | None = None) -> dict[str, float]:
    n = self.n
    needs_cfg = (overrides or {}).get("needs", {})
    
    result = {}
    for kind, value in n.items():
        cfg = needs_cfg.get(kind, {})
        formula_str = cfg.get("urge_curve", "")
        formula = parse_formula(formula_str, 'x')
        
        if formula:
            try:
                result[kind] = max(0.0, min(1.0, formula(value)))
            except:
                result[kind] = value  # fallback
        else:
            # Hardcoded defaults (current behavior)
            if kind == "hunger":
                result[kind] = min(1.0, (value / 0.6) ** 1.5) if value > 0 else 0.0
            elif kind == "social":
                result[kind] = value ** 2
            elif kind == "stimulation":
                result[kind] = 1.0 - (2 * value - 1) ** 2
            elif kind == "achievement":
                result[kind] = value ** 2.5
            else:
                result[kind] = value
    
    return result
```

### Phase 2: Frontend — Formula editor with live preview

**File**: `web/src/views/Balance.tsx`

Add `FormulaCell` component:
```tsx
function FormulaCell({ 
  value, 
  onSave, 
  preview 
}: { 
  value: string; 
  onSave: (v: string) => void; 
  preview?: (formula: string) => boolean;  // returns true if valid
}) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState(value)
  const [valid, setValid] = useState(true)
  
  useEffect(() => {
    if (editing && preview) {
      setValid(preview(v))
    }
  }, [v, editing, preview])
  
  if (!editing) return (
    <span
      onClick={() => { setV(value); setEditing(true) }}
      className="cursor-text font-mono text-[10.5px] rounded px-1 -mx-1 hover:bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] transition-colors">
      {value || '—'}
    </span>
  )
  
  return (
    <div className="relative">
      <input
        autoFocus
        value={v}
        onChange={e => setV(e.target.value)}
        onBlur={() => { 
          setEditing(false)
          if (v !== value && valid) onSave(v)
        }}
        onKeyDown={e => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          if (e.key === 'Escape') { setEditing(false) }
        }}
        className={`w-full min-w-[120px] font-mono text-[10.5px] rounded bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] border ${
          valid ? 'border-[color-mix(in_srgb,var(--accent)_50%,transparent)]' : 'border-[var(--critical)]'
        } px-1 outline-none`}
      />
      {!valid && (
        <span className="absolute -bottom-4 left-0 text-[9px] text-[var(--critical)]">
          公式语法错误
        </span>
      )}
    </div>
  )
}
```

Add larger curve preview:
```tsx
function FormulaCurvePreview({ 
  formula, 
  varName = 'x',
  color = 'var(--accent)'
}: { 
  formula: string; 
  varName?: string;
  color?: string;
}) {
  const W = 200, H = 120
  const [hovering, setHovering] = useState<{x: number, y: number} | null>(null)
  
  // Parse formula client-side (simplified safe eval)
  const evalFormula = (x: number): number => {
    try {
      // Normalize and eval (UNSAFE in production — need proper parser)
      const normalized = formula
        .replace(/²/g, '**2')
        .replace(/³/g, '**3')
        .replace(/\^/g, '**')
        .replace(/u=/g, '')
        .replace(/s=/g, '')
      
      // eslint-disable-next-line no-eval
      const result = eval(normalized.replace(/x/g, `(${x})`))
      return Math.max(0, Math.min(1, result))
    } catch {
      return 0
    }
  }
  
  const points = Array.from({ length: 51 }, (_, i) => {
    const x = i / 50
    const y = evalFormula(x)
    return { x: x * W, y: H - y * H }
  })
  
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  
  return (
    <div className="relative inline-block">
      <svg 
        width={W} 
        height={H} 
        className="border border-edge rounded"
        onMouseMove={e => {
          const rect = e.currentTarget.getBoundingClientRect()
          const x = (e.clientX - rect.left) / W
          const y = 1 - (e.clientY - rect.top) / H
          setHovering({ x, y: evalFormula(x) })
        }}
        onMouseLeave={() => setHovering(null)}
      >
        {/* Grid */}
        {[0.25, 0.5, 0.75].map(v => (
          <g key={v}>
            <line x1="0" y1={H - v * H} x2={W} y2={H - v * H} stroke="var(--edge)" strokeDasharray="2 2" />
            <line x1={v * W} y1="0" x2={v * W} y2={H} stroke="var(--edge)" strokeDasharray="2 2" />
          </g>
        ))}
        
        {/* Axes */}
        <line x1="0" y1={H} x2={W} y2={H} stroke="var(--text-3)" strokeWidth="1" />
        <line x1="0" y1="0" x2="0" y2={H} stroke="var(--text-3)" strokeWidth="1" />
        
        {/* Curve */}
        <path d={pathD} fill="none" stroke={color} strokeWidth="2" />
        
        {/* Hover indicator */}
        {hovering && (
          <circle cx={hovering.x * W} cy={H - hovering.y * H} r="3" fill={color} />
        )}
      </svg>
      
      {hovering && (
        <div className="absolute -top-6 left-0 bg-[var(--card)] border border-edge rounded px-2 py-0.5 text-[9px] text-t2 font-mono whitespace-nowrap">
          {varName}={hovering.x.toFixed(2)} → {hovering.y.toFixed(3)}
        </div>
      )}
    </div>
  )
}
```

Update `NeedsEditor`:
```tsx
function NeedsEditor({ data, onChange }: { data: Record<string, NeedsEntry>; onChange: (v: Record<string, NeedsEntry>) => void }) {
  const update = (name: string, field: keyof NeedsEntry, raw: string) => {
    const next = JSON.parse(JSON.stringify(data)) as typeof data
    next[name][field] = raw
    onChange(next)
  }
  
  const validateFormula = (formula: string): boolean => {
    try {
      const normalized = formula.replace(/²/g, '**2').replace(/\^/g, '**').replace(/u=/g, '').replace(/s=/g, '')
      // Simple validation: check for forbidden chars
      if (/[;(){}\[\]import]/.test(normalized)) return false
      return true
    } catch {
      return false
    }
  }
  
  return (
    <div className="space-y-4">
      {Object.entries(data).map(([name, row]) => (
        <Card key={name} className="p-4">
          <SectionTitle dot={cssVar('--persona')}>{name}</SectionTitle>
          <div className="grid grid-cols-1 gap-3 text-[11.5px]">
            <div className="flex items-start gap-3 py-1 border-b border-edge">
              <span className="w-28 shrink-0 text-t3">累积规则</span>
              <span className="text-t2 flex-1"><Cell value={row.accumulate} onSave={v => update(name, 'accumulate', v)} /></span>
            </div>
            <div className="flex items-start gap-3 py-1 border-b border-edge">
              <span className="w-28 shrink-0 text-t3">满足事件</span>
              <span className="text-t2 flex-1"><Cell value={row.satisfy_events} onSave={v => update(name, 'satisfy_events', v)} /></span>
            </div>
            
            {/* Urge curve with live preview */}
            <div className="flex items-start gap-3 py-2 border-b border-edge">
              <span className="w-28 shrink-0 text-t3">驱动力曲线 u(x)</span>
              <div className="flex-1 space-y-2">
                <FormulaCell 
                  value={row.urge_curve} 
                  onSave={v => update(name, 'urge_curve', v)}
                  preview={validateFormula}
                />
                <FormulaCurvePreview formula={row.urge_curve} varName="x" color={cssVar('--persona')} />
              </div>
            </div>
            
            {/* Satisfy curve with live preview */}
            <div className="flex items-start gap-3 py-2">
              <span className="w-28 shrink-0 text-t3">满足曲线 s(u)</span>
              <div className="flex-1 space-y-2">
                <FormulaCell 
                  value={row.satisfy_curve} 
                  onSave={v => update(name, 'satisfy_curve', v)}
                  preview={validateFormula}
                />
                <FormulaCurvePreview formula={row.satisfy_curve} varName="u" color={cssVar('--good')} />
              </div>
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}
```

### Phase 3: Usage validation

Add API endpoint to detect formula usage:

**File**: `usersim/server/app.py`
```python
@app.get("/api/balance/usage")
def get_formula_usage():
    """Return which config formulas are actually used in code."""
    import ast
    from pathlib import Path
    
    usage = {
        "habituation": {},
        "needs": {},
        "persona_modulation": {}
    }
    
    # Scan anthro.py for references
    anthro_path = Path("usersim/world/anthro.py")
    if anthro_path.exists():
        source = anthro_path.read_text()
        tree = ast.parse(source)
        
        # Check if habit_params() is called
        # Check if SOCIAL_EVENTS/STIM_EVENTS/ACHIEVE_EVENTS are referenced
        # Mark as used/unused
        
        # Habituation
        hab_defaults = ["吃好吃的", "好好休息", "出门走走", ...]  # from HABITUATION_DEFAULTS keys
        for key in hab_defaults:
            usage["habituation"][key] = "used"  # All defaults are used via habit_params()
        
        # Needs
        for kind in ["饥饿", "社交", "刺激", "成就"]:
            usage["needs"][kind] = "used"  # urges() always calls all four
        
        # Persona
        usage["persona_modulation"] = {
            "外向性": "used",
            "神经质": "used",
            "开放性": "used"
        }
    
    return usage
```

Frontend badge in editor:
```tsx
<Badge 
  label={usageStatus === 'used' ? '✓ 已生效' : '⚠ 未检测到使用'} 
  color={usageStatus === 'used' ? cssVar('--good') : cssVar('--warning')} 
/>
```

## Remaining Concerns

### Security
- Client-side `eval()` is **unsafe** for production
- Need proper expression parser (consider `mathjs` or custom AST walker)
- Backend formula eval must be sandboxed (current `ast.parse` approach is safe)

### Performance
- Parsing formulas on every urge/satisfaction call could be slow
- Cache parsed functions at config load time
- Invalidate cache when config changes

### Breaking changes
- Existing saves have state but no formula overrides
- Must fall back to hardcoded defaults gracefully
- Migration: seed `needs.json` / `persona_modulation.json` with current hardcoded formulas

## Next Steps

1. **Phase 1**: Implement backend formula parser + Needs.urges() override logic
2. **Phase 2**: Add FormulaCell + FormulaCurvePreview to frontend
3. **Phase 3**: Add usage detection API + badges
4. **Testing**: Verify formulas execute correctly, compare outputs vs hardcoded
5. **Documentation**: Update CLAUDE.md with formula syntax reference

---

**Date**: 2026-08-05  
**Status**: Planning complete — awaiting approval to implement
