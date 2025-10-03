import time
import requests
import streamlit as st
from typing import Dict, List, Any, Optional
from google_sheets_client import read_config

# ---- 内部ユーティリティ -------------------------------------------------
@st.cache_resource(show_spinner=False)
def _base() -> Dict[str, Any]:
    conf = read_config()
    key = conf.get("RAPIDAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("RAPIDAPI_KEY が config シートにありません。")
    return {
        "key": key,
        "hosts": ["api-football-v1.p.rapidapi.com", "api-football.p.rapidapi.com"],
        "base": "https://api-football-v1.p.rapidapi.com/v3",
        "league_id": int(conf.get("API_FOOTBALL_LEAGUE_ID", "39")),
        "season": int(conf.get("API_FOOTBALL_SEASON", "2025")),
    }

def _get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    base = _base()
    last_err: Optional[str] = None
    for host in base["hosts"]:
        headers = {"x-rapidapi-key": base["key"], "x-rapidapi-host": host}
        try:
            r = requests.get(f'{base["base"]}{path}', headers=headers, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            last_err = f"{r.status_code} {r.text[:200]}"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.3)
    raise RuntimeError(f"API-Football 呼び出し失敗: {last_err}")

# ---- 公開API -------------------------------------------------------------

def get_fixtures_for_round(round_num: int) -> List[Dict[str, Any]]:
    """
    今シーズン/指定ラウンド（GW）のプレミア日程を返す。
    API-Football の round 指定は 'Regular Season - {n}' 形式。
    """
    base = _base()
    params = {
        "league": base["league_id"],
        "season": base["season"],
        "round": f"Regular Season - {round_num}",
    }
    data = _get("/fixtures", params)
    return data.get("response", [])

def get_odds_for_fixture(fixture_id: int) -> Dict[str, Any]:
    """
    指定試合のプリマッチ・オッズ（Match Winner）を返す。
    返り値例: {"1": 1.85, "X": 3.60, "2": 4.2}
    """
    data = _get("/odds", {"fixture": fixture_id})
    resp = data.get("response", [])
    if not resp:
        return {}
    # 最初に見つかった「Match Winner」を採用
    for bk in resp[0].get("bookmakers", []):
        for bet in bk.get("bets", []):
            if bet.get("name", "").lower() in ("match winner", "match-winner", "1x2"):
                out = {}
                for v in bet.get("values", []):
                    label = (v.get("value") or "").strip()
                    odd = v.get("odd")
                    if not odd:
                        continue
                    if label.lower().startswith("home") or label == "1":
                        out["1"] = float(odd)
                    elif label.lower().startswith("draw") or label.upper() == "X":
                        out["X"] = float(odd)
                    elif label.lower().startswith("away") or label == "2":
                        out["2"] = float(odd)
                if out:
                    return out
    return {}
