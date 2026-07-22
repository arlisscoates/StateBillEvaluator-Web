"""Domain model helpers ported from the macOS app (Bill.swift / Category.swift)."""

# Ported verbatim from BillCategory.predefinedCategories
PREDEFINED_CATEGORIES = [
    "Healthcare",
    "Education",
    "Criminal Justice",
    "Taxation",
    "Environment",
    "Elections",
    "Housing",
    "Labor",
    "Technology & Privacy",
    "Transportation",
    "Agriculture",
    "Energy",
    "Gun Policy",
    "Immigration",
    "Budget & Appropriations",
]

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
