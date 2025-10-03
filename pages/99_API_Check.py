# pages/99_API_Check.py
# RapidAPI / API-FOOTBALL への疎通確認ページ
from __future__ import annotations
import streamlit as st

from google_sheets_client import read_config
from football_api import (
    get_fixtures_next_days,
    get_fixtures_by_league_and_season,
    get_odds_for_fixture,
)

st.set_page_config(page_title="API 接続チェック", page_icon="🧪", layout="wide")


def _pill(text: str, color: str = "gray"):
    st.markdown(
        f"""
        <span style="
            display:inline-block;padding:3px 8px;border-radius:999px;
            background:{color};color:white;font-size:12px;">
            {text}
        </span>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.markdown("## 🧪 API 接続チェック（RapidAPI / API-FOOTBALL） ↪︎")

    days = st.slider("何日先までチェックするか", 3, 21, 14)
    if st.button("▶︎ 接続テストを実行", use_container_width=True):
        try:
            conf = read_config()

            # 設定の概要
            c1, c2, c3, c4 = st.columns(4)
            c1.write(f"**League ID**: {conf.get('API_FOOTBALL_LEAGUE_ID', '39')}")
            c2.write(f"**Season**: {conf.get('API_FOOTBALL_SEASON', '2025')}")
            c3.write(f"**Bookmaker**: {conf.get('bookmaker_username', 'Bet365')}")
            c4.write(f"**ODDS_MARKET**: {conf.get('ODDS_MARKET', '1')} (1=1X2)")

            st.divider()

            # 1) Fixtures（リーグ＋シーズンで & 日付絞り）
            st.caption("Fixtures を取得中…")
            fixtures = get_fixtures_next_days(days=days)
            total = len(fixtures)
            if total == 0:
                _pill("0 fixtures", "#d9534f")
                st.warning("この期間では試合が見つかりませんでした。日付範囲やシーズンをご確認ください。")
                return

            _pill(f"{total} fixtures", "#5cb85c")
            with st.expander("サンプル（上位3件）", expanded=False):
                for fx in fixtures[:3]:
                    f = fx["fixture"]
                    t = fx["teams"]
                    st.write(
                        f"- **{t['home']['name']} vs {t['away']['name']}**  "
                        f"({f['date']})  / fixture_id={f['id']}"
                    )

            st.divider()

            # 2) 1つ目の fixture でオッズ取得
            target_id = fixtures[0]["fixture"]["id"]
            st.caption(f"fixture_id={target_id} の 1X2 オッズを取得中…")
            odds_json = get_odds_for_fixture(target_id)

            results = odds_json.get("results", 0)
            if results == 0:
                _pill("odds: 0", "#f0ad4e")
                st.info("この試合はまだオッズが配信されていない可能性があります。")
            else:
                _pill(f"odds: {results}", "#5bc0de")
                # 代表的な抜粋表示（1X2）
                with st.expander("オッズ JSON（抜粋）", expanded=False):
                    st.json(odds_json)

            st.success("✅ 接続テストは正常に完了しました。")
        except Exception as e:
            st.error(f"HTTPError: {e}")


if __name__ == "__main__":
    main()
