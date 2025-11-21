# PRF4: Pipeline Debug View Polish & UX Refinement

## overview

this pr is a **presentation-only polish pass** on the existing pipeline debug view. no backend changes, no new data fields, no new api contracts, no new state beyond what already exists from prf0-prf3.

goal: make the pipeline debug view demo-ready by improving visual hierarchy, scannability, and readability.

## what changed

### 1. visual hierarchy: onboarding vs decision (StageList)

**problem**: all stages were rendered in a flat list with no clear separation between the two conceptual phases of the pipeline.

**solution**: 
- grouped stages by `kind` into two sections:
  - **onboarding pipeline** (o0-o4): "structuring the factory"
  - **decision pipeline** (d1-d5): "intent → futures → sim → briefing"
- added group headers with visual distinction (blue accent, bold title, italic subtitle)
- kept grouping logic generic: infers groups from existing `kind` field, not hard-coded positions

**implementation**:
- `StageList.tsx`: added `groupStages()` helper that filters by `kind: "ONBOARDING"` vs `kind: "DECISION" | "SIMULATION"`
- `StageList.css`: added `.stage-group`, `.stage-group-header`, `.stage-group-title`, `.stage-group-subtitle` classes

**rationale**: at a glance, an evaluator can now see "this is a multi-stage pipeline with two phases" without reading every stage name.

---

### 2. scannable stage rows (StageList)

**problem**: summary text was verbose and inconsistent across stage types.

**solution**: tightened summaries to one-liners that convey essential info:
- **onboarding examples**:
  - o0: `6 ids detected (3 machines, 3 jobs)`
  - o1: `3 machines, 3 jobs extracted`
  - o4: `coverage 100%` or `coverage 67% (missing: m5, j7)`
- **decision examples**:
  - d1: `intent: baseline`
  - d2: `3 scenarios`
  - d3: `3 sims run`
  - d5: `briefing 1200 chars`

**implementation**:
- refactored `getStageSummaryText()` to compute tight summaries from existing `summary` payload
- added tooltip via `title` attribute on stage row: shows status + errors inline

**rationale**: an engineer should be able to scan the list and understand what happened in 2-3 seconds without opening every detail panel.

---

### 3. readable detail panel (StageDetailPanel)

**problem**: detail panel was dense and hard to parse. coverage failure case didn't tell a clear story.

**solution**: restructured detail panel into clear sections:

**header improvements**:
- cleaner title: `[✓] o4: coverage assessment`
- metadata on second line: badge for `kind` + monospace for `agent_model`
- removed redundant "status: SUCCESS" (icon already conveys this)

**summary section improvements**:
- added **section intro**: plain-language description of what the stage does (e.g., "verified that parsed entities cover detected ids")
- broke content into **subsections** with h5 headers:
  - `detected ids` (what o0 found)
  - `parsed entities` (what o1-o3 extracted)
  - `coverage` (percentages + 100% flag)
  - `missing` (highlighted in yellow if present)
- used **bullet lists** instead of inline comma sludge
- for coverage failure, added **action taken** block: "system fell back to demo factory; decision pipeline ran using fallback config."

**implementation**:
- refactored `renderSummaryContent()` to return structured JSX with subsections
- added `.section-intro`, `.summary-subsection`, `.summary-list`, `.action-taken` CSS classes
- used `.summary-subsection--warning` for missing entities

**rationale**: when onboarding fails, the path from "what went wrong" → "what we did" is now obvious. no more wall of text.

---

### 4. fallback banner integration (App.tsx)

**problem**: fallback banner had a "view pipeline details" button, but it wasn't obvious which stage to open.

**solution**:
- updated button logic to prefer `o4` (coverage assessment) if it failed
- fallback to first failed onboarding stage otherwise
- lowercased banner text to match the rest of the app's casual tone

**implementation**:
- in `App.tsx`, filter onboarding stages by `kind: "ONBOARDING"` and status `FAILED`
- check if `o4` is in failed list first, otherwise take first failed
- set `expandedStageId` on button click

**rationale**: when the user clicks "view pipeline details" from the fallback banner, they land directly on the stage that caused the fallback (usually o4 for coverage mismatch).

---

### 5. pipeline summary improvements (PipelineSummary)

**problem**: summary text was generic and didn't highlight which phase failed.

**solution**:
- for `SUCCESS`: show counts by phase: `all stages succeeded (5 onboarding, 5 decision)`
- for `PARTIAL`: identify failing stage: `onboarding failed at o4 → using demo factory; decision pipeline succeeded`
- for `FAILED`: identify failing decision stage: `decision pipeline failed at d3`

