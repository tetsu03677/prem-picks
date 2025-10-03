import streamlit as st

def render():
    st.header("⏱ リアルタイム")
    st.caption("更新ボタンで都度取得（自動更新なし）を後続で実装します。")
    if st.button("更新"):
        st.success("ダミー更新（後でAPI連携に差し替え）")
