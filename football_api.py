# football_api.py
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

import requests
import pytz
import streamlit as st

BASE = "https://api.football-data.org/v4"

def _headers(conf: Dict[str, str]) -> Dict[str, str]:
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
            return None
        r.raise_for_status()
        return r
    except Exception:
        return None

# ---- 追加：ID正規化（数字だけを抜き出して文字列化） ----
def _norm_id(x) -> str:
    s = "".join(ch for ch in str(x or "").strip() if ch.isdigit())
    return s or str(x or "").strip()

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
            "id": _norm_id(m["id"]),
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
    for r in rows:
        r["gw"] = gw
    return rows, gw

def fetch_scores_for_match_ids(conf: Dict[str, str], match_ids: List[str]) -> Dict[str, Dict]:
    """指定 match_id 群のスコア（LIVE/FINISHED含む）。403 等は空 dict を返す。"""
    out = {}
    # 受け取ったIDをすべて正規化してから問い合わせ
    ids = [ _norm_id(mid) for mid in (match_ids or []) ]
    ids = [ mid for mid in ids if mid ]
    for mid in ids:
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
        out[mid] = {
            "status": status,
            "home": j.get("homeTeam", {}).get("name", ""),
            "away": j.get("awayTeam", {}).get("name", ""),
            "home_score": live_home,
            "away_score": live_away,
        }
    return out

# ===== 追加：GW名（GW7 / 7）からその節の全試合を取得 =====
def fetch_matches_by_gw(conf: Dict[str, str], gw_name: str) -> Tuple[List[Dict], str]:
    """
    指定GWの全試合を Football-Data から取得して返す。
    app.py の救済処理（odds.fd_match_id の自動補完）で使用。
    season がズレている可能性に備えてフォールバック（season無し → season-1）を行う。
    """
    # 'GW7' や '7' を数値に
    s = str(gw_name or "").strip().upper()
    num = "".join(ch for ch in s if ch.isdigit())
    if not num:
        return [], s or ""
    matchday = int(num)

    comp, season = _league_and_season(conf)

    def _fetch(season_param):
        url = f"{BASE}/competitions/{comp}/matches"
        params = {"matchday": matchday}
        if season_param is not None:
            params["season"] = season_param
        r = _safe_get(url, _headers(conf), params)
        return r.json().get("matches", []) if r else []

    # 1) conf の season で試行
    items = _fetch(season)
    # 2) ダメなら season 指定なし
    if not items:
        items = _fetch(None)
    # 3) それでもダメなら season-1
    if not items and season and str(season).isdigit():
        items = _fetch(str(int(season) - 1))

    tzname = conf.get("timezone", "UTC")
    rows: List[Dict] = []
    for m in items or []:
        utc = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        rows.append({
            "id": _norm_id(m["id"]),  # ← 正規化
            "utc_kickoff": utc,
            "local_kickoff": _localize(utc, tzname),
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"],
            "status": m.get("status", "TIMED"),
            "gw": f"GW{m.get('matchday', matchday)}",
        })
    return rows, f"GW{matchday}"
