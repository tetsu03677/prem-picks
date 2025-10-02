# /app.py
from __future__ import annotations
import streamlit as st
from typing import Dict, Any, List
from google_sheets_client import read_users_from_config, list_bets
from google_sheets_client import get_config_value
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="centered")

# ---------- Session helpers ----------
def is_logged_in() -> bool:
    return "user" in st.session_state

def require_login():
    if not is_logged_in():
        login_card()
        st.stop()

def login_card():
    st.markdown(
        "<div style='text-align:center;'><h1 style='margin-bottom:0.2rem;'>Premier Picks</h1><p>ログイン</p></div>",
        unsafe_allow_html=True,
    )
    users = read_users_from_config()
    names = [u.get("username") for u in users]
    colA, colB, colC = st.columns([1,2,1])
    with colB:
        with st.container(border=True):
            username = st.selectbox("ユーザー名", names, index=0 if names else None)
            password = st.text_input("パスワード", type="password")
            if st.button("ログイン", type="primary", use_container_width=True):
                u = next((x for x in users if x.get("username")==username), None)
                if not u or (u.get("password") or "") != password:
                    st.error("ユーザー名またはパスワードが違います。")
                else:
                    st.session_state["user"] = {
                        "username": u["username"],
                        "role": u.get("role","user"),
                        "team": u.get("team",""),
                    }
                    st.rerun()

# ---------- Navbar ----------
def navbar():
    user = st.session_state.get("user", {})
    role = user.get("role","user")
    cols = st.columns([1,1,1,1,1,1])
    with cols[0]:
        st.page_link("app.py", label="🏠 トップ", use_container_width=True)
    with cols[1]:
        st.page_link("pages/02_Bets.py", label="🎯 試合とベット", use_container_width=True)
    with cols[2]:
        st.page_link("pages/03_History.py", label="📜 履歴", use_container_width=True)
    with cols[3]:
        st.page_link("pages/04_Realtime.py", label="⏱ リアルタイム", use_container_width=True)
    with cols[4]:
        st.page_link("pages/05_Rules.py", label="📘 ルール", use_container_width=True)
    with cols[5]:
        if role == "admin":
            st.page_link("pages/01_Settings.py", label="🛠 設定", use_container_width=True)
        else:
            st.write("")

# ---------- Dashboard ----------
def dashboard():
    require_login()
    navbar()
    user = st.session_state["user"]
    username = user["username"]

    current_gw = get_config_value("current_gw","GW7")
    # KPI（betsから集計）
    rows = list_bets(user=username, gw=current_gw)
    total_stake = sum(int(r.get("stake") or 0) for r in rows)
    total_payout = sum(int(float(r.get("payout") or 0)) for r in rows)
    total_net = sum(int(float(r.get("net") or 0)) for r in rows)

    st.markdown("### ダッシュボード")
    c1,c2,c3 = st.columns(3)
    c1.metric("今GWステーク合計", f"{total_stake}")
    c2.metric("今GW払戻合計", f"{total_payout}")
    c3.metric("今GW損益", f"{total_net}")

    st.markdown("#### 最新ベット（自分）")
    if not rows:
        st.info("今GWのベットはまだありません。")
    else:
        for r in rows[-5:]:
            st.write(f"- {r.get('match')} | {r.get('pick')} | Stake: {r.get('stake')} | Status: {r.get('status')}")

if not is_logged_in():
    login_card()
else:
    dashboard()
