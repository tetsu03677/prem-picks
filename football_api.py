from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import streamlit as st
import requests
from datetime import datetime, timedelta, timezone

API_BASE = "https://api.football-data.org/v4"  # v4推奨

def _headers(token: str) -> Dict[str, str]:
    return {"X-Auth-Token": token}

def _tok(conf: Dict[str, str]) -> str:
    tok = conf.get("FOOTBALL_DATA_API_TOKEN","").strip()
    if not tok:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が config にありません。")
    return tok

def get_timezone(conf: Dict[str, str]) -> timezone:
    # football-data はUTCを返すため、表示側だけJSTなどに寄せたい時の便宜関数
    return timezone(timedelta(hours=9))  # Asia/Tokyo 固定でOK

def fixtures_by_date_range(conf: Dict[str,str], league_id: str, date_from: datetime, date_to: datetime) -> List[Dict[str, Any]]:
    """指定期間の試合（リーグ絞り）を取得。最大30日幅を想定。"""
    token = _tok(conf)
    params = {
        "dateFrom": date_from.strftime("%Y-%m-%d"),
        "dateTo":   date_to.strftime("%Y-%m-%d"),
        "competitions": league_id
    }
    url = f"{API_BASE}/matches"
    r = requests.get(url, headers=_headers(token), params=params, timeout=20)
    if r.status_code == 403:
        raise RuntimeError("football-data.org 403: トークン/プラン権限を確認してください。")
    r.raise_for_status()
    data = r.json()
    return data.get("matches", [])

def team_name(t: Dict[str,Any]) -> str:
    return t.get("shortName") or t.get("name") or ""

def simplify_match(m: Dict[str,Any]) -> Dict[str,Any]:
    mid   = m.get("id")
    utc   = m.get("utcDate")
    comp  = m.get("competition", {}).get("name", "")
    home  = team_name(m.get("homeTeam", {}))
    away  = team_name(m.get("awayTeam", {}))
    score = m.get("score", {})
    full  = score.get("fullTime", {})
    status = m.get("status","")
    return {
        "match_id": mid,
        "utcDate": utc,
        "competition": comp,
        "home": home,
        "away": away,
        "status": status,
        "home_ft": full.get("home"),
        "away_ft": full.get("away"),
    }
