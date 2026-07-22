"""Domain model helpers.

Retargeted for Accela's sales use case: classify bills by the Accela product
line they touch, and score how strongly they signal a sales opportunity.
"""

# Accela product lines a bill might drive demand for. "Not Relevant" is the
# catch-all for legislation with no govtech permitting/licensing/portal angle.
ACCELA_PRODUCT_LINES = [
    "Permitting & Land Management",
    "Professional & Business Licensing",
    "Citizen Engagement & Portals",
    "Code Enforcement",
    "Cannabis & Regulated Licensing",
    "Short-Term Rental Regulation",
    "Records, Transparency & Digital Government",
    "Not Relevant",
]

# Back-compat alias (some modules still import PREDEFINED_CATEGORIES).
PREDEFINED_CATEGORIES = ACCELA_PRODUCT_LINES


def opportunity_band(score) -> str:
    """Bucket a 0-100 opportunity score into a label."""
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "Unscored"
    if s >= 75:
        return "Hot"
    if s >= 50:
        return "Warm"
    if s >= 25:
        return "Watch"
    return "Low"


def opportunity_badge(score) -> str:
    """Emoji + score badge for display, e.g. '🔥 82 Hot'."""
    band = opportunity_band(score)
    icon = {"Hot": "🔥", "Warm": "🟠", "Watch": "🟡", "Low": "⚪", "Unscored": "❔"}[band]
    try:
        return f"{icon} {int(score)} {band}"
    except (TypeError, ValueError):
        return f"{icon} {band}"

# Passage likelihood, highest-chance first (matches the app's sort order)
LIKELIHOOD_ORDER = ["Passed", "High", "Medium", "Low", "Dead"]


def passage_likelihood(status: str, last_action: str | None) -> str:
    """Derive a passage likelihood from status + last action.

    Ported from Bill.passageLikelihood computed property: case-insensitive
    string matching over the combined status/lastAction text.
    """
    text = f"{status or ''} {last_action or ''}".lower()

    if any(k in text for k in ("veto", "failed", "fail ", "tabled", "dead", "died", "withdrawn")):
        return "Dead"
    if any(k in text for k in ("enacted", "signed", "chaptered", "adopted", "became law")):
        return "Passed"
    if "passed" in text or "engrossed" in text or "third reading" in text:
        return "High"
    if any(k in text for k in ("committee", "amend", "hearing", "reported", "referred")):
        return "Medium"
    return "Low"


def likelihood_meter(level: str) -> str:
    """A 5-dot meter string, e.g. Passed -> '●●●●●'."""
    filled = {"Dead": 0, "Low": 1, "Medium": 2, "High": 3, "Passed": 5}.get(level, 1)
    return "●" * filled + "○" * (5 - filled)
