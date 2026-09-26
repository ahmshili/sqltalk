"""Visual theme for the Streamlit UI.

Kept intentionally simple (no external UI framework): a single CSS block
injected once, using Streamlit's own theme variables where possible so the
app respects the user's light/dark preference instead of fighting it.
"""

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
