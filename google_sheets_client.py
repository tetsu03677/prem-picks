import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

def _client():
    info = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def _spreadsheet():
    ssid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(ssid)

def ws(sheet_name: str):
    return _spreadsheet().worksheet(sheet_name)

def _records(worksheet):
    return worksheet.get_all_records()

def read_rows_by_sheet(sheet_name: str):
    return _records(ws(sheet_name))

def read_config():
    return read_rows_by_sheet("config")

def upsert_row(sheet_name: str, key_col: str, key_val: str, row_dict: dict):
    sh = ws(sheet_name)
    headers = sh.row_values(1)
    col_index = {h: i+1 for i, h in enumerate(headers)}
    key_col_idx = col_index.get(key_col)

    if key_col_idx is None:
        headers = headers + [k for k in row_dict.keys() if k not in headers]
        sh.resize(rows=sh.row_count, cols=len(headers))
        sh.update("1:1", [headers])
        col_index = {h: i+1 for i, h in enumerate(headers)}
        key_col_idx = col_index[key_col]

    vals = sh.col_values(key_col_idx)
    target_row = None
    for i, v in enumerate(vals[1:], start=2):
        if str(v) == str(key_val):
            target_row = i
            break

    missing = [k for k in row_dict.keys() if k not in col_index]
    if missing:
        headers = headers + missing
        sh.resize(rows=sh.row_count, cols=len(headers))
        sh.update("1:1", [headers])
        col_index = {h: i+1 for i, h in enumerate(headers)}

    row_values = sh.row_values(target_row) if target_row else []
    row_values = (row_values + [""] * (len(headers) - len(row_values)))[:len(headers)]
    for k, v in row_dict.items():
        row_values[col_index[k]-1] = str(v)

    if target_row:
        sh.update(f"{target_row}:{target_row}", [row_values])
    else:
        sh.append_row(row_values, value_input_option="RAW")
