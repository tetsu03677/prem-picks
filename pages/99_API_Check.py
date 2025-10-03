import streamlit as st
from football_api import fetch_matches_window
from google_sheets_client import read_config

st.set_page_config(page_title="API 接続チェック（football-data.org）", page_icon="🧪")

def main():
    conf = read_config()
    days = st.slider("何日先までチェックするか", 3, 21, 10)
    token = conf.get("FOOTBALL_DATA_API_TOKEN")
    comp  = conf.get("FOOTBALL_DATA_COMPETITION", "PL")
    season = str(conf.get("API_FOOTBALL_SEASON", "2025"))
    tz = conf.get("timezone", "Asia/Tokyo")

    try:
        matches, gw = fetch_matches_window(days, str(comp), season, token, tz)
        st.success(f"取得件数: {len(matches)}")
        st.json(matches)
    except Exception as e:
        st.exception(e)

if __name__ == "__main__":
    main()
