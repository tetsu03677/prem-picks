# google_sheets_client.py
import json
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _client():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def _spreadsheet():
    sid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(sid)

def ws(sheet_name):
    return _spreadsheet().worksheet(sheet_name)

def _records(w):
    vals = w.get_all_records()
    return [{k.strip(): (v if v != "" else "") for k,v in row.items()} for row in vals]

def read_rows_by_sheet(sheet_name):
    return _records(ws(sheet_name))

def read_config():
    return read_rows_by_sheet("config")

def upsert_row(sheet_name, key_col, row: dict):
    """row に '_delete': True を含めるとそのキー行を削除"""
    w = ws(sheet_name)
    data = _records(w)
    key = row[key_col]
    idx = next((i for i,r in enumerate(data) if str(r.get(key_col))==str(key)), -1)
    if row.get("_delete"):
        if idx>=0:
            w.delete_rows(idx+2)  # header分+1
        return
    # 既存 -> 更新、無ければ追加
    headers = w.row_values(1)
    if idx>=0:
        for k,v in row.items():
            if k in headers:
                w.update_cell(idx+2, headers.index(k)+1, v)
    else:
        append = [row.get(h,"") for h in headers]
        w.append_row(append, value_input_option="USER_ENTERED")

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")
