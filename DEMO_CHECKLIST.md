# Demo Checklist

Use this checklist to verify the system is ready for demonstration or deployment.

## Pre-Demo Setup

- [ ] Backend dependencies installed (`pip install -U openai pydantic pytest fastapi uvicorn`)
- [ ] Frontend dependencies installed (in `frontend/`, run `npm install`)
- [ ] OpenAI API key set: `export OPENAI_API_KEY="sk-..."`

## Running the Demo Locally

### Backend

```bash
# In repository root
uvicorn backend.server:app --reload
```

- [ ] Backend starts without errors
- [ ] Server shows: `Uvicorn running on http://127.0.0.1:8000`
- [ ] API docs available at `http://localhost:8000/docs`

### Frontend

```bash
# In frontend/ directory
npm run dev
```

- [ ] Frontend dev server starts
- [ ] Browser opens automatically (or navigate to `http://localhost:5173`)
- [ ] No console errors

## Integration Verification

- [ ] Both backend and frontend running simultaneously
- [ ] Frontend can reach backend at `http://localhost:8000/api/simulate`
- [ ] CORS headers are present in response (no CORS errors in browser console)

## UI/UX Checks

- [ ] Instructions text visible at top: "1) Describe your factory..."
- [ ] Left textarea labeled: "Factory Description (machines, jobs, routing)"
- [ ] Right textarea labeled: "Today's Situation / Priorities (rush orders, slowdowns, constraints)"
- [ ] "Simulate" button is green and clickable
- [ ] Loading state shows "Simulating..." while request is in flight

## Test Simulation 1: Normal Day

**Input:**
- Factory: "3 machines (M1 assembly, M2 drill, M3 pack). J1: 2h on M1, 3h on M2, 1h on M3. J2: 1.5h on M1, 2h on M2, 1.5h on M3. J3: 3h on M1, 1h on M2, 2h on M3."
- Situation: "Normal production day. No rush orders. Understand baseline performance."

**Expected:**
- [ ] Simulation completes without error
- [ ] Factory panel shows 3 machines and 3 jobs
- [ ] Metrics table displays with at least 1 scenario
- [ ] Briefing appears in scrollable panel
- [ ] No red error banner

## Test Simulation 2: Rush Order

**Input:**
- Factory: (same as above)
- Situation: "Rush order for J2. Must deliver by hour 12. J1 can be slightly delayed but try to minimize. J3 is flexible."

**Expected:**
- [ ] Simulation completes
- [ ] Metrics show different makespan/lateness compared to Test 1
- [ ] Briefing mentions rush order impact
- [ ] All panels are readable and scrollable

## Briefing Panel Readability

- [ ] Briefing text wraps correctly (no horizontal overflow)
- [ ] Briefing is scrollable if content exceeds ~400px height
- [ ] Whitespace is preserved in formatted sections
- [ ] Links/bold text (if any) are readable

## Error Handling

- [ ] Stop backend (e.g., `Ctrl+C` on uvicorn)
- [ ] Try to simulate in frontend
- [ ] Error banner appears with readable message
- [ ] Restart backend, simulate again – works

## Environment Configuration (Optional – for deployment)

### Backend CORS

- [ ] Default behavior: CORS allows `*` (localhost dev works)
- [ ] Set `BACKEND_CORS_ORIGINS=https://example.com` in `backend/.env`
- [ ] Verify backend respects this on next start

### Frontend API URL

- [ ] Default behavior: Frontend calls `http://localhost:8000`
- [ ] Set `VITE_API_BASE_URL=https://api.example.com` in `frontend/.env`
- [ ] Rebuild/restart frontend
- [ ] Verify requests go to new URL (inspect Network tab in browser DevTools)

## Deployment Readiness

- [ ] `backend/.env.example` exists with comments
- [ ] `frontend/.env.example` exists with comments
- [ ] No real secrets or API keys committed (check `.gitignore`)
- [ ] README.md has clear "Backend" and "Frontend" setup sections
- [ ] DEMO_CHECKLIST.md is comprehensive and follows this template

## Final Verification

- [ ] All tests pass: `python -m pytest` (in repo root)
- [ ] No TypeScript errors in frontend (build should succeed: `npm run build`)
- [ ] Git history is clean and PR description is clear

---

**Demo complete!** System is ready for presentation or deployment.
