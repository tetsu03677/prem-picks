# /google_sheets_client.py
from __future__ import annotations
from typing import Dict, List
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

# ───────────────────────────────
# 接続ユーティリティ
# ───────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
JST = timezone(timedelta(hours=9))

def _col_label(n: int) -> str:
    """1→A, 26→Z, 27→AA ..."""
    s = ""
    while n > 0:
        n, r = divmod(n-1, 26)
        s = chr(65 + r) + s
    return s

@st.cache_resource(show_spinner=False)
def _client():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.Client(auth=creds)
    gc.session = gspread.auth.AuthorizedSession(creds)
    return gc

@st.cache_resource(show_spinner=False)
def _spreadsheet():
    ssid = st.secrets["sheets"]["sheet_id"]
    gc = _client()
    return gc.open_by_key(ssid)

def ws(name: str):
    return _spreadsheet().worksheet(name)

# ───────────────────────────────
# config 読み込み
# ───────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def read_rows_by_sheet(sheet_name: str) -> List[Dict]:
    try:
        return ws(sheet_name).get_all_records()
    except Exception:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    rows = read_rows_by_sheet("config")
    conf = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = str(r.get("value", "")).strip()
        if k:
            conf[k] = v
    # football_api 側で参照できるようにキャッシュに一部保持
    st.session_state["_conf_cache"] = conf
    return conf

# ───────────────────────────────
# bets 読み書き
# ───────────────────────────────
def _find_row_idx_by_keys(sheet, keys: Dict[str, str|int]) -> int | None:
    """指定カラム群の一致で行番号（1始まり）を返す。ヘッダは1行目なので2行目=データの先頭"""
    rows = sheet.get_all_records()
    for i, r in enumerate(rows, start=2):
        hit = True
        for k, v in keys.items():
            if str(r.get(k)) != str(v):
                hit = False
                break
        if hit:
            return i
    return None

def upsert_bet_row(gw: int, match_id: int, username: str, match: str, pick: str, stake: int, odds: float):
    sheet = ws("bets")
    keys = {"gw": gw, "match_id": match_id, "user": username}
    row_idx = _find_row_idx_by_keys(sheet, keys)
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    values = {
        "gw": gw,
        "match_id": match_id,
        "user": username,
        "match": match,
        "pick": pick,
        "stake": stake,
        "odds": odds,
        "status": "",
        "payout": "",
        "net": "",
        "ts": now
    }
    headers = sheet.row_values(1)
    ordered = [values.get(h, "") for h in headers]
    last_col = _col_label(len(headers))
    if row_idx:
        sheet.update(f"A{row_idx}:{last_col}{row_idx}", [ordered])
    else:
        sheet.append_row(ordered, value_input_option="USER_ENTERED")

def list_bets_by_gw_and_user(gw: int, username: str) -> List[Dict]:
    rows = read_rows_by_sheet("bets")
    return [r for r in rows if str(r.get("gw")) == str(gw) and r.get("user") == username]

def list_bets_by_gw(gw: int) -> List[Dict]:
    rows = read_rows_by_sheet("bets")
    return [r for r in rows if str(r.get("gw")) == str(gw)]

# ───────────────────────────────
# odds 読み書き
# ───────────────────────────────
def upsert_odds_row(gw: int, match_id: int, home_team: str, away_team: str, home_win: float, draw: float, away_win: float):
    sheet = ws("odds")
    keys = {"gw": gw, "match_id": match_id}
    row_idx = _find_row_idx_by_keys(sheet, keys)
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    values = {
        "gw": gw,
        "match_id": match_id,
        "home_team": home_team,
        "away_team": away_team,
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "updated_at": now
    }
    headers = sheet.row_values(1)
    ordered = [values.get(h, "") for h in headers]
    last_col = _col_label(len(headers))
    if row_idx:
        sheet.update(f"A{row_idx}:{last_col}{row_idx}", [ordered])
    else:
        sheet.append_row(ordered, value_input_option="USER_ENTERED")
