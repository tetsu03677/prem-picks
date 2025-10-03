from typing import Dict, List
import streamlit as st
import gspread

# ── 接続（Secrets に gcp_service_account / sheets.sheet_id が必要） ──
@st.cache_resource(show_spinner=False)
def _gc():
    creds = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def _ws(name: str):
    return _sh().worksheet(name)

# ── config の取得（key-value を dict 化） ──
@st.cache_data(ttl=30, show_spinner=False)
def read_config() -> Dict[str, str]:
    recs = _ws("config").get_all_records()
    conf = {}
    for r in recs:
        k = str(r.get("key","")).strip()
        v = str(r.get("value","")).strip()
        if k:
            conf[k] = v
    return conf

# ── bets 読み書き ──
@st.cache_data(ttl=10, show_spinner=False)
def read_bets() -> List[Dict]:
    # 期待ヘッダー: gw, match, user, bet_team, stake, odds, timestamp
    vals = _ws("bets").get_all_records()
    return vals

def upsert_bet_row(gw: str, match: str, user: str, bet_team: str,
                   stake: int, odds: float, ts: str):
    ws = _ws("bets")
    ws.append_row([gw, match, user, bet_team, stake, odds, ts])
    read_bets.clear()  # cacheクリア
