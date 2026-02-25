import math
import time
import unicodedata

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sleeper.api import draft as draft_api
from sleeper.api import league as league_api

# ── Session state guard ────────────────────────────────────────────────────────
if not st.session_state.get("league_id"):
    st.error("No league selected. Return to the **Home** page to select a league.")
    st.stop()

league_id = st.session_state["league_id"]

# ── Scoring constants ──────────────────────────────────────────────────────────
SCORING = {
    "PTS":  0.5,
    "REB":  1.0,
    "AST":  1.0,
    "STL":  2.0,
    "BLK":  2.0,
    "TOV": -1.0,
    "FG3M": 0.5,
}
BONUS_DD  = 1.0
BONUS_TD  = 2.0
BONUS_40P = 2.0
BONUS_50P = 2.0

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

# Manager palette for scatter plot
MGR_PALETTE = [
    "#3A7BD5", "#E67E22", "#9B59B6", "#E74C3C", "#1ABC9C",
    "#F39C12", "#2ECC71", "#E91E63", "#00BCD4", "#FF5722",
    "#607D8B", "#CDDC39",
]


# ── Cached data functions ──────────────────────────────────────────────────────

@st.cache_data
def load_draft_data(league_id: str):
    """Fetch drafted players + manager names. No TTL — draft data never changes."""
    drafts   = draft_api.get_drafts_in_league(league_id=league_id)
    draft_id = drafts[0]["draft_id"]
    from sleeper.api import draft as _draft_api
    picks   = _draft_api.get_player_draft_picks(draft_id=draft_id)
    members = league_api.get_users_in_league(league_id=league_id)

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
    return df


@st.cache_data(ttl=86400)
def fetch_nba_player_map() -> dict[str, int]:
    """name.lower() → NBA player id. Uses static data — no API call."""
    from nba_api.stats.static import players
    return {p["full_name"].lower(): p["id"] for p in players.get_players()}


@st.cache_data(ttl=86400)
def fetch_game_log(nba_id: int, season: str) -> pd.DataFrame:
    """Per-game box score for one player. 0.6 s sleep for rate limiting."""
    from nba_api.stats.endpoints import playergamelog
    time.sleep(0.6)
    gl = playergamelog.PlayerGameLog(player_id=nba_id, season=season)
    return gl.get_data_frames()[0]


# ── Score calculation ──────────────────────────────────────────────────────────

def calc_fantasy_score(df: pd.DataFrame) -> pd.Series:
    score = sum(df[col] * mult for col, mult in SCORING.items() if col in df.columns)
    dd_counts = (df[["PTS", "REB", "AST", "STL", "BLK"]] >= 10).sum(axis=1)
    score += (dd_counts >= 3) * BONUS_TD
    score += (dd_counts == 2) * BONUS_DD
    score += (df["PTS"] >= 40) * BONUS_40P
    score += (df["PTS"] >= 50) * BONUS_50P
    return score


def best_game_per_week(df: pd.DataFrame) -> pd.DataFrame:
    """df must have GAME_DATE (str) and FANTASY_SCORE columns."""
    df = df.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    df["ISO_WEEK"]  = df["GAME_DATE"].dt.isocalendar().week.astype(int)
    df["ISO_YEAR"]  = df["GAME_DATE"].dt.isocalendar().year.astype(int)
    return df.groupby(["ISO_YEAR", "ISO_WEEK"])["FANTASY_SCORE"].max().reset_index()


