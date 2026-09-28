# Contributing to SQLTalk

Thank you for taking the time to look at this project — genuine bug reports
and improvement suggestions are very welcome.

Because this repository is published under a **restricted evaluation
license** (see [`LICENSE`](./LICENSE)) — it exists to be reviewed by
recruiters and hiring teams — contributions work a little differently than
in a typical open-source project:

## The ground rules

- ✅ **Bug reports and issues** — always welcome, no restrictions. See
  [Reporting a bug](#reporting-a-bug) below.
- ✅ **Pull requests** — welcome and encouraged, submitted **to this
  repository**. Improvements to code, docs, tests, and UX are all in scope.
- ✅ **A temporary GitHub fork used only as the mechanism to open a PR back
  here** is permitted — that is exactly the "preparing and submitting a
  pull request back to this repository" grant in the license.
- ❌ **Standing forks, mirrors, or re-publication** of the code anywhere
  else — not permitted. The canonical copy stays in this repository.
- ❌ **Commercial use** of the code — not permitted without written
  permission from the author.

## Getting set up

```powershell
# Windows (PowerShell)
git clone https://github.com/ahmshili/sqltalk.git
cd sqltalk

python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# fill in DB_CONNECTION_STRING and at least one provider key
```

```bash
# macOS / Linux
git clone https://github.com/ahmshili/sqltalk.git
cd sqltalk

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

You do **not** need a live database or real API keys to work on most of the
codebase — the test suite mocks both layers (see below). A real `.env` is
only needed for manually running the app.

## Running the tests

```bash
pytest
```

The suite covers configuration validation, provider-order resolution,
dialect handling, safety guards, connection-string building, provider spec
collection, the LLM health check, and agent/toolkit/fallback wiring — all
with mocked LLMs and databases. Please make sure the suite passes before
opening a PR, and add tests for any new behavior.

## Opening a pull request

1. Create a feature branch from `main`
   (`git checkout -b my-improvement`).
2. Keep changes small and focused; one logical change per PR.
3. Run `pytest` and make sure it passes.
4. Open the PR against **this repository** with a short description of the
   motivation and the approach.

## Reporting a bug

1. Go to [github.com/ahmshili/sqltalk/issues](https://github.com/ahmshili/sqltalk/issues)
2. Click **New issue** → **Bug report** and fill in the template
   (what you did, what you expected, what happened, your `DB_DIALECT` and
   Python version).

**Please redact secrets** — never paste API keys, connection strings, or
passwords into an issue. Sanitized error messages are enough.
