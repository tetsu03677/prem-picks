# pages/05_Rules.py
import streamlit as st

st.set_page_config(page_title="ルール", page_icon="📘", layout="wide")

def require_login():
    if not st.session_state.get("is_authenticated"):
        st.switch_page("app.py")

def page():
    require_login()
    st.page_link("app.py", label="🏠 トップ")
    st.markdown("## ルール")
    st.markdown("""
- 掛金は100円単位、上限は `config` の **MAX_STAKE**。
- ブックメーカー（`BOOKMAKER`）の人はその節はベット不可。
- ロック時刻（`LOCK_AT_UTC`）を過ぎると編集不可。
- ユーザー・PINは `config` の **USER_LIST**（例: `Tetsu:admin, Gotaro, Guest`）と **LOGIN_PIN** を使用。
    """)

if __name__ == "__main__":
    page()
