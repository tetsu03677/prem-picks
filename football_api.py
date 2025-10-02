from __future__ import annotations
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google_sheets_client import get_config_value

API_BASE = "https://api.football-data.org/v4"
JST = ZoneInfo("Asia/Tokyo")

def _api_token() -> str:
    token = get_config_value("FOOTBALL_DATA_API_TOKEN")
    if not token:
        raise RuntimeError("APIトークンがconfigシートにありません（FOOTBALL_DATA_API_TOKEN）。")
    return token

def get_pl_fixtures_next_days(days: int = 7) -> list[dict]:
    token = _api_token()
    date_from = datetime.now(JST).date().isoformat()
    date_to   = (datetime.now(JST) + timedelta(days=days)).date().isoformat()
    url = f"{API_BASE}/competitions/PL/matches"
    params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
    headers = {"X-Auth-Token": token}

    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    out = []
    for m in data.get("matches", []):
        utc = m.get("utcDate")
        ko_jst = None
        if utc:
            ko_jst = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(JST)
        out.append({
            "matchday": m.get("matchday"),
            "id": m.get("id"),
            "home": (m.get("homeTeam") or {}).get("name"),
            "away": (m.get("awayTeam") or {}).get("name"),
            "kickoff_jst": ko_jst.strftime("%Y-%m-%d %H:%M") if ko_jst else "",
        })
    return out
