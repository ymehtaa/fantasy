from datetime import datetime

import streamlit as st
from sleeper.api import league as league_api
from sleeper.api import user as user_api


@st.cache_data(ttl=300)
def fetch_user(username: str) -> dict | None:
    try:
        return user_api.get_user(identifier=username)
    except Exception:
        return None


@st.cache_data(ttl=300)
def fetch_nba_leagues(user_id: str, year: int) -> list[dict]:
    try:
        return league_api.get_user_leagues_for_year(user_id=user_id, sport="nba", year=year) or []
    except Exception:
        return []


# ── Dashboard tiles when a league is already selected ──────────────────────────
if st.session_state.get("league_id"):
    league_name = st.session_state.get("league_name", "My League")
    st.title(f"🏀 {league_name}")
    st.markdown("---")

    col_a, col_b, _ = st.columns([1, 1, 2])

    with col_a:
        st.markdown(
            "<div style='background:#1E1E2E;border-radius:12px;padding:28px 20px;"
            "text-align:center;border:1px solid #333'>"
            "<div style='font-size:40px'>🏀</div>"
            "<div style='font-size:18px;font-weight:700;color:white;margin-top:10px'>Draft Recap</div>"
            "<div style='font-size:13px;color:#888;margin-top:6px'>Full draft board · pick analysis</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("Open Draft Recap →", key="nav_draft", use_container_width=True, type="primary"):
            st.switch_page("pages/draft.py")

    with col_b:
        st.markdown(
            "<div style='background:#1E1E2E;border-radius:12px;padding:28px 20px;"
            "text-align:center;border:1px solid #333'>"
            "<div style='font-size:40px'>📋</div>"
            "<div style='font-size:18px;font-weight:700;color:white;margin-top:10px'>Transactions</div>"
            "<div style='font-size:13px;color:#888;margin-top:6px'>Waiver wire · trades · activity</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("Open Transactions →", key="nav_txn", use_container_width=True, type="primary"):
            st.switch_page("pages/transactions.py")

    st.markdown("---")
    if st.button("← Switch League", type="secondary"):
        for key in ("league_id", "league_name", "last_scored_week"):
            st.session_state.pop(key, None)
        st.rerun()

else:
    # ── Username entry form ────────────────────────────────────────────────────
    st.title("🏀 Sleeper Fantasy NBA")
    st.markdown("Enter your Sleeper username to load your league.")

    with st.form("username_form"):
        username = st.text_input("Sleeper Username", placeholder="e.g. sleeper123")
        submitted = st.form_submit_button("Find My Leagues", type="primary")

    if submitted and username:
        with st.spinner("Looking up account..."):
            user = fetch_user(username.strip())

        if not user or not user.get("user_id"):
            st.error(f"User '{username}' not found. Double-check the username and try again.")
            st.stop()

        user_id = user["user_id"]
        current_year = datetime.now().year

        with st.spinner("Fetching NBA leagues..."):
            leagues: list[dict] = []
            seen: set[str] = set()
            for year in [current_year, current_year - 1]:
                for lg in fetch_nba_leagues(user_id, year):
                    lid = lg.get("league_id")
                    if lid and lid not in seen:
                        seen.add(lid)
                        leagues.append(lg)

        if not leagues:
            st.error("No NBA leagues found for this account.")
            st.stop()

        if len(leagues) == 1:
            lg = leagues[0]
            st.session_state["league_id"]        = lg["league_id"]
            st.session_state["league_name"]      = lg.get("name", "My League")
            st.session_state["last_scored_week"] = (lg.get("settings") or {}).get("last_scored_leg", 1)
            st.session_state["username"] = username
            st.rerun()

        # Multiple leagues — show selector
        st.success(f"Found {len(leagues)} NBA league(s) for **{user.get('display_name', username)}**")
        options = {
            lg["league_id"]: f"{lg.get('name', 'Unnamed League')}  ({lg.get('season', '?')})"
            for lg in leagues
        }
        selected_id = st.selectbox(
            "Select a league",
            options=list(options.keys()),
            format_func=lambda lid: options[lid],
        )
        if st.button("Load League →", type="primary"):
            selected_lg = next(lg for lg in leagues if lg["league_id"] == selected_id)
            st.session_state["league_id"]        = selected_lg["league_id"]
            st.session_state["league_name"]      = selected_lg.get("name", "My League")
            st.session_state["last_scored_week"] = (selected_lg.get("settings") or {}).get("last_scored_leg", 1)
            st.session_state["username"] = username
            st.rerun()
