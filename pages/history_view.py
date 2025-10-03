import streamlit as st
import pandas as pd
from google_sheets_client import ws, read_config

def _df():
    try:
        return pd.DataFrame(ws("bets").get_all_records())
    except Exception:
        return pd.DataFrame(columns=["gw","match","user","bet_team","stake","odds","timestamp"])

def render():
    st.markdown("<div class='pp-header'>🧻 履歴</div>", unsafe_allow_html=True)
    df = _df()
    if df.empty:
        st.info("まだベット履歴がありません。")
        return

    u = st.session_state.get("user", {}).get("username")
    my = st.toggle("自分のみ表示", value=True)
    show = df[df["user"]==u] if my and u else df

    # KPI
    if not show.empty:
        st.metric("ベット回数", len(show))
        st.metric("総額(円)", int(show["stake"].sum()))

    st.dataframe(show.sort_values(["timestamp"], ascending=False), use_container_width=True)
