
# pages/01_Settings.py
import streamlit as st
import pandas as pd
from google_sheets_client import read_config

st.set_page_config(page_title="設定", page_icon="⚙️", layout="wide")

def require_admin():
    if not (st.session_state.get("is_authenticated") and st.session_state.get("role")=="admin"):
        st.switch_page("app.py")

def page():
    require_admin()
    st.page_link("app.py", label="🏠 トップ")
    st.markdown("## 設定（閲覧用）")

    conf = read_config()
    if not conf:
        st.warning("config シートが空です。")
        return

    df = pd.DataFrame([{"key":k, "value":v} for k,v in conf.items()])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.caption("""
**主なキー**
- `USER_LIST` … 例: `Tetsu:admin, Gotaro, Guest`
- `LOGIN_PIN` … 管理者ログイン用PIN（空ならPIN不要）
- `CURRENT_GW` … 例: `GW7`
- `BOOKMAKER` … 例: `Tetsu`
- `MAX_STAKE` … 例: `5000`
- `LOCK_AT_UTC` … 例: `2025-10-05 03:00`（UTC）
""")

if __name__ == "__main__":
    page()
