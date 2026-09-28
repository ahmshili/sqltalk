# Deploying the free public demo

This guide takes the SQLTalk demo from zero to a live, 100%-free, public
URL — **Neon Postgres** (free tier) for the database and **Streamlit
Community Cloud** (free tier) for hosting. It is written for a recruiter
demo, so it also covers seeding realistic sample data and keeping your
local MS SQL Server workflow untouched.

The local development workflow (SQL Server 2022 + `AdventureWorks2022`)
does not change. The public demo is a *second profile* selected by
`DB_DIALECT=postgres`.

---

## 1. Create the Neon database (free)

1. Sign up at [neon.tech](https://neon.tech) (free — GitHub login works).
   The **Free plan** includes ~10 compute hours/day of activity on a
   shared, auto-suspending compute instance. No credit card required.
2. Create a project (any name, e.g. `sqltalk-demo`). Neon provisions a
   Postgres 16+ database with a `neondb` database by default.
3. Open the project's **Dashboard → Connection string** (or **Connection
   Details**) and copy the pooled connection string. It looks like:

   ```
   postgresql://<user>@<endpoint>:<password>@<host>/<dbname>?sslmode=require
   ```

   Two Neon quirks worth knowing:
   - The **endpoint is embedded in the username** as
     `user@ep-cool-name-123456` — that whole string is the username.
   - Neon's URI uses the `postgres://` scheme. SQLTalk's SQLAlchemy layer
     needs `postgresql+psycopg2://`; either paste it into the app's
     `DB_CONNECTION_STRING` after swapping the scheme, or use the parts
     form (below) and SQLTalk builds it for you.

### Configure the app's database

**Option A — full URI** (`.env` or Streamlit secrets):

```
DB_DIALECT=postgres
DB_CONNECTION_STRING="postgresql+psycopg2://<user>@<endpoint>:<password>@<host>/<dbname>?sslmode=require"
```

**Option B — parts** (recommended for Streamlit Cloud secrets):

```
DB_DIALECT=postgres
DB_HOST=ep-cool-name-123456.us-east-2.aws.neon.tech
DB_NAME=neondb
DB_USER=<user>@ep-cool-name-123456
DB_PASSWORD=<password>
```

(`DB_PORT` and `DB_SSLMODE` are optional; defaults are 5432 and `require`.)

---

## 2. Seed the demo data

With your local `.env` pointed at Neon (set `DB_DIALECT=postgres` and the
connection string from step 1), run:

```powershell
.\.venv\Scripts\activate
python seed_postgres_demo.py
```

The script:
- creates two business schemas, `production` and `sales` (lowercase,
  Postgres-style naming in the spirit of AdventureWorks);
- loads a fixed, deterministic dataset — 4 product categories, 16 products,
  9 sales territories, 60 customers, 420 orders (2012–2014), ~800 order
  items — so every demo run answers questions against identical data;
- is **idempotent**: rerunning wipes and reloads only the demo schemas.

After seeding, questions like *"Which sales territory generated the most
revenue?"*, *"Top 10 products by total sales."* and *"Which customers never
placed an order?"* all have real answers.

> Tip: run the seeder from a machine where you can spare the wait — the
> first connection to a sleeping Neon compute takes a few seconds.

---

## 3. Get the free LLM keys

The fallback chain tries providers in inference-speed order:
**Groq → Gemini → OpenRouter**. Configure at least one; all three makes the
demo resilient to rate limits (each provider's free tier has different
quotas).

