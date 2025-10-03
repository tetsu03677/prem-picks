import streamlit as st
from google_sheets_client import read_config
from football_api import fetch_fixtures_fd, simplify_matches

def main():
    st.title("🧪 API 接続チェック（football-data.org）")
    conf = read_config()
    days = st.slider("何日先までチェックするか", 3, 21, 14)
    try:
        raw = fetch_fixtures_fd(conf, days)
        matches = simplify_matches(raw)
        st.success(f"{len(matches)} 試合を取得しました。")
        for m in matches[:10]:
            st.write(m["matchday"], m["home"], "vs", m["away"], m["utc"])
    except Exception as e:
        st.error(f"{e}")

if __name__ == "__main__":
    main()
