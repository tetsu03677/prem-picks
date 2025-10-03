from typing import Dict, List
import streamlit as st
import gspread

# ── 接続 ───────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gc():
    creds = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds)

@st.cache_resource(show_spinner=False)
def _sh():
    sid = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sid)

def ws(name: str):
    return _sh().worksheet(name)

# ── config を dictで取得 ───────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    sheet = ws("config")
    values = sheet.get_all_values()
    conf = {}
    if not values:
        return conf
    header = values[0]
    for row in values[1:]:
        if not row or len(row) < 2:
            continue
        k = row[0].strip()
        v = row[1]
        if k:
            conf[k] = v
    return conf

# ── シート読み書き（ヘッダー含め2次元配列で扱う） ─────────────────
@st.cache_data(ttl=10, show_spinner=False)
def read_sheet(name: str) -> List[List[str]]:
    return ws(name).get_all_values()

def write_sheet(name: str, values: List[List[str]]) -> None:
    sheet = ws(name)
    sheet.clear()
    if values:
        sheet.update("A1", values)
    # 変更が反映されたのでキャッシュをクリア
    read_sheet.clear()
    read_config.clear()
