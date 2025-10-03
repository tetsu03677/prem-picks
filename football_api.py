# football_api.py
from __future__ import annotations
import os
import requests
from datetime import datetime, timedelta, timezone

TZ_UTC = timezone.utc
FD_BASE = "https://api.football-data.org/v4"

def _headers_fd(api_token: str):
    return {"X-Auth-Token": api_token}

def _iso_to_dt(s: str) -> datetime:
    # football-data は ISO8601（末尾Z）なので UTC として解釈
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ_UTC)

def fetch_next_round_fd(api_token: str, league_id: str | int, season: str | int):
    """
    次に来るラウンド（matchday=GW）をまとめて返す。
    - まず今から+30日までのSCHEDULEDを取得
    - 最も早い試合の matchday を次節とみなし、その matchday の試合を全部返す
    """
    url = f"{FD_BASE}/competitions/{league_id}/matches"
    # 余裕をもって30日先まで取得してから「次のGW」を切り出す
    today = datetime.now(TZ_UTC).date()
    params = {
        "season": str(season),
        "dateFrom": today.isoformat(),
        "dateTo": (today + timedelta(days=30)).isoformat(),
        "status": "SCHEDULED",
    }
    r = requests.get(url, headers=_headers_fd(api_token), params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    matches = data.get("matches", [])
    if not matches:
        return {"fixtures": [], "earliest_utc": None, "matchday": None}

    # 一番早い試合を探す
    matches_sorted = sorted(matches, key=lambda m: _iso_to_dt(m["utcDate"]))
    first = matches_sorted[0]
    next_md = first.get("matchday") or first.get("season", {}).get("currentMatchday")
    # 同じ matchday の試合をまとめる
    gw_fixtures = [m for m in matches_sorted if m.get("matchday") == next_md]

    fixtures = []
    for m in gw_fixtures:
        fixtures.append({
            "match_id": m["id"],
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "utc": _iso_to_dt(m["utcDate"]).isoformat(),
            "matchday": m.get("matchday"),
        })

    return {
        "fixtures": fixtures,
        "earliest_utc": _iso_to_dt(first["utcDate"]),
        "matchday": next_md,
    }
