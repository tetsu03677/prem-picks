from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone
import pytz
import requests
import streamlit as st

FD_BASE = "https://api.football-data.org/v4"

def _tz(conf) -> pytz.BaseTzInfo:
    return pytz.timezone(conf.get("timezone","Asia/Tokyo"))

def _headers(conf) -> Dict[str,str]:
    return {"X-Auth-Token": conf["FOOTBALL_DATA_API_TOKEN"]}

def _gw_from_date(dt_utc: datetime, conf) -> str:
    # ここは football-data の GW 名が API上にないため、簡易に "GW{weeknum}" を採用
    # 実運用では config[current_gw] を優先表示
    return conf.get("current_gw","GW?")

def fetch_matches_window(days: int, competition: str, conf) -> Tuple[List[Dict[str,Any]], str]:
    """今日から days 日先までの試合を取得し、(試合配列, 表示対象GW) を返す"""
    tz = _tz(conf)
    now_local = datetime.now(tz)
    date_from = now_local.date().isoformat()
    date_to = (now_local + timedelta(days=days)).date().isoformat()
    url = f"{FD_BASE}/competitions/{competition}/matches"
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "season": conf.get("API_FOOTBALL_SEASON","2025")
    }
    r = requests.get(url, headers=_headers(conf), params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    matches_raw = js.get("matches", [])

    out = []
    for m in matches_raw:
        mid = str(m.get("id"))
        utc_str = m.get("utcDate")
        try:
            utc_dt = datetime.fromisoformat(utc_str.replace("Z","+00:00"))
        except Exception:
            continue
        local_dt = utc_dt.astimezone(tz)
        status = m.get("status","SCHEDULED")
        home = m.get("homeTeam",{}).get("name","")
        away = m.get("awayTeam",{}).get("name","")
        score = m.get("score",{})
        full = score.get("fullTime",{})
        h_ft = full.get("home")
        a_ft = full.get("away")
        live = score.get("halfTime",{})  # 代用（FD はライブ値は status/state 依存）
        out.append({
            "id": mid,
            "gw": _gw_from_date(utc_dt, conf),
            "utc_kickoff": utc_dt.replace(tzinfo=timezone.utc),
            "local_kickoff": local_dt,
            "home": home,
            "away": away,
            "status": status,
            "score_home": h_ft,
            "score_away": a_ft,
        })
    # 表示対象 GW は config[current_gw] を優先
    gw_display = conf.get("current_gw") or (out[0]["gw"] if out else "GW?")
    return out, gw_display

def fetch_live_snapshot(competition: str, conf) -> List[Dict[str,Any]]:
    """リアルタイムページの更新用：直近7日の試合を取得"""
    matches, _ = fetch_matches_window(7, competition, conf)
    return matches
