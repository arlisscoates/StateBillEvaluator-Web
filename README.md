# State Bill Evaluator — Windows port

A Python/Streamlit port of the macOS **StateBillEvaluator** (LegisTracker) app.
Tracks U.S. state legislation via the **LegiScan API** and uses **Claude** to
categorize bills and analyze their industry/market impact — running in your
browser on Windows.

## What it does

- **Sync** bills from LegiScan by search query and (optionally) state.
- **Categorize** each bill into one of 15 predefined categories with Claude.
- **Impact analysis** — Claude identifies winning/losing industries & companies
  (with tickers) for a bill.
- **Company Rankings** — aggregates winners/losers across analyzed bills.
- **Chat** — free-form Q&A with Claude about legislation.
- **CSV export** of the current filtered bill list.
- **Sample data** — 20 built-in bills so you can try it with no API keys.

Bills persist locally in SQLite at `~/.state_bill_evaluator/bills.db`.

## Setup

```powershell
cd C:\Users\acoates\StateBillEvaluator-Web
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

It opens at http://localhost:8501.

## API keys

Enter them in the sidebar **⚙️ Settings**, or set environment variables before
launching:

```powershell
$env:LEGISCAN_API_KEY = "..."   # free at legiscan.com/user/register
$env:ANTHROPIC_API_KEY = "..."  # from console.anthropic.com
```

- No keys? Click **Load sample data** to explore the UI.
- LegiScan key only → sync + browse (bills stay uncategorized).
- Both keys → full functionality (categorize, impact, chat).

## Notes / differences from the macOS app

- SwiftUI → Streamlit; SwiftData → SQLite.
- Same Claude model (`claude-sonnet-4-5-20250929`), prompts, and token limits.
- Keys live in the Streamlit session / env vars (not macOS `UserDefaults`).
- Categories, the passage-likelihood heuristic, and the impact-analysis JSON
  schema are ported to match the original's behavior.
