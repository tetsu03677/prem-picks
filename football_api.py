from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

import requests
import streamlit as st

def _api_token(conf: Dict) -> str:
    # config を優先。なければ secrets
    t = conf.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("FOOTBALL_DATA_API_TOKEN", "")
    return str(t)

def _headers(token: str) -> Dict:
    return {"X-Auth-Token": token}

def fetch_matches_window(day_window: int, competition: str, season: str, token: str) -> List[Dict]:
    now = datetime.now(timezone.utc)
    date_from = now.date().isoformat()
    date_to = (now + timedelta(days=day_window)).date().isoformat()
    url = f"https://api.football-data.org/v4/matches"
    params = {"dateFrom": date_from, "dateTo": date_to, "competitions": competition}
    r = requests.get(url, headers=_headers(token), params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    matches = data.get("matches", [])
    # フィルタ：シーズン一致のみ
    if season:
        matches = [m for m in matches if str(m.get("season",{}).get("startDate","")).startswith(season[:4]) or str(m.get("season",{}).get("currentMatchday",""))]
    return matches

def fetch_matches_next_gw(conf: Dict, day_window: int = 7) -> Tuple[List[Dict], Optional[str]]:
    token = _api_token(conf)
    comp = str(conf.get("FOOTBALL_DATA_COMPETITION", "PL"))
    season = str(conf.get("API_FOOTBALL_SEASON", ""))

    window = fetch_matches_window(day_window, comp, season, token)
    if not window:
        return [], None
    # 最初に来る matchday を次節とみなして同一 matchday を抽出
    md = None
    for m in sorted(window, key=lambda x: x.get("utcDate","")):
        md = m.get("matchday") or m.get("season",{}).get("currentMatchday")
        if md:
            break
    if md is None:
        return [], None
    gw = f"GW{int(md)}"
    next_matches = [m for m in window if (m.get("matchday") or m.get("season",{}).get("currentMatchday")) == md]
    return next_matches, gw

def simplify_matches(matches: List[Dict], tz) -> List[Dict]:
    out = []
    for m in sorted(matches, key=lambda x: x.get("utcDate","")):
        utc_dt = datetime.fromisoformat(m["utcDate"].replace("Z","+00:00"))
        out.append({
            "id": int(m["id"]),
            "gw": f"GW{int(m.get('matchday') or 0)}" if m.get("matchday") else "GW",
            "utc_kickoff": utc_dt,
            "local_kickoff": utc_dt.astimezone(tz),
            "home": m.get("homeTeam",{}).get("name",""),
            "away": m.get("awayTeam",{}).get("name",""),
            "status": m.get("status","")
        })
    return out

def fetch_match_results_for_ids(conf: Dict, match_ids: List[int], realtime: bool=False, finished_only: bool=False) -> Dict[int, Dict]:
    """match_id -> {'home':score, 'away':score, 'status':...}"""
    token = _api_token(conf)
    out = {}
    for mid in match_ids:
        url = f"https://api.football-data.org/v4/matches/{mid}"
        r = requests.get(url, headers=_headers(token), timeout=30)
        if r.status_code != 200:
            continue
        m = r.json().get("match", r.json())
        status = m.get("status","")
        if finished_only and status != "FINISHED":
            continue
        score = m.get("score",{})
        full = score.get("fullTime",{}) or {}
        # リアルタイム時は live/halfTime を優先
        if realtime:
            live = score.get("live",{}) or score.get("halfTime",{}) or full
            full = live or full
        out[int(mid)] = {
            "home": int(full.get("home", 0) or 0),
            "away": int(full.get("away", 0) or 0),
            "status": status
        }
    return out

def outcome_from_score(score: Optional[Dict]) -> Optional[str]:
    if not score:
        return None
    h, a = int(score.get("home",0)), int(score.get("away",0))
    if h > a:
        return "HOME"
    if a > h:
        return "AWAY"
    return "DRAW"
