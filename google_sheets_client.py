from __future__ import annotations

import time
from typing import Dict, List, Any, Optional

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ===== Low-level helpers =====
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
    gc = _client()
    return gc.open_by_key(ssid)

def ws(sheet_name: str):
    sh = _spreadsheet()
    try:
        return sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        # Auto-create sheet with no headers; caller can decide to write
        return sh.add_worksheet(title=sheet_name, rows=1000, cols=26)

def _records(worksheet) -> List[Dict[str, Any]]:
    vals = worksheet.get_all_values()
    if not vals:
        return []
    headers = vals[0]
    recs: List[Dict[str, Any]] = []
    for row in vals[1:]:
        if any(c.strip() for c in row):
            recs.append({h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)})
    return recs

# ===== High-level helpers =====
def read_rows_by_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    return _records(ws(sheet_name))

def read_config() -> Dict[str, str]:
    """config シート(A:key, B:value)を dict 化"""
    cfg: Dict[str, str] = {}
    rows = _records(ws("config"))
    for r in rows:
        k = (r.get("key") or "").strip()
        v = (r.get("value") or "").strip()
        if k:
            cfg[k] = v
    return cfg

def upsert_row(sheet_name: str, key_col: str, key_value: str, data: Dict[str, Any]) -> None:
    """key_col==key_value の行を更新。無ければヘッダ補完の上で末尾に追加。"""
    w = ws(sheet_name)
    recs = _records(w)
    # ヘッダ整備
    headers = w.row_values(1)
    all_keys = list(dict.fromkeys([*headers, *data.keys()]))
    if all_keys != headers:
        # ヘッダ更新
        w.update([all_keys], "A1")
        # 少し待つ（Google API の保護）
        time.sleep(0.5)

    # 行探索
    target_idx = None
    for i, r in enumerate(recs):
        if str(r.get(key_col, "")).strip() == str(key_value).strip():
            target_idx = i  # 0-based for recs; +2 is the sheet row
            break

    row_vals = [str(data.get(h, "")) for h in all_keys]
    if target_idx is None:
        # append
        w.append_row(row_vals, value_input_option="RAW")
    else:
        # update existing
        row_no = target_idx + 2
        w.update(f"A{row_no}:{chr(64+len(all_keys))}{row_no}", [row_vals], value_input_option="RAW")

def append_row(sheet_name: str, data: Dict[str, Any]) -> None:
    w = ws(sheet_name)
    headers = w.row_values(1)
    new_headers = list(dict.fromkeys([*headers, *data.keys()]))
    if new_headers != headers:
        w.update([new_headers], "A1")
        time.sleep(0.4)
    w.append_row([str(data.get(h, "")) for h in new_headers], value_input_option="RAW")
