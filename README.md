# SQLTalk

**Natural-language interface for Microsoft SQL Server.**

Ask a question in plain English, get a real answer computed from your live
database — SQLTalk turns the question into T-SQL, runs it against SQL
Server, and explains the result back to you in words.

```
Natural-language question
        │
        ▼
 LLM reasons about schema (OpenRouter)
        │
        ▼
   T-SQL generated
        │
        ▼
  Executed on SQL Server
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

---

## Features

- Natural-language querying of a Microsoft SQL Server database
- Automatic T-SQL generation, execution, and result interpretation
- Conversational follow-ups (no need to repeat table/column names)
- Full query transparency — inspect the generated SQL, raw results, and
  execution details for every answer
- Read-only safety mode by default, with a configurable row cap
- Pluggable LLM provider via an OpenAI-compatible client (OpenRouter today;
  swapping providers means changing one factory function, not the app)
- Modern, minimal Streamlit UI with live connection status
- Small, focused test suite covering config, safety, database, and agent wiring

## Architecture

```
sqltalk/
├── app.py                  # entrypoint (streamlit run app.py)
├── app/
│   ├── config/settings.py  # env loading & validation
│   ├── llm/provider.py     # OpenRouter client factory (OpenAI-compatible)
│   ├── database/
│   │   ├── connection.py   # SQLDatabase wrapper, connection testing
│   │   └── safety.py       # read-only guard, row-limit enforcement
│   ├── agent/
│   │   ├── toolkit.py      # guarded SQL tools (safety + transparency hooks)
│   │   └── executor.py     # ReAct SQL agent construction
│   └── ui/
│       ├── main.py         # Streamlit page orchestration
│       ├── sidebar.py      # DB / LLM / agent / about panels
│       ├── chat.py         # chat rendering + transparency tabs
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

## Installation (Windows PowerShell)

```powershell
git clone https://github.com/ahmshili/sqltalk.git
cd sqltalk

python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
notepad .env   # fill in DB_CONNECTION_STRING and OPENROUTER_API_KEY
```

## Configuration

Copy `.env.example` to `.env` and fill it in. Key variables:

| Variable                 | Required | Default                                     | Notes                                                   |
|---------------------------|:--------:|----------------------------------------------|----------------------------------------------------------|
| `DB_CONNECTION_STRING`    | ✅       | —                                            | SQLAlchemy/pyodbc URI, see below                         |
| `OPENROUTER_API_KEY`      | ✅       | —                                            | From [openrouter.ai/keys](https://openrouter.ai/keys)     |
| `OPENROUTER_MODEL`        |          | `meta-llama/llama-3.1-405b-instruct:free`    | Any OpenRouter model slug; free-tier availability shifts  |
| `OPENROUTER_TEMPERATURE`  |          | `0`                                          | Keep low for reliable SQL generation                      |
| `AGENT_MAX_ITERATIONS`    |          | `6`                                          | Reasoning steps before the agent gives up                 |
| `AGENT_MAX_ROWS`          |          | `200`                                        | Row cap enforced on every query                            |
| `READ_ONLY_MODE`          |          | `true`                                       | Blocks DROP/DELETE/TRUNCATE/ALTER/INSERT/UPDATE/etc.       |

### Building `DB_CONNECTION_STRING`

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

`OPENROUTER_MODEL` note: free-model availability on OpenRouter changes
frequently as providers add and retire models. If the default above stops
working, check [openrouter.ai/models filtered to $0](https://openrouter.ai/models?max_price=0)
and update the variable — or set it to `openrouter/free`, which
auto-routes each request to whatever free model is currently available.

## Running

```powershell
.\.venv\Scripts\activate
streamlit run app.py
```

Then open the printed local URL (typically `http://localhost:8501`).

## Example questions

- How many products are in the database?
- Show me the 5 most expensive products.
- Which products have never been sold?
- Which customers placed the most orders?
- What are the top 10 products by total sales?
- How much revenue did each year generate?
- Which sales territory generated the most revenue?
- Compare sales between 2012 and 2013.
- Which customers have never placed an order?

## Query transparency

Every answer comes with three expandable tabs:

- **Generated SQL** — the exact T-SQL the agent executed
- **Query Results** — the raw rows/aggregates returned
- **Execution Details** — query count, failures, and timing

The main chat stays clean; the detail is one click away.

## Safety

SQLTalk executes LLM-generated SQL against a real database. It ships with:

- **Read-only mode (default: on)** — statements containing `DROP`, `DELETE`,
  `TRUNCATE`, `ALTER`, `CREATE`, `INSERT`, `UPDATE`, `MERGE`, `EXEC`,
  `GRANT`, `REVOKE`, or `DENY` are rejected before reaching the database.
- **Row cap** — a `TOP N` clause is injected into unbounded `SELECT`s.
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

Covers: required-configuration validation, read-only/keyword safety checks,
row-limit enforcement, database connection creation and error wrapping, and
agent/toolkit wiring (LLM and DB layers are mocked — no live database or
API key needed to run the suite).

## Security limitations (general)

- Generated SQL is AI-produced. Read-only mode reduces but does not
  eliminate risk — see above.
- API keys and connection strings are read from environment variables only;
  never commit `.env`.
- The Streamlit sidebar never displays the database password or API key.

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
evaluation license**: you may run it locally to evaluate/test it, read the
code, and submit pull requests back to this repository — forking,
redistribution, and commercial use are not permitted without written
permission.
