from __future__ import annotations

import time
from typing import Dict, List, Any

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


# -------- Low-level --------
def _client() -> gspread.Client:
    info = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def _spreadsheet():
    ssid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(ssid)

def ws(sheet_name: str):
    sh = _spreadsheet()
    try:
        return sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=sheet_name, rows=1000, cols=26)

def _records(worksheet) -> List[Dict[str, Any]]:
    vals = worksheet.get_all_values()
    if not vals:
        return []
    headers = vals[0]
    out: List[Dict[str, Any]] = []
    for row in vals[1:]:
        if any(c.strip() for c in row):
            out.append({h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)})
    return out


# -------- High-level --------
def read_rows_by_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    return _records(ws(sheet_name))

def read_config() -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    for r in _records(ws("config")):
        k = (r.get("key") or "").strip()
        v = (r.get("value") or "").strip()
        if k:
            cfg[k] = v
    return cfg

def upsert_row(sheet_name: str, key_col: str, key_value: str, data: Dict[str, Any]) -> None:
    w = ws(sheet_name)
    rows = _records(w)

    headers = w.row_values(1)
    new_headers = list(dict.fromkeys([*headers, *data.keys()]))
    if new_headers != headers:
        w.update([new_headers], "A1")
        time.sleep(0.4)

    # search (0-based in rows, +2 to get sheet row)
    idx = None
    for i, r in enumerate(rows):
        if str(r.get(key_col, "")).strip() == str(key_value).strip():
            idx = i
            break

    row_vals = [str(data.get(h, "")) for h in new_headers]
    if idx is None:
        w.append_row(row_vals, value_input_option="RAW")
    else:
        rno = idx + 2
        w.update(
            f"A{rno}:{chr(64+len(new_headers))}{rno}",
            [row_vals],
            value_input_option="RAW",
        )

def append_row(sheet_name: str, data: Dict[str, Any]) -> None:
    w = ws(sheet_name)
    headers = w.row_values(1)
    new_headers = list(dict.fromkeys([*headers, *data.keys()]))
    if new_headers != headers:
        w.update([new_headers], "A1")
        time.sleep(0.4)
    w.append_row([str(data.get(h, "")) for h in new_headers], value_input_option="RAW")
