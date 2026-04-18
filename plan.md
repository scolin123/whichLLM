# LLM Arena — Project Spec

## Overview

LLM Arena is a model-routing chat application and evaluation platform. It operates in two modes:

1. **Arena mode** — Submit a prompt, get side-by-side outputs from Claude, GPT, and Gemini with automated + human scoring. Historical win rates tracked on an analytics dashboard.
2. **Chat mode** — A conversational interface where an intelligent router picks the best model per turn, maintaining full context across model switches.

Users bring their own API keys (BYOK), stored in-session only — never persisted server-side.

---

## Tech Stack

| Layer          | Technology                          |
|----------------|-------------------------------------|
| Frontend       | Next.js (React), Tailwind CSS       |
| Backend        | FastAPI (Python)                    |
| Database       | PostgreSQL                          |
| Cache          | Redis                               |
| Auth           | NextAuth.js (optional, for user accounts) |
| Deployment     | Vercel (frontend) + Railway/Render (backend + DB) |

---

## Core Architecture

### 1. Provider Abstraction Layer

A base class that every LLM provider extends. Adding a new model = adding one file.

```
providers/
  base.py          # Abstract base: send_prompt(messages, api_key) -> Response
  claude.py        # Anthropic adapter
  openai.py        # OpenAI adapter
  gemini.py        # Google adapter
  registry.py      # Maps provider names to classes
```

Each adapter handles:
- Translating the canonical message format → provider-specific format
- Attaching the user's API key from the request context
- Normalizing the response back to canonical format
- Token counting and context window management per model

### 2. Canonical Message Format

All conversation history is stored in one model-agnostic schema:

```json
{
  "role": "user" | "assistant",
  "content": "message text",
  "metadata": {
    "provider": "claude" | "openai" | "gemini",
    "model": "claude-sonnet-4-20250514",
    "task_type": "code" | "summarization" | "math" | "creative",
    "score": null,
    "tokens_used": 342,
    "latency_ms": 1820
  }
}
```

When sending to a provider, the adapter strips metadata and reshapes. When the response returns, metadata is attached and the message is appended to the canonical history.

### 3. Task Classifier

A lightweight classifier that labels each user prompt with a task type. Two approaches (use both):

- **Keyword/heuristic classifier** — Fast, rule-based. Catches obvious signals like "write a function", "summarize this", "solve for x".
- **LLM-based classifier** — For ambiguous prompts, use one cheap API call to classify. Use the model whose key is available, with a short system prompt: "Classify this prompt as one of: code, summarization, math, creative. Respond with one word."

### 4. Router (Chat Mode)

Uses the task classification + historical eval data to pick the best provider:

```python
def route(task_type: str, available_providers: list[str]) -> str:
    # Look up win rates from eval history
    win_rates = db.get_win_rates(task_type)
    # Filter to providers the user has keys for
    candidates = {k: v for k, v in win_rates.items() if k in available_providers}
    # Return highest win rate, with fallback to default ranking
    return max(candidates, key=candidates.get, default=available_providers[0])
```

Default ranking (before enough eval data exists): Claude for code, GPT for creative, Gemini for summarization, Claude for math. These are starting heuristics — the eval data will override them over time.

### 5. Context Management (Cross-Model Continuity)

The backend maintains a session-level conversation history:

```
sessions/
  {session_id}/
    history: List[CanonicalMessage]
    active_keys: { claude: "sk-...", openai: "sk-...", gemini: "..." }
    eval_results: List[EvalResult]  # Arena mode only
```

**Context window handling:**
- Before each API call, count tokens in the full history
- If over 80% of the target model's limit, apply truncation:
  - Keep system prompt + last 10 turns (always)
  - Summarize older turns into a 1-paragraph context block using the cheapest available model
- Store the full untruncated history server-side — only the API payload gets trimmed

**Cross-model context example:**
1. User asks "Write a Flask route for user authentication" → Router picks Claude
2. Claude responds with code → Appended to canonical history
3. User asks "Create a hero image for this auth page" → Router picks GPT
4. GPT receives the full history including Claude's code, so it understands the project context

### 6. Scoring Engine (Arena Mode)

Three scoring layers, applied based on task type:

| Layer | Applies to | How it works |
|-------|-----------|--------------|
| **Automated checks** | Code, Math | Execute code (sandboxed), verify math answers against known solutions |
| **LLM-as-judge** | All types | A fourth LLM call evaluates all outputs on a rubric (coherence, completeness, accuracy, style) scored 1-10 |
| **Human rating** | All types | User clicks thumbs up/down or ranks outputs 1-3 |

**LLM-as-judge implementation:**
- Use whichever model the user has a key for (prefer the cheapest)
- System prompt provides the original task + all outputs (anonymized as "Response A/B/C") + scoring rubric
- Request structured JSON output with scores per criterion
- To minimize bias, randomize the order of A/B/C across evaluations

