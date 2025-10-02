# /football_api.py
from __future__ import annotations
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Any, Optional

from google_sheets_client import get_config_value

JST = ZoneInfo("Asia/Tokyo")
BASE = "https://api.football-data.org/v4"

def _token() -> str:
    tok = (get_config_value("FOOTBALL_DATA_API_TOKEN") or "").strip()
    if not tok:
        raise RuntimeError("config に FOOTBALL_DATA_API_TOKEN がありません。")
    return tok

def fetch_upcoming_pl_matches(days_ahead: int = 21) -> List[Dict[str, Any]]:
    """今からdays_ahead日先までのSCHEDULED/TIMEDを取得してJST整形"""
    token = _token()
    now = datetime.now(JST)
    params = {
        "dateFrom": now.date().isoformat(),
        "dateTo": (now + timedelta(days=days_ahead)).date().isoformat(),
        "status": "SCHEDULED,TIMED",
    }
    r = requests.get(f"{BASE}/competitions/PL/matches", params=params, headers={"X-Auth-Token": token}, timeout=20)
    r.raise_for_status()
    data = r.json()
    out: List[Dict[str, Any]] = []
    for m in data.get("matches", []):
        utc = m.get("utcDate")
        dt = datetime.fromisoformat(utc.replace("Z","+00:00")).astimezone(JST) if utc else None
        out.append({
            "matchday": m.get("matchday"),
            "id": m.get("id"),
            "home": (m.get("homeTeam") or {}).get("name"),
            "away": (m.get("awayTeam") or {}).get("name"),
            "kickoff_jst": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "stage": m.get("stage"),
        })
    out.sort(key=lambda x: x["kickoff_jst"])
    return out

def pick_matchday_block(target_gw: str, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """target_gw（例 'GW7'）のmatchday群を返す。無ければ target+1 のブロックを返す。"""
    try:
        tgt = int(target_gw.replace("GW","").strip())
    except Exception:
        return []
    # グルーピング
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for m in matches:
        md = int(m.get("matchday") or 0)
        if md <= 0: 
            continue
        groups.setdefault(md, []).append(m)
    if tgt in groups:
        return groups[tgt]
    # 無ければ次に近い大きいMD
    for k in sorted(groups.keys()):
        if k > tgt:
            return groups[k]
    return []
