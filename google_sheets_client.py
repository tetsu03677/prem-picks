# prem-picks/google_sheets_client.py
# -*- coding: utf-8 -*-
"""
Googleスプレッドシート クライアント
- append_bet: 追記
- upsert_bet: (gw, match, user) が同じ行なら上書き、なければ追加
- シート/ヘッダがなければ自動作成
"""
from typing import Optional
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials
import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_NAME = "bets"
HEADERS = ["gw", "match", "user", "bet_team", "stake", "odds", "timestamp"]

def _get_creds():
    info = st.secrets["gcp_service_account"]
    return Credentials.from_service_account_info(info, scopes=SCOPES)

def _get_client():
    return gspread.authorize(_get_creds())

def _get_or_create_sheet(sheet_name=SHEET_NAME):
    key = st.secrets["sheets"]["sheet_id"]
    client = _get_client()
    ss = client.open_by_key(key)
    try:
        ws = ss.worksheet(sheet_name)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=sheet_name, rows=1000, cols=10)
        ws.append_row(HEADERS)
        return ws
    # ヘッダ補正
    header_row = ws.row_values(1)
    if header_row != HEADERS:
        ws.update("A1:G1", [HEADERS])
    return ws

def append_bet(gw, match, user, bet_team, stake, odds, timestamp):
    ws = _get_or_create_sheet()
    ws.append_row([gw, match, user, bet_team, stake, odds, timestamp])

def upsert_bet(gw, match, user, bet_team, stake, odds, timestamp) -> str:
    """
    (gw, match, user) をキーにアップサート。
    既存があれば更新、無ければ追加。戻り値: "updated" or "inserted"
    """
    ws = _get_or_create_sheet()
    rows = ws.get_all_values()
    found_idx = None
    for idx, row in enumerate(rows[1:], start=2):  # 2行目からデータ
        if len(row) >= 3 and row[0] == gw and row[1] == match and row[2] == user:
            found_idx = idx
            break
    values = [gw, match, user, bet_team, str(stake), str(odds), timestamp]
    if found_idx:
        ws.update(f"A{found_idx}:G{found_idx}", [values])
        return "updated"
    else:
        ws.append_row(values)
        return "inserted"

def get_bets_for(gw: str, user: Optional[str] = None):
    """簡易取得（将来の画面用）"""
    ws = _get_or_create_sheet()
    recs = ws.get_all_records()
    if user:
        return [r for r in recs if r.get("gw") == gw and r.get("user") == user]
    return [r for r in recs if r.get("gw") == gw]
