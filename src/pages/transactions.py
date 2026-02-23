from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from sleeper.api import league as league_api
from sleeper.api import player as player_api

# ── Session state guard ────────────────────────────────────────────────────────
if not st.session_state.get("league_id"):
    st.error("No league selected. Return to the **Home** page to select a league.")
    st.stop()

league_id = st.session_state["league_id"]

# ── Type display config ────────────────────────────────────────────────────────
TYPE_CONFIG = {
    "waiver":       {"label": "Waiver Claim", "color": "#8E44AD", "icon": "🔄"},
    "free_agent":   {"label": "Free Agent",   "color": "#2980B9", "icon": "➕"},
    "drop":         {"label": "Drop",         "color": "#7F8C8D", "icon": "➖"},
    "trade":        {"label": "Trade",        "color": "#E67E22", "icon": "🔀"},
    "commissioner": {"label": "Commissioner", "color": "#16A085", "icon": "⚙️"},
}


# ── API-backed data loaders ────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_league_meta(league_id: str) -> dict[int, str]:
    """Returns roster_id -> display_name map (1-hour cache)."""
    rosters = league_api.get_rosters(league_id=league_id)
    members = league_api.get_users_in_league(league_id=league_id)
    uid_to_name = {m["user_id"]: m["display_name"] for m in members}
    return {
        r["roster_id"]: uid_to_name.get(r["owner_id"], f"Team {r['roster_id']}")
        for r in rosters
    }


@st.cache_data(ttl=86400)
def fetch_all_players() -> dict[str, str]:
    """Returns player_id -> full_name map. Expensive call — cached 24 hours."""
    all_players = player_api.get_all_players(sport="nba")
    return {pid: p.get("full_name", f"Player {pid}") for pid, p in all_players.items()}


@st.cache_data(ttl=3600)
def fetch_all_transactions(league_id: str) -> tuple[list[dict], list[str]]:
    """
    Fetch all completed transactions via the Sleeper API for weeks 1–20.
    Weeks that return an empty array (not yet played) are silently skipped.
    Returns (txs, sorted_player_ids).
    """
    txs: list[dict] = []
    all_pids: set[str] = set()

    for week in range(1, 21):
        raw = league_api.get_transactions(league_id=league_id, week=week) or []
        for tx in raw:
            if tx.get("status") != "complete":
                continue

            adds     = tx.get("adds")  or {}
            drops    = tx.get("drops") or {}
            raw_type = tx.get("type", "free_agent")

            # Classify pure drops (free_agent with no adds) as "drop"
            tx_type = "drop" if raw_type == "free_agent" and not adds and drops else raw_type

            all_pids.update(adds.keys())
            all_pids.update(drops.keys())

            txs.append({
                "tx_id":      tx.get("transaction_id", ""),
                "week":       tx.get("leg", week),
                "type":       tx_type,
                "created_ms": tx.get("created", 0),
                "adds":       adds,   # {player_id: roster_id}
                "drops":      drops,  # {player_id: roster_id}
                "roster_ids": tx.get("roster_ids") or [],
                "waiver_seq": (tx.get("settings") or {}).get("seq"),
            })

    txs.sort(key=lambda x: x["created_ms"], reverse=True)
    return txs, sorted(all_pids)


# ── Processing helpers ─────────────────────────────────────────────────────────

def fmt_ts(ms: int) -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%b %-d, %Y")


def type_badge(tx_type: str) -> str:
    cfg = TYPE_CONFIG.get(tx_type, TYPE_CONFIG["free_agent"])
    return (
        f"<span style='background:{cfg['color']};padding:2px 8px;border-radius:4px;"
        f"color:white;font-size:12px;font-weight:600'>{cfg['icon']} {cfg['label']}</span>"
    )


def build_leaderboard(txs: list[dict], roster_to_name: dict) -> pd.DataFrame:
    """
    - Total Moves: 1 per transaction per roster (matches Sleeper's move counter)
    - Adds/Drops:  count of individual players added/dropped per roster
    A single waiver claim that adds 1 and drops 1 = 1 move, 1 add, 1 drop.
    A trade swapping 2 players each way = 1 move, 2 adds, 2 drops per team.
    """
    counts = {
        rid: {"Team": name, "Adds": 0, "Drops": 0, "Trades": 0, "Total Moves": 0}
        for rid, name in roster_to_name.items()
    }

    for tx in txs:
        t = tx["type"]
        for rid in tx["roster_ids"]:
            if rid not in counts:
                continue
            counts[rid]["Total Moves"] += 1
            if t == "trade":
                counts[rid]["Trades"] += 1
            counts[rid]["Adds"]  += sum(1 for dest in tx["adds"].values()  if dest == rid)
            counts[rid]["Drops"] += sum(1 for src  in tx["drops"].values() if src  == rid)

    return (
        pd.DataFrame(list(counts.values()))
        .sort_values("Total Moves", ascending=False)
        .reset_index(drop=True)
        [["Team", "Adds", "Drops", "Trades", "Total Moves"]]
    )


