# football_api.py
from datetime import datetime, timedelta, timezone
import requests
import streamlit as st

BASE = "https://api.football-data.org/v4"

def _headers():
    return {"X-Auth-Token": st.secrets["FOOTBALL_DATA_API_TOKEN"]}

def _to_match_row(m, gw_tag="GW?"):
    # v4の試合を内部形式へ
    mid = str(m["id"])
    status = m.get("status","SCHEDULED")
    utc = datetime.fromisoformat(m["utcDate"].replace("Z","+00:00")).astimezone(timezone.utc)
    home = m["homeTeam"]["name"]
    away = m["awayTeam"]["name"]
    return {"id": mid, "gw": gw_tag, "utc_kickoff": utc, "home": home, "away": away, "status": status}

def fetch_matches_window(day_window: int, competition: str, season: str, status=None):
    date_from = datetime.utcnow().date()
    date_to = date_from + timedelta(days=day_window)
    params = {"dateFrom": str(date_from), "dateTo": str(date_to), "competitions": competition}
    if status:
        params["status"] = status
    url = f"{BASE}/matches"
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    data = r.json().get("matches", [])
    # GW判定：最も近い週を仮にGWタグに
    gw = "GW?"
    rows = [_to_match_row(m, gw) for m in data]
    return rows, gw

def fetch_matches_next_gw(conf, day_window=7, accept_today=False, include_live=False):
    comp = conf.get("FOOTBALL_DATA_COMPETITION","PL")
    season = conf.get("API_FOOTBALL_SEASON","2025")
    rows, gw = fetch_matches_window(day_window, comp, season)
    if not rows:
        return [], gw
    # 今日より前は除外（accept_todayで当日含む）
    today = datetime.utcnow().date()
    rows = [r for r in rows if r["utc_kickoff"].date() > today or (accept_today and r["utc_kickoff"].date()==today)]
    if not include_live:
        return rows, gw
    # ライブ・終了試合も混ざる場合は status フィルタ不要（v4は自動で返す）
    return rows, gw
