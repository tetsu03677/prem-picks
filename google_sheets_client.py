# google_sheets_client.py
from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
import streamlit as st
import gspread

UTC = timezone.utc

# ── 接続 ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gc():
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

# ── odds（指定GW）: {match_id: {...}} ───────────────────────────
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

# ── 自分の合計ステーク（指定GW） ───────────────────────────────
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

# ── その試合の自分ベット取得（行番号つき） ───────────────────────
def get_user_bet_for_match(user: str, gw: int, match_id: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    sheet = ws("bets")
    rows = sheet.get_all_records()
    for idx, r in enumerate(rows):
        if (
            str(r.get("gw", "")) == str(gw)
            and str(r.get("user", "")) == user
            and str(r.get("match_id", "")) == str(match_id)
            and str(r.get("status", "OPEN")).upper() == "OPEN"
        ):
            return idx + 2, r  # 行番号（ヘッダが1行目）
    return None

# ── 試合別：他ユーザーのOPENベット一覧（自分含む） ───────────────
@st.cache_data(ttl=10, show_spinner=False)
def open_bets_for_match(gw: int, match_id: str) -> List[Dict[str, Any]]:
    sheet = ws("bets")
    rows = sheet.get_all_records()
    out: List[Dict[str, Any]] = []
    for r in rows:
        if (
            str(r.get("gw", "")) == str(gw)
            and str(r.get("match_id", "")) == str(match_id)
            and str(r.get("status", "OPEN")).upper() == "OPEN"
        ):
            out.append(r)
    return out

# ── 新規追記 ────────────────────────────────────────────────────
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
    row = [
        key, gw, user, match_id, match_label, pick, stake, odds,
        now_utc, "OPEN", "", "", "", ""
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")
    user_total_stake_for_gw.clear()

# ── upsert（既存があれば上書き） ───────────────────────────────
def upsert_bet_row(
    gw: int,
    user: str,
    match_id: str,
    match_label: str,
    pick: str,      # "HOME"/"DRAW"/"AWAY"
    stake: int,
    odds: float,
) -> None:
    sheet = ws("bets")
    found = get_user_bet_for_match(user, gw, match_id)
    now_utc = datetime.now(UTC).isoformat()

    if found:
        row_no, r = found
        key = r.get("key", f"{gw}-{user}-{match_id}")
        values = [
            key, gw, user, match_id, match_label, pick, stake, odds,
            now_utc, r.get("status","OPEN"), r.get("result",""),
            r.get("payout",""), r.get("net",""), r.get("settled_at","")
        ]
        sheet.update(f"A{row_no}:N{row_no}", [values], value_input_option="USER_ENTERED")
    else:
        append_bet_row(gw, user, match_id, match_label, pick, stake, odds)

    user_total_stake_for_gw.clear()
    open_bets_for_match.clear()
