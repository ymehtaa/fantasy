import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sleeper.api import draft as draft_api
from sleeper.api import league as league_api
from sleeper.api import player as player_api

# ── Session state guard ────────────────────────────────────────────────────────
if not st.session_state.get("league_id"):
    st.error("No league selected. Return to the **Home** page to select a league.")
    st.stop()

league_id = st.session_state["league_id"]

INJURY_COLORS = {
    "Out":          "#C0392B",
    "IR":           "#922B21",
    "Doubtful":     "#E67E22",
    "Questionable": "#F39C12",
    "GTD":          "#D4AC0D",
    "DTD":          "#D4AC0D",
}

POSITION_COLORS = {
    "PG": "#3A7BD5",
    "SG": "#6EB5FF",
    "G":  "#00C9FF",
    "SF": "#27AE60",
    "PF": "#52BE80",
    "F":  "#A9DFBF",
    "C":  "#E67E22",
}
FALLBACK_COLOR = "#7F8C8D"


@st.cache_data
def load_data(league_id: str):
    """Fetch draft picks and league members from the Sleeper API. No TTL — draft data never changes."""
    drafts   = draft_api.get_drafts_in_league(league_id=league_id)
    draft_id = drafts[0]["draft_id"]
    picks    = draft_api.get_player_draft_picks(draft_id=draft_id)
    members  = league_api.get_users_in_league(league_id=league_id)

    uid_to_name = {m["user_id"]: m["display_name"] for m in members}

    rows = []
    for p in picks:
        meta = p["metadata"]
        rows.append({
            "pick_no":     p["pick_no"],
            "round":       p["round"],
            "draft_slot":  p["draft_slot"],
            "picked_by":   p["picked_by"],
            "player_id":   p["player_id"],
            "player_name": f"{meta['first_name']} {meta['last_name']}",
            "position":    meta["position"],
            "nba_team":    meta["team"],
        })

    df = pd.DataFrame(rows)
    df["manager"] = df["picked_by"].map(uid_to_name)
    return df, uid_to_name


@st.cache_data(ttl=3600)
def fetch_player_statuses() -> dict[str, dict]:
    """Fetch all NBA players from Sleeper API (1-hour cache) for fresh injury data."""
    all_players = player_api.get_all_players(sport="nba")
    return {
        pid: {
            "injury_status": p.get("injury_status"),
            "status":        p.get("status"),
        }
        for pid, p in all_players.items()
    }


@st.cache_data(ttl=3600)
def fetch_roster_ownership(league_id: str) -> dict[str, str]:
    """Return player_id -> manager display_name map from live Sleeper rosters (1-hour cache)."""
    rosters = league_api.get_rosters(league_id=league_id)
    members = league_api.get_users_in_league(league_id=league_id)
    uid_to_name = {m["user_id"]: m["display_name"] for m in members}

    player_to_owner: dict[str, str] = {}
    for r in rosters:
        owner = uid_to_name.get(r["owner_id"], r["owner_id"])
        for pid in (r.get("players") or []):
            player_to_owner[pid] = owner
    return player_to_owner


df, uid_to_name = load_data(league_id)

num_rounds = df["round"].max()
slots = sorted(df["draft_slot"].unique())
slot_to_manager = {
    slot: df[df["draft_slot"] == slot]["manager"].iloc[0]
    for slot in slots
}
manager_names = [slot_to_manager[s] for s in slots]

# ── Header ────────────────────────────────────────────────────────────────────
league_name = st.session_state.get("league_name", "My League")
st.title(f"{league_name} — Draft Board")
st.caption(f"NBA Fantasy · {len(slots)} teams · {num_rounds} rounds · Snake draft")

