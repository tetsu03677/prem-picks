# google_sheets_client.py
from __future__ import annotations
from typing import Dict, List, Any
from datetime import datetime, timezone
import json
import streamlit as st
import gspread

UTC = timezone.utc

# ── 接続 ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gc():
    # secrets.toml の gcp_service_account を使用
    creds_dict = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds_dict)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    return _sh().worksheet(name)

# ── config の key-value を dict で取得 ──────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    data = ws("config").get_all_records()
    conf: Dict[str, str] = {}
    for row in data:
        k = str(row.get("key", "")).strip()
        v = str(row.get("value", "")).strip()
        if k:
            conf[k] = v
    return conf

# ── odds を指定GWで {match_id: {...}} に整形して返す ───────────────
@st.cache_data(ttl=30, show_spinner=False)
def read_odds_map_for_gw(gw: int) -> Dict[str, Dict[str, Any]]:
    sheet = ws("odds")
    rows = sheet.get_all_records()
    odmap: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if str(r.get("gw", "")).strip() != str(gw):
            continue
        mid = str(r.get("match_id", "")).strip()
        if not mid:
            continue
        odmap[mid] = {
            "home": float(r.get("home_win", 0) or 0),
            "draw": float(r.get("draw", 0) or 0),
            "away": float(r.get("away_win", 0) or 0),
            "locked": bool(r.get("locked", False)),
            "updated_at": r.get("updated_at", ""),
        }
    return odmap

# ── bets 合計金額（そのGWの自分の投票合計）を算出 ────────────────
@st.cache_data(ttl=10, show_spinner=False)
def user_total_stake_for_gw(user: str, gw: int) -> int:
    sheet = ws("bets")
    rows = sheet.get_all_records()
    total = 0
    for r in rows:
        if str(r.get("gw", "")) == str(gw) and str(r.get("user", "")) == user:
            try:
                total += int(float(r.get("stake", 0) or 0))
            except Exception:
                pass
    return total

# ── ベットを一行追記 ─────────────────────────────────────────────
def append_bet_row(
    gw: int,
    user: str,
    match_id: str,
    match_label: str,
    pick: str,          # "HOME" / "DRAW" / "AWAY"
    stake: int,
    odds: float,
) -> None:
    sheet = ws("bets")
    now_utc = datetime.now(UTC).isoformat()
    key = f"{gw}-{user}-{match_id}-{int(datetime.now().timestamp())}"

    # シート列: key, gw, user, match_id, match, pick, stake, odds, placed_at, status, result, payout, net, settled_at
    row = [
        key,
        gw,
        user,
        match_id,
        match_label,
        pick,
        stake,
        odds,
        now_utc,
        "OPEN",
        "",     # result
        "",     # payout
        "",     # net
        "",     # settled_at
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")
    # 合計額キャッシュをクリア
    user_total_stake_for_gw.clear()
