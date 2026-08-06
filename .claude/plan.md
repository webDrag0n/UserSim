# Migration Plan: Excel → JSON Config Files with Frontend Editing

## Current State Analysis

### Excel-Based System
- **Single file**: `balance-sheet/UserSim数值配表.xlsx`
- **8 sheets**: 恢复事件配表, 日常事件配表, 自定义活动类目, 职业收入表, 扰动事件配表, 模板与动力学, 系列事件配表, 经济与全局参数, 习惯化曲线, 需求参数, 人格调节
- **Loading**: `usersim/world/balance.py` loads with openpyxl, process-level cache
- **Editing**: Frontend (`Balance.tsx`) edits cells via `/api/balance` and `/api/balance/cell`
- **Hot reload**: `reload()` invalidates cache after writes
- **Generation**: `scripts/export_balance_sheet.py` generates from code constants

### Code Constants
- `usersim/world/catalog.py`: RECOVERY_ACTIONS, MEAL_TIERS, SLEEP_TIERS, DISTURBANCES, PROFESSIONS, CUSTOM_ACTIVITIES, ECONOMY, TEMPLATE_EVENTS
- `usersim/world/anthro.py`: HABITUATION_DEFAULTS
- `usersim/world/series.py`: SERIES_TYPES (inferred from export script)
- Need parameters and persona modulation rules (currently in Excel only)

---

## Migration Strategy

### 1. New Directory Structure
```
config/
├── system.toml                    # existing - unchanged
├── llm.toml                       # existing - unchanged
├── balance/                       # NEW
│   ├── recovery_actions.json      # 恢复事件配表
│   ├── meal_tiers.json            # 日常事件配表 - meals
│   ├── sleep_tiers.json           # 日常事件配表 - sleep
│   ├── custom_activities.json     # 自定义活动类目
│   ├── professions.json           # 职业收入表
│   ├── disturbances.json          # 扰动事件配表
│   ├── template_events.json       # 模板与动力学
│   ├── series_types.json          # 系列事件配表
│   ├── economy.json               # 经济与全局参数 - economy part
│   ├── dynamics.json              # 经济与全局参数 - dynamics part
│   ├── habituation.json           # 习惯化曲线
│   ├── needs.json                 # 需求参数
│   └── persona_modulation.json    # 人格调节
```

### 2. JSON Schema Design

**Rationale**: Keep JSON structure close to Python constants for minimal code changes.

#### recovery_actions.json
```json
[
  {
    "id": "A1",
    "action": "吃好吃的",
    "category": "饮食",
    "base_effect": {"satiety": 0.25},
    "design_intent": "都能吃饱；档位差异主要体现在心情与减压",
    "variants": [
      {
        "vid": "A1-1",
        "location": "楼下快餐",
        "tier": "平价",
        "cost": 30,
        "span": 1,
        "weight": {"valence": 0.02, "stress": -0.02},
        "effect": {}
      }
    ]
  }
]
```

#### habituation.json
```json
{
  "吃好吃的": {"w_min": 0.5, "tau": 2.0, "curve": "exp"},
  "好好休息": {"w_min": 0.4, "tau": 1.5, "curve": "exp"}
}
```

#### needs.json
```json
{
  "饥饿": {
    "accumulate": "由饱腹推导（低饱腹加速）",
    "satisfy_events": "吃好吃的/三餐",
    "urge_curve": "u=((1-x)/0.6)^1.5",
    "satisfy_curve": "s=1+1.5u"
  }
}
```

#### persona_modulation.json
```json
{
  "外向性": {
    "rule": "社交事件精力×(1+1.2E)/(1.6-1.2E)；E>0.7 额外心情+0.03",
    "intent": "社交电池：内向耗电、外向回血"
  }
}
```

### 3. Backend Changes

#### A. New Loader Module: `usersim/world/balance_json.py`
Replace `balance.py` with JSON-based loader:
- `load_balance_config() -> dict`: Load all JSON files from `config/balance/`
- Process-level cache with `reload()` for hot updates
- Fallback to `catalog.py` constants if files missing
- Compute `variant["effect"]` from `base_effect + weight` on load
- Return same dict structure as current `load_overrides()`

#### B. Update `catalog.py`
- Keep Python constants as fallback defaults
- Update `_ov()` to call new `load_balance_config()`
- No changes to public API (`get_recovery_actions()`, etc.)

#### C. Update `config.py`
- Add `load_balance_config()` as a module-level function
- Update `artifact_hashes()` to hash JSON files instead of Excel

#### D. Migration Script: `scripts/migrate_excel_to_json.py`
- Read existing Excel file if present
- Export each sheet to corresponding JSON file
- Preserve user edits from Excel
- One-time migration tool

#### E. Export Script: `scripts/export_balance_json.py`
- Replace `export_balance_sheet.py`
- Generate JSON files from code constants
- Used for initial setup or reset to defaults

### 4. API Changes

#### New Endpoints in `server/app.py`
Replace Excel-specific endpoints:

**GET `/api/balance`** → **GET `/api/balance/config`**
```python
@app.get("/api/balance/config")
def get_balance_config() -> dict:
    """Return all balance config files as nested structure for editing."""
    return {
        "source": "json",  # or "default" if using code fallback
        "files": {
            "recovery_actions": {...},
            "meal_tiers": [...],
            # ... all 12 files
        }
    }
```

**POST `/api/balance/cell`** → **POST `/api/balance/save`**
```python
class BalanceSaveRequest(BaseModel):
    file: str  # e.g., "recovery_actions"
    content: Any  # full JSON content

@app.post("/api/balance/save")
def save_balance_config(req: BalanceSaveRequest) -> dict:
    """Write entire JSON file and hot-reload."""
    path = CONFIG_ROOT / "balance" / f"{req.file}.json"
    path.write_text(json.dumps(req.content, ensure_ascii=False, indent=2))
    reload_balance_config()
    return {"ok": True, "file": req.file}
```

