# football_api.py —— 差し替え版
from __future__ import annotations
import datetime as dt
import requests
from typing import Dict, Any, List
import streamlit as st

def _fd_headers(token: str) -> Dict[str, str]:
    return {"X-Auth-Token": token}

def _competition_value(conf: Dict[str, str]) -> str:
    """
    configの値を安全に正規化。
    - 'PL' や '39' が来ても Premier League の ID '2021' に寄せる
    - 未設定なら '2021'
    """
    raw = (conf.get("FOOTBALL_DATA_COMPETITION") or "").strip().upper()
    if raw in ("", "PL", "39", "2021"):
        return "2021"   # Premier League ID
    return raw

def fetch_fixtures_fd(conf: Dict[str, str], days_ahead: int) -> Dict[str, Any]:
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が未設定です。（config シート）")

    comp = _competition_value(conf)

    # 未来日を取りすぎると 400 のことがあるので最大 21 日でクリップ
    days = max(1, min(int(days_ahead), 21))
    today = dt.datetime.utcnow().date()
    params = {
        "dateFrom": today.isoformat(),
        "dateTo":   (today + dt.timedelta(days=days)).isoformat(),
        "competitions": comp,
        # データが出やすいようにステータスも明示
        "status": "SCHEDULED,IN_PLAY,PAUSED,FINISHED,POSTPONED",
    }

    url = "https://api.football-data.org/v4/matches"
    r = requests.get(url, headers=_fd_headers(token), params=params, timeout=20)
    # 失敗時はサーバーからのエラー本文を出す（デバッグしやすく）
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = r.json().get("message", "")
        except Exception:
            detail = r.text[:200]
        raise requests.HTTPError(f"{e} :: {detail}") from None

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
