"""Visual theme for the Streamlit UI.

Kept intentionally simple (no external UI framework): a single CSS block
injected once, using Streamlit's own theme variables where possible so the
app respects the user's light/dark preference instead of fighting it.

Branding assets (assets/banner.svg, assets/mascot.svg) are inlined by
`banner_img` / `mascot_img` as data-URI `<img>` tags — data URIs are the one
reliable way to render SVG through Streamlit's `unsafe_allow_html` across
deployments. Every helper degrades to an empty string (and callers to a
plain-text fallback) if the asset file is missing.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"


@lru_cache(maxsize=None)
def _svg_data_uri(filename: str) -> str | None:
    """Read an SVG asset and encode it as a data URI (None if missing)."""
    path = ASSETS_DIR / filename
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def banner_img() -> str | None:
    """`<img>` tag for the banner SVG, or None when the asset is absent."""
    uri = _svg_data_uri("banner.svg")
    if not uri:
        return None
    return (
        f'<img class="sqltalk-banner-img" src="{uri}" '
        'alt="SQLTalk — natural language in, real SQL out" draggable="false">'
    )


def mascot_img(size: int = 64, extra_class: str = "") -> str | None:
    """`<img>` tag for the mascot SVG at a given pixel size, or None when
    the asset is absent."""
    uri = _svg_data_uri("mascot.svg")
    if not uri:
        return None
    cls = f"sqltalk-mascot {extra_class}".strip()
    return (
        f'<img class="{cls}" src="{uri}" width="{size}" height="{size}" '
        'alt="SQLTalk mascot" draggable="false">'
    )


CUSTOM_CSS = """
<style>
/* Tighten the default Streamlit chrome */
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 900px;
}

/* Header */
.sqltalk-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.25rem;
}
.sqltalk-title {
    font-size: 1.6rem;
    font-weight: 700;
    margin: 0;
}
.sqltalk-subtitle {
    color: var(--text-color-secondary, #8a8a8a);
    font-size: 0.95rem;
    margin-top: -0.4rem;
    margin-bottom: 1.2rem;
}
.sqltalk-attribution {
    font-size: 0.78rem;
    color: var(--text-color-secondary, #8a8a8a);
    text-align: right;
}
.sqltalk-attribution a {
    text-decoration: none;
}

/* Banner (header identity image) */
.sqltalk-banner {
    margin: 0 0 0.75rem 0;
    border-radius: 18px;
    overflow: hidden;
    line-height: 0;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
}
.sqltalk-banner-img {
    width: 100%;
    height: auto;
    display: block;
}

/* Mascot accents */
.sqltalk-mascot {
    border-radius: 20%;
    vertical-align: middle;
}
.empty-state .sqltalk-mascot {
    margin-bottom: 0.75rem;
}

/* About card */
.about-card {
    border: 1px solid rgba(120, 120, 120, 0.25);
    border-radius: 14px;
    padding: 0.9rem 1rem;
    margin-top: 0.25rem;
}
.about-identity {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    margin-bottom: 0.4rem;
}
.about-name {
    font-weight: 700;
    font-size: 0.98rem;
    line-height: 1.2;
}
.about-role {
    color: var(--text-color-secondary, #8a8a8a);
    font-size: 0.8rem;
}
.about-links {
    display: flex;
    flex-direction: column;
    gap: 0.28rem;
    font-size: 0.88rem;
    margin-top: 0.5rem;
}
.about-links a {
    text-decoration: none;
}
.about-links a:hover {
    text-decoration: underline;
}

/* Status pill */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.85rem;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    background: rgba(120, 120, 120, 0.12);
}
.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}
.status-dot.connected { background: #22c55e; }
.status-dot.disconnected { background: #ef4444; }
.status-dot.unknown { background: #a3a3a3; }

/* Empty state */
.empty-state {
    text-align: center;
    padding: 3rem 1rem;
    color: var(--text-color-secondary, #8a8a8a);
}
.empty-state h2 {
    font-size: 1.4rem;
    margin-bottom: 0.5rem;
    color: inherit;
}
.example-grid {
    display: grid;
    gap: 0.5rem;
    margin-top: 1.5rem;
}

/* Footer bar */
.sqltalk-footer {
    margin-top: 2rem;
    padding-top: 0.75rem;
    border-top: 1px solid rgba(120, 120, 120, 0.2);
    font-size: 0.82rem;
    color: var(--text-color-secondary, #8a8a8a);
    display: flex;
    justify-content: space-between;
}
</style>
"""

EXAMPLE_QUESTIONS = [
    "How many products are in the database?",
    "What are the top 10 most expensive products?",
    "Which customers placed the most orders?",
    "Compare sales between 2012 and 2013.",
    "Which sales territory generated the most revenue?",
    "Which customers have never placed an order?",
]