**POST `/api/balance/reset`** (new)
```python
@app.post("/api/balance/reset")
def reset_balance_config(file: str | None = None) -> dict:
    """Reset one or all config files to code defaults."""
    # Export from catalog.py constants
```

### 5. Frontend Changes

#### A. Update `web/src/api.ts`
```typescript
export interface BalanceConfig {
  source: 'json' | 'default'
  files: {
    recovery_actions: RecoveryAction[]
    meal_tiers: MealTier[]
    // ... typed interfaces for all 12 files
  }
}

export const api = {
  getBalanceConfig: (): Promise<BalanceConfig> => 
    fetch('/api/balance/config').then(r => r.json()),
  
  saveBalanceFile: (file: string, content: any) =>
    fetch('/api/balance/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({file, content})
    }).then(r => r.json()),
  
  resetBalanceFile: (file?: string) =>
    fetch('/api/balance/reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({file})
    }).then(r => r.json())
}
```

#### B. Rewrite `web/src/views/Balance.tsx`
**New UI approach**: JSON editor with structured forms instead of spreadsheet

**Layout**:
- **Left sidebar**: File selector (12 files)
- **Right panel**: JSON editor with two modes:
  - **Visual mode**: Structured forms with validation
  - **Code mode**: Monaco editor with JSON schema validation

**Features**:
- Real-time validation
- Undo/redo
- Reset to defaults per file
- Save button with hot-reload confirmation
- Curve/urge previews preserved
- Effect calculator (base + weight → total)

**Component structure**:
```tsx
<BalancePage>
  <Sidebar files={...} selected={...} onSelect={...} />
  <Editor>
    <ModeToggle visual|code />
    {mode === 'visual' ? (
      <VisualEditor file={...} data={...} onChange={...} />
    ) : (
      <CodeEditor value={...} schema={...} onChange={...} />
    )}
    <Actions>
      <Button onClick={save}>Save</Button>
      <Button onClick={reset}>Reset</Button>
    </Actions>
  </Editor>
</BalancePage>
```

**Visual editors per file type**:
- `recovery_actions`: Expandable action cards, nested variant editing
- `habituation`: Table with curve preview (existing `CurvePreview`)
- `needs`: Table with urge curve preview (existing `UrgePreview`)
- `economy`/`dynamics`: Simple key-value form
- Others: Generic JSON tree editor with add/remove/edit

### 6. Migration Path

#### Phase 1: Backend Foundation (implement first)
1. Create `config/balance/` directory structure
2. Implement `balance_json.py` loader
3. Write `scripts/migrate_excel_to_json.py`
4. Update `catalog.py` to use new loader
5. Update `config.py` artifact hashes
6. Run migration script to convert existing Excel → JSON

#### Phase 2: API Layer
1. Implement new `/api/balance/config` endpoint
2. Implement `/api/balance/save` endpoint
3. Implement `/api/balance/reset` endpoint
4. Keep old endpoints for backward compatibility (deprecated)

#### Phase 3: Frontend
1. Update `api.ts` with new types and endpoints
2. Rewrite `Balance.tsx` with new UI
3. Add JSON schema validation
4. Add Monaco editor for code mode
5. Preserve curve/urge preview components

#### Phase 4: Cleanup
1. Remove `balance.py` (replaced by `balance_json.py`)
2. Remove `export_balance_sheet.py` (replaced by `export_balance_json.py`)
3. Archive Excel file to `balance-sheet/archive/`
4. Update documentation

### 7. Testing Strategy

1. **Unit tests**: Test JSON loader with valid/invalid files
2. **Integration tests**: Test API endpoints save/load cycle
3. **Migration tests**: Verify Excel → JSON conversion preserves data
4. **Frontend tests**: Verify visual/code editor modes
5. **Hot reload tests**: Verify running simulations pick up changes

### 8. Rollback Plan

- Keep Excel file as `UserSim数值配表.xlsx.backup`
- Add `--use-excel` flag to runner for emergency fallback
- JSON loader can detect Excel file and auto-migrate on first run

### 9. Benefits

1. **Human-readable**: JSON diffs in git, easy code review
2. **Granular editing**: Edit one file without touching others
3. **Type safety**: JSON schema validation in frontend
4. **Version control**: Proper git tracking instead of binary Excel
5. **Flexibility**: Easy to add new config files
6. **Modern UX**: Monaco editor with autocomplete vs. spreadsheet cells
7. **API-friendly**: Standard REST JSON vs. Excel-specific cell updates

### 10. Implementation Order

1. ✅ Write this plan
2. Create directory structure and JSON schema
3. Implement `balance_json.py` loader
4. Write migration script and test with current Excel
5. Update backend (`catalog.py`, `config.py`, `server/app.py`)
6. Update frontend types (`api.ts`)
7. Rewrite `Balance.tsx` UI
8. Testing and validation
9. Documentation updates
10. Cleanup and archival

---

## Questions for User

None - the requirements are clear: replace Excel with JSON config files that can be edited in the frontend.

## Technical Decisions

1. **JSON over TOML/YAML**: Arrays of objects are cleaner in JSON; frontend can use native `JSON.parse()`
2. **12 files over 1 monolithic file**: Granular git diffs, parallel editing safety
3. **Preserve Python constants**: Fallback for missing files, easier testing
4. **Hot reload preserved**: Same `reload()` pattern, just loading JSON instead of Excel
5. **Visual + Code modes**: Visual for non-technical users, code for power users
6. **Compute effects on load**: Same pattern as current `catalog.py`, no schema changes
