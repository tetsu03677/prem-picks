# google_sheets_client.py
from __future__ import annotations

import gspread
import streamlit as st

# シート名固定
SHEET_CONFIG = "config"
SHEET_ODDS = "odds"
SHEET_BETS = "bets"

# ------------------------------------------------------------
# 内部：クライアント生成
# ------------------------------------------------------------
@st.cache_resource
def _client() -> gspread.Client:
    creds = st.secrets["gcp_service_account"]
    gc = gspread.service_account_from_dict(creds)
    return gc

@st.cache_resource
def _spreadsheet():
    gc = _client()
    ssid = st.secrets["sheets"]["sheet_id"]
    return gc.open_by_key(ssid)

def ws(sheet_name: str):
    sh = _spreadsheet()
    return sh.worksheet(sheet_name)

# ------------------------------------------------------------
# 便利関数
# ------------------------------------------------------------
def _records(ws_) -> list[dict]:
    try:
        return ws_.get_all_records()
    except Exception:
        return []

def read_rows_by_sheet(sheet_name: str) -> list[dict]:
    return _records(ws(sheet_name))

def read_config_map() -> dict:
    rows = read_rows_by_sheet(SHEET_CONFIG)
    mp = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = str(r.get("value", "")).strip()
        if k:
            mp[k] = v
    return mp

def _find_row_idx_by_key(worksheet, key: str, key_col: str = "key"):
    # 1行目ヘッダ前提、対象列のインデックスを特定
    header = worksheet.row_values(1)
    try:
        idx = header.index(key_col) + 1
    except ValueError:
        # key_col が存在しない場合は失敗
        return None
    # 2行目以降を探索
    col_vals = worksheet.col_values(idx)
    for i, val in enumerate(col_vals[1:], start=2):
        if str(val) == str(key):
            return i
    return None

def _header_index_map(worksheet):
    header = worksheet.row_values(1)
    return {h: i for i, h in enumerate(header, start=1)}

def upsert_row(sheet_name: str, row: dict, key_col: str | None = None, key_cols: list[str] | None = None):
    """
    単一キー（key_col）または複合キー（key_cols）で upsert。
    見つかれば更新、なければ末尾に追加。
    """
    ws_ = ws(sheet_name)
    header_map = _header_index_map(ws_)

    # 書き込む行データ（ヘッダ順に並べる）
    values = [""] * len(header_map)
    for col_name, idx in header_map.items():
        values[idx - 1] = str(row.get(col_name, ""))

    target_row = None

    if key_col:
        row_idx = _find_row_idx_by_key(ws_, str(row.get(key_col, "")), key_col=key_col)
        if row_idx:
            target_row = row_idx

    if key_cols:
        # 全行を読み、複合キー一致を探す
        all_rows = ws_.get_all_records()
        for i, r in enumerate(all_rows, start=2):
            if all(str(r.get(k, "")) == str(row.get(k, "")) for k in key_cols):
                target_row = i
                break

    if target_row:
        ws_.update(f"A{target_row}:{chr(ord('A') + len(values) - 1)}{target_row}", [values])
    else:
        ws_.append_row(values, value_input_option="USER_ENTERED")
