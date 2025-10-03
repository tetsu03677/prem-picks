# google_sheets_client.py
import streamlit as st
import gspread
from typing import Dict, List, Any

# ── 接続 ─────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gc():
    creds_dict = st.secrets["gcp_service_account"]  # Service Account JSON（Secrets）
    return gspread.service_account_from_dict(creds_dict)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]     # スプレッドシートID（Secrets）
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    return _sh().worksheet(name)

# ── config の key-value を dict で取得 ─────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    data = ws("config").get_all_records()
    # 期待するヘッダー: key, value
    conf = {}
    for row in data:
        k = str(row.get("key", "")).strip()
        v = str(row.get("value", "")).strip()
        if k:
            conf[k] = v
    return conf

# ── betsを取得 ─────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def read_bets() -> List[Dict[str, Any]]:
    return ws("bets").get_all_records()

# ── betsに追記 ─────────────────────────────────────────────
def append_bet(row: List[Any]):
    ws("bets").append_row(row, value_input_option="USER_ENTERED")
    # キャッシュ破棄
    read_bets.clear()