**implementation**:
- filter stages by `kind` to separate onboarding vs decision
- find first failed stage in each group
- construct status text with stage id

**rationale**: high-level summary should tell you at a glance which phase failed and where.

---

### 6. css polish

**principles**:
- minimal additions: ~20 new classes total across 3 files
- no inline styles
- consistent with existing app.css patterns (same color palette, spacing rhythm)
- responsive: stage rows stack on narrow screens (<768px)

**changes**:
- `StageList.css`: group headers, responsive stacking
- `StageDetailPanel.css`: subsection structure, metadata badges, action-taken block
- `PipelineSummary.css`: no changes needed (status badges already worked)

---

## edge cases handled

1. **debug is null**: show "pipeline details not available for this run."
2. **debug.stages is empty**: show "no pipeline stages recorded for this run."
3. **some stage ids missing**: don't crash; render what you have; grouping still works if stages have `kind` field
4. **all stages success**: summary shows green, no fallback
5. **onboarding failure + fallback**: summary explains which stage failed, fallback banner points to it, detail panel shows "action taken"
6. **decision failure**: summary identifies failing decision stage

---

## what didn't change

- **no backend changes**: didn't touch python at all
- **no new api fields**: only used existing `PipelineDebugPayload`, `PipelineStageRecord`, `summary` shape
- **no new global state**: still just `pipelineDebug` and `expandedStageId`
- **no business logic in components**: all logic is presentational (grouping, formatting)
- **no css framework**: stayed with vanilla css

---

## testing

- **typecheck**: `tsc` passes
- **build**: `npm run build` passes
- **linter**: no errors
- **manual smoke test**: tested with:
  - all stages success
  - onboarding failure (coverage < 100%)
  - missing debug payload
  - empty stages list

---

## files modified

### components:
- `frontend/src/components/StageList.tsx`: grouping logic, tighter summaries
- `frontend/src/components/StageList.css`: group header styles, responsive
- `frontend/src/components/StageDetailPanel.tsx`: structured summary rendering, fallback messaging
- `frontend/src/components/StageDetailPanel.css`: subsection styles, metadata badges
- `frontend/src/components/PipelineSummary.tsx`: smarter status text
- `frontend/src/components/PipelineSummary.css`: (no changes)

### app:
- `frontend/src/App.tsx`: improved fallback banner button logic

---

## diff size

- **lines changed**: ~400 (mostly in StageList.tsx and StageDetailPanel.tsx)
- **new files**: 0
- **deleted files**: 0

small, targeted diff. no architectural changes.

---

## demo readiness checklist

- [x] visual clarity: onboarding vs decision sections are obvious
- [x] scannable rows: each stage has a tight, meaningful summary
- [x] selected stage: visually obvious (blue border)
- [x] detail quality: not a wall of text; sectioned and structured
- [x] coverage failure story: reads like a coherent narrative
- [x] fallback explainability: 1-click path from banner to failing stage
- [x] no regressions: build passes, typechecks clean, no backend changes
- [x] responsive: works on narrow screens

---

## design decisions

### why group by kind instead of hard-coding o0-o4 / d1-d5?

because if we add a new onboarding stage later (e.g., o5), it will automatically appear in the onboarding group. hard-coding positions would break.

### why prefer o4 for the fallback banner button?

o4 (coverage assessment) is the most common onboarding failure mode and the most informative for users. if coverage passed but something else failed (e.g., normalization), we fall back to the first failed stage.

### why lowercase text in the banner?

matches the user's stated preference for casual, grounded tone. also matches the rest of the app (status badge text is now lowercase too).

### why subsections instead of flat key-value pairs?

coverage assessment has a lot of info (detected, parsed, missing). subsections with headers make it scannable instead of overwhelming.

### why the "action taken" block?

when onboarding fails, the user needs to know "what did the system do?" not just "what went wrong?". the action-taken block closes the loop.

---

## future work (out of scope for prf4)

- expand/collapse groups
- keyboard navigation (arrow keys)
- copy stage summary to clipboard
- link from detail panel to factory panel (e.g., click missing machine id to scroll to factory list)
- performance: virtualize stage list if we ever have >50 stages

---

## conclusion

prf4 makes the pipeline debug view demo-ready with minimal code changes. the view now tells a clear story: "here's what the pipeline did, here's where it failed, here's what we fell back to."

no backend changes. no new data. just presentation polish.

