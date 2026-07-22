"""State Bill Evaluator — Windows/Streamlit port of the macOS LegisTracker app.

Tracks U.S. state legislation via the LegiScan API and uses Claude to
categorize bills and analyze their industry/market impact.
"""
import csv
import io
import json
import os
import time
from collections import defaultdict

import streamlit as st

# Bridge Streamlit secrets -> environment variables so store.py (DATABASE_URL)
# and the API clients pick them up. Must run before store.init_db().
try:
    for _k in ("DATABASE_URL", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "LEGISCAN_API_KEY"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass  # no secrets.toml present (e.g. local dev)

import store
from models import (LIKELIHOOD_ORDER, likelihood_meter, opportunity_badge,
                    opportunity_band, passage_likelihood)
import sample_data


def bill_score(b: dict):
    """Extract the opportunity score from a bill's stored analysis, or None."""
    if not b.get("impact_json"):
        return None
    try:
        return json.loads(b["impact_json"]).get("opportunity_score")
    except (ValueError, AttributeError):
        return None

st.set_page_config(page_title="State Bill Evaluator", page_icon="🏛️", layout="wide")
store.init_db()

# ---------------------------------------------------------------- settings ---
st.sidebar.title("🏛️ Accela Legislation Radar")
st.sidebar.caption("State bills that could drive demand for Accela products")

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

if store.is_postgres():
    st.sidebar.caption("🟢 Storage: Supabase Postgres (persistent)")
else:
    st.sidebar.caption("🟡 Storage: local SQLite (not persistent on cloud)")

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
    b["score"] = bill_score(b)

tab_legis, tab_rank, tab_chat = st.tabs(
    ["📋 Legislation", "🎯 Opportunity Dashboard", "💬 Chat"])

# ===== Legislation ==========================================================
with tab_legis:
    if not bills:
        st.info("No bills yet. Sync from LegiScan or load the sample data in the sidebar.")
    else:
        f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
        cat_filter = f1.multiselect("Product line", sorted({b["category_name"] for b in bills if b["category_name"]}))
        like_filter = f2.multiselect("Likelihood", LIKELIHOOD_ORDER)
        text_filter = f3.text_input("Search text", "")
        sort_order = f4.selectbox("Sort", ["Opportunity", "State", "Date", "Title", "Likelihood"])

        rows = bills
        if cat_filter:
            rows = [b for b in rows if b["category_name"] in cat_filter]
        if like_filter:
            rows = [b for b in rows if b["likelihood"] in like_filter]
        if text_filter:
            t = text_filter.lower()
            rows = [b for b in rows if t in b["title"].lower() or t in b["state"].lower()
                    or t in (b["description"] or "").lower()]

        if sort_order == "Opportunity":
            rows.sort(key=lambda b: (b["score"] if b["score"] is not None else -1), reverse=True)
        elif sort_order == "State":
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
        w.writerow(["Bill ID", "Title", "State", "Opportunity Score", "Product Line",
                    "Status", "Session", "Likelihood", "Last Action", "Last Action Date",
                    "Sponsors", "URL", "Description"])
        for b in rows:
            w.writerow([b["bill_id"], b["title"], b["state"],
                        b["score"] if b["score"] is not None else "", b["category_name"] or "",
                        b["status"], b["session"], b["likelihood"], b["last_action"] or "",
                        b["last_action_date"] or "", b["sponsors"] or "", b["url"], b["description"]])
        ec1, ec2 = st.columns([1, 1])
        with ec1:
            st.download_button("⬇️ Export CSV", buf.getvalue(), "bills.csv", "text/csv",
                               use_container_width=True)
        with ec2:
            analyzed = [b for b in bills if b["impact_json"]]
            if st.button(f"🔄 Rescore all opportunities ({len(analyzed)})",
                         disabled=not analyzed, use_container_width=True,
                         help="Re-run the Claude sales-opportunity scoring on every scored bill"):
                from claude_client import ClaudeService, ClaudeError
                try:
                    claude = ClaudeService(claude_key)
                    prog = st.progress(0.0, text="Reanalyzing…")
                    for i, bill in enumerate(analyzed):
                        try:
                            impact = claude.analyze_impact(bill["title"], bill["description"])
                            store.set_impact(bill["bill_id"], json.dumps(impact))
                        except ClaudeError as e:
                            st.warning(f"Failed on {bill['title'][:40]}…: {e}")
                            break
                        prog.progress((i + 1) / len(analyzed),
                                      text=f"Reanalyzing… {i + 1}/{len(analyzed)}")
                        time.sleep(0.3)  # gentle rate-limit, mirrors the macOS app
                    st.rerun()
                except ClaudeError as e:
                    st.error(str(e))

        st.caption(f"{len(rows)} of {len(bills)} bills")

        for b in rows:
            badge = opportunity_badge(b["score"]) if b["score"] is not None else ""
            header = f"{badge}   {b['state']} · {b['title']}   ·   {b['likelihood']} passage"
            with st.expander(header):
                st.markdown(f"**Product line:** {b['category_name'] or '_unclassified_'}  \n"
                            f"**Passage likelihood:** {likelihood_meter(b['likelihood'])} {b['likelihood']}  \n"
                            f"**Status:** {b['status']}  \n"
                            f"**Last action:** {b['last_action'] or '—'} ({b['last_action_date'] or '—'})  \n"
                            f"**Session:** {b['session'] or '—'}")
                if b["sponsors"]:
                    st.markdown(f"**Sponsors:** {b['sponsors']}")
                st.write(b["description"])
                if b["url"]:
                    st.markdown(f"[View on LegiScan]({b['url']})")

                bc1, bc2 = st.columns(2)
                if bc1.button("📄 Fetch full detail", key=f"detail_{b['bill_id']}",
                              help="Pull description, status, session & sponsors from LegiScan",
                              use_container_width=True):
                    from legiscan import LegiScanService, LegiScanError
                    try:
                        legi = LegiScanService(legiscan_key)
                        with st.spinner("Fetching from LegiScan…"):
                            raw = legi.get_bill(b["bill_id"])
                            store.set_detail(b["bill_id"], **LegiScanService.parse_detail(raw))
                        st.rerun()
                    except LegiScanError as e:
                        st.error(str(e))

                if bc2.button("🎯 Score sales opportunity", key=f"impact_{b['bill_id']}",
                              use_container_width=True):
                    from claude_client import ClaudeService, ClaudeError
                    try:
                        claude = ClaudeService(claude_key)
                        with st.spinner("Scoring with Claude…"):
                            impact = claude.analyze_impact(b["title"], b["description"])
                            store.set_impact(b["bill_id"], json.dumps(impact))
                        st.rerun()
                    except ClaudeError as e:
                        st.error(str(e))

                if b["impact_json"]:
                    a = json.loads(b["impact_json"])
                    if "opportunity_score" in a:  # new Accela sales-signal format
                        st.divider()
                        st.markdown(f"### {opportunity_badge(a.get('opportunity_score'))} sales opportunity")
                        cols = st.columns(2)
                        cols[0].markdown(f"**Product line(s):** {', '.join(a.get('product_lines', [])) or '—'}")
                        cols[1].markdown(f"**Likely buyer:** {a.get('buyer', '—')}")
                        if a.get("drivers"):
                            st.markdown("**What creates the demand:**")
                            for d in a["drivers"]:
                                st.markdown(f"- {d}")
                        if a.get("why_it_matters"):
                            st.markdown("**Why it matters to sales:**")
                            st.info(a["why_it_matters"])
                        if a.get("talking_point"):
                            st.markdown(f"**Outreach hook:** _{a['talking_point']}_")
                    else:  # legacy winners/losers analysis
                        st.caption("Legacy analysis — click “Score sales opportunity” to refresh.")

# ===== Opportunity Dashboard ===============================================
with tab_rank:
    st.subheader("Opportunity Dashboard")
    st.caption("Every scored bill, ranked by how strongly it signals demand for Accela products.")

    scored = [b for b in bills if b["score"] is not None]
    if not scored:
        st.info("No scored bills yet. Open a bill in the Legislation tab and click "
                "“🎯 Score sales opportunity”.")
    else:
        scored.sort(key=lambda b: b["score"], reverse=True)

        # Headline metrics
        hot = sum(1 for b in scored if opportunity_band(b["score"]) == "Hot")
        warm = sum(1 for b in scored if opportunity_band(b["score"]) == "Warm")
        m1, m2, m3 = st.columns(3)
        m1.metric("Scored bills", len(scored))
        m2.metric("🔥 Hot (75+)", hot)
        m3.metric("🟠 Warm (50-74)", warm)

        # Count by product line
        by_line = defaultdict(int)
        for b in scored:
            by_line[b["category_name"] or "Unclassified"] += 1
        st.markdown("**Bills by product line**")
        st.bar_chart({"bills": dict(sorted(by_line.items(), key=lambda kv: kv[1], reverse=True))})

        # Ranked leaderboard
        st.markdown("**Top opportunities**")
        table = []
        for b in scored:
            a = json.loads(b["impact_json"])
            table.append({
                "Score": b["score"],
                "Band": opportunity_band(b["score"]),
                "State": b["state"],
                "Bill": b["title"],
                "Product line": b["category_name"] or "",
                "Buyer": a.get("buyer", ""),
                "Passage": b["likelihood"],
            })
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
                        system="You help Accela sales reps understand U.S. state "
                               "legislation and where it creates demand for Accela's "
                               "permitting, licensing, and citizen-portal govtech "
                               "products. Be concrete about which governments must act "
                               "(the buyers) and why a bill is or isn't a sales opening.",
                    )
                    st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        except ClaudeError as e:
            st.error(str(e))
