# football_api.py  --- football-data.org からPLの直近試合を取得（JST変換つき）
from __future__ import annotations
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st

BASE = "https://api.football-data.org/v4"

def _headers() -> dict:
    token = st.secrets.get("FOOTBALL_DATA_API_TOKEN")
    if not token:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が Secrets にありません。")
    return {"X-Auth-Token": token}

def get_pl_fixtures_next_days(days_ahead: int = 7) -> list[dict]:
    """今日から days_ahead 日先までのPLのSCHEDULED試合を返す（JST整形済み）。"""
    today = datetime.now(timezone.utc).date()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()

    url = f"{BASE}/competitions/PL/matches"
    params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
    r = requests.get(url, headers=_headers(), params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    fixtures = []
    for m in data.get("matches", []):
        # UTC -> JST（表示用）
        utc_raw = m.get("utcDate")  # 例: "2025-10-04T16:30:00Z"
        if not utc_raw:
            continue
        dt_utc = datetime.fromisoformat(utc_raw.replace("Z", "+00:00"))
        dt_jst = dt_utc.astimezone(ZoneInfo("Asia/Tokyo"))

        fixtures.append({
            "id": m.get("id"),
            "matchday": m.get("matchday"),
            "kickoff_jst": dt_jst.strftime("%Y-%m-%d %H:%M"),
            "home": (m.get("homeTeam") or {}).get("name"),
            "away": (m.get("awayTeam") or {}).get("name"),
            "stage": m.get("stage"),
        })

    # キックオフ順にソート
    fixtures.sort(key=lambda x: x["kickoff_jst"])
    return fixtures
