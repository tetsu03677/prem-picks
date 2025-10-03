# football_api.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple
import requests
import pytz

def get_upcoming(conf: Dict[str, Any], days: int = 7) -> Tuple[List[Dict[str, Any]], str]:
    """
    football-data.org から 7日以内（デフォルト）の SCHEDULED 試合を取得
    返り値: (matches, gw)
      matches: [
        {"id","gw","utc_kickoff","local_kickoff","home","away","status"}
      ]
      gw: "GW7" など（取得した最初の試合の matchday で表現）
    """
    token = conf["FOOTBALL_DATA_API_TOKEN"]
    competition = conf.get("FOOTBALL_DATA_COMPETITION", "2021")  # PL
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    tz = pytz.timezone(conf.get("timezone", "Asia/Tokyo"))

    today = datetime.utcnow().date()
    date_from = today.strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=days)).strftime("%Y-%m-%d")

    url = (
        f"https://api.football-data.org/v4/competitions/{competition}/matches"
        f"?season={season}&dateFrom={date_from}&dateTo={date_to}&status=SCHEDULED"
    )
    headers = {"X-Auth-Token": token}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    matches: List[Dict[str, Any]] = []
    gw = None

    for m in data.get("matches", []):
        matchday = m.get("matchday")
        if gw is None and matchday:
            gw = f"GW{matchday}"
        utc_dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        local_dt = utc_dt.astimezone(tz)
        matches.append({
            "id": str(m["id"]),
            "gw": f"GW{matchday}" if matchday else (gw or conf.get("current_gw", "")),
            "utc_kickoff": utc_dt,
            "local_kickoff": local_dt,
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "status": m.get("status", ""),
        })
    # gw が取れなかった時のフォールバック
    if gw is None:
        gw = conf.get("current_gw", "GW?")
    return matches, gw
