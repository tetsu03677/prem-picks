from __future__ import annotations

import datetime as dt
from typing import Dict, Any, List, Tuple

import requests
from dateutil.tz import gettz

BASE = "https://api.football-data.org/v4"

def _hdr(token: str) -> Dict[str, str]:
    return {"X-Auth-Token": token}

def _iso(d: dt.date) -> str:
    return d.isoformat()

def fetch_matches_next_window(days: int, competition: str, season: str, token: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    次の 'days' 日間の SCHEDULED 試合を取得（competition は 'PL' 等のコード or 数値ID どちらでも可）
    """
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    params = {
        "dateFrom": _iso(start),
        "dateTo": _iso(end),
        "season": season,
        "status": "SCHEDULED",
    }
    url = f"{BASE}/competitions/{competition}/matches"
    r = requests.get(url, headers=_hdr(token), params=params, timeout=20)
    if r.status_code == 404:
        return [], "no_window"
    r.raise_for_status()
    data = r.json()
    return data.get("matches", []), "ok"

def simplify_matches(raw: List[Dict[str, Any]], tz_name: str) -> List[Dict[str, Any]]:
    tz = gettz(tz_name) or gettz("UTC")
    out: List[Dict[str, Any]] = []
    for m in raw:
        utc_str = m.get("utcDate") or m.get("utc_date")
        kf_utc = dt.datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        kf_local = kf_utc.astimezone(tz)
        out.append({
            "id": str(m["id"]),
            "gw": f"GW{m.get('matchday') or m.get('matchDay') or '?'}",
            "utc_kickoff": kf_utc,
            "local_kickoff": kf_local,
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "status": m.get("status", ""),
        })
    out.sort(key=lambda x: x["utc_kickoff"])
    return out
