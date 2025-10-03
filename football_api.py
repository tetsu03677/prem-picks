# football_api.py
# -*- coding: utf-8 -*-

import requests
from datetime import datetime, timedelta, timezone
import pytz
import streamlit as st

# -----------------------------------------------------
# football-data.org APIから次節の試合を取得
# -----------------------------------------------------
def get_upcoming(conf, days=7):
    """
    次節の試合データを取得する
    - conf: config dict
    - days: 何日先まで取得するか
    戻り値: (matches, gw)
    """
    token = conf.get("FOOTBALL_DATA_API_TOKEN")
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")  # Premier League ID
    season = conf.get("API_FOOTBALL_SEASON", "2025")

    headers = {"X-Auth-Token": token}
    base = "https://api.football-data.org/v4/competitions"
    date_from = datetime.utcnow().strftime("%Y-%m-%d")
    date_to = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")

    url = f"{base}/{comp}/matches?season={season}&dateFrom={date_from}&dateTo={date_to}&status=SCHEDULED"

    r = requests.get(url, headers=headers)
    r.raise_for_status()
    data = r.json()

    matches = []
    gw = None
    tz = pytz.timezone(conf.get("timezone", "Asia/Tokyo"))

    for m in data.get("matches", []):
        mid = str(m["id"])
        gw = m.get("season", {}).get("currentMatchday") or f"GW{m.get('matchday')}"
        utc_kickoff = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        local_kickoff = utc_kickoff.astimezone(tz)
        matches.append({
            "id": mid,
            "gw": gw,
            "utc_kickoff": utc_kickoff,
            "local_kickoff": local_kickoff,
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "status": m["status"]
        })

    return matches, gw
