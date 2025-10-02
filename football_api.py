# repo-root/football_api.py
from __future__ import annotations
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st

API_BASE = "https://api.football-data.org/v4"
JST = ZoneInfo("Asia/Tokyo")


def _get_headers() -> dict:
    """Secrets から安全にトークンを読む（未設定なら分かりやすく止める）"""
    token = st.secrets.get("FOOTBALL_DATA_API_TOKEN")
    if not token:
        # ここで KeyError を起こさず、アプリ側で例外表示できるようにする
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が Secrets にありません。Settings → Secrets に追加して保存してください。")
    return {"X-Auth-Token": token}


def _iso_utc_to_jst_string(iso_utc: str) -> str:
    """'2025-10-02T11:30:00Z' → '2025-10-02 Thu 20:30 JST'"""
    dt_utc = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    dt_jst = dt_utc.astimezone(JST)
    return dt_jst.strftime("%Y-%m-%d %a %H:%M JST")


@st.cache_data(ttl=900)  # 15分キャッシュで無料枠を節約
def get_pl_fixtures_next_days(days: int = 10) -> list[dict]:
    """
    プレミアリーグの『今からdays日先まで』のSCHEDULED試合を取得。
    返り値: [{kickoff_jst, homeTeam, awayTeam, matchday, id}, ...]
    """
    today = datetime.now(timezone.utc).date()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=days)).isoformat()

    params = {
        "competitions": "PL",
        "status": "SCHEDULED",
        "dateFrom": date_from,
        "dateTo": date_to,
    }
    url = f"{API_BASE}/matches"
    headers = _get_headers()  # ← ここで初めてSecrets参照
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    fixtures = []
    for m in data.get("matches", []):
        fixtures.append(
            {
                "id": m["id"],
                "matchday": m.get("matchday"),
                "kickoff_jst": _iso_utc_to_jst_string(m["utcDate"]),
                "homeTeam": m["homeTeam"]["name"],
                "awayTeam": m["awayTeam"]["name"],
            }
        )
    fixtures.sort(key=lambda x: x["kickoff_jst"])
    return fixtures
