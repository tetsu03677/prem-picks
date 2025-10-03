from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import os
import requests
import streamlit as st

BASE = "https://api.football-data.org/v4"

def _token() -> str:
    # config から読む（app.py 側で read_config 済みならそちらを渡して使ってもOK）
    from google_sheets_client import read_config
    conf = read_config()
    tok = conf.get("FOOTBALL_DATA_API_TOKEN") or conf.get("FOOTBALL_DATA_API_KEY") or ""
    return tok.strip()

def _headers():
    return {"X-Auth-Token": _token()}

def fetch_matches_window(days: int, competition_id: str, season: str) -> Tuple[List[Dict], str]:
    """
    football-data v4 /matches を competitions=ID で叩く（これが 404 を避ける安定形）
    """
    today = datetime.utcnow().date()
    date_from = today
    date_to = today + timedelta(days=days)

    params = {
        "dateFrom": date_from.isoformat(),
        "dateTo": date_to.isoformat(),
        "competitions": str(competition_id),
        "status": "SCHEDULED",
        "season": str(season)
    }
    url = f"{BASE}/matches"
    r = requests.get(url, headers=_headers(), params=params, timeout=20)
    r.raise_for_status()
    js = r.json()
    matches = js.get("matches", [])

    # 必要情報だけ整形
    out = []
    for m in matches:
        mid = str(m.get("id"))
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        utc = m.get("utcDate")
        out.append({
            "match_id": mid,
            "utcDate": utc,
            "home": home,
            "away": away,
            "gw": ""  # GW 表示は app 側で current_gw を使う
        })

    debug = f"{url}?dateFrom={params['dateFrom']}&dateTo={params['dateTo']}&competitions={competition_id}&status=SCHEDULED&season={season}"
    return out, debug
