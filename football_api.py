from __future__ import annotations
import datetime as dt
import requests
from typing import Dict, Any, List
import streamlit as st

def _fd_headers(token: str) -> Dict[str, str]:
    return {"X-Auth-Token": token}

def _normalize_comp(v: str) -> str:
    if not v:
        return "PL"
    v = str(v).strip().upper()
    if v == "39":     # API-Footballの名残り救済
        return "PL"
    if v in ("PL", "2021"):  # football-data のPLコード or ID
        return v
    return v

def fetch_fixtures_fd(conf: Dict[str, str], days_ahead: int) -> Dict[str, Any]:
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が未設定です。（config シート）")
    comp = _normalize_comp(conf.get("FOOTBALL_DATA_COMPETITION", "PL"))
    today = dt.datetime.utcnow().date()
    params = {
        "dateFrom": today.isoformat(),
        "dateTo": (today + dt.timedelta(days=int(days_ahead))).isoformat(),
        "competitions": comp,
    }
    url = "https://api.football-data.org/v4/matches"
    r = requests.get(url, headers=_fd_headers(token), params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def simplify_matches(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for m in raw.get("matches", []):
        out.append({
            "id": m.get("id"),
            "utc": m.get("utcDate"),
            "status": m.get("status"),
            "home": m.get("homeTeam", {}).get("name"),
            "away": m.get("awayTeam", {}).get("name"),
            "score": m.get("score", {}),
            "stage": m.get("stage"),
            "matchday": m.get("matchday"),
        })
    return out
