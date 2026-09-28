<div align="center">

<img src="assets/banner.svg" alt="SQLTalk — natural language in, real SQL out" width="820">

# SQLTalk

**Natural-language interface for your database.**

Ask a question in plain English — get a real answer computed from your live database.

[![License: Restricted evaluation](https://img.shields.io/badge/license-restricted%20evaluation-red)](#license)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.38-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![LangChain](https://img.shields.io/badge/LangChain-0.2-1C3C3C?logo=langchain&logoColor=white)](https://www.langchain.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon%20demo-4169E1?logo=postgresql&logoColor=white)](https://neon.tech)
[![MS SQL Server](https://img.shields.io/badge/MS%20SQL%20Server-local%20dev-CC2927?logo=microsoftsqlserver&logoColor=white)](https://www.microsoft.com/en-us/sql-server)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-green)](#contributing)
[![Issues Welcome](https://img.shields.io/badge/issues-welcome-brightgreen)](#reporting-an-issue)

</div>

---

SQLTalk turns a question into SQL, runs it against the database, and explains
the result back to you in words. Developed against **Microsoft SQL Server**
(T-SQL + AdventureWorks) and also deployed as a free public demo on
**PostgreSQL (Neon)** + **Streamlit Community Cloud** — see
[`DEPLOYMENT.md`](./DEPLOYMENT.md).

```
Natural-language question
        │
        ▼
 LLM reasons about schema (multi-provider fallback chain)
        │
        ▼
   SQL generated (T-SQL or PostgreSQL, per the active dialect)
        │
        ▼
  Executed on SQL Server / Postgres
        │
        ▼
  Rows / aggregates returned
        │
        ▼
 LLM interprets the result
        │
        ▼
 Human-readable answer
```

Built by **Ahmed Shili** — [GitHub](https://github.com/ahmshili) ·
[Portfolio](https://ashili.pages.dev)

## Features

- Natural-language querying of a **Microsoft SQL Server** or **PostgreSQL**
  database (dialect selected via `DB_DIALECT`; row limits and the
  query-checker prompt adapt automatically — `TOP N` vs `LIMIT N`,
  `GETDATE()` vs `CURRENT_DATE`)
- Automatic SQL generation, execution, and result interpretation
- Conversational follow-ups (no need to repeat table/column names)
- **Multi-provider LLM fallback, ordered by inference speed** — Groq
  (default, fastest) → Gemini → OpenRouter. One complete SQL agent is built
  per provider/key and fallback happens at the agent-invocation level (the
  LangChain SQL toolkit rejects `with_fallbacks` wrappers, so this is
  implemented explicitly)
- **Configurable provider priority** — reorder the fallback chain via the
  `LLM_PROVIDER_ORDER` environment variable, or interactively in developer
  mode (see [Developer mode](#developer-mode))
- Multiple API keys per provider (comma-separated or numbered variables)
- **Deployment-clean by design** — the production UI never exposes which
  providers, models, or chain order it uses; it shows only a yes/no *LLM
  health* signal. Full provider detail lives exclusively in the env-gated
  developer mode
- **Query transparency by default** — the generated SQL, raw results, and
  execution details are shown under every answer (one toggle to hide them)
- **Automatic health checks** — the database and the model layer are
  verified on page load, so visitors see a real status, never "Not tested"
- Read-only safety mode by default, with a configurable row cap
- Modern, minimal Streamlit UI with live connection status
- Small, focused test suite covering config, safety, database, and agent wiring

## Architecture

```
sqltalk/
├── app.py                  # entrypoint (streamlit run app.py)
├── seed_postgres_demo.py   # seeds the free Neon demo dataset
├── DEPLOYMENT.md           # Neon + Streamlit Community Cloud guide
├── assets/                 # banner + mascot (SVG)
├── app/
│   ├── config/settings.py  # env loading & validation (dialect, providers, order)
│   ├── llm/provider.py     # Groq / Gemini / OpenRouter factories
│   ├── database/
│   │   ├── uri.py          # dialect-aware connection-string builder
│   │   ├── connection.py   # SQLDatabase wrapper, connection testing
│   │   ├── multi_schema.py # multi-schema reflection (MSSQL + Postgres)
│   │   └── safety.py       # read-only guard, row-limit enforcement
│   ├── agent/
│   │   ├── toolkit.py      # guarded SQL tools (safety + transparency hooks)
│   │   ├── executor.py     # ReAct SQL agent construction
│   │   └── fallback.py     # per-provider agent chain, invocation-level fallback
│   └── ui/
│       ├── main.py         # Streamlit page orchestration
│       ├── sidebar.py      # DB / LLM status / agent / about / dev-mode panels
│       ├── chat.py         # chat rendering + transparency panels
│       └── theme.py        # CSS + empty-state copy
├── tests/
└── .env.example
```

Each layer only depends on the one below it: the UI never touches
SQLAlchemy directly, the agent never touches Streamlit, and the LLM layer
knows nothing about SQL. This is what makes it realistic to swap OpenRouter
for OpenAI, a local Ollama endpoint, or anything else OpenAI-compatible
without touching the agent or UI code.

## Requirements

- Python 3.10+
- Microsoft SQL Server 2019+ (developed against SQL Server 2022 Developer
  Edition, `AdventureWorks2022` sample database)
- [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- An [OpenRouter](https://openrouter.ai) account and API key (free tier
  works — no payment method required)

## Installation

### Windows (PowerShell)

```powershell
git clone https://github.com/ahmshili/sqltalk.git
cd sqltalk

python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
notepad .env   # fill in DB_CONNECTION_STRING and OPENROUTER_API_KEY
```

### macOS / Linux

```bash
git clone https://github.com/ahmshili/sqltalk.git
cd sqltalk

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# then edit .env: fill in DB_CONNECTION_STRING and OPENROUTER_API_KEY
```

## Running

```powershell
# Windows
.\.venv\Scripts\activate
streamlit run app.py
```

```bash
# macOS / Linux
source .venv/bin/activate
streamlit run app.py
```

Then open the printed local URL (typically `http://localhost:8501`).

## Configuration

Copy `.env.example` to `.env` and fill it in. Key variables:

| Variable                 | Required | Default                                     | Notes                                                   |
|---------------------------|:--------:|----------------------------------------------|----------------------------------------------------------|
| `DB_DIALECT`              |          | `mssql`                                      | `mssql` (SQL Server, local) or `postgres` (Neon demo)   |
| `DB_CONNECTION_STRING`    | ✅       | —                                            | SQLAlchemy URI — or the `DB_*` parts below              |
| `DB_HOST` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | | —                    | Parts form; the URI is built per dialect               |
| `GROQ_API_KEY`            | ✅*      | —                                            | *One of the three providers is required                 |
| `GEMINI_API_KEY`          |          | —                                            | Second in the fallback chain                            |
| `OPENROUTER_API_KEY`      |          | —                                            | Third in the fallback chain                             |
| `GROQ_MODEL`              |          | `llama-3.3-70b-versatile`                    | Groq model slug                                         |
| `GEMINI_MODEL`            |          | `gemini-1.5-flash`                           | Gemini model slug                                       |
| `OPENROUTER_MODEL`        |          | `nvidia/nemotron-3-ultra-550b-a55b:free`     | Any OpenRouter model slug                               |
| `LLM_PROVIDER_ORDER`      |          | *(speed order)*                              | Comma-separated fallback priority, e.g. `openrouter,groq,gemini` |
| `OPENROUTER_MAX_TOKENS`   |          | `8192`                                       | Completion budget advertised per OpenRouter request     |
| `OPENROUTER_TEMPERATURE`  |          | `0`                                          | Keep low for reliable SQL generation                    |
| `AGENT_MAX_ITERATIONS`    |          | `6`                                          | Reasoning steps before the agent gives up               |
| `AGENT_MAX_ROWS`          |          | `200`                                        | Row cap enforced on every query                         |
| `READ_ONLY_MODE`          |          | `true`                                       | Blocks DROP/DELETE/TRUNCATE/ALTER/INSERT/UPDATE/etc.    |
| `DB_SCHEMAS`              |          | *(auto-discovered)*                          | Comma-separated schema allowlist                        |
| `DEV_MODE`                |          | *(off)*                                      | `true` enables the session-only developer sidebar       |

### Building `DB_CONNECTION_STRING`

**MS SQL Server (default profile):**

```
mssql+pyodbc://<username>:<password>@<server>/<database>?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
```

**If your password contains special URL characters** (`@ : / ? # [ ] %` ...),
URL-encode them first, or the connection string will parse incorrectly —
e.g. `p@ss` becomes `p%40ss`.

Example for a local default instance with SQL authentication as `sa`:

```
mssql+pyodbc://sa:MyStr0ngPass%40@localhost/adventureWorks?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
```

**PostgreSQL / Neon (demo profile, `DB_DIALECT=postgres`):**

```
postgresql+psycopg2://<user>@<endpoint>:<password>@<host>/<dbname>?sslmode=require
```

Neon's own connection string works after swapping the scheme to
`postgresql+psycopg2://` — or set the `DB_HOST`/`DB_NAME`/`DB_USER`/
`DB_PASSWORD` parts and SQLTalk builds it (with `sslmode=require` by
default). See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for the full walkthrough,
including the free seed dataset (`python seed_postgres_demo.py`).

`OPENROUTER_MODEL` note: free-model availability on OpenRouter changes
frequently as providers add and retire models — the original default here
(`meta-llama/llama-3.1-405b-instruct:free`) was retired and started failing
with 404. If the default above stops working, check
[openrouter.ai/models filtered to $0](https://openrouter.ai/models?max_price=0)
and update the variable. Avoid `openrouter/auto` and `openrouter/free`
routers: they serve *different underlying models* on consecutive calls
(breaking the agent's ReAct format, and producing answers that don't match
query results) and can route to paid models you have no credits for.

Two OpenRouter quota gotchas worth knowing:

- The free tier allows **~50 free-model requests per day**, shared across
  all free models per account. One question costs several model calls
  (every agent step and query check is a call), so a handful of questions
  can exhaust the day. The fallback chain absorbs per-minute limits, but
  the *daily* cap needs either a second provider key (Groq is generous) or
  the daily reset.
- Retired free models fail with `404 No endpoints found` — pin a slug that
  currently exists on the [free-models list](https://openrouter.ai/models?max_price=0).
- `openrouter/auto` and other paid routers reject requests when the
  advertised completion budget exceeds your credit headroom (HTTP 402).
  SQLTalk caps the advertised budget (`OPENROUTER_MAX_TOKENS`, default
  8192) so near-zero-credit accounts keep working — but prefer pinning a
  specific `:free` model slug.

### LLM provider fallback (how it works)

Providers are tried in a configurable priority order — by default the
inference-speed order **Groq → Gemini → OpenRouter**, reorderable via
`LLM_PROVIDER_ORDER` (or the developer-mode UI) — and expanded over every
configured key per provider. The app builds one complete, ready-to-invoke
LangChain SQL agent per provider/key (all sharing one database reflection),
then invokes them in order per question: if an agent throws (rate limit,
auth error, outage), the next one answers. This lives at the
agent-invocation level because LangChain's SQL toolkit validates its model
as a genuine `BaseLanguageModel` and rejects fallback wrappers like
`ChatOpenAI.with_fallbacks(...)`.

An ordering override **re-prioritizes but never disables**: any configured
provider missing from `LLM_PROVIDER_ORDER` keeps a slot at the end of the
chain, and unknown names are ignored.

## Query transparency

Every answer can be inspected down to the exact SQL. A **Show SQL details**
toggle in the sidebar (Agent section) controls three collapsible panels:

- **Generated SQL** — the exact statement the agent executed
- **Query Results** — the raw rows/aggregates returned
- **Execution Details** — query count, failures, and timing

The panels are **on by default** — transparency is the point — and the
toggle turns them off for a minimal chat. Errors are always shown with
their technical detail regardless of the toggle.

## Developer mode

Set `DEV_MODE=true` (env or `.env`) to reveal a session-only **Developer
Mode** section in the sidebar:

- **Fallback order editor** — reorder the provider chain interactively
  (↑/↓ buttons); a preview shows the resulting chain
- Per-provider model overrides
- Temporary session API keys
- Provider on/off switches

Overrides live in Streamlit session state only — nothing is written to
`.env` or disk — and the section does not exist at all unless the variable
is set, so production deployments stay clean.

## Example questions

Example prompts also stay available during a session via the persistent
"💡 Example questions" strip below the chat transcript — not just on the
empty state.

- How many products are in the database?
- Show me the 5 most expensive products.
- Which products have never been sold?
- Which customers placed the most orders?
- What are the top 10 products by total sales?
- How much revenue did each year generate?
- Which sales territory generated the most revenue?
- Compare sales between 2012 and 2013.
- Which customers have never placed an order?

## Schema visibility

SQL Server scopes table listings to a single schema by default, and that
default is `dbo` — but real databases (AdventureWorks included) keep their
actual business tables in `Production`, `Sales`, `Person`, `HumanResources`,
`Purchasing`, and so on. SQLTalk auto-discovers every non-system schema in
the connected database on startup, so the agent sees the real tables out of
the box. If you want to scope it down (e.g. for a large multi-tenant
database), set `DB_SCHEMAS=Production,Sales` in `.env`.

## Choosing an OpenRouter model

Pin `OPENROUTER_MODEL` to a specific model slug, not to OpenRouter's
`openrouter/free` auto-router. The auto-router can serve a *different*
underlying model on every single call within one agent run, and this
project's agent relies on the model consistently reproducing one exact
`Thought / Action / Action Input` text format turn after turn — switching
models mid-conversation reliably breaks that, and has also been observed to
produce answers that don't match the actual query results. Pick one model
and stick with it for a session.

## Safety

SQLTalk executes LLM-generated SQL against a real database. It ships with:

- **Read-only mode (default: on)** — statements containing `DROP`, `DELETE`,
  `TRUNCATE`, `ALTER`, `CREATE`, `INSERT`, `UPDATE`, `MERGE`, `EXEC`,
  `GRANT`, `REVOKE`, or `DENY` are rejected before reaching the database.
- **Row cap** — a `TOP N` (MSSQL) or `LIMIT N` (Postgres) clause is
  injected into unbounded `SELECT`s, matching the active dialect.
- **Graceful error handling** — SQL and LLM errors are shown as clear
  messages in the chat, with full technical detail available in an
  expandable diagnostics section, never as a raw stack trace.

### Honest limitation

The keyword-based safety guard is a **defense-in-depth measure, not a
security boundary**. It's a regex-based check on generated text — it does
not parse or validate SQL semantically, and a sufficiently unusual query
could in principle slip past it. The only real security boundary is running
the app against a **database login with least-privilege permissions**
(ideally read-only). This project currently connects as `sa` for local
development convenience; **do not do this against a database you care
about.** If you deploy this anywhere beyond your own machine, create a
dedicated read-only SQL login first.

## Tests

```powershell
pytest
```

Covers: required-configuration validation, provider-order resolution and
normalization, read-only/keyword safety checks, row-limit enforcement (both
dialects), database connection creation and error wrapping, provider spec
collection and ordering, the LLM health check, and agent/toolkit/fallback
wiring (LLM and DB layers are mocked — no live database or API key needed
to run the suite).

## Security limitations (general)

- Generated SQL is AI-produced. Read-only mode reduces but does not
  eliminate risk — see above.
- API keys and connection strings are read from environment variables only;
  never commit `.env`.
- The Streamlit sidebar never displays the database password or API key.

## Deployment (free public demo)

A complete walkthrough — Neon Postgres + Streamlit Community Cloud, seed
data, secrets, and free-tier expectations — lives in
[`DEPLOYMENT.md`](./DEPLOYMENT.md). The local MS SQL Server workflow is
unchanged by any of it.

## Sponsorship

If this project is useful to you — or you'd like to support keeping the
free public demo running (Neon compute and LLM free tiers cost time and
occasionally money to keep warm) — sponsorships are appreciated:

- **GitHub Sponsors:** [github.com/sponsors/ahmshili](https://github.com/sponsors/ahmshili)

Sponsorship is entirely optional; the project and the public demo are free
to use and review. Commercial licensing beyond the terms of the
[license](#license) below is available on request via the same profile.

## Reporting an issue

Found a bug, or an idea that would make this stronger? Please open a GitHub
Issue in **this repository**:

1. Go to [github.com/ahmshili/sqltalk/issues](https://github.com/ahmshili/sqltalk/issues)
2. Click **New issue** and pick the bug-report form
3. Describe what you did, what you expected, and what happened

**Please redact secrets** — never paste API keys, connection strings, or
passwords into an issue. A sanitized error message and your `DB_DIALECT` /
Python version are usually enough to reproduce.

## Contributing

Pull requests and bug reports are welcome and encouraged — **in this
repository**. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the ground
rules (short version: code stays here; no forks or re-publication) and
setup instructions for running the test suite locally.

## Project origin & attribution

SQLTalk is a complete architectural rewrite — new project structure,
configuration system, LLM integration, safety layer, UI, and documentation —
built using an existing open-source Streamlit SQL chatbot as a functional
starting point. It is **not** a fork and is not published as, or intended to
be confused with, that project; no files, branding, or license text from it
are reused. It shares the same general idea (LangChain + Streamlit +
natural-language-to-SQL) as the publicly available `trinhvanminh/SQL_Agent`
project, implemented independently with different naming, code
organization, UI, and provider integration.

## License

See [`LICENSE`](./LICENSE). This project is shared under a **restricted
evaluation license**, published for the express purpose of **evaluation and
review by recruiters, hiring teams, and technical reviewers**:

- ✅ **Permitted:** running it locally to evaluate it, reading and reviewing
  the code, and submitting pull requests or bug reports **to this
  repository**
- ❌ **Not permitted:** forking, redistributing, or re-publishing the code
  anywhere else, or any commercial use, without prior written permission

The code stays in this repository — the value of the project is in the
review and the conversation around it, not in copies of it.
