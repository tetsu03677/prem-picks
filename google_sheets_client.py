from typing import Dict, Any, List
import streamlit as st
import gspread

# ── 接続（Secrets から） ────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gc() -> gspread.Client:
    # Secrets 例：
    # [gcp_service_account]  ← jsonの各フィールド
    # [sheets]
    # sheet_id = "xxxxx"
    creds_dict = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds_dict)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    return _sh().worksheet(name)

# ── config の読み出し（key-value） ──────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def read_config() -> Dict[str, str]:
    rows = ws("config").get_all_records()
    conf: Dict[str, str] = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = str(r.get("value", "")).strip()
        if k:
            conf[k] = v
    return conf

# 参考：bets への書き込み系は次ステップで追加予定