**Score normalization:**
- Auto checks: binary pass/fail → 0 or 10
- LLM judge: raw 1-10 scores averaged across criteria
- Human rating: thumbs up = +2 bonus, thumbs down = -2 penalty
- Final score = weighted combination (auto 40%, judge 40%, human 20%)

### 7. BYOK (Bring Your Own Key)

**Frontend:** Settings panel where users paste API keys for each provider. Keys are stored in browser `sessionStorage` — cleared on tab close. Sent to the backend via request headers (never query params).

**Backend:** Keys are read from request headers per-call. Never logged, never written to disk or database. The backend validates keys with a lightweight test call (e.g., a 1-token completion) and reports which providers are active.

**No key provided?** That provider is grayed out in Arena mode and excluded from the router in Chat mode. The system gracefully degrades — if you only have a Claude key, it's Claude-only and the routing is skipped.

### 8. Analytics Dashboard

**Data stored per evaluation:**
- Timestamp
- Task type
- Provider + model used
- Scores (auto, judge, human)
- Latency (ms)
- Token usage (input + output)

**Dashboard views:**
- **Win rate by category** — Bar chart showing which model wins most often per task type
- **Score distribution** — Box plots of scores per model
- **Latency comparison** — Average response time per model
- **History table** — Scrollable list of past evaluations with expand-to-view outputs
- **Trends over time** — Line chart of win rates as more data accumulates

---

## API Routes

```
POST   /api/arena/evaluate     # Arena mode: send prompt to all models, score, return comparison
POST   /api/chat/send          # Chat mode: classify, route, send with context, return response
POST   /api/keys/validate      # Validate user API keys
GET    /api/analytics/summary  # Dashboard aggregate stats
GET    /api/analytics/history  # Paginated evaluation history
GET    /api/session/{id}       # Retrieve session conversation history
DELETE /api/session/{id}       # Clear session
```

---

## Frontend Pages

| Route | Description |
|-------|-------------|
| `/` | Landing page — choose Arena or Chat mode |
| `/arena` | Prompt input + task selector → side-by-side results with scores |
| `/chat` | Conversational UI with model indicator showing which model is responding |
| `/dashboard` | Analytics charts and evaluation history |
| `/settings` | API key input + validation status per provider |

---

## Development Timeline (4 Weeks)

### Week 1 — Backend Foundation
- [ ] FastAPI project scaffolding + project structure
- [ ] Provider abstraction layer (base class + Claude/GPT/Gemini adapters)
- [ ] Canonical message format + format translation per provider
- [ ] API key validation endpoint
- [ ] Task classifier (keyword heuristic + LLM fallback)
- [ ] Redis caching layer for duplicate prompts
- [ ] PostgreSQL schema + migrations (evaluations, sessions)

### Week 2 — Scoring Engine + Arena Mode
- [ ] Arena endpoint: fan out prompt to all active providers concurrently (asyncio.gather)
- [ ] Automated scoring: code execution sandbox, math answer verification
- [ ] LLM-as-judge pipeline with randomized ordering + structured output
- [ ] Score normalization and aggregation
- [ ] Store evaluation results in PostgreSQL
- [ ] Basic arena API tested end-to-end with curl/Postman

### Week 3 — Frontend + Chat Mode
- [ ] Next.js project setup with Tailwind
- [ ] Settings page: API key input with validation indicators
- [ ] Arena page: prompt input, task selector, side-by-side results view
- [ ] Human rating UI (thumbs up/down on each output)
- [ ] Chat page: conversational UI with model indicator badge
- [ ] Chat backend: context management, router logic, cross-model history
- [ ] Session management (create, retrieve, clear)

### Week 4 — Dashboard + Polish
- [ ] Analytics dashboard with charts (use Recharts or Chart.js)
- [ ] Win rate by category, latency comparison, score distributions
- [ ] Evaluation history table with expandable rows
- [ ] Loading states, error handling, empty states across all pages
- [ ] Mobile responsiveness
- [ ] README with setup instructions, architecture diagram, demo GIFs
- [ ] Deploy: Vercel (frontend) + Railway or Render (backend + Postgres + Redis)
- [ ] Record a 2-minute demo video for portfolio

---

## Stretch Goals (Post-MVP)
- **Hybrid mode in Chat** — "Show me alternatives" button on any Chat mode response that fires the same prompt to the other two providers for an on-demand side-by-side comparison without leaving the chat flow. The router still picks the primary model, but users can spot-check its choice on any turn.
- **User accounts + encrypted key storage** — NextAuth.js login (Google/GitHub OAuth) so users don't need to re-enter API keys each session. Keys encrypted with AES-256 before writing to Postgres, master encryption key stored as an environment variable. Includes key rotation (update/revoke from settings) and per-user rate limiting.
- Add more providers (Mistral, Llama via Groq, Cohere)
- Prompt optimization mode: auto-rewrite prompts per model's strengths
- Export evaluation reports as PDF
- Shareable comparison links
- Custom scoring rubrics per task type
- WebSocket streaming for real-time response rendering in chat mode