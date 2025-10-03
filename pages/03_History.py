# pages/03_History.py
import streamlit as st
import pandas as pd
from google_sheets_client import read_bets

st.set_page_config(page_title="履歴", page_icon="🪵", layout="wide")

def require_login():
    if not st.session_state.get("is_authenticated"):
        st.switch_page("app.py")

def page():
    require_login()
    st.page_link("app.py", label="🏠 トップ")
    st.markdown("## 履歴")

    data = read_bets()
    if not data:
        st.info("まだベット履歴がありません。")
        return

    df = pd.DataFrame(data)  # columns: gw, match, user, bet_team, stake, odds, timestamp
    me = st.session_state.get("user_name","")
    view = st.radio("表示範囲", ["自分のみ","全員"], horizontal=True)
    if view == "自分のみ" and me:
        df = df[df["user"]==me]

    # KPI
    if "stake" in df.columns and "odds" in df.columns:
        df["stake"] = pd.to_numeric(df["stake"], errors="coerce").fillna(0)
        df["odds"]  = pd.to_numeric(df["odds"],  errors="coerce").fillna(0)
        total_stake = int(df["stake"].sum())
        potential   = (df["stake"]*df["odds"]).sum()
        c1,c2,c3 = st.columns(3)
        c1.metric("総ベット額", f"{total_stake:,} 円")
        c2.metric("理論払戻合計", f"{int(potential):,} 円")
        c3.metric("件数", f"{len(df)}")

    st.dataframe(df, use_container_width=True, hide_index=True)

if __name__ == "__main__":
    page()
