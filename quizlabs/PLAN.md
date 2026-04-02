# QuizLabs Feature Plan

> Last updated: 2026-04-02

## Status Summary

| Phase | Status | Items |
|---|---|---|
| Phase 1: Quick Fixes | ✅ Complete | 2/2 |
| Phase 2: Sync DB ↔ Frontend | ✅ Complete | 1/1 |
| Phase 3: Free Dailies | ✅ Code complete | 3/3 (K8s CronJob manifest pending) |
| Phase 4: Frontend UX | 🔶 Partial | 2/3 |
| Phase 5: Monitoring | 🔲 Not started | 0/3 |
| Phase 6: Research | ✅ Complete | 1/1 |

---

## Phase 1: Quick Fixes ✅

- [x] **Step 1** — Add dots to AI prompt sentences
  - File: `quiz-app-backend/common/utils/ai/prompts.py`
  - Fixed missing periods on all prompt templates, typos ("an very" → "a very", "challange" → "challenge")

- [x] **Step 2** — Add settings note about model quality
  - File: `quiz-app-frontend/react-app/src/components/layout/RightSidebar.jsx`
  - Added italic note below AI model selection: "The better the model, the better the content will be."

## Phase 2: Sync DB ↔ Frontend Categories ✅

- [x] **Step 3** — Match DB topics to the 9 frontend category sections
  - File: `quiz-app-frontend/react-app/src/constants/categoryGroups.js`
  - Renamed: `CI/CD Foundations` → `CI/CD Methodology`, `Reliability & On-Call` → `Reliability & Alerting`
  - Replaced: `AppSec & Supply Chain` → `Security Testing` + `SSO & OIDC`
  - Removed: `Network Infrastructure` (not in DB)
  - Added: `DevOps Methodology` (Delivery section), `Databases Basics` (Data section)

## Phase 3: Pre-Generated Free Dailies ✅ (code complete)

- [x] **Step 4** — Cronjob script for daily generation
  - File: `quiz-app-backend/api/scripts/generate_dailies.py` (new)
  - Pre-generates tomorrow's daily challenge + deep dive article using server API key
  - Reuses `DBController`, `QuizRepository`, `AIQuestionService`
  - **⚠️ TODO**: K8s CronJob manifest needed — Dockerfile, Job spec, secret mount for OpenAI API key

- [x] **Step 5** — Daily endpoints serve pre-generated content
  - Files: `quiz-app-backend/api/server/routes/daily_challenge_routes.py`, `daily_deep_dive_routes.py`
  - Removed lazy-generation fallback — returns 404 if cronjob hasn't run
  - Answer evaluation uses server API key (free for all users, 1/day naturally)
  - Cleaned up unused imports and background thread code

- [x] **Step 6** — Frontend: Remove API key gate on dailies
  - Files: `quiz-app-frontend/react-app/src/api/quizAPI.js`, `DailyChallengeView.jsx`, `DailyDeepDiveView.jsx`
  - Removed `getAIHeaders()` from daily API calls
  - Removed generating state/polling from deep dive view

## Phase 4: Frontend UX 🔶

- [x] **Step 7** — Daily question history in right sidebar
  - Backend: `daily_challenge_repository.py` — added `get_user_history()` via aggregation pipeline
  - Backend: `daily_challenge_routes.py` — added `GET /api/daily-challenge/history?limit=10`
  - Frontend: `quizAPI.js` — added `getDailyChallengeHistory()`
  - Frontend: `RightSidebar.jsx` — added `DailyHistoryPanel` wired to `activeTab === 'daily'`

- [x] **Mobile leaderboard** — Added `LeaderboardPanel` to `StatsView.jsx` with `lg:hidden` wrapper

- [ ] **Mobile game chat** — Mobile users should access live game chat via a dedicated styled button

## Phase 5: Monitoring 🔲

- [ ] **Step 8** — Enhanced Prometheus metrics + Grafana dashboard
  - Custom counters: `questions_generated_total`, `answers_evaluated_total`, `daily_challenges_completed_total`, `ai_tokens_used_total`
  - K8s ServiceMonitor + Grafana dashboard JSON
  - Structured JSON logging with request_id correlation

- [ ] **Database management** — Integrate direct database management access using web UI

## Phase 6: Research ✅

- [x] **Step 9** — Pretext library research
  - `@chenglou/pretext` — pure JS/TS text measurement/layout without DOM reflow (32k+ stars, MIT)
  - Potential uses: virtualized lists, canvas text effects, shrink-wrap text
  - Decision: low priority, no code changes for now

---

## Decisions

| Decision | Status |
|---|---|
| **Free tier questions** | Deferred — requires abuse prevention (Google OAuth gating recommended) |
| **Free dailies** | Yes — cronjob pre-generates using server API key |
| **DB reorg & job topics** | Excluded (handled personally) |
| **Daily answer evaluation** | Uses server API key (free for all) |
| **Cronjob runtime** | Python script, deployable as K8s CronJob |

## Changed Files

### quiz-app-backend
- `common/utils/ai/prompts.py` — prompt sentence fixes
- `common/repositories/daily_challenge_repository.py` — added `get_user_history()`
- `api/server/routes/daily_challenge_routes.py` — removed lazy gen, added history endpoint, server-key eval
- `api/server/routes/daily_deep_dive_routes.py` — removed lazy gen + background thread
- `api/scripts/generate_dailies.py` — NEW: cronjob script

### quiz-app-frontend
- `react-app/src/constants/categoryGroups.js` — synced with DB topics
- `react-app/src/components/layout/RightSidebar.jsx` — settings note, daily history panel
- `react-app/src/api/quizAPI.js` — removed AI headers from dailies, added history API
- `react-app/src/views/DailyDeepDiveView.jsx` — removed generating/polling state
- `react-app/src/views/StatsView.jsx` — mobile leaderboard