# ── Position legend ────────────────────────────────────────────────────────────
legend_cols = st.columns(len(POSITION_COLORS))
for col, (pos, color) in zip(legend_cols, POSITION_COLORS.items()):
    col.markdown(
        f"<span style='background:{color};padding:3px 10px;border-radius:4px;"
        f"color:white;font-weight:600;font-size:13px'>{pos}</span>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Draft board ────────────────────────────────────────────────────────────────
st.subheader("Full Draft Board")

round_col_vals   = [f"Rd {r}" for r in range(1, num_rounds + 1)]
round_col_colors = ["#262730"] * num_rounds

cell_texts  = [round_col_vals]
cell_colors = [round_col_colors]

for slot in slots:
    texts  = []
    colors = []
    for rnd in range(1, num_rounds + 1):
        pick = df[(df["draft_slot"] == slot) & (df["round"] == rnd)]
        if not pick.empty:
            p = pick.iloc[0]
            texts.append(f"{p['player_name']}\n{p['position']} · {p['nba_team']}")
            colors.append(POSITION_COLORS.get(p["position"], FALLBACK_COLOR))
        else:
            texts.append("")
            colors.append(FALLBACK_COLOR)
    cell_texts.append(texts)
    cell_colors.append(colors)

fig_board = go.Figure(data=[go.Table(
    columnwidth=[38] + [110] * len(slots),
    header=dict(
        values=[""] + manager_names,
        fill_color="#1E1E2E",
        font=dict(color="white", size=12, family="monospace"),
        align="center",
        height=36,
        line_color="#333",
    ),
    cells=dict(
        values=cell_texts,
        fill_color=cell_colors,
        font=dict(color="white", size=11),
        align="center",
        height=48,
        line_color="#1E1E2E",
    ),
)])

fig_board.update_layout(
    margin=dict(l=0, r=0, t=4, b=0),
    height=num_rounds * 50 + 60,
    paper_bgcolor="#0E1117",
)

st.plotly_chart(fig_board, width="stretch")

st.markdown("---")

# ── Per-manager breakdown ──────────────────────────────────────────────────────
st.subheader("Manager Picks")

default_index = 0
if "username" in st.session_state:
    target_user = st.session_state["username"]
    if target_user in manager_names:
        default_index = manager_names.index(target_user)

# 2. Apply it to the selectbox
selected_manager = st.selectbox(
    "Select a manager",
    options=manager_names,
    index=default_index,
)

with st.spinner("Loading live player data..."):
    player_statuses  = fetch_player_statuses()
    roster_ownership = fetch_roster_ownership(league_id)

mgr_raw = (
    df[df["manager"] == selected_manager]
    .sort_values("round")
    .reset_index(drop=True)
)


def injury_label(pid: str) -> str:
    status = player_statuses.get(pid, {})
    inj = status.get("injury_status")
    return inj if inj else "Healthy"


def roster_label(pid: str) -> str:
    return roster_ownership.get(pid, "Free Agent")


mgr_picks = mgr_raw[["round", "pick_no", "player_name", "position", "nba_team"]].copy()
mgr_picks["injury_status"] = mgr_raw["player_id"].map(injury_label)
mgr_picks["roster_status"] = mgr_raw["player_id"].map(roster_label)
mgr_picks = mgr_picks.rename(columns={
    "round":         "Round",
    "pick_no":       "Pick #",
    "player_name":   "Player",
    "position":      "Position",
    "nba_team":      "Team",
    "injury_status": "Injury Status",
    "roster_status": "Roster",
})


def color_position(val):
    color = POSITION_COLORS.get(val, FALLBACK_COLOR)
    return f"background-color: {color}; color: white; font-weight: 600"


def color_injury(val):
    color = INJURY_COLORS.get(val)
    if color:
        return f"background-color: {color}; color: white; font-weight: 600"
    return "color: #27AE60; font-weight: 600"


def color_roster(val):
    if val == "Free Agent":
        return "color: #7F8C8D; font-style: italic"
    return ""


st.dataframe(
    mgr_picks.style
        .applymap(color_position, subset=["Position"])
        .applymap(color_injury,   subset=["Injury Status"])
        .applymap(color_roster,   subset=["Roster"]),
    width="stretch",
    hide_index=True,
)

st.markdown("---")

# ── Position distribution ──────────────────────────────────────────────────────
st.subheader("Position Distribution by Manager")

pos_counts = (
    df.groupby(["manager", "position"])
    .size()
    .reset_index(name="count")
)

positions_in_order = ["PG", "SG", "G", "SF", "PF", "F", "C"]

fig_pos = go.Figure()
for pos in positions_in_order:
    subset = pos_counts[pos_counts["position"] == pos]
    y_vals = []
    for mgr in manager_names:
        row = subset[subset["manager"] == mgr]
        y_vals.append(int(row["count"].iloc[0]) if not row.empty else 0)

    fig_pos.add_trace(go.Bar(
        name=pos,
        x=manager_names,
        y=y_vals,
        marker_color=POSITION_COLORS.get(pos, FALLBACK_COLOR),
    ))

fig_pos.update_layout(
    barmode="stack",
    paper_bgcolor="#0E1117",
    plot_bgcolor="#0E1117",
    font=dict(color="white"),
    legend=dict(orientation="h", y=1.08),
    xaxis=dict(tickangle=-30, gridcolor="#333"),
    yaxis=dict(title="# of Picks", gridcolor="#333"),
    margin=dict(l=40, r=20, t=40, b=80),
    height=400,
)

st.plotly_chart(fig_pos, width="stretch")

st.markdown("---")

# ── Round-by-round pick number reference ──────────────────────────────────────
st.subheader("Snake Draft Order Reference")
st.caption("Pick numbers by round — odd rounds go left→right, even rounds right→left")

order_rows = []
for rnd in range(1, num_rounds + 1):
    rnd_picks = df[df["round"] == rnd].sort_values("pick_no")
    row = {"Round": rnd}
    for _, p in rnd_picks.iterrows():
        row[slot_to_manager[p["draft_slot"]]] = p["pick_no"]
    order_rows.append(row)

order_df = pd.DataFrame(order_rows).set_index("Round")
st.dataframe(order_df, width="stretch")
