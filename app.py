# app.py
import streamlit as st
from datetime import datetime, timezone
from google_sheets_client import read_config

st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

# ===== 共通: ログイン保護 & ナビ =====
def require_login():
    if not st.session_state.get("is_authenticated"):
        show_login()
        st.stop()

def navbar():
    left, mid, right = st.columns([1,6,2])
    with left:
        st.markdown("### Premier Picks")
    with mid:
        st.page_link("app.py", label="🏠 トップ", icon=None)
        st.page_link("pages/02_Bets.py", label="🎯 試合とベット")
        st.page_link("pages/03_History.py", label="🪵 履歴")
        st.page_link("pages/04_Realtime.py", label="⏱ リアルタイム")
        st.page_link("pages/05_Rules.py", label="📘 ルール")
        # 管理者のみ
        if st.session_state.get("role") == "admin":
            st.page_link("pages/01_Settings.py", label="⚙️ 設定")
    with right:
        if st.session_state.get("is_authenticated"):
            st.caption(f"👤 {st.session_state.get('user_name', 'User')}")
            if st.button("ログアウト", key="logout_btn"):
                for k in ["is_authenticated","user_name","role"]:
                    st.session_state.pop(k, None)
                st.rerun()

# ===== ログイン画面 =====
def show_login():
    st.markdown("## Premier Picks")
    st.write("ログインしてください。")
    conf = read_config()

    # USER_LIST: 例) "Tetsu,Gotaro,Guest"
    users_csv = conf.get("USER_LIST", "").strip()
    users = [u.strip() for u in users_csv.split(",") if u.strip()] or ["Guest"]

    pin_required = conf.get("LOGIN_PIN", "").strip() != ""
    role_map = {u.split(":")[0]: (u.split(":")[1] if ":" in u else "") for u in users}  # "tetsu:admin"にも対応

    with st.form("login_form", clear_on_submit=False):
        user = st.selectbox("ユーザー", users, index=0)
        pin = st.text_input("PIN（管理者のみ）", type="password") if pin_required else ""
        submitted = st.form_submit_button("ログイン", use_container_width=True)

    if submitted:
        ok = True
        if pin_required and role_map.get(user,"") == "admin":
            ok = (pin == conf.get("LOGIN_PIN",""))
        if ok:
            st.session_state.is_authenticated = True
            st.session_state.user_name = user.split(":")[0]
            st.session_state.role = role_map.get(user, "")  # "admin" or ""
            st.success("ログインしました。")
            st.rerun()
        else:
            st.error("認証失敗：PINが違います。")

# ===== トップ（ダッシュボードの雛形） =====
def dashboard():
    require_login()
    navbar()

    st.markdown("## ダッシュボード")
    st.caption("まずは雛形。KPIや残高などは後で実装します。")

    # 参考情報：ロック時刻（任意）
    conf = read_config()
    lock_txt = conf.get("LOCK_AT_UTC","")
    if lock_txt:
        st.info(f"現在のロック時刻（UTC）: {lock_txt}")

# ===== エントリーポイント =====
if __name__ == "__main__":
    if st.session_state.get("is_authenticated"):
        dashboard()
    else:
        show_login()
