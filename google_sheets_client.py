# google_sheets_client.py
from __future__ import annotations
import streamlit as st
import gspread
from typing import Dict, Any

# --- 内部: クライアント生成（呼ばれた時だけ secrets を読む） ---
@st.cache_resource(show_spinner=False)
def _gc():
    creds = st.secrets["gcp_service_account"]  # ここではじめて参照
    return gspread.service_account_from_dict(creds)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    """ワークシート取得（例: ws('config') / ws('bets')）。"""
    return _sh().worksheet(name)

# --- config 読み込み（key-value で返す）---
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    rows = ws("config").get_all_records()  # 期待: A列=key, B列=value
    conf: Dict[str, str] = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = str(r.get("value", "")).strip()
        if k:
            conf[k] = v
    return conf
