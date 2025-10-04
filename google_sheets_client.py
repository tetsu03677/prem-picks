# /google_sheets_client.py
from __future__ import annotations
from typing import Dict, List
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
JST = timezone(timedelta(hours=9))

def _col_label(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n-1, 26)
        s = chr(65 + r) + s
    return s

@st.cache_resource(show_spinner=False)
def _client():
    info = st.secrets["gcp_service_account"]  # secrets.toml に service account を設定
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.Client(auth=creds)
    gc.session = gspread.auth.AuthorizedSession(creds)
    return gc

@st.cache_resource(show_spinner=False)
def _spreadsheet():
    ssid = st.secrets["sheets"]["sheet_id"]   # スプレッドシートID
    gc = _client()
    return gc.open_by_key(ssid)

def ws(name: str):
    return _spreadsheet().worksheet(name)

@st.cache_data(ttl=60, show_spinner=False)
def read_rows_by_sheet(sheet_name: str) -> List[Dict]:
    try:
        return ws(sheet_name).get_all_records()
    except Exception:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    rows = read_rows_by_sheet("config")
    conf: Dict[str, str] = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = str(r.get("value", "")).strip()
        if k:
            conf[k] = v
    # football_api で利用するため保持
    st.session_state["_conf_cache"] = conf
    return conf

def _find_row_idx_by_keys(sheet, keys: Dict[str, str|int]) -> int | None:
    rows = sheet.get_all_records()
    for i, r in enumerate(rows, start=2):  # 2=データ先頭（1行目はヘッダ）
        if all(str(r.get(k)) == str(v) for k, v in keys.items()):
            return i
    return None

# ---- bets ----
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

# ---- odds ----
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