| Provider | Key URL | Free tier notes | Default model |
|---|---|---|---|
| Groq (recommended) | [console.groq.com/keys](https://console.groq.com/keys) | Generous per-minute limits, fastest tokens/sec | `llama-3.3-70b-versatile` |
| Gemini | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) | Free tier with per-day quota | `gemini-1.5-flash` |
| OpenRouter | [openrouter.ai/keys](https://openrouter.ai/keys) | Free `:free` models, no card needed | `nvidia/nemotron-3-ultra-550b-a55b:free` |

**Multiple keys per provider** (optional): comma-separate them, or use
numbered variables — Streamlit Cloud secrets cannot repeat a name:

```
GROQ_API_KEY=key1,key2
# or
GROQ_API_KEY_1=key1
GROQ_API_KEY_2=key2
```

Keys are tried left-to-right before the chain moves to the next provider.

---

## 4. Deploy to Streamlit Community Cloud (free)

1. Push the repository to GitHub (public repo, free).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with
   GitHub.
3. **Create app** → pick the repo/branch →
   - Main file path: `app.py`
   - App URL: anything, e.g. `sqltalk-demo`
4. Expand **Advanced settings** before deploying:
   - Python version: 3.10+ (3.11 recommended)
   - (Secrets can also be added after deploy.)
5. Deploy. First build takes a few minutes.

### Add the secrets

In the app's **Manage app → Edit secrets**, paste (values from steps 1 & 3):

```toml
# ── Database (Neon) ─────────────────────────────
DB_DIALECT = "postgres"
DB_HOST = "ep-cool-name-123456.us-east-2.aws.neon.tech"
DB_NAME = "neondb"
DB_USER = "user@ep-cool-name-123456"
DB_PASSWORD = "your-neon-password"

# ── LLM providers ───────────────────────────────
GROQ_API_KEY = "gsk_..."
GEMINI_API_KEY = "AI..."
OPENROUTER_API_KEY = "sk-or-..."

# Multiple keys per provider (optional):
# GROQ_API_KEY = "gsk_key1,gsk_key2"

# Fallback order (optional) — re-prioritizes the chain; configured
# providers missing from the list keep a slot at the end.
# LLM_PROVIDER_ORDER = "openrouter,groq,gemini"

# Completion budget advertised per OpenRouter request (optional; default
# 8192). Low values keep near-zero-credit accounts working (402 guard).
# OPENROUTER_MAX_TOKENS = "8192"

# ── Agent ───────────────────────────────────────
AGENT_MAX_ITERATIONS = "6"
AGENT_MAX_ROWS = "200"
READ_ONLY_MODE = "true"
```

These become real environment variables at runtime (the app's settings
layer reads env vars first, `.env` second — the `.env` file is not deployed
and must never be committed).

**Do NOT set `DEV_MODE` in production** — the developer sidebar (model
overrides, temporary keys, provider reorder editor) is hidden unless it is
explicitly `true`.

### What visitors see (and don't)

The deployed app intentionally reveals nothing about its provider setup:
no provider names, no model slugs, no key counts, no chain order. Both the
database and the model layer are **checked automatically on first load**,
so visitors land on a real status (Connected / LLM · Ready) instead of
"Not tested"; manual re-test buttons remain in the sidebar. All provider
detail is confined to `DEV_MODE=true` sessions.

### Cold starts (set expectations)

- **Neon** suspends idle computes. The first query after inactivity takes
  ~5–15s to wake; the UI shows an honest note about this in its empty state.
- **Streamlit Community Cloud** sleeps apps after ~7 days of inactivity,
  and the first boot after a push re-installs dependencies (a few minutes).
- **Free LLM tiers** occasionally rate-limit; the app falls back to the
  next provider automatically, which can add a few seconds.

The app's empty state tells users exactly this: *"First load may take
~15-30s while the free infrastructure wakes up."*

---

## 5. Post-deploy checklist

- [ ] Open the deployed URL — the empty state appears with the cold-start note.
- [ ] Sidebar pills show Connected / LLM · Ready by themselves — both
      layers are checked automatically on first load (no "Not tested";
      manual re-test buttons remain).
- [ ] Ask *"How many products are in the database?"* → answer says 16.
- [ ] Ask *"Which sales territory generated the most revenue?"* → real SQL,
      real numbers (flip **Show SQL details** on in the sidebar to inspect
      the Generated SQL / Query Results / Execution Details panels; they are
      off by default for a clean chat).
- [ ] Example-question strip is still visible under the chat transcript.
- [ ] No `DEV_MODE` section in the sidebar, and no provider/model names
      anywhere in the production UI.

## 6. Operations & limits (free tiers)

| Resource | Limit | Coping strategy |
|---|---|---|
| Neon compute | auto-suspend after 5 min idle; ~10h/day activity | cold start ~5–15s per wake; fine for demos |
| Neon storage | 0.5 GB | demo dataset is a few MB |
| Streamlit Cloud | 1 app, sleeps after inactivity, ~1 GB RAM | wakes on visit; keep the repo lean |
| Groq free | per-minute/per-day token quotas | fallback chain absorbs 429s |
| Gemini free | per-day request quota | fallback chain moves on |
| OpenRouter free | per-model daily caps | third in line, rarely hit |

## 7. Security notes for a public demo

- The Neon role used by the app should have **only the demo schemas**
  (`production`, `sales`) — the seed script creates nothing outside them.
- The app ships with `READ_ONLY_MODE=true` and blocks destructive
  statements before they reach the database, but the *real* boundary is
  least privilege: if you want belt-and-braces, Neon's SQL editor can
  create a second role limited to `SELECT` on the demo schemas and point
  the app at that instead.
- Secrets live in Streamlit's encrypted secrets store / your local `.env`
  (gitignored). Rotate keys if they ever appear in logs or screenshots.
- The row cap (`AGENT_MAX_ROWS`) bounds every query result, so a curious
  recruiter can't accidentally pull a giant table into the chat.

---

## Local workflow: unchanged

Developing against MS SQL Server stays exactly as documented in the
README: leave `DB_DIALECT` unset (or `mssql`) and keep your existing
`DB_CONNECTION_STRING`. The Postgres code paths are selected only when
`DB_DIALECT=postgres` (or a postgres URI is configured).
