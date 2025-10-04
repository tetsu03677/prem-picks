from __future__ import annotations
import json, re
from typing import Dict, Optional, Iterable

def safe_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default

def fmt_yen(n: float | int) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

def to_local(dt, tz):
    return dt.astimezone(tz)

def gw_label(gw: str|int|None) -> str:
    if gw is None: return "GW"
    s = str(gw)
    return s if s.startswith("GW") else f"GW{safe_int(s,0)}"

def gw_sort_key(gw: str) -> tuple:
    """'GW7','GW10' 等を正しく昇順にするキー"""
    m = re.search(r"(\d+)", str(gw))
    n = int(m.group(1)) if m else 0
    return (n, str(gw))

def outcome_text_jp(o: Optional[str]) -> str:
    return {"HOME":"ホーム勝ち","DRAW":"引き分け","AWAY":"アウェイ勝ち"}.get(o or "", "-")

def calc_payout_and_net(pick: str|None, outcome: str|None, stake: int|float,
                        odds_home: float, odds_draw: float, odds_away: float) -> tuple[int,int]:
    pick = (pick or "").upper()
    outcome = (outcome or "").upper()
    stake = safe_int(stake, 0)
    if pick and outcome and pick == outcome:
        odd = {"HOME":odds_home, "DRAW":odds_draw, "AWAY":odds_away}[pick]
        payout = int(round(stake * float(odd)))
        return payout, payout - stake
    return 0, -stake if pick else 0

def safe_userlist_from_config(users_json: str) -> list[dict]:
    try:
        data = json.loads(users_json) if users_json else []
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []
