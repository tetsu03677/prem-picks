# /pages/99_API_Check.py
import streamlit as st
from football_api import fetch_matches_window, simplify_matches

st.set_page_config(page_title="API Check", page_icon="🧪", layout="wide")

st.title("API 接続テスト")
days = st.number_input("取得日数", min_value=1, max_value=30, value=7, step=1)
competition = st.text_input("competition", value="2021")  # Premier League
season = st.text_input("season", value="2025")

if st.button("テスト実行", use_container_width=True):
    try:
        with st.spinner("取得中..."):
            js, meta = fetch_matches_window(days, competition=competition, season=season)
            ms = simplify_matches(js)
        st.success("OK")
        st.caption(meta)
        st.write(f"試合数: {len(ms)}")
        for m in ms[:20]:
            st.write(m)
    except Exception as e:
        st.exception(e)
