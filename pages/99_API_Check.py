import time
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

from google_sheets_client import read_config


def _tz_aware_range(days: int, tz_name: str) -> tuple[str, str]:
    # RapidAPI(API-FOOTBALL)はISO8601文字列の from/to を受け付ける
    # 例: "2025-10-03", "2025-10-17"
    # タイムゾーンは日付だけ渡すので実質影響なし（見やすさのため保持）
    now = datetime.now(timezone.utc)
    start = (now).date().isoformat()
    end = (now + timedelta(days=days)).date().isoformat()
    return start, end


def _api_call(path: str, params: dict, key: str) -> dict:
    url = f"https://api-football-v1.p.rapidapi.com/v3/{path}"
    headers = {
        "x-rapidapi-key": key,
        "x-rapidapi-host": "api-football.p.rapidapi.com",
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    st.set_page_config(page_title="API接続チェック", page_icon="🧪", layout="wide")
    st.title("🧪 API 接続チェック（RapidAPI / API-FOOTBALL）")

    conf = read_config()
    key = conf.get("RAPIDAPI_KEY", "")
    league = int(conf.get("API_FOOTBALL_LEAGUE_ID", "39"))
    season = int(conf.get("API_FOOTBALL_SEASON", "2025"))
    bookmaker = int(conf.get("ODDS_BOOKMAKER_ID", "8"))     # bet365
    bet_market = int(conf.get("ODDS_MARKET", "1"))          # 1 = 1X2
    tz_name = conf.get("timezone", "Asia/Tokyo")

    if not key:
        st.error("RAPIDAPI_KEY が config シートにありません。")
        return

    col1, col2 = st.columns(2)
    with col1:
        days = st.slider("何日先までチェックするか", 3, 21, 14, help="from/to で直近期間を指定して叩きます")
    with col2:
        if st.button("▶ 接続テストを実行", use_container_width=True):
            with st.spinner("APIに接続しています…"):
                try:
                    # 期間レンジ
                    date_from, date_to = _tz_aware_range(days, tz_name)

                    # --- Fixtures（試合予定） ---
                    fx_params = dict(
                        league=league,
                        season=season,
                        _from=date_from,
                        to=date_to,
                        timezone=tz_name,
                    )
                    fixtures = _api_call("fixtures", fx_params, key)
                    fx_list = fixtures.get("response", [])

                    st.success(f"Fixtures OK: {len(fx_list)} 試合取得")
                    if not fx_list:
                        st.info("期間内に取得できる試合がありませんでした。リーグ/シーズン/日付範囲を見直してください。")

                    # サンプル1件
                    sample_fx = None
                    for f in fx_list:
                        # Not Started中心に1件
                        if f.get("fixture", {}).get("status", {}).get("short") in ("NS", "TBD"):
                            sample_fx = f
                            break
                    if not sample_fx and fx_list:
                        sample_fx = fx_list[0]

                    if sample_fx:
                        fid = sample_fx["fixture"]["id"]
                        card = f"{sample_fx['teams']['home']['name']} vs {sample_fx['teams']['away']['name']}"
                        kickoff = sample_fx["fixture"]["date"]
                        st.write(f"例: fixture_id={fid} / {card} / kick-off={kickoff}")

                    # --- Odds（1X2 / bet365） ---
                    # 注意: オッズは近い試合しか入らないことがあります。league/season/bookmaker/bet+期間で取得。
                    od_params = dict(
                        league=league,
                        season=season,
                        bookmaker=bookmaker,
                        bet=bet_market,
                        _from=date_from,
                        to=date_to,
                    )
                    odds = _api_call("odds", od_params, key)
                    od_list = odds.get("response", [])

                    # 件数
                    st.success(f"Odds OK: {len(od_list)} 試合分のオッズ候補")

                    # サンプル表示（fixture.id一致を探す）
                    if sample_fx:
                        fid = sample_fx["fixture"]["id"]
                        match_odds = None
                        for item in od_list:
                            if item.get("fixture", {}).get("id") == fid:
                                match_odds = item
                                break
                        if match_odds:
                            # 1X2（Home/Draw/Away）抽出
                            try:
                                bm = match_odds["bookmakers"][0]
                                bet = next(b for b in bm["bets"] if int(b["id"]) == bet_market or b["name"] == "Match Winner")
                                values = {v["value"]: v["odd"] for v in bet["values"]}
                                st.write("この試合のオッズ（bet365 / 1X2）: ", values)
                            except Exception:
                                st.info("取得できたが、1X2 の値の展開に失敗（レスポンス形状が想定外）。")
                        else:
                            st.info("期間・条件内にサンプル試合のオッズが見つかりませんでした（オッズは直前にしか出ないことがあります）。")

                    st.balloons()
                except requests.HTTPError as e:
                    st.error(f"HTTPError: {e.response.status_code} {e.response.text[:240]}")
                except Exception as e:
                    st.exception(e)

    st.caption("※ このページは接続確認用の一時ページです。通ったら削除してOK。")
    

if __name__ == "__main__":
    main()
