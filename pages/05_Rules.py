# /pages/05_Rules.py
from __future__ import annotations
import streamlit as st

st.set_page_config(page_title="ルール", page_icon="📘", layout="centered")

if "user" not in st.session_state:
    st.switch_page("app.py")
user = st.session_state["user"]

# 簡易ナビ
cols = st.columns([1,1,1,1,1,1])
with cols[0]: st.page_link("app.py", label="🏠 トップ", use_container_width=True)
with cols[1]: st.page_link("pages/02_Bets.py", label="🎯 試合とベット", use_container_width=True)
with cols[2]: st.page_link("pages/03_History.py", label="📜 履歴", use_container_width=True)
with cols[3]: st.page_link("pages/04_Realtime.py", label="⏱ リアルタイム", use_container_width=True)
with cols[4]: st.page_link("pages/05_Rules.py", label="📘 ルール", use_container_width=True)
with cols[5]:
    if user.get("role")=="admin":
        st.page_link("pages/01_Settings.py", label="🛠 設定", use_container_width=True)
    else:
        st.write("")

st.markdown("### ルール（簡易版）")
st.write("- 毎節1人はブックメーカー（configの `bookmaker_username`）で、残り2人がベット可能。")
st.write("- 一括ロック：その節で一番早い試合のキックオフ **{lock} 分前**（configの `lock_minutes_before_earliest`）。")
st.write("- 一人あたり節の合計上限：`max_total_stake_per_gw`。刻み：`stake_step`。")
st.write("- ベットはロック時点のオッズを確定保存（本ページの実装ではオッズを入力式にしています）。")
lock = st.secrets.get("lock_minutes_before_earliest","（config参照）")