def build_player_activity(
    txs: list[dict],
    pid_to_name: dict,
    roster_to_name: dict,
    top_n: int = 15,
) -> pd.DataFrame:
    """
    For each player that appeared in any transaction, compute:
      - Total Moves: total add + drop events involving the player
      - Most Added By: team that acquired the player most often (with count)
      - Teams: number of distinct rosters that have acquired the player
    """
    stats: dict[str, dict] = {}

    for tx in txs:
        for pid, rid in tx["adds"].items():
            s = stats.setdefault(pid, {"total": 0, "adds_by": {}, "teams": set()})
            s["total"] += 1
            s["adds_by"][rid] = s["adds_by"].get(rid, 0) + 1
            s["teams"].add(rid)
        for pid in tx["drops"]:
            s = stats.setdefault(pid, {"total": 0, "adds_by": {}, "teams": set()})
            s["total"] += 1

    rows = []
    for pid, s in stats.items():
        if not s["adds_by"]:
            continue
        top_rid   = max(s["adds_by"], key=s["adds_by"].get)
        top_team  = roster_to_name.get(top_rid, f"Roster {top_rid}")
        top_count = s["adds_by"][top_rid]
        rows.append({
            "Player":        pid_to_name.get(pid, pid),
            "Total Moves":   s["total"],
            "Most Added By": f"{top_team} ({top_count}x)",
            "Teams":         len(s["teams"]),
        })

    return (
        pd.DataFrame(rows)
        .sort_values("Total Moves", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def build_player_timeline(
    txs: list[dict],
    player_id: str,
    roster_to_name: dict,
    pid_to_name: dict,
) -> list[dict]:
    events = []
    for tx in txs:
        in_adds  = player_id in tx["adds"]
        in_drops = player_id in tx["drops"]
        if not in_adds and not in_drops:
            continue

        date = fmt_ts(tx["created_ms"])
        week = tx["week"]
        t    = tx["type"]
        cfg  = TYPE_CONFIG.get(t, TYPE_CONFIG["free_agent"])

        if t == "trade":
            to_rid    = tx["adds"].get(player_id)
            from_rid  = tx["drops"].get(player_id)
            to_name   = roster_to_name.get(to_rid,   f"Roster {to_rid}")
            from_name = roster_to_name.get(from_rid, f"Roster {from_rid}")
            desc = f"Traded from **{from_name}** → **{to_name}**"
        elif in_adds:
            rid  = tx["adds"][player_id]
            team = roster_to_name.get(rid, f"Roster {rid}")
            if t == "waiver":
                seq   = tx.get("waiver_seq")
                extra = f" (priority #{seq + 1})" if seq is not None else ""
                desc  = f"Waiver claim by **{team}**{extra}"
            elif t == "commissioner":
                desc = f"Commissioner added to **{team}**"
            else:
                desc = f"Added as free agent by **{team}**"
        else:
            rid  = tx["drops"][player_id]
            team = roster_to_name.get(rid, f"Roster {rid}")
            desc = f"Dropped by **{team}**"

        events.append({
            "Week":   week,
            "Date":   date,
            "_type":  t,
            "_color": cfg["color"],
            "_icon":  cfg["icon"],
            "_label": cfg["label"],
            "Event":  desc,
        })

    return events


# ── Page render ────────────────────────────────────────────────────────────────

league_name = st.session_state.get("league_name", "My League")
st.title(f"{league_name} — League Activity")
st.caption("All completed transactions")

with st.spinner("Loading league data..."):
    roster_to_name = fetch_league_meta(league_id)

with st.spinner("Fetching transaction data..."):
    txs, all_pids = fetch_all_transactions(league_id)

with st.spinner("Loading player names..."):
    pid_to_name = fetch_all_players()

tab_ledger, tab_board, tab_lookup = st.tabs([
    "📋  Weekly Ledger",
    "🏆  Activity Leaderboard",
    "🔍  Player Lookup",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Weekly Ledger
# ══════════════════════════════════════════════════════════════════════════════
with tab_ledger:
    available_weeks = sorted({tx["week"] for tx in txs})

    if not available_weeks:
        st.info("No completed transactions found for this league.")
    else:
        week_sel = st.selectbox(
            "Select week",
            options=available_weeks,
            index=len(available_weeks) - 1,
            format_func=lambda w: f"Week {w}",
        )

        week_txs = [tx for tx in txs if tx["week"] == week_sel]

    if available_weeks and week_txs:
        st.caption(f"{len(week_txs)} transaction(s) — most recent first")

        for tx in week_txs:
            t    = tx["type"]
            cfg  = TYPE_CONFIG.get(t, TYPE_CONFIG["free_agent"])
            date = fmt_ts(tx["created_ms"])
            adds = tx["adds"]
            drops = tx["drops"]
            rids = tx["roster_ids"]

            with st.container():
                left, right = st.columns([2, 8])

                with left:
                    st.markdown(
                        f"<div style='padding-top:10px'>{type_badge(t)}<br>"
                        f"<span style='color:#888;font-size:11px'>{date}</span></div>",
                        unsafe_allow_html=True,
                    )

                with right:
                    if t == "trade":
                        received: dict[int, list[str]] = {}
                        for pid, rid in adds.items():
                            received.setdefault(rid, []).append(pid_to_name.get(pid, pid))
                        parts = []
                        for rid, names in received.items():
                            team = roster_to_name.get(rid, f"Roster {rid}")
                            parts.append(f"**{team}** ← {', '.join(names)}")
                        st.markdown("  &nbsp;·&nbsp;  ".join(parts))
                    else:
                        team  = roster_to_name.get(rids[0] if rids else 0, "Unknown")
                        lines = []
                        for pid in adds:
                            lines.append(f"<span style='color:#27AE60'>+</span> {pid_to_name.get(pid, pid)}")
                        for pid in drops:
                            lines.append(f"<span style='color:#E74C3C'>−</span> {pid_to_name.get(pid, pid)}")
                        st.markdown(
                            f"**{team}** &nbsp;{'&nbsp;&nbsp;'.join(lines)}",
                            unsafe_allow_html=True,
                        )

            st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Activity Leaderboard
# ══════════════════════════════════════════════════════════════════════════════
with tab_board:
    leaderboard = build_leaderboard(txs, roster_to_name)
    st.caption("Adds and Drops counted per player move. Trades counted once per team involved.")

    def color_total(val):
        max_val = leaderboard["Total Moves"].max()
        pct = val / max_val if max_val else 0
        if pct >= 0.7:
            return "color: #E74C3C; font-weight: 700"
        if pct >= 0.4:
            return "color: #F39C12; font-weight: 600"
        return "color: #27AE60"

    # ~35px per row + 39px header; enough to show all teams without scrolling
    team_table_height = len(leaderboard) * 35 + 39

    st.dataframe(
        leaderboard.style.applymap(color_total, subset=["Total Moves"]),
        width="stretch",
        hide_index=True,
        height=team_table_height,
    )

    st.markdown("---")
    st.subheader("Most Active Players")
    st.caption("Top 15 players by total transaction events (adds + drops) this season.")

    player_activity = build_player_activity(txs, pid_to_name, roster_to_name)

    st.dataframe(
        player_activity,
        width="stretch",
        hide_index=True,
        height=len(player_activity) * 35 + 39,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Player Lookup
# ══════════════════════════════════════════════════════════════════════════════
with tab_lookup:
    transacted_players = sorted(
        [(pid, pid_to_name.get(pid, pid)) for pid in all_pids],
        key=lambda x: x[1],
    )
    player_options = [pid for pid, _ in transacted_players]
    player_labels  = {pid: name for pid, name in transacted_players}

    selected_pid = st.selectbox(
        "Search for a player",
        options=player_options,
        format_func=lambda pid: player_labels.get(pid, pid),
        index=None,
        placeholder="Type a player name...",
    )

    if selected_pid is None:
        st.info("Select a player above to see their transaction history.")
    else:
        player_name = player_labels.get(selected_pid, selected_pid)
        events = build_player_timeline(txs, selected_pid, roster_to_name, pid_to_name)

        col_metric, _ = st.columns([2, 8])
        col_metric.metric("Total Times Relocated", len(events))

        st.markdown(f"### {player_name} — Transaction Timeline")

        if not events:
            st.info("No transaction history found for this player.")
        else:
            for ev in events:
                color = ev["_color"]
                icon  = ev["_icon"]
                label = ev["_label"]
                st.markdown(
                    f"""<div style="display:flex;align-items:flex-start;gap:12px;
                                   margin-bottom:14px;padding:10px 14px;
                                   background:#1E1E2E;border-radius:8px;
                                   border-left:4px solid {color}">
                        <div style="min-width:90px;color:#888;font-size:12px;padding-top:2px">
                            Wk {ev['Week']}<br>{ev['Date']}
                        </div>
                        <div>
                            <span style="background:{color};padding:2px 7px;border-radius:4px;
                                         color:white;font-size:11px;font-weight:600;margin-right:8px">
                                {icon} {label}
                            </span><br>
                            <span style="color:white;font-size:14px">{ev['Event']}</span>
                        </div>
                    </div>""",
                    unsafe_allow_html=True,
                )
