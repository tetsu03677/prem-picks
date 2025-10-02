# /football_api.py
import os
import requests
import streamlit as st
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

def _get_api_token() -> str:
    # Secrets → 環境変数の順で取得（見つからなければ空文字）
    token = st.secrets.get("FOOTBALL_DATA_API_TOKEN") or os.environ.get("FOOTBALL_DATA_API_TOKEN", "")
    return token.strip()

def get_pl_fixtures_next_days(days: int = 7):
    """
    football-data.org から、今日を含む days 日先までのプレミアリーグ日程を取得して返す。
    トークン未設定時は (False, エラーメッセージ) を返す。
    """
    token = _get_api_token()
    if not token:
        return False, "FOOTBALL_DATA_API_TOKEN が Secrets にありません。Settings→Secrets に追加して保存してください。"

    headers = {"X-Auth-Token": token}
    base = "https://api.football-data.org/v4/matches"

    date_from = datetime.now(JST).date().isoformat()
    date_to = (datetime.now(JST).date() + timedelta(days=days)).isoformat()

    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "competitions": "PL",  # Premier League
        "status": "SCHEDULED"
    }

    try:
        r = requests.get(base, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        matches = []
        for m in data.get("matches", []):
            utc = m.get("utcDate")
            dt = datetime.fromisoformat(utc.replace("Z","+00:00")).astimezone(JST) if utc else None
            home = m.get("homeTeam", {}).get("name")
            away = m.get("awayTeam", {}).get("name")
            comp = m.get("competition", {}).get("code")
            matches.append({
                "kickoff_jst": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
                "home": home, "away": away, "competition": comp
            })
        return True, matches
    except requests.HTTPError as e:
        # トークン不正などのときは本文も返す
        try:
            body = r.json()
        except Exception:
            body = r.text
        return False, f"HTTP {r.status_code}: {body}"
    except Exception as e:
        return False, f"取得エラー: {e}"
