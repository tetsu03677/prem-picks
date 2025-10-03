# football_api.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Iterable
from datetime import datetime, timedelta, timezone
import requests
import pytz

def _headers(conf: Dict[str, Any]) -> Dict[str, str]:
    return {"X-Auth-Token": conf["FOOTBALL_DATA_API_TOKEN"]}

def _tz(conf: Dict[str, Any]):
    return pytz.timezone(conf.get("timezone", "Asia/Tokyo"))

def _iso_date(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def get_upcoming(conf: Dict[str, Any], days: int = 7) -> Tuple[List[Dict[str, Any]], str]:
    """7日固定で“次節”を取得（SCHEDULEDのみ）。GWは最初に見つかったmatchdayを使う。"""
    competition = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    tz = _tz(conf)

    today = datetime.utcnow().date()
    date_from = _iso_date(datetime.utcnow())
    date_to = _iso_date(datetime.utcnow() + timedelta(days=days))
    url = (f"https://api.football-data.org/v4/competitions/{competition}/matches"
           f"?season={season}&dateFrom={date_from}&dateTo={date_to}&status=SCHEDULED")
    r = requests.get(url, headers=_headers(conf), timeout=20)
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
            "status": m.get("status","SCHEDULED"),
        })
    if gw is None:
        gw = conf.get("current_gw", "GW?")
    return matches, gw

def get_matches_range(conf: Dict[str, Any], date_from: datetime, date_to: datetime) -> List[Dict[str, Any]]:
    """ステータス制限なしで区間の試合（スコア含む）を取得。リアルタイム/履歴用。"""
    competition = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    tz = _tz(conf)
    url = (f"https://api.football-data.org/v4/competitions/{competition}/matches"
           f"?season={season}&dateFrom={_iso_date(date_from)}&dateTo={_iso_date(date_to)}")
    r = requests.get(url, headers=_headers(conf), timeout=20)
    r.raise_for_status()
    out: List[Dict[str, Any]] = []
    for m in r.json().get("matches", []):
        utc_dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        out.append({
            "id": str(m["id"]),
            "gw": f"GW{m.get('matchday')}" if m.get('matchday') else "",
            "utc_kickoff": utc_dt,
            "local_kickoff": utc_dt.astimezone(tz),
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "status": m.get("status",""),
            "score": m.get("score",{}),  # includes fullTime/halfTime
        })
    return out

def get_matches_by_ids(conf: Dict[str, Any], ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """/matches/{id} を順次取得して辞書で返す（件数はbetsの実数想定でOK）"""
    base = "https://api.football-data.org/v4/matches/"
    out: Dict[str, Dict[str, Any]] = {}
    tz = _tz(conf)
    for mid in ids:
        r = requests.get(base + str(mid), headers=_headers(conf), timeout=20)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        m = r.json().get("match", {})
        utc_dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        out[str(mid)] = {
            "id": str(m.get("id")),
            "gw": f"GW{m.get('matchday')}" if m.get('matchday') else "",
            "utc_kickoff": utc_dt,
            "local_kickoff": utc_dt.astimezone(tz),
            "home": m.get("homeTeam",{}).get("name",""),
            "away": m.get("awayTeam",{}).get("name",""),
            "status": m.get("status",""),
            "score": m.get("score",{}),
        }
    return out

def winner_from_score(score_obj: Dict[str, Any]) -> str | None:
    """score.fullTime から HOME/DRAW/AWAY を返す。未確定は None"""
    ft = score_obj.get("fullTime") or {}
    h, a = ft.get("home"), ft.get("away")
    if h is None or a is None:
        return None
    if h > a: return "HOME"
    if h < a: return "AWAY"
    return "DRAW"
