# /football_api.py
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
import requests
import streamlit as st

JST = timezone(timedelta(hours=9))
SESSION = requests.Session()

@st.cache_data(ttl=180, show_spinner=False)
def _fd_headers() -> Dict[str, str]:
    # app.py 側の read_config() で st.session_state["_conf_cache"] に格納済み
    conf = st.session_state.get("_conf_cache") or {}
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    return {"X-Auth-Token": token} if token else {}

@st.cache_data(ttl=180, show_spinner=False)
def fetch_matches_window(days: int, competition: str = "2021", season: str = "2025") -> Tuple[Dict, Dict]:
    """
    football-data.org から直近days日分（今日～+days）の試合を取得
    """
    base = "https://api.football-data.org/v4/competitions"
    frm = datetime.utcnow().date()
    to = (datetime.utcnow().date() + timedelta(days=days))
    url = f"{base}/{competition}/matches"
    params = {
        "dateFrom": frm.isoformat(),
        "dateTo": to.isoformat(),
        "season": season
    }
    h = _fd_headers()
    if not h:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が設定されていません。config で設定してください。")
    r = SESSION.get(url, headers=h, params=params, timeout=(3, 10))
    r.raise_for_status()
    js = r.json()
    return js, {"from": frm.isoformat(), "to": to.isoformat()}

def simplify_matches(js: Dict) -> List[Dict]:
    """
    APIレスポンスを画面用に薄く整形
    """
    out = []
    for m in js.get("matches", []):
        score = m.get("score", {})
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
    treat_inplay_as_provisional=True の場合は IN_PLAY なども現在スコアで暫定判定
    """
    status = (m or {}).get("status")
    sc = (m or {}).get("score", "0-0")
    try:
        h, a = [int(x) for x in sc.split("-")]
    except Exception:
        h, a = 0, 0

    if status == "FINISHED":
        if h > a:
            return "HOME"
        elif h < a:
            return "AWAY"
        else:
            return "DRAW"

    if treat_inplay_as_provisional and status in {"IN_PLAY", "PAUSED"}:
        if h > a:
            return "HOME"
        elif h < a:
            return "AWAY"
        else:
            return "DRAW"
    return None
