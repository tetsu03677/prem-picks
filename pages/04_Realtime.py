# pages/04_Realtime.py
import streamlit as st

st.set_page_config(page_title="リアルタイム", page_icon="⏱", layout="wide")

def require_login():
    if not st.session_state.get("is_authenticated"):
        st.switch_page("app.py")

def page():
    require_login()
    st.page_link("app.py", label="🏠 トップ")
    st.markdown("## リアルタイム（雛形）")
    st.info("ここに試合のリアルタイムスコアと自分のベット照合を表示します。（API接続後に実装）")

if __name__ == "__main__":
    page()
