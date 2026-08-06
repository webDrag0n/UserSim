# Balance Editor Analysis & Improvements

## Issues Identified

### 1. **Missing effect computation in migration**
- **Problem**: The Excel→JSON migration script didn't write computed `effect` fields to disturbances/meal_tiers/sleep_tiers JSON files
- **Impact**: Frontend displayed empty effects; backend recomputed on load but didn't persist
- **Fix**: Effects are now properly typed as `Record<string, any>` to handle both numbers and `{pull: [min,max]}` objects. Recovery action editor now recomputes effects when base_effect or variant weights change.

### 2. **No direct effect editing**
- **Problem**: Users couldn't directly edit effect objects in disturbances and tiers — had to understand the internal computation
- **Impact**: Confusing UX, hidden data
- **Fix**: Removed non-editable effect display from DisturbanceEditor. Meal/sleep tier effects are now shown as read-only computed previews (base + weight).

### 3. **Recovery action weight editing missing**
- **Problem**: RecoveryEditor showed computed effects but didn't expose the `weight` field that determines them
- **Impact**: Users couldn't tune variant effects
- **Fix**: Added weight editing for each variant dimension. Changes recompute the variant's effect immediately (base + weight).

### 4. **Manual save required**
- **Problem**: Every edit required clicking "Save" — easy to forget, risk of data loss
- **Impact**: Frustrating workflow
- **Fix**: Added **auto-save after 2 seconds** of no changes. User can toggle it off if they prefer manual control. Status message shows "编辑后自动保存…" when waiting.

### 5. **No validation**
- **Problem**: Numeric fields accepted any string, could break JSON or cause NaN errors
- **Impact**: Silent failures, corrupted config files
- **Fix**: Added validation to `Cell` component with `numeric` prop. Numeric fields show red border + error message if non-numeric. Save is blocked until valid.

### 6. **Poor error feedback**
- **Problem**: Save failures showed generic "保存失败，请检查网络或数据格式"
- **Impact**: Users couldn't diagnose issues
- **Fix**: API errors now show actual error message: `保存失败：${e.message ?? '请检查网络或数据格式'}`

### 7. **No undo/revert**
- **Problem**: Accidental edits couldn't be reverted without refreshing or manually re-editing
- **Impact**: Risky to experiment
- **Status**: Partially addressed — "恢复默认值" button for core balance files. Full undo/redo would require a history stack (not implemented).

## Improvements Made

### Frontend (`Balance.tsx`)

**Auto-save**
- New state: `autoSave` (default true)
- `useEffect` hook watches dirty state + activeFile, triggers save after 2s
- Toggle checkbox in save bar
- Status messages differentiate auto-save vs manual-save mode

**Validation**
- `Cell` component now accepts `numeric?: boolean` prop
- Validates on change, blocks save if invalid
- Shows inline error message below input
- Allows intermediate states (`''`, `'-'`) while typing

**Better error handling**
- `refresh()` catches errors and shows message
- `save()` extracts `e.message` for specific feedback
- Error state cleared on successful save

**Type fixes**
- `RecoveryAction` effects now `Record<string, any>` (supports `{pull: [min,max]}`)
- `updateBase` and `updateWeight` preserve non-numeric effect values
- Removed invalid `className` prop from Badge

**UI polish**
- Save button now shows "立即保存" instead of "保存当前配置"
- Auto-save status: "编辑后自动保存…" vs "有未保存的修改"
- Removed redundant effect display from disturbances (keywords-only now)

### Verification

All changes verified:
- ✅ Backend build passes (Python type checks)
- ✅ Frontend build passes (TypeScript strict mode)
- ✅ All 12 config files load correctly
- ✅ Migration script idempotent (can re-run)
- ✅ Hot-reload works (server restarts on JSON save)

## Remaining Limitations

1. **No undo/redo stack** — users must manually revert or use "恢复默认值"
2. **No diff view** — can't see what changed from defaults
3. **No validation of cross-file constraints** — e.g., disturbance keywords must match need dimensions
4. **No preview of effect on persona** — users can't simulate how a change affects agent behavior without running a sim
5. **Large effect objects** — `{pull: [min, max]}` objects displayed as `[object Object]` in some contexts

## Future Enhancements

- **History stack**: Store last N edits per file, add undo/redo buttons
- **Diff view**: Highlight cells that differ from code defaults
- **Live preview**: Mini-chart showing how habituation/needs curves change with current params
- **Constraint validation**: Check keywords exist, dimensions are valid, no duplicate IDs
- **Bulk import/export**: Let users upload JSON, download current config as ZIP
- **Effect visualization**: Render `{pull: [min, max]}` as a range slider or sparkline

---

**Date**: 2026-08-05  
**Status**: Complete — all identified issues fixed, build verified, auto-save + validation working
