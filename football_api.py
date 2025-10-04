from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple, Optional

import pytz
import requests
import streamlit as st

FD_BASE = "https://api.football-data.org/v4"

def _tz(conf: Dict[str, str]):
    name = conf.get("timezone") or "UTC"
    try:
        return pytz.timezone(name)
    except Exception:
        return pytz.UTC

def _headers(conf: Dict[str, str]):
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    return {"X-Auth-Token": token}

def fetch_matches_window(days: int, conf: Dict[str, str]) -> List[Dict[str, Any]]:
    """次のN日分の試合（競技会＝PL）を取得"""
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "PL")
    season = conf.get("API_FOOTBALL_SEASON", "")
    # 期間はUTCで投げる
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    date_from = now_utc.date().isoformat()
    date_to = (now_utc + timedelta(days=days)).date().isoformat()
    params = {"dateFrom": date_from, "dateTo": date_to}
    if season:
        params["season"] = season
    url = f"{FD_BASE}/competitions/{comp}/matches"
    r = requests.get(url, headers=_headers(conf), params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("matches", [])

def simplify_matches(raw: List[Dict[str, Any]], conf: Dict[str, str]) -> List[Dict[str, Any]]:
    tz = _tz(conf)
    out = []
    for m in raw:
        utc_iso = m.get("utcDate")
        try:
            utc_dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        except Exception:
            continue
        local_dt = utc_dt.astimezone(tz)
        out.append({
            "id": str(m.get("id")),
            "gw": f"GW{conf.get('current_gw', '').replace('GW','') or ''}",
            "utc_kickoff": utc_dt,
            "local_kickoff": local_dt,
            "home": m.get("homeTeam", {}).get("name", ""),
            "away": m.get("awayTeam", {}).get("name", ""),
            "status": m.get("status", ""),
            "score": m.get("score", {})  # raw score (for future RT)
        })
    # kickoff 昇順
    out.sort(key=lambda x: x["utc_kickoff"])
    return out

def gw_lock_times(matches: List[Dict[str, Any]], conf: Dict[str, str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """GWのロック開始/終了（UTC）を返す。最初の試合の2時間前〜最後の試合終了想定時刻(＋2h)"""
    if not matches:
        return None, None
    earliest = min(m["utc_kickoff"] for m in matches)
    latest = max(m["utc_kickoff"] for m in matches)
    lock_start = earliest - timedelta(minutes=int(conf.get("lock_minutes_before_earliest", "120") or "120"))
    # 終了は安全に+2時間
    lock_end = latest + timedelta(hours=2)
    return lock_start, lock_end
