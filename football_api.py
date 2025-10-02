# repo-root/football_api.py

from __future__ import annotations
import os
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st

API_BASE = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": st.secrets["FOOTBALL_DATA_API_TOKEN"]}

JST = ZoneInfo("Asia/Tokyo")


def _iso_utc_to_jst_string(iso_utc: str) -> str:
    """'2025-10-02T11:30:00Z' → '2025-10-02 Thu 20:30 JST' のような表示に変換"""
    dt_utc = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    dt_jst = dt_utc.astimezone(JST)
    return dt_jst.strftime("%Y-%m-%d %a %H:%M JST")


@st.cache_data(ttl=900)  # 15分キャッシュで無料枠の呼び出し回数を節約
def get_pl_fixtures_next_days(days: int = 10) -> list[dict]:
    """
    プレミアリーグ(PL)の「今からdays日先まで」のSCHEDULED試合を取得。
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
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()  # freeプランでもこのエンドポイントは使えます

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
    # キックオフ昇順
    fixtures.sort(key=lambda x: x["kickoff_jst"])
    return fixtures
