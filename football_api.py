from __future__ import annotations
from typing import Tuple, List, Dict, Any
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

BASE = "https://api.football-data.org/v4"
_API_ERR: str | None = None  # 直近のHTTPエラーメッセージ保存

def last_api_error() -> str | None:
    return _API_ERR

@st.cache_data(ttl=120, show_spinner=False)
def _fetch(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """HTTP取得（キャッシュ付き）。失敗は例外を投げず空データを返す。"""
    global _API_ERR
    _API_ERR = None
    headers = {}
    # token キー名は大小どちらでも許容
    if "FOOTBALL_DATA_API_TOKEN" in st.secrets:
        headers["X-Auth-Token"] = st.secrets["FOOTBALL_DATA_API_TOKEN"]
    elif "football_data_api_token" in st.secrets:
        headers["X-Auth-Token"] = st.secrets["football_data_api_token"]

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        # 明示的にステータス処理
        if r.status_code >= 400:
            _API_ERR = f"HTTP {r.status_code}"
            return {}
        return r.json()
    except requests.RequestException as e:
        _API_ERR = f"{e.__class__.__name__}"
        return {}

def fetch_matches_window(day_window: int, competition: str, season: str) -> Tuple[List[Dict[str, Any]], str]:
    start = datetime.utcnow().date()
    end = (datetime.utcnow() + timedelta(days=day_window)).date()
    url = f"{BASE}/competitions/{competition}/matches"
    params = {
        "season": season,
        "dateFrom": start.isoformat(),
        "dateTo": end.isoformat(),
        "status": "SCHEDULED,TIMED,IN_PLAY,PAUSED,FINISHED",
    }
    data = _fetch(url, params)
    rows = data.get("matches", []) if isinstance(data, dict) else []
    gw = ""
    for m in rows:
        md = m.get("matchday")
        if md:
            gw = f"GW{md}"
            break
    return rows, gw or "GW?"

def fetch_matches_next_gw(conf: Dict[str, str], day_window: int = 7) -> Tuple[List[Dict[str, Any]], str]:
    comp = conf.get("FOOTBALL_DATA_COMPETITION") or "2021"
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
    if hasattr(utc, "tz_convert"):
        local = utc.tz_convert(tzinfo)
    else:
        local = utc.tz_localize(timezone.utc).astimezone(tzinfo)
    return {
        "id": str(m.get("id")),
        "gw": f"GW{m.get('matchday','')}" if m.get("matchday") else "GW?",
        "utc_kickoff": utc.to_pydatetime(),
        "local_kickoff": local.to_pydatetime(),
        "home": m.get("homeTeam", {}).get("name", ""),
        "away": m.get("awayTeam", {}).get("name", ""),
        "status": m.get("status", ""),
    }

def calc_gw_lock_threshold(matches_raw: List[Dict[str, Any]], minutes_before: int) -> datetime | None:
    if not matches_raw:
        return None
    kickoffs = [pd.to_datetime(m["utcDate"]).to_pydatetime().replace(tzinfo=timezone.utc) for m in matches_raw]
    earliest = min(kickoffs)
    return earliest - timedelta(minutes=int(minutes_before))
