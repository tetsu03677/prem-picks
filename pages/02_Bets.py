# pages/02_Bets.py
import streamlit as st
from datetime import datetime
from google_sheets_client import read_config, append_bet

st.set_page_config(page_title="試合とベット", page_icon="🎯", layout="wide")

def require_login():
    if not st.session_state.get("is_authenticated"):
        st.switch_page("app.py")

def navbar():
    left, mid, right = st.columns([1,6,2])
    with left:
        st.page_link("app.py", label="🏠 トップ")
    with mid:
        st.page_link("pages/02_Bets.py", label="🎯 試合とベット")
        st.page_link("pages/03_History.py", label="🪵 履歴")
        st.page_link("pages/04_Realtime.py", label="⏱ リアルタイム")
        st.page_link("pages/05_Rules.py", label="📘 ルール")
        if st.session_state.get("role") == "admin":
            st.page_link("pages/01_Settings.py", label="⚙️ 設定")
    with right:
        if st.button("ログアウト"):
            for k in ["is_authenticated","user_name","role"]:
                st.session_state.pop(k, None)
            st.switch_page("app.py")

def page():
    require_login()
    navbar()
    st.markdown("## 試合とベット")

    conf = read_config()
    user = st.session_state.get("user_name","")
    # 設定: 現在GW, ブックメーカー、上限、ロック
    gw = conf.get("CURRENT_GW", "GW?")
    bookmaker = conf.get("BOOKMAKER", "")          # 例) "Tetsu"
    max_stake = int(conf.get("MAX_STAKE","5000") or 0)
    lock_txt  = conf.get("LOCK_AT_UTC","")         # "YYYY-MM-DD HH:MM"
    is_locked = False
    if lock_txt:
        try:
            # UTC前提
            lock_dt = datetime.fromisoformat(lock_txt.replace("Z",""))
            is_locked = datetime.utcnow() >= lock_dt
        except Exception:
            pass

    # ブクメはベット不可
    if user and bookmaker and (user.lower() == bookmaker.lower()):
        st.warning(f"{gw} はブックメーカー（{bookmaker}）のため、ベッティングできません。")
        st.stop()

    if is_locked:
        st.error(f"{gw} はロックされました（LOCK_AT_UTC={lock_txt}）。閲覧のみ可能です。")

    # ここではまず「手入力」UI（API連携は後で差し替え）
    st.caption("※デモ：対戦カードとオッズは一旦手入力。API接続は後で差し替えます。")
    with st.form("bet_form"):
        match = st.text_input("対戦カード（例: Arsenal vs Spurs）")
        bet_team = st.selectbox("賭け先", ["Home","Away","Draw"])
        stake = st.number_input("掛金（100円単位）", min_value=0, step=100, value=100)
        odds  = st.number_input("オッズ（例: 1.90）", min_value=0.0, step=0.01, value=1.90, format="%.2f")
        submitted = st.form_submit_button("保存する", disabled=is_locked)

    if submitted:
        if stake > max_stake:
            st.error(f"掛金が上限({max_stake})を超えています。")
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [gw, match, user, bet_team, stake, odds, ts]
        try:
            append_bet(row)
            st.success("保存しました。")
        except Exception as e:
            st.exception(e)

if __name__ == "__main__":
    page()
