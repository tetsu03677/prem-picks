# football_api.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta, timezone
import requests
import pytz

def get_upcoming(conf: Dict[str, Any], days: int = 7) -> Tuple[List[Dict[str, Any]], str]:
    token = conf["FOOTBALL_DATA_API_TOKEN"]
    competition = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    tz = pytz.timezone(conf.get("timezone", "Asia/Tokyo"))

    today = datetime.utcnow().date()
    date_from = today.strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=days)).strftime("%Y-%m-%d")

    url = (f"https://api.football-data.org/v4/competitions/{competition}/matches"
           f"?season={season}&dateFrom={date_from}&dateTo={date_to}&status=SCHEDULED")
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
            "status": m.get("status",""),
        })
    if gw is None:
        gw = conf.get("current_gw", "GW?")
    return matches, gw
