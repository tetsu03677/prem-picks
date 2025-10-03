import json
import streamlit as st
from google_sheets_client import read_config, ws

def render():
    st.markdown("<div class='pp-header'>⚙️ 設定（管理者）</div>", unsafe_allow_html=True)
    user = st.session_state.get("user", {})
    if user.get("role") != "admin":
        st.error("権限がありません。")
        return

    conf = read_config()
    st.caption("config シート内容（読み取り）。編集が必要な値はスプレッドシートで直接更新してください。")
    view = {k:conf[k] for k in sorted(conf.keys())}
    st.json(view)

    st.divider()
    st.write("#### ユーザー一覧（users_json）")
    try:
        st.table(json.loads(conf.get("users_json","[]")))
    except Exception:
        st.warning("users_json が JSON として読み取れませんでした。")
