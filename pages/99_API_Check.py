from __future__ import annotations
import streamlit as st
from datetime import datetime, timedelta, timezone
from google_sheets_client import read_config
from football_api import fixtures_by_date_range, simplify_match

def main():
    st.set_page_config(page_title="API接続チェック", page_icon="🧪", layout="wide")
    st.title("🧪 API 接続チェック（football-data.org）")

    conf = read_config()
    league = conf.get("API_FOOTBALL_LEAGUE_ID","39")
    season = conf.get("API_FOOTBALL_SEASON","2025")  # 表示用
    st.caption(f"League ID: {league} / Season: {season}")

    days = st.slider("何日先までチェックするか", 3, 21, 14)
    today = datetime.utcnow().date()
    date_from = today
    date_to   = today + timedelta(days=days)

    if st.button("▶ 接続テストを実行", use_container_width=True):
        with st.status("Fixtures を取得中…", expanded=True):
            try:
                matches = fixtures_by_date_range(conf, league, datetime.combine(date_from, datetime.min.time()), datetime.combine(date_to, datetime.min.time()))
                st.write(f"取得件数: **{len(matches)}**")
                if matches:
                    mini = [simplify_match(m) for m in matches[:10]]
                    st.dataframe(mini, use_container_width=True)
                st.success("OK: API 到達できました")
            except Exception as e:
                st.error(f"{type(e).__name__}: {e}")

    st.divider()
    st.caption("※このページは動作確認用。通ったら削除してOK。")

if __name__ == "__main__":
    main()
