"""SQL safety guard.

This is a best-effort, defense-in-depth safeguard against the LLM emitting
destructive SQL — it is NOT a substitute for running the app against a
database user with least-privilege permissions. See the README's "Security
limitations" section for the honest version of this story.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from app.config.settings import DEFAULT_BLOCKED_KEYWORDS

# Matches a keyword only as a standalone SQL token (word boundary on both
# sides), so e.g. a column named "created_at" doesn't trip the "CREATE" guard.
_TOKEN_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _pattern_for(keyword: str) -> re.Pattern[str]:
    if keyword not in _TOKEN_PATTERN_CACHE:
        _TOKEN_PATTERN_CACHE[keyword] = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
    return _TOKEN_PATTERN_CACHE[keyword]


@dataclass
class SafetyViolation:
    keyword: str
    message: str


def find_violations(
    sql: str, blocked_keywords: Iterable[str] = DEFAULT_BLOCKED_KEYWORDS
) -> List[SafetyViolation]:
    """Return every blocked keyword found in `sql`, empty if the statement
    looks safe (read-only)."""
    violations: List[SafetyViolation] = []
    for keyword in blocked_keywords:
        if _pattern_for(keyword).search(sql):
            violations.append(
                SafetyViolation(
                    keyword=keyword,
                    message=(
                        f"Statement blocked: contains '{keyword}', which is "
                        "disallowed while read-only mode is enabled."
                    ),
                )
            )
    return violations


def is_safe(sql: str, blocked_keywords: Iterable[str] = DEFAULT_BLOCKED_KEYWORDS) -> bool:
    return not find_violations(sql, blocked_keywords)


def enforce_row_limit(sql: str, max_rows: int) -> str:
    """Best-effort injection of a `TOP N` clause into a `SELECT` statement
    that doesn't already limit its result set, to avoid huge result sets
    being pulled back and dumped into the conversation.

    This is intentionally conservative: if the statement already contains
    TOP/OFFSET or isn't a simple SELECT, it's left untouched rather than risk
    producing invalid T-SQL.
    """
    stripped = sql.strip()
    if not re.match(r"(?is)^\s*select\b", stripped):
        return sql
    if re.search(r"(?is)\btop\s*\(?\s*\d+\s*\)?", stripped):
        return sql
    if re.search(r"(?is)\boffset\b", stripped):
        return sql

    return re.sub(
        r"(?is)^\s*select\b",
        f"SELECT TOP {max_rows}",
        stripped,
        count=1,
    )
