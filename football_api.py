from __future__ import annotations
from typing import Tuple, List, Dict, Any
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
import streamlit as st

BASE = "https://api.football-data.org/v4"

def _headers():
    return {"X-Auth-Token": st.secrets["FOOTBALL_DATA_API_TOKEN"]} if "FOOTBALL_DATA_API_TOKEN" in st.secrets else \
           {"X-Auth-Token": st.secrets.get("football_data_api_token", "")}

def fetch_matches_window(day_window: int, competition: str, season: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    きっちり 7 日ウィンドウで SCHEDULED/TIMED/IN_PLAY/FINISHED を取得
    """
    start = datetime.utcnow().date()
    end = (datetime.utcnow() + timedelta(days=day_window)).date()
    url = f"{BASE}/competitions/{competition}/matches"
    params = {
        "season": season,
        "dateFrom": start.isoformat(),
        "dateTo": end.isoformat(),
        "status": "SCHEDULED,TIMED,IN_PLAY,PAUSED,FINISHED",
    }
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    rows = data.get("matches", [])
    # GW の候補（matchday / stage 等から）
    gw = ""
    for m in rows:
        md = m.get("matchday")
        if md:
            gw = f"GW{md}"
            break
    return rows, gw or "GW?"

def fetch_matches_next_gw(conf: Dict[str, str], day_window: int = 7) -> Tuple[List[Dict[str, Any]], str]:
    comp = conf.get("FOOTBALL_DATA_COMPETITION") or conf.get("FOOTBALL_DATA_COMPETITION".lower()) or conf.get("FOOTBALL_DATA_COMPETITION".upper()) or "2021"
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    return fetch_matches_window(day_window, comp, season)

def simplify_match_row(m: Dict[str, Any], conf: Dict[str, str]) -> Dict[str, Any]:
    tzname = conf.get("timezone", "Asia/Tokyo")
    try:
        from zoneinfo import ZoneInfo
        tzinfo = ZoneInfo(tzname)
    except Exception:
        tzinfo = timezone(timedelta(hours=9))
    utc = pd.to_datetime(m.get("utcDate"))
    local = utc.tz_convert(tzinfo) if hasattr(utc, "tz_convert") else utc.tz_localize(timezone.utc).astimezone(tzinfo)
    return {
        "id": str(m.get("id")),
        "gw": f"GW{m.get('matchday','')}" if m.get("matchday") else "GW?",
        "utc_kickoff": utc.to_pydatetime(),
        "local_kickoff": local.to_pydatetime(),
        "home": m.get("homeTeam", {}).get("name", ""),
        "away": m.get("awayTeam", {}).get("name", ""),
        "status": m.get("status", ""),
    }

def calc_gw_lock_threshold(matches_raw: List[Dict[str, Any]], minutes_before: int) -> datetime:
    if not matches_raw:
        return None
    kickoffs = [pd.to_datetime(m["utcDate"]).to_pydatetime().replace(tzinfo=timezone.utc) for m in matches_raw]
    earliest = min(kickoffs)
    return earliest - timedelta(minutes=int(minutes_before))
