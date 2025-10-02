# /pages/04_Realtime.py
from __future__ import annotations
import streamlit as st

st.set_page_config(page_title="リアルタイム", page_icon="⏱", layout="centered")

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

st.info("リアルタイムページはこの後のステップで実装します（ライブスコア×自分のベットを突合して暫定損益を表示）。")
