# football_api.py
# Football-Data.org v4 を使用。トークンは config から供給（Secrets 依存なし）

from datetime import datetime, timedelta, timezone
from dateutil import tz
import requests
import streamlit as st

from google_sheets_client import read_config

FD_BASE = "https://api.football-data.org/v4"

def _headers(conf: dict):
    # ← 重要: Secrets ではなく config シートから
    return {"X-Auth-Token": conf.get("FOOTBALL_DATA_API_TOKEN", "").strip()}

def _competition_param(conf: dict):
    # 'PL' でも '2021' でも動くように
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "PL").strip()
    return comp

def _season_param(conf: dict):
    return str(conf.get("FOOTBALL_DATA_SEASON", "2025")).strip()

def _to_utc(dt: datetime):
    return dt.astimezone(timezone.utc)

@st.cache_data(show_spinner=False, ttl=60)
def fetch_matches_window(day_window: int, competition: str, season: str, conf: dict):
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    date_from = now_utc.date().isoformat()
    date_to = (now_utc + timedelta(days=day_window)).date().isoformat()

    url = f"{FD_BASE}/matches"
    params = {
        "competitions": competition,
        "dateFrom": date_from,
        "dateTo": date_to,
        "season": season,
        # status を絞ると取りこぼし易いので指定しない
    }
    r = requests.get(url, headers=_headers(conf), params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def _parse_gw(m: dict):
    # v4 では "matchday" がある
    md = m.get("matchday")
    return f"GW{md}" if md else "GW?"

def simplify_matches(api_json: dict, tzinfo):
    out = []
    for m in api_json.get("matches", []):
        utc_str = m.get("utcDate")
        try:
            utc_dt = datetime.fromisoformat(utc_str.replace("Z","+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        local_dt = utc_dt.astimezone(tzinfo or tz.gettz("Asia/Tokyo"))
        out.append({
            "id": m.get("id"),
            "gw": _parse_gw(m),
            "utc_kickoff": utc_dt,
            "local_kickoff": local_dt,
            "home": (m.get("homeTeam") or {}).get("name",""),
            "away": (m.get("awayTeam") or {}).get("name",""),
            "status": m.get("status",""),
            "score": m.get("score", {}),
        })
    # キックオフ昇順
    out.sort(key=lambda x: x["utc_kickoff"])
    return out

def compute_gw_lock_threshold(matches: list, conf: dict, tzinfo):
    """当GWの最初の試合の kickoff - freeze_minutes （UTC）の時刻を返す"""
    if not matches:
        return None
    first_utc = min(m["utc_kickoff"] for m in matches)
    minutes = int(conf.get("odds_freeze_minutes_before_first", "120") or 120)
    return first_utc - timedelta(minutes=minutes)

def _first_gw_label(matches: list, fallback: str):
    # 最初に現れる gw を採用
    for m in matches:
        if m.get("gw"):
            return m["gw"]
    return fallback

def fetch_matches_current_gw(conf: dict, day_window: int = 7):
    comp = _competition_param(conf)
    season = _season_param(conf)
    js = fetch_matches_window(day_window, comp, season, conf)
    tzinfo = tz.gettz(conf.get("timezone", "Asia/Tokyo"))
    ms = simplify_matches(js, tzinfo)
    gw = _first_gw_label(ms, conf.get("current_gw", "GW?"))
    # 今節: 直近で status が TIMED/SCHEDULED/IN_PLAY の最小 matchday を採用
    if not ms:
        return {"matches": []}, gw
    # そのまま返す（選別はアプリ側で）
    return js, gw

@st.cache_data(show_spinner=False, ttl=60)
def fetch_matches_next_gw(conf: dict, day_window: int = 7):
    # 7日先で再検索し、最小 matchday を抽出
    comp = _competition_param(conf)
    season = _season_param(conf)
    js = fetch_matches_window(day_window, comp, season, conf)
    tzinfo = tz.gettz(conf.get("timezone", "Asia/Tokyo"))
    ms = simplify_matches(js, tzinfo)
    if not ms:
        return {"matches": []}, "GW?"
    # もっとも早い matchday を次GWとみなす
    first_gw = _first_gw_label(ms, "GW?")
    return {"matches": [m for m in js.get("matches", []) if _parse_gw(m)==first_gw]}, first_gw

@st.cache_data(show_spinner=False, ttl=45)
def fetch_match_snapshots_by_ids(conf: dict, ids: list[str]):
    if not ids:
        return []
    # Football-Data は ids クエリにカンマ区切りを受け付ける
    url = f"{FD_BASE}/matches"
    params = {
        "ids": ",".join(ids)
    }
    r = requests.get(url, headers=_headers(conf), params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    return js.get("matches", [])
