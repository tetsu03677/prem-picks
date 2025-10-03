from __future__ import annotations
import json
from typing import Dict, List, Any, Optional
import streamlit as st
import gspread

# ====== 接続 ======
@st.cache_resource(show_spinner=False)
def _gc():
    # Streamlit Secrets にサービスアカウント & シートIDを設定済み前提
    creds = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds)

@st.cache_resource(show_spinner=False)
def _sheet():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    return _sheet().worksheet(name)

# ====== config 読み書き ======
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    data = ws("config").get_all_records()
    conf: Dict[str, str] = {}
    for row in data:
        k = str(row.get("key", "")).strip()
        v = row.get("value", "")
        if k:
            conf[k] = str(v).strip()
    return conf

# ====== users_json からユーザー一覧 ======
@st.cache_data(ttl=60, show_spinner=False)
def load_users() -> List[Dict[str, str]]:
    conf = read_config()
    raw = conf.get("users_json", "").strip()
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []

# ====== bets ======
def append_bet(rec: Dict[str, Any]) -> None:
    ws_bets = ws("bets")
    values = [
        rec.get("key",""),
        rec.get("gw",""),
        rec.get("user",""),
        rec.get("match_id",""),
        rec.get("match",""),
        rec.get("pick",""),
        rec.get("stake",""),
        rec.get("odds",""),
        rec.get("placed_at",""),
        rec.get("status",""),
        rec.get("result",""),
        rec.get("payout",""),
        rec.get("net",""),
        rec.get("settled_at",""),
    ]
    ws_bets.append_row(values, value_input_option="USER_ENTERED")

@st.cache_data(ttl=30, show_spinner=False)
def read_bets(gw: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = ws("bets").get_all_records()
    return [r for r in rows if (gw is None or str(r.get("gw")) == str(gw))]

# ====== odds ======
@st.cache_data(ttl=10, show_spinner=False)
def read_odds(gw: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = ws("odds").get_all_records()
    return [r for r in rows if (gw is None or str(r.get("gw")) == str(gw))]

def upsert_odds(rows: List[Dict[str, Any]], gw: str) -> None:
    """
    rows: [{gw, match_id, home, away, home_win, draw, away_win, locked, updated_at}, ...]
    同じ gw の既存行を削除 → 新行を書き込み
    """
    sh = ws("odds")
    all_vals = sh.get_all_values()
    # ヘッダを探す（1行目前提）
    header = all_vals[0] if all_vals else []
    # 既存の gw の行 index を抽出
    delete_idx = []
    for i, r in enumerate(all_vals[1:], start=2):  # 2行目以降
        if len(r) > 0 and str(r[0]) == str(gw):
            delete_idx.append(i)
    # 下から削除
    for i in reversed(delete_idx):
        sh.delete_rows(i)

    # 追記
    to_append = []
    for r in rows:
        to_append.append([
            r.get("gw",""),
            r.get("match_id",""),
            r.get("home",""),
            r.get("away",""),
            r.get("home_win",""),
            r.get("draw",""),
            r.get("away_win",""),
            r.get("locked",""),
            r.get("updated_at",""),
        ])
    if to_append:
        sh.append_rows(to_append, value_input_option="USER_ENTERED")
