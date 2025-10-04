# football_api.py
from __future__ import annotations

from typing import Dict, List, Tuple
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st

API_BASE = "https://api.football-data.org/v4"

def _token_from_conf(conf: Dict[str, str]) -> str:
    # まず config シートの値、無ければ Secrets をフォールバック
    t = conf.get("FOOTBALL_DATA_API_TOKEN", "").strip()
    if t:
        return t
    return st.secrets.get("FOOTBALL_DATA_API_TOKEN", "")

def _headers(conf: Dict[str, str]) -> Dict[str, str]:
    token = _token_from_conf(conf)
    if not token:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が見つかりません（config か secrets に設定してください）")
    return {"X-Auth-Token": token}

def _dates_range(day_window: int) -> Tuple[str, str]:
    """
    UTC で今日〜day_window 日後を YYYY-MM-DD で返す
    """
    today_utc = datetime.utcnow().date()
    end_utc = today_utc + timedelta(days=day_window)
    return (today_utc.isoformat(), end_utc.isoformat())

def fetch_matches_window(day_window: int, competition: str, season: str, conf: Dict[str, str]) -> Tuple[List[Dict], str]:
    """
    近傍の試合（スケジュール・進行中含む）を取得し、最も近い matchday（=GW）に属する試合のみ返す。
    戻り値: (matches, gw_label)
    """
    date_from, date_to = _dates_range(day_window)
    url = f"{API_BASE}/competitions/{competition}/matches"
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "season": season,
        # "status": "SCHEDULED,IN_PLAY,PAUSED,FINISHED,POSTPONED"  # 権限により 403 が出る場合はコメントアウト
    }
    r = requests.get(url, headers=_headers(conf), params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    items: List[Dict] = data.get("matches", []) or []

    # 最も近い matchday を特定
    upcoming = [m for m in items if m.get("utcDate")]
    if not upcoming:
        return [], ""

    # 直近の kick-off
    upcoming.sort(key=lambda m: m["utcDate"])
    nearest_day = upcoming[0].get("matchday")
    same_day = [m for m in upcoming if m.get("matchday") == nearest_day]
    gw_label = f"GW{nearest_day}" if nearest_day else ""

    def _map(m):
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        # utc/local kickoff
        utc_kick = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        tz = ZoneInfo(st.session_state.get("app_tz", "Asia/Tokyo"))
        local_kick = utc_kick.astimezone(tz)
        score = m.get("score", {})
        full = score.get("fullTime", {}) or {}
        live = score.get("halfTime", {}) or {}

        return {
            "id": str(m.get("id")),
            "gw": gw_label,
            "matchday": nearest_day,
            "status": m.get("status"),
            "utc_kickoff": utc_kick,
            "local_kickoff": local_kick,
            "home": home,
            "away": away,
            "home_score": full.get("home", live.get("home")),
            "away_score": full.get("away", live.get("away")),
        }

    return list(map(_map, same_day)), gw_label

def fetch_matches_next_gw(conf: Dict[str, str], day_window: int = 7) -> Tuple[List[Dict], str]:
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
    season = conf.get("API_FOOTBALL_SEASON", "")
    return fetch_matches_window(day_window, comp, season, conf)
