import json
import time
from typing import List, Dict, Any, Optional

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ---- low level --------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _client():
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def _spreadsheet():
    gc = _client()
    ssid = st.secrets["sheets"]["sheet_id"]
    return gc.open_by_key(ssid)

def ws(sheet_name: str):
    return _spreadsheet().worksheet(sheet_name)

# ---- utilities --------------------------------------------------------------
def _records(sh) -> List[Dict[str, Any]]:
    """worksheet → list of records (first row is header). 空シートは [] を返す"""
    vals = sh.get_all_values()
    if not vals:
        return []
    header = vals[0]
    recs = []
    for row in vals[1:]:
        item = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
        if any(v != "" for v in item.values()):
            recs.append(item)
    return recs

def read_rows_by_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    return _records(ws(sheet_name))

def read_config() -> Dict[str, str]:
    cfg_rows = read_rows_by_sheet("config")
    cfg = {r.get("key", ""): r.get("value", "") for r in cfg_rows if r.get("key")}
    return cfg

def parse_users_from_config(cfg: Dict[str, str]) -> List[Dict[str, Any]]:
    raw = cfg.get("users_json", "").strip()
    if not raw:
        return []
    try:
        users = json.loads(raw)
        # normalize fields / minimal validation
        norm = []
        for u in users:
            norm.append({
                "username": str(u.get("username", "")).strip(),
                "password": str(u.get("password", "")).strip(),
                "role": (u.get("role") or "user").strip(),
                "team": (u.get("team") or "").strip(),
            })
        # remove empty usernames / duplicates by last one wins
        uniq = {}
        for u in norm:
            if u["username"]:
                uniq[u["username"]] = u
        return list(uniq.values())
    except Exception:
        return []

def upsert_row(sheet_name: str, key_col: str, key_value: str, payload: Dict[str, Any]) -> None:
    """key_col の値で行を探し、あれば更新、無ければ末尾に追加"""
    sh = ws(sheet_name)
    rows = sh.get_all_records()
    headers = sh.row_values(1)
    if key_col not in headers:
        # 1 行目にヘッダがない場合は作る
        if not headers:
            headers = list(payload.keys())
            sh.append_row(headers)
        else:
            headers.append(key_col)
            for k in payload.keys():
                if k not in headers:
                    headers.append(k)
            sh.update("1:1", [headers])
    # map index
    key_idx = headers.index(key_col) + 1
    found_row = None
    for i, row in enumerate(rows, start=2):
        if str(row.get(key_col, "")) == str(key_value):
            found_row = i
            break
    # align values by header order
    row_values = []
    for h in headers:
        row_values.append(payload.get(h, "" if h != key_col else key_value))
    if found_row:
        sh.update(f"{found_row}:{found_row}", [row_values])
    else:
        sh.append_row(row_values, value_input_option="USER_ENTERED")

def read_bets() -> List[Dict[str, Any]]:
    try:
        return read_rows_by_sheet("bets")
    except Exception:
        return []

def read_odds() -> List[Dict[str, Any]]:
    try:
        return read_rows_by_sheet("odds")
    except Exception:
        return []
