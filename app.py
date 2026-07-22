"""State Bill Evaluator — Windows/Streamlit port of the macOS LegisTracker app.

Tracks U.S. state legislation via the LegiScan API and uses Claude to
categorize bills and analyze their industry/market impact.
"""
import csv
import io
import json
import os
from collections import defaultdict

import streamlit as st

import store
from models import (LIKELIHOOD_ORDER, PREDEFINED_CATEGORIES, likelihood_meter,
                    passage_likelihood)
import sample_data

st.set_page_config(page_title="State Bill Evaluator", page_icon="🏛️", layout="wide")
store.init_db()

# ---------------------------------------------------------------- settings ---
st.sidebar.title("🏛️ State Bill Evaluator")

with st.sidebar.expander("⚙️ Settings", expanded=False):
    legiscan_key = st.text_input(
        "LegiScan API key", type="password",
        value=st.session_state.get("legiscan_key", os.environ.get("LEGISCAN_API_KEY", "")),
        help="Get a free key at legiscan.com/user/register",
    )
    claude_key = st.text_input(
        "Claude API key", type="password",
        value=st.session_state.get("claude_key", os.environ.get("ANTHROPIC_API_KEY", "")),
        help="From console.anthropic.com",
    )
    st.session_state["legiscan_key"] = legiscan_key
    st.session_state["claude_key"] = claude_key

# --------------------------------------------------------------- sync panel ---
st.sidebar.subheader("Sync bills")
sync_query = st.sidebar.text_input("Search query", value="healthcare")
sync_states = st.sidebar.text_input("States (comma-sep, blank = all)", value="")

if st.sidebar.button("⟳ Sync from LegiScan", type="primary", use_container_width=True):
    from legiscan import LegiScanService, LegiScanError
    from claude_client import ClaudeService, ClaudeError
    try:
        legi = LegiScanService(legiscan_key)
        states = [s.strip().upper() for s in sync_states.split(",") if s.strip()]
        with st.status("Syncing…", expanded=True) as status:
            st.write("Fetching bills from LegiScan…")
            fetched = []
            if states:
                for s in states:
                    fetched.extend(legi.search_bills(sync_query, s))
            else:
                fetched = legi.search_bills(sync_query)
            for b in fetched:
                store.upsert_summary(b)
            st.write(f"Fetched {len(fetched)} bills.")

            uncategorized = store.uncategorized_bills()
            if uncategorized and claude_key.strip():
                claude = ClaudeService(claude_key)
                prog = st.progress(0.0, text="Categorizing with Claude…")
                for i, bill in enumerate(uncategorized):
                    try:
                        cat = claude.categorize_bill(bill["title"], bill["description"])
                        store.set_category(bill["bill_id"], cat)
                    except ClaudeError as e:
                        st.write(f"⚠️ Categorize failed for {bill['bill_id']}: {e}")
                    prog.progress((i + 1) / len(uncategorized),
                                  text=f"Categorizing… {i + 1}/{len(uncategorized)}")
            elif uncategorized:
                st.write("No Claude key set — bills left uncategorized.")
            status.update(label="Sync complete", state="complete")
    except (LegiScanError, ClaudeError) as e:
        st.sidebar.error(str(e))

col_a, col_b = st.sidebar.columns(2)
if col_a.button("Load sample data", use_container_width=True):
    for b in sample_data.as_dicts():
        store.insert_sample_bill(b)
    st.sidebar.success("Loaded 20 sample bills.")
if col_b.button("Clear all", use_container_width=True):
    store.clear_all()
    st.sidebar.warning("Database cleared.")

# ------------------------------------------------------------------- tabs ---
bills = store.all_bills()
for b in bills:
    b["likelihood"] = passage_likelihood(b["status"], b["last_action"])

tab_legis, tab_rank, tab_chat = st.tabs(["📋 Legislation", "🏢 Company Rankings", "💬 Chat"])

