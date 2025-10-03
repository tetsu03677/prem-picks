from __future__ import annotations
import json
from typing import Dict, Any, List
import streamlit as st
import gspread
import pandas as pd

# ─────────────────────────────────────────────────────────────────────
# Google Sheets 接続
# ─────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gc() -> gspread.Client:
    creds_dict = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds_dict)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    return _sh().worksheet(name)

# ─────────────────────────────────────────────────────────────────────
# 設定(config) 読み込み
# ─────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    table = ws("config").get_all_records()
    conf: Dict[str, str] = {}
    for row in table:
        k = str(row.get("key", "")).strip()
        v = "" if row.get("value") is None else str(row.get("value")).strip()
        if k:
            conf[k] = v
    return conf

# users_json を安全に辞書化
def read_users_from_config(conf: Dict[str, str]) -> List[Dict[str, Any]]:
    raw = conf.get("users_json", "").strip()
    if not raw:
        return [{"username":"guest","password":"guest","role":"user","team":"Neutral"}]
    try:
        return json.loads(raw)
    except Exception:
        return [{"username":"guest","password":"guest","role":"user","team":"Neutral"}]

# ─────────────────────────────────────────────────────────────────────
# odds / bets の DataFrame ユーティリティ
# ─────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def load_odds_df() -> pd.DataFrame:
    data = ws("odds").get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=[
            "gw","match_id","home","away","home_win","draw","away_win","locked","updated_at"
        ])
    return df

@st.cache_data(ttl=30, show_spinner=False)
def load_bets_df() -> pd.DataFrame:
    data = ws("bets").get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=[
            "key","gw","user","match_id","match","pick","stake","odds",
            "placed_at","status","result","payout","net","settled_at"
        ])
    return df

def append_bet_row(row: List[Any]) -> None:
    ws("bets").append_row(row, value_input_option="USER_ENTERED")

def upsert_odds_rows(rows: List[List[Any]]) -> None:
    """管理者画面からの一括上書き用（今回は土台だけ）"""
    w = ws("odds")
    # ヘッダは行1固定、2行目以降をクリア→書き込み
    last_row = len(w.get_all_values())
    if last_row >= 2:
        w.batch_clear([f"A2:I{last_row}"])
    if rows:
        w.update(f"A2:I{1+len(rows)}", rows, value_input_option="USER_ENTERED")
