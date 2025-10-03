import json
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone
import streamlit as st
import gspread

# ===== 基本接続 =====
@st.cache_resource(show_spinner=False)
def _gc():
    creds = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    return _sh().worksheet(name)

# ===== config 読み込み =====
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    data = ws("config").get_all_records()
    conf = {}
    for r in data:
        k = str(r.get("key", "")).strip()
        v = r.get("value", "")
        if k:
            conf[k] = str(v)
    return conf

# ===== odds 読み書き =====
@st.cache_data(ttl=30, show_spinner=False)
def read_odds() -> Dict[str, Dict]:
    rows = ws("odds").get_all_records()
    by_mid = {}
    for r in rows:
        mid = str(r.get("match_id", "")).strip()
        if not mid:
            continue
        by_mid[mid] = {
            "gw": str(r.get("gw", "")).strip(),
            "home": str(r.get("home", "")).strip(),
            "away": str(r.get("away", "")).strip(),
            "home_win": float(r.get("home_win", 0) or 0),
            "draw": float(r.get("draw", 0) or 0),
            "away_win": float(r.get("away_win", 0) or 0),
            "locked": str(r.get("locked", "")).strip().upper() in ("1","TRUE","YES"),
            "updated_at": str(r.get("updated_at","")).strip()
        }
    return by_mid

def upsert_odds_row(gw: str, match_id: str, home: str, away: str,
                    home_win: float, draw: float, away_win: float, locked: bool):
    w = ws("odds")
    vals = w.get_all_values()
    header = vals[0] if vals else []
    idx_map = {h:i for i,h in enumerate(header)}
    def row_to_key(row):
        return str(row[idx_map["match_id"]]) if "match_id" in idx_map else ""

    # 既存検索
    target_row = None
    for i,row in enumerate(vals[1:], start=2):
        if row_to_key(row) == str(match_id):
            target_row = i
            break

    payload = {
        "gw": gw, "match_id": match_id, "home": home, "away": away,
        "home_win": home_win, "draw": draw, "away_win": away_win,
        "locked": "1" if locked else "", "updated_at": datetime.now(timezone.utc).isoformat()
    }

    # ヘッダ順に並べた行へ
    out = []
    for h in header:
        out.append(str(payload.get(h,"")))

    if target_row:
        w.update(f"A{target_row}:{gspread.utils.rowcol_to_a1(target_row, len(header))}", [out])
    else:
        # 無い場合は行追加
        w.append_row(out, value_input_option="USER_ENTERED")

    # キャッシュクリア
    read_odds.clear()

# ===== bets 読み書き =====
@st.cache_data(ttl=20, show_spinner=False)
def read_bets() -> List[Dict]:
    return ws("bets").get_all_records()

def _bet_key(gw: str, user: str, match_id: str) -> str:
    return f"{gw}__{user}__{match_id}"

def upsert_bet(gw: str, user: str, match_id: str, match_label: str,
               pick: str, stake: int, odds: float, status: str = "placed"):
    w = ws("bets")
    vals = w.get_all_values()
    header = vals[0]
    idx = {h:i for i,h in enumerate(header)}

    # 既存検索
    key = _bet_key(gw, user, match_id)
    found_row = None
    for i,row in enumerate(vals[1:], start=2):
        if idx.get("key") is not None and row[idx["key"]] == key:
            found_row = i
            break

    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "key": key,
        "gw": gw,
        "user": user,
        "match_id": match_id,
        "match": match_label,
        "pick": pick,
        "stake": stake,
        "odds": odds,
        "placed_at": now_iso,
        "status": status,
        "result": "",
        "payout": "",
        "net": "",
        "settled_at": ""
    }
    row_out = [str(record.get(h,"")) for h in header]

    if found_row:
        w.update(f"A{found_row}:{gspread.utils.rowcol_to_a1(found_row, len(header))}", [row_out])
    else:
        w.append_row(row_out, value_input_option="USER_ENTERED")

    read_bets.clear()

def user_total_stake_in_gw(user: str, gw: str) -> int:
    total = 0
    for r in read_bets():
        if str(r.get("gw")) == gw and str(r.get("user")) == user:
            total += int(float(r.get("stake") or 0))
    return total

def other_bets_for_match(match_id: str, exclude_user: str) -> List[Dict]:
    out = []
    for r in read_bets():
        if str(r.get("match_id")) == str(match_id) and str(r.get("user")) != exclude_user:
            out.append({
                "user": r.get("user"),
                "pick": r.get("pick"),
                "stake": r.get("stake"),
                "odds": r.get("odds")
            })
    return out