# ===== Legislation ==========================================================
with tab_legis:
    if not bills:
        st.info("No bills yet. Sync from LegiScan or load the sample data in the sidebar.")
    else:
        f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
        cat_filter = f1.multiselect("Category", sorted({b["category_name"] for b in bills if b["category_name"]}))
        like_filter = f2.multiselect("Likelihood", LIKELIHOOD_ORDER)
        text_filter = f3.text_input("Search text", "")
        sort_order = f4.selectbox("Sort", ["State", "Date", "Title", "Likelihood"])

        rows = bills
        if cat_filter:
            rows = [b for b in rows if b["category_name"] in cat_filter]
        if like_filter:
            rows = [b for b in rows if b["likelihood"] in like_filter]
        if text_filter:
            t = text_filter.lower()
            rows = [b for b in rows if t in b["title"].lower() or t in b["state"].lower()
                    or t in (b["description"] or "").lower()]

        if sort_order == "State":
            rows.sort(key=lambda b: b["state"])
        elif sort_order == "Date":
            rows.sort(key=lambda b: b["last_action_date"] or "", reverse=True)
        elif sort_order == "Title":
            rows.sort(key=lambda b: b["title"])
        else:
            rows.sort(key=lambda b: LIKELIHOOD_ORDER.index(b["likelihood"]))

        # CSV export (ported from exportCSV)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Bill ID", "Title", "State", "Category", "Status", "Session",
                    "Likelihood", "Last Action", "Last Action Date", "Sponsors", "URL", "Description"])
        for b in rows:
            w.writerow([b["bill_id"], b["title"], b["state"], b["category_name"] or "",
                        b["status"], b["session"], b["likelihood"], b["last_action"] or "",
                        b["last_action_date"] or "", b["sponsors"] or "", b["url"], b["description"]])
        st.download_button("⬇️ Export CSV", buf.getvalue(), "bills.csv", "text/csv")

        st.caption(f"{len(rows)} of {len(bills)} bills")

        for b in rows:
            header = f"{b['state']} · {b['title']}  —  {likelihood_meter(b['likelihood'])} {b['likelihood']}"
            with st.expander(header):
                st.markdown(f"**Category:** {b['category_name'] or '_uncategorized_'}  \n"
                            f"**Status:** {b['status']}  \n"
                            f"**Last action:** {b['last_action'] or '—'} ({b['last_action_date'] or '—'})  \n"
                            f"**Session:** {b['session'] or '—'}")
                if b["sponsors"]:
                    st.markdown(f"**Sponsors:** {b['sponsors']}")
                st.write(b["description"])
                if b["url"]:
                    st.markdown(f"[View on LegiScan]({b['url']})")

                if st.button("🔍 Analyze impact with Claude", key=f"impact_{b['bill_id']}"):
                    from claude_client import ClaudeService, ClaudeError
                    try:
                        claude = ClaudeService(claude_key)
                        with st.spinner("Analyzing…"):
                            impact = claude.analyze_impact(b["title"], b["description"])
                            store.set_impact(b["bill_id"], json.dumps(impact))
                            b["impact_json"] = json.dumps(impact)
                    except ClaudeError as e:
                        st.error(str(e))

                if b["impact_json"]:
                    impact = json.loads(b["impact_json"])
                    wc, lc = st.columns(2)
                    with wc:
                        st.markdown("#### 🟢 Winners")
                        for e in impact.get("winners", []):
                            st.markdown(f"**{e['industry']}** — {', '.join(e.get('companies', []))}")
                            st.caption(e.get("reason", ""))
                    with lc:
                        st.markdown("#### 🔴 Losers")
                        for e in impact.get("losers", []):
                            st.markdown(f"**{e['industry']}** — {', '.join(e.get('companies', []))}")
                            st.caption(e.get("reason", ""))

# ===== Company Rankings =====================================================
with tab_rank:
    st.subheader("Company Rankings")
    st.caption("Aggregated across every bill you've run impact analysis on.")
    tally = defaultdict(lambda: {"wins": 0, "losses": 0, "ticker": "", "scale": ""})
    for b in bills:
        if not b["impact_json"]:
            continue
        impact = json.loads(b["impact_json"])
        for side, key in (("winners", "wins"), ("losers", "losses")):
            for entry in impact.get(side, []):
                details = entry.get("company_details") or [{"name": n} for n in entry.get("companies", [])]
                for d in details:
                    name = d.get("name")
                    if not name:
                        continue
                    tally[name][key] += 1
                    if d.get("ticker"):
                        tally[name]["ticker"] = d["ticker"]
                    if d.get("scale"):
                        tally[name]["scale"] = d["scale"]

    if not tally:
        st.info("No impact analyses yet. Open a bill in the Legislation tab and click "
                "“Analyze impact with Claude”.")
    else:
        ranked = sorted(tally.items(), key=lambda kv: (kv[1]["wins"] - kv[1]["losses"]), reverse=True)
        table = [{
            "Company": name, "Ticker": v["ticker"], "Scale": v["scale"],
            "Winner in": v["wins"], "Loser in": v["losses"],
            "Net": v["wins"] - v["losses"],
        } for name, v in ranked]
        st.dataframe(table, use_container_width=True, hide_index=True)

# ===== Chat =================================================================
with tab_chat:
    st.subheader("Ask Claude about legislation")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for m in st.session_state.chat_history:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if prompt := st.chat_input("Ask about a bill, a policy area, or market impact…"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        from claude_client import ClaudeService, ClaudeError
        try:
            claude = ClaudeService(claude_key)
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    reply = claude.chat(
                        st.session_state.chat_history,
                        system="You are a knowledgeable assistant helping analyze U.S. "
                               "state legislation and its market and policy impact.",
                    )
                    st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        except ClaudeError as e:
            st.error(str(e))
