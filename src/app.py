import streamlit as st

st.set_page_config(
    page_title="Glub Club",
    layout="wide",
    initial_sidebar_state="expanded",
)

home_page      = st.Page("pages/home.py",         title="Home",             icon="🏠")
draft_page     = st.Page("pages/draft.py",         title="Draft Recap",      icon="🏀")
txn_page       = st.Page("pages/transactions.py",  title="Transactions",     icon="📋")
rankings_page  = st.Page("pages/2_Rankings.py",    title="Player Rankings",  icon="📊")

if st.session_state.get("league_id"):
    pages = [home_page, draft_page, txn_page, rankings_page]
else:
    pages = [home_page]

pg = st.navigation(pages)
pg.run()