def normalize_name(name: str) -> str:
    """Lowercase + strip accents for fuzzy name matching."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# ── Draft value math functions ─────────────────────────────────────────────────

def calc_expected_value(pick_no: int) -> float:
    """Exponential decay curve: 100 * e^(-0.03 * (pick_no - 1))."""
    return 100.0 * math.exp(-0.03 * (pick_no - 1))


def calc_log_roi(pick_no: int, current_rank: int) -> float:
    """Logarithmic ratio: ln(pick_no / current_rank).
    Positive = player ranked higher than drafted (Steal).
    Negative = player ranked lower than drafted (Bust).
    """
    return math.log(pick_no / current_rank)


# ── Derive NBA API season string ───────────────────────────────────────────────
raw_season = st.session_state.get("league_season", "2024")
try:
    start_year = int(raw_season)
except ValueError:
    start_year = 2024
nba_season = f"{start_year}-{str(start_year + 1)[2:]}"  # e.g. "2024-25"

# ── Page header ───────────────────────────────────────────────────────────────
league_name = st.session_state.get("league_name", "My League")
st.title(f"{league_name} — Player Rankings")
st.caption(f"NBA season {nba_season} · Ranked by avg best fantasy game per week")

# ── Load draft data ────────────────────────────────────────────────────────────
with st.spinner("Loading draft data..."):
    draft_df = load_draft_data(league_id)

# ── Load NBA static player map ─────────────────────────────────────────────────
with st.spinner("Loading NBA player index..."):
    nba_map = fetch_nba_player_map()

# ── Build normalised lookup (accent-stripped) ──────────────────────────────────
nba_map_norm = {normalize_name(k): v for k, v in nba_map.items()}

# ── Fetch game logs for each drafted player ────────────────────────────────────
st.markdown("### Fetching per-game stats")
st.caption("First load fetches one API call per player (~100 s). Subsequent loads are instant from cache.")

players_list = (
    draft_df[["player_name", "position", "pick_no", "manager"]]
    .drop_duplicates("player_name")
    .to_dict("records")
)

progress_bar = st.progress(0, text="Starting...")
not_found: list[str] = []
ranking_rows: list[dict] = []

for i, row in enumerate(players_list):
    name   = row["player_name"]
    norm   = normalize_name(name)
    nba_id = nba_map_norm.get(norm) or nba_map.get(name.lower())
    progress_bar.progress(
        (i + 1) / len(players_list),
        text=f"Loading {name} ({i + 1}/{len(players_list)})",
    )

    if nba_id is None:
        not_found.append(name)
        continue

    try:
        gl = fetch_game_log(nba_id, nba_season)
    except Exception:
        not_found.append(name)
        continue

    # Players found in the map but with no games this season are still tracked
    # so they appear as losses of draft capital (Value Surplus = -100)
    if gl.empty:
        ranking_rows.append({
            "Player":          name,
            "Position":        row["position"],
            "Draft Pick #":    row["pick_no"],
            "Manager":         row["manager"],
            "Avg Best Gm/Wk": 0.0,
            "Season Avg/Game": 0.0,
            "Best Game":       0.0,
            "Games Played":    0,
        })
        continue

    gl["FANTASY_SCORE"] = calc_fantasy_score(gl)
    weekly_bests        = best_game_per_week(gl)

    ranking_rows.append({
        "Player":          name,
        "Position":        row["position"],
        "Draft Pick #":    row["pick_no"],
        "Manager":         row["manager"],
        "Avg Best Gm/Wk": round(weekly_bests["FANTASY_SCORE"].mean(), 1),
        "Season Avg/Game": round(gl["FANTASY_SCORE"].mean(), 1),
        "Best Game":       round(gl["FANTASY_SCORE"].max(), 1),
        "Games Played":    len(gl),
    })

progress_bar.empty()

# ── Build rankings DataFrame with derived columns ──────────────────────────────
if not ranking_rows:
    st.warning("No player stats could be loaded.")
    st.stop()

rankings_df = (
    pd.DataFrame(ranking_rows)
    .sort_values("Avg Best Gm/Wk", ascending=False)
    .reset_index(drop=True)
)
rankings_df.index += 1  # 1-based rank

# Derived columns — computed after sorting so Performance Rank is known
rankings_df["Performance Rank"] = rankings_df.index
rankings_df["Exp. Value"]       = rankings_df["Draft Pick #"].apply(
    lambda p: round(calc_expected_value(p), 1)
)
rankings_df["Value Surplus"]    = rankings_df.apply(
    lambda r: -100.0 if r["Games Played"] == 0
    else round(r["Avg Best Gm/Wk"] - r["Exp. Value"], 1),
    axis=1,
)
rankings_df["Log ROI"]          = rankings_df.apply(
    lambda r: round(calc_log_roi(r["Draft Pick #"], r["Performance Rank"]), 2),
    axis=1,
)

# ── Formula reference blocks ──────────────────────────────────────────────────
st.markdown("### Ranking Methodology")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        "<div style='background:#1E1E2E;border-radius:10px;padding:16px 18px;border:1px solid #333;height:100%'>"
        "<div style='font-size:12px;color:#888;font-weight:600;letter-spacing:0.08em;margin-bottom:6px'>AVG BEST GM/WK</div>"
        "<div style='font-family:monospace;font-size:15px;color:#6EB5FF;margin-bottom:8px'>"
        "mean( max(score) per ISO week )"
        "</div>"
        "<div style='font-size:12px;color:#aaa;line-height:1.5'>"
        "For each calendar week, take the player's single highest fantasy game. "
        "Average those weekly peaks across the season."
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        "<div style='background:#1E1E2E;border-radius:10px;padding:16px 18px;border:1px solid #333;height:100%'>"
        "<div style='font-size:12px;color:#888;font-weight:600;letter-spacing:0.08em;margin-bottom:6px'>EXP. VALUE (DRAFT COST)</div>"
        "<div style='font-family:monospace;font-size:15px;color:#6EB5FF;margin-bottom:8px'>"
        "100 · e<sup style='font-size:11px'>−0.03·(pick−1)</sup>"
        "</div>"
        "<div style='font-size:12px;color:#aaa;line-height:1.5'>"
        "Exponential decay curve assigning a 0–100 value to each draft slot. "
        "Pick 1 = 100, pick 50 ≈ 22, pick 100 ≈ 5."
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        "<div style='background:#1E1E2E;border-radius:10px;padding:16px 18px;border:1px solid #333;height:100%'>"
        "<div style='font-size:12px;color:#888;font-weight:600;letter-spacing:0.08em;margin-bottom:6px'>VALUE SURPLUS</div>"
        "<div style='font-family:monospace;font-size:15px;color:#2ECC71;margin-bottom:8px'>"
        "Avg Best/Wk − Exp. Value"
        "</div>"
        "<div style='font-size:12px;color:#aaa;line-height:1.5'>"
        "Actual performance minus the draft-slot cost. "
        "<span style='color:#2ECC71'>Positive = Steal</span>, "
        "<span style='color:#E74C3C'>negative = Bust</span>. "
        "0 games played → −100."
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

with col4:
    st.markdown(
        "<div style='background:#1E1E2E;border-radius:10px;padding:16px 18px;border:1px solid #333;height:100%'>"
        "<div style='font-size:12px;color:#888;font-weight:600;letter-spacing:0.08em;margin-bottom:6px'>LOG ROI</div>"
        "<div style='font-family:monospace;font-size:15px;color:#6EB5FF;margin-bottom:8px'>"
        "ln( pick# / perf. rank )"
        "</div>"
        "<div style='font-size:12px;color:#aaa;line-height:1.5'>"
        "Late pick, high rank → large positive. Early pick, low rank → large negative. "
        "Scale-independent steal/bust signal."
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

# ── Main rankings table ────────────────────────────────────────────────────────
st.markdown("### Player Rankings")

display_cols = [
    "Performance Rank", "Player", "Position", "Draft Pick #", "Manager",
    "Avg Best Gm/Wk", "Season Avg/Game", "Best Game", "Games Played",
    "Value Surplus", "Log ROI",
]


def color_position(val):
    color = POSITION_COLORS.get(val, FALLBACK_COLOR)
    return f"background-color: {color}; color: white; font-weight: 600"


def color_surplus(val):
    if pd.isna(val):
        return ""
    if val > 0:
        return "color: #2ECC71; font-weight: 600"
    if val < 0:
        return "color: #E74C3C; font-weight: 600"
    return ""


st.dataframe(
    rankings_df[display_cols].style
        .map(color_position, subset=["Position"])
        .map(color_surplus,  subset=["Value Surplus", "Log ROI"]),
    width="stretch",
    hide_index=True,
)

st.markdown("---")

# ── Manager draft value leaderboard ───────────────────────────────────────────
st.subheader("Manager Draft Value Leaderboard")
st.caption(
    "Average Log ROI: positive = managers who drafted value picks. "
    "Total Value Surplus: cumulative over/under vs. exponential draft cost curve."
)

mgr_summary = (
    rankings_df
    .groupby("Manager")
    .agg(
        **{"Avg Log ROI":        ("Log ROI",       "mean")},
        **{"Total Value Surplus": ("Value Surplus", "sum")},
        **{"Players Tracked":    ("Player",         "count")},
    )
    .round({"Avg Log ROI": 3, "Total Value Surplus": 1})
    .sort_values("Avg Log ROI", ascending=False)
)

st.dataframe(
    mgr_summary.style
        .map(color_surplus, subset=["Avg Log ROI", "Total Value Surplus"]),
    width="stretch",
)

st.markdown("---")

# ── Scatter plot: Draft Pick # vs Performance Rank ─────────────────────────────
st.subheader("Draft Value Scatter: Pick # vs Performance Rank")
st.caption(
    "Points **below** the dashed y=x line outperformed their draft slot (Steals). "
    "Points **above** underperformed (Busts). Hover for details."
)

n_players  = len(rankings_df)
max_axis   = max(rankings_df["Draft Pick #"].max(), n_players) + 2

fig = go.Figure()

# y=x trendline
fig.add_trace(go.Scatter(
    x=[1, max_axis],
    y=[1, max_axis],
    mode="lines",
    name="y = x  (Expected)",
    line=dict(color="#888888", dash="dash", width=1.5),
    hoverinfo="skip",
))

# One trace per manager so the legend is useful
managers_in_order = rankings_df.drop_duplicates("Manager")["Manager"].tolist()
mgr_color_map     = {mgr: MGR_PALETTE[i % len(MGR_PALETTE)] for i, mgr in enumerate(managers_in_order)}

for mgr in managers_in_order:
    sub = rankings_df[rankings_df["Manager"] == mgr]
    fig.add_trace(go.Scatter(
        x=sub["Draft Pick #"],
        y=sub["Performance Rank"],
        mode="markers",
        name=mgr,
        marker=dict(size=10, color=mgr_color_map[mgr], opacity=0.88,
                    line=dict(width=1, color="#1E1E2E")),
        text=sub.apply(
            lambda r: (
                f"<b>{r['Player']}</b><br>"
                f"Pick #{int(r['Draft Pick #'])} → Rank #{int(r['Performance Rank'])}<br>"
                f"Avg Best: {r['Avg Best Gm/Wk']} pts/wk<br>"
                f"Value Surplus: {r['Value Surplus']}<br>"
                f"Log ROI: {r['Log ROI']}"
            ),
            axis=1,
        ),
        hovertemplate="%{text}<extra></extra>",
    ))

fig.update_layout(
    xaxis=dict(title="Draft Pick #",      gridcolor="#333", range=[0, max_axis]),
    yaxis=dict(title="Performance Rank",  gridcolor="#333", range=[0, max_axis]),
    paper_bgcolor="#0E1117",
    plot_bgcolor="#0E1117",
    font=dict(color="white"),
    legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
    margin=dict(l=50, r=20, t=20, b=100),
    height=520,
)

st.plotly_chart(fig, width="stretch")

st.markdown("---")

# ── Not-found warning ─────────────────────────────────────────────────────────
if not_found:
    with st.expander(f"Players not matched to NBA API ({len(not_found)})"):
        for n in sorted(not_found):
            st.write(f"- {n}")
