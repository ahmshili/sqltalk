"""Display sanitization for normal (non-developer) mode.

Raw provider/database error strings routinely carry credentials-adjacent
detail: LLM API error payloads can echo the account or project a key belongs
to, and database errors can embed the connecting role (e.g. Neon's
`role "user@ep-xxxx"`), hostnames, or full connection strings. A public
visitor should never see any of that.

`sanitize_for_display` strips the sensitive patterns while keeping the parts
a reviewer legitimately needs: the error *kind* (rate limit, timeout, auth
failure), HTTP status codes, and the app's own explanatory text. Dev mode
always receives the raw text.
"""

from __future__ import annotations

import re

# Full connection strings / URIs (postgres://user:pass@host/db, etc.).
_URI_RE = re.compile(r"\b[\w.+-]+://[^\s\"'<)]+")

# key=value / key: value credential assignments (api_key=..., token: ...).
_CRED_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|password|passwd|pwd|token|secret|"
    r"authorization|bearer|credential[s]?)"
    r"(\s*[=:]\s*)(?:[\"']?)[^\s,\"';]+"
)

# user=... / role "..." / account: ... — DB and LLM identity mentions.
_ROLE_USER_RE = re.compile(
    r"(?i)\b(user|role|account|org(?:anization)?)\s*([=:])\s*[\"']?[\w.@\-]+[\"']?"
)
_ROLE_QUOTED_RE = re.compile(r"(?i)\b(role|user)\s+(\"[^\"]*\"|'[^']*')")

# Bearer <token> — the auth-header form (no =/: separator).
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[^\s,;\"]+")


def sanitize_for_display(text: str, dev_mode: bool) -> str:
    """Return `text` safe for public display.

    Dev mode gets the raw text unchanged; normal mode has connection
    strings, credential assignments, and account/role identifiers redacted.
    Everything else — error kinds, status codes, app-authored messages —
    is preserved so the output stays useful to a reviewer.
    """
    if dev_mode or not text:
        return text
    text = _URI_RE.sub("[connection string removed]", text)
    text = _CRED_ASSIGN_RE.sub(r"\1\2[removed]", text)
    text = _BEARER_RE.sub(r"\1 [removed]", text)
    text = _ROLE_QUOTED_RE.sub(r"\1 [removed]", text)
    text = _ROLE_USER_RE.sub(r"\1\2 [removed]", text)
    return text
