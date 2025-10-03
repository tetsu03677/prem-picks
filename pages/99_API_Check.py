import streamlit as st
from google_sheets_client import read_config
from football_api import fetch_matches_next_window, simplify_matches

st.set_page_config(page_title="API 接続チェック", page_icon="🧪", layout="wide")

def main():
    conf = read_config()
    st.title("🧪 API 接続チェック（football-data.org）")

    token = conf.get("FOOTBALL_DATA_API_TOKEN","")
    comp = conf.get("FOOTBALL_DATA_COMPETITION","PL")
    season = conf.get("API_FOOTBALL_SEASON","2025")

    if st.button("接続テストを実行"):
        try:
            raw, _ = fetch_matches_next_window(7, comp, season, token)
            sims = simplify_matches(raw, conf.get("timezone","Asia/Tokyo"))
            st.success(f"取得件数: {len(sims)}")
            for m in sims[:10]:
                st.write(m)
        except Exception as e:
            st.exception(e)

if __name__ == "__main__":
    main()
