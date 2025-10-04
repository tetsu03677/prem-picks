from __future__ import annotations
from typing import Dict, List
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource
def _client():
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPE)
    return gspread.authorize(creds)

def _spreadsheet():
    ssid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(ssid)

def ws(sheet_name: str):
    return _spreadsheet().worksheet(sheet_name)

def _records(w):
    rows = w.get_all_records()
    # ヘッダが空の列は捨てる
    clean = []
    for r in rows:
        clean.append({k: v for k,v in r.items() if k})
    return clean

def read_rows_by_sheet(sheet_name: str) -> List[Dict]:
    return _records(ws(sheet_name))

def read_config() -> List[Dict]:
    return read_rows_by_sheet("config")

def read_bets() -> List[Dict]:
    return read_rows_by_sheet("bets")

def read_odds() -> List[Dict]:
    return read_rows_by_sheet("odds")

def upsert_row(sheet: str, keys: List[str], row: Dict):
    w = ws(sheet)
    rows = w.get_all_records()
    # 探索
    keyvals = tuple(str(row.get(k,"")) for k in keys)
    hit_idx = None
    for i, r in enumerate(rows, start=2):  # 2 = header 1行分
        if tuple(str(r.get(k,"")) for k in keys) == keyvals:
            hit_idx = i
            break
    # 書き込み（ヘッダ整列）
    header = w.row_values(1)
    values = [row.get(h,"") for h in header]
    if hit_idx:
        w.update(f"A{hit_idx}:{chr(64+len(header))}{hit_idx}", [values])
    else:
        w.append_row(values, value_input_option="USER_ENTERED")
