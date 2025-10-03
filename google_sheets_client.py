# google_sheets_client.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json
from typing import List, Dict, Any, Optional
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone

# --- Google Sheets client ----------------------------------------------------
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_CLIENT = None
_SHEET = None

def _client():
    global _CLIENT
    if _CLIENT:
        return _CLIENT
    # secrets.toml の [gcp_service_account] と [sheets] を使う
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    _CLIENT = gspread.authorize(creds)
    return _CLIENT

def _spreadsheet():
    global _SHEET
    if _SHEET:
        return _SHEET
    ssid = st.secrets["sheets"]["sheet_id"]
    _SHEET = _client().open_by_key(ssid)
    return _SHEET

def ws(sheet_name: str):
    return _spreadsheet().worksheet(sheet_name)

# --- helpers -----------------------------------------------------------------
def _records(wks) -> List[Dict[str, Any]]:
    """1行目をヘッダとしてレコード化（空行はスキップ）"""
    values = wks.get_all_values()
    if not values:
        return []
    headers = [h.strip() for h in values[0]]
    out = []
    for row in values[1:]:
        if not any(cell.strip() for cell in row):
            continue
        rec = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        out.append(rec)
    return out

def read_rows_by_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    return _records(ws(sheet_name))

def read_config() -> Dict[str, Any]:
    """config シート： key,value を dict 化"""
    rows = read_rows_by_sheet("config")
    conf = {}
    for r in rows:
        k = r.get("key", "").strip()
        v = r.get("value", "").strip()
        if k:
            conf[k] = v
    return conf

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---- odds -------------------------------------------------------------------
def read_odds(gw: str) -> Dict[str, Dict[str, Any]]:
    """odds シートを読み込み、{match_id: {...}} に整形"""
    try:
        rows = read_rows_by_sheet("odds")
    except Exception:
        return {}
    out = {}
    for r in rows:
        if r.get("gw") != gw:
            continue
        out[r.get("match_id")] = r
    return out

def upsert_odds_row(gw: str, match_id: str, home: str, away: str,
                    home_win: str, draw: str, away_win: str, locked: str) -> None:
    w = ws("odds")
    rows = _records(w)
    headers = [h.strip() for h in w.row_values(1)]
    idx = None
    for i, r in enumerate(rows):
        if r.get("gw") == gw and r.get("match_id") == match_id:
            idx = i + 2  # シート行番号
            break
    rec = {
        "gw": gw, "match_id": match_id, "home": home, "away": away,
        "home_win": home_win, "draw": draw, "away_win": away_win,
        "locked": locked, "updated_at": _now_utc_iso()
    }
    row = [rec.get(h, "") for h in headers]
    if idx:
        w.update(f"A{idx}:{chr(64+len(headers))}{idx}", [row])
    else:
        # 追加
        w.append_row(row, value_input_option="USER_ENTERED")

# ---- bets -------------------------------------------------------------------
def read_bets(gw: str) -> List[Dict[str, Any]]:
    try:
        rows = read_rows_by_sheet("bets")
    except Exception:
        return []
    return [r for r in rows if r.get("gw") == gw]

def upsert_bet(gw: str, user: str, match_id: str, match: str,
               pick: str, stake: int, odds: float, placed_at_iso: Optional[str] = None):
    """bets の主キーは (gw, user, match_id)"""
    w = ws("bets")
    rows = _records(w)
    headers = [h.strip() for h in w.row_values(1)]
    row_idx = None
    for i, r in enumerate(rows):
        if r.get("gw") == gw and r.get("user") == user and r.get("match_id") == match_id:
            row_idx = i + 2
            break
    rec = {
        "key": f"{gw}:{user}:{match_id}",
        "gw": gw, "user": user, "match_id": match_id, "match": match,
        "pick": pick, "stake": str(stake), "odds": str(odds),
        "placed_at": placed_at_iso or _now_utc_iso(),
        "status": "OPEN", "result": "", "payout": "", "net": "", "settled_at": ""
    }
    row = [rec.get(h, "") for h in headers]
    if row_idx:
        w.update(f"A{row_idx}:{chr(64+len(headers))}{row_idx}", [row])
    else:
        w.append_row(row, value_input_option="USER_ENTERED")
