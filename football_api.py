# /football_api.py
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests
import streamlit as st

JST = timezone(timedelta(hours=9))
SESSION = requests.Session()

@st.cache_data(ttl=180, show_spinner=False)
def _fd_headers() -> Dict[str, str]:
    conf = st.session_state.get("_conf_cache") or {}
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    return {"X-Auth-Token": token} if token else {}

@st.cache_data(ttl=180, show_spinner=False)
def fetch_matches_window(days: int, competition: str = "2021", season: str = "2025") -> Tuple[Dict, Dict]:
    """
    football-data.org:
    GET /v4/competitions/{competition}/matches?dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD&season=2025
    """
    base = "https://api.football-data.org/v4/competitions"
    frm = datetime.utcnow().date()
    to = (datetime.utcnow().date() + timedelta(days=days))
    url = f"{base}/{competition}/matches"
    params = {"dateFrom": frm.isoformat(), "dateTo": to.isoformat(), "season": season}
    headers = _fd_headers()
    if not headers:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が未設定です（config を確認）。")
    r = SESSION.get(url, headers=headers, params=params, timeout=(3, 10))
    r.raise_for_status()
    return r.json(), {"from": frm.isoformat(), "to": to.isoformat()}

def simplify_matches(js: Dict) -> List[Dict]:
    out = []
    for m in js.get("matches", []):
        score = m.get("score", {}) or {}
        full = score.get("fullTime", {}) or {}
        ht = m.get("homeTeam", {}) or {}
        at = m.get("awayTeam", {}) or {}
        out.append({
            "id": m.get("id"),
            "utcDate": m.get("utcDate"),
            "status": m.get("status"),
            "matchday": m.get("matchday"),
            "homeTeam": ht.get("shortName") or ht.get("name"),
            "awayTeam": at.get("shortName") or at.get("name"),
            "score": f"{full.get('home', 0)}-{full.get('away', 0)}",
        })
    return out

def get_match_result_symbol(m: Dict, treat_inplay_as_provisional: bool = False) -> str | None:
    """
    戻り値: "HOME" | "DRAW" | "AWAY" | None
    FINISHED は確定。treat_inplay_as_provisional=True なら IN_PLAY/PAUSED は途中スコアで暫定判定。
    """
    status = (m or {}).get("status")
    sc = (m or {}).get("score", "0-0")
    try:
        h, a = [int(x) for x in sc.split("-")]
    except Exception:
        h, a = 0, 0

    if status == "FINISHED":
        if h > a: return "HOME"
        if h < a: return "AWAY"
        return "DRAW"

    if treat_inplay_as_provisional and status in {"IN_PLAY", "PAUSED"}:
        if h > a: return "HOME"
        if h < a: return "AWAY"
        return "DRAW"
    return None
