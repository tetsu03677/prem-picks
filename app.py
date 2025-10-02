# /app.py
from __future__ import annotations
import streamlit as st
from google_sheets_client import ensure_basics, list_users, get_user

st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="centered")

# 初期セットアップ（不足シート/ヘッダを自動作成）
with st.spinner("初期セットアップ中..."):
    ensure_basics()

def _login_card():
    st.markdown(
        "<div style='text-align:center;'><h1 style='margin-bottom:0.2rem;'>Premier Picks</h1><p>ログイン</p></div>",
        unsafe_allow_html=True,
    )
    st.write("")
    colA, colB, colC = st.columns([1, 2, 1])
    with colB:
        with st.container(border=True):
            users = list_users()
            names = [u.get("username") for u in users]
            username = st.selectbox("ユーザー名", names, index=0 if names else None)
            password = st.text_input("パスワード", type="password")
            ok = st.button("ログイン", type="primary", use_container_width=True)
            if ok:
                u = get_user(username)
                if not u or (u.get("password") or "") != password:
                    st.error("ユーザー名またはパスワードが違います。")
                else:
                    st.session_state["user"] = {
                        "username": u["username"],
                        "role": u.get("role", "user"),
                        "team": u.get("team", ""),
                    }
                    st.success("ログイン成功")
                    st.switch_page("pages/02_Bets.py")

# すでにログインしていたらベットページへ
if "user" in st.session_state:
    st.switch_page("pages/02_Bets.py")
else:
    _login_card()
