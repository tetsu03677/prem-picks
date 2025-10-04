# google_sheets_client.py
from __future__ import annotations

import json
from typing import Dict, List, Optional
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone

# ---- GSpread クライアント -------------------------------------------------

@st.cache_resource(show_spinner=False)
def _client() -> gspread.Client:
    """
    Secrets のサービスアカウント情報から gspread.Client を生成。
    """
    info = st.secrets.get("gcp_service_account")
    if not info:
        raise RuntimeError("Secrets[gcp_service_account] が設定されていません。")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def _spreadsheet():
    ssid = st.secrets.get("sheets", {}).get("sheet_id")
    if not ssid:
        raise RuntimeError("Secrets[sheets.sheet_id] が設定されていません。")
    return _client().open_by_key(ssid)

def ws(sheet_name: str):
    return _spreadsheet().worksheet(sheet_name)

# ---- 読み書きユーティリティ -----------------------------------------------

def _records(w) -> List[Dict]:
    """
    ヘッダ行をキーにしたレコード配列を返す（空シートでも空配列）。
    """
    try:
        values = w.get_all_records()
    except gspread.exceptions.APIError:
        values = []
    return values or []

def read_rows_by_sheet(sheet_name: str) -> List[Dict]:
    return _records(ws(sheet_name))

def read_config() -> Dict[str, str]:
    """
    config シート => {key: value}
    """
    data = read_rows_by_sheet("config")
    conf = {str(r.get("key", "")).strip(): str(r.get("value", "")).strip() for r in data if r.get("key")}
    return conf

def _header_index_map(w) -> Dict[str, int]:
    header = w.row_values(1)
    return {name: idx+1 for idx, name in enumerate(header)}

def upsert_row(sheet_name: str, key_value: str, row_dict: Dict[str, object], key_col: str = "key") -> None:
    """
    key_col が一致する行を更新。無ければ末尾に挿入。
    ヘッダに存在しないキーは無視、欠損列は空で埋める。
    """
    w = ws(sheet_name)
    header_map = _header_index_map(w)
    # 探索
    cell = None
    try:
        cell = w.find(key_value, in_column=header_map.get(key_col, 1))
    except Exception:
        cell = None

    # 行データをヘッダ順に整形
    max_col = max(header_map.values()) if header_map else 0
    row = ["" for _ in range(max_col)]
    for col_name, col_idx in header_map.items():
        if col_name in row_dict:
            row[col_idx-1] = row_dict[col_name]

    if cell:
        w.update(f"A{cell.row}:{gspread.utils.rowcol_to_a1(cell.row, max_col).rstrip(str(cell.row))}", [row])
    else:
        w.append_row(row, value_input_option="USER_ENTERED")

def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
