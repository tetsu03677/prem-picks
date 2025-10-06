# football_api.py
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

import requests
import pytz
import streamlit as st

BASE = "https://api.football-data.org/v4"

def _headers(conf: Dict[str, str]) -> Dict[str, str]:
    # APIトークンは config シートの "FOOTBALL_DATA_API_TOKEN"
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "").strip()
    return {"X-Auth-Token": token} if token else {}

def _league_and_season(conf: Dict[str, str]) -> Tuple[str, str]:
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")  # EPL=2021
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    return comp, season

def _localize(dt_utc: datetime, tzname: str) -> datetime:
    tz = pytz.timezone(tzname or "UTC")
    return dt_utc.astimezone(tz)

def _safe_get(url, headers, params):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 403:
            # レート / 403 は呼び出し側で UI アラートするため、空で返す
            return None
        r.raise_for_status()
        return r
    except Exception:
        return None

def fetch_matches_window(day_window: int, comp: str, season: str, conf: Dict[str, str]) -> Tuple[List[Dict], str]:
    """今日から day_window 日の試合（EPL のみ）"""
    today_utc = datetime.now(timezone.utc)
    to_utc = today_utc + timedelta(days=day_window)
    params = {
        "competitions": comp,
        "dateFrom": today_utc.date().isoformat(),
        "dateTo": to_utc.date().isoformat(),
        "season": season,
    }
    url = f"{BASE}/matches"
    r = _safe_get(url, _headers(conf), params)
    if not r:
        return [], ""

    data = r.json()
    items = data.get("matches", [])
    tzname = conf.get("timezone", "UTC")
    rows = []
    gw_name = ""
    for m in items:
        utc = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        rows.append({
            "id": m["id"],
            "utc_kickoff": utc,
            "local_kickoff": _localize(utc, tzname),
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "status": m.get("status", "TIMED"),
        })
        gw_name = f"GW{m.get('matchday','')}" if m.get("matchday") else conf.get("current_gw", "")
    return rows, gw_name or conf.get("current_gw", "")

@st.cache_data(ttl=60)
def fetch_matches_next_gw(conf: Dict[str, str], day_window: int = 7) -> Tuple[List[Dict], str]:
    comp, season = _league_and_season(conf)
    rows, gw = fetch_matches_window(day_window, comp, season, conf)
    # GW を付与
    for r in rows:
        r["gw"] = gw
    return rows, gw

def fetch_scores_for_match_ids(conf: Dict[str, str], match_ids: List[str]) -> Dict[str, Dict]:
    """指定 match_id 群のスコア（LIVE/FINISHED含む）。403 等は空 dict を返す。"""
    out = {}
    for mid in match_ids:
        url = f"{BASE}/matches/{mid}"
        r = _safe_get(url, _headers(conf), params={})
        if not r:
            continue
        j = r.json().get("match", {})
        score = j.get("score", {})
        full = score.get("fullTime", {}) or {}
        live_home = full.get("home", 0)
        live_away = full.get("away", 0)
        status = j.get("status", "TIMED")
        out[str(mid)] = {
            "status": status,
            "home": j.get("homeTeam", {}).get("name", ""),
            "away": j.get("awayTeam", {}).get("name", ""),
            "home_score": live_home,
            "away_score": live_away,
        }
    return out
