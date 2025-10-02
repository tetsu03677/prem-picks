# /google_sheets_client.py
from __future__ import annotations
import json
from typing import Any, Dict, List, Tuple, Optional

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _client():
    fields = [
        "type","project_id","private_key_id","private_key","client_email","client_id",
        "auth_uri","token_uri","auth_provider_x509_cert_url","client_x509_cert_url","universe_domain"
    ]
    info = {k: st.secrets[k] for k in fields}
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)

def _spreadsheet():
    sid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(sid)

def _get_ws(title: str):
    # 既存シートのみ使用（新規作成しない方針）
    sh = _spreadsheet()
    for ws in sh.worksheets():
        if ws.title.strip().lower() == title.strip().lower():
            return ws
    raise RuntimeError(f"Worksheet '{title}' is missing. Please create it in the spreadsheet.")

def now_jst_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

# -------- config --------
def read_config_raw() -> Dict[str, str]:
    ws = _get_ws("config")
    values = ws.get_all_values()
    if not values:
        return {}
    header = [(c or "").strip().lower() for c in values[0]]
    try:
        ki = header.index("key")
    except ValueError:
        ki = 0
    try:
        vi = header.index("value")
    except ValueError:
        vi = 1
    out: Dict[str, str] = {}
    for row in values[1:]:
        if len(row) <= max(ki, vi):
            continue
        k = (row[ki] or "").strip()
        v = (row[vi] or "").strip()
        if k:
            out[k] = v
    return out

def get_config_value(key: str, default: Optional[str] = None) -> Optional[str]:
    return read_config_raw().get(key, default)

def set_config_value(key: str, value: str) -> None:
    """管理者のみが使う想定。configの key/value を上書き or 追加"""
    ws = _get_ws("config")
    values = ws.get_all_values()
    if not values:
        ws.update("A1:B1", [["key","value"]])
        values = ws.get_all_values()
    header = [(c or "").strip().lower() for c in values[0]]
    try:
        ki = header.index("key")
    except ValueError:
        ki = 0
    try:
        vi = header.index("value")
    except ValueError:
        vi = 1
    # 探索
    target_row = None
    for idx, row in enumerate(values[1:], start=2):
        if len(row) > ki and (row[ki] or "").strip() == key:
            target_row = idx
            break
    if target_row:
        ws.update(f"A{target_row}:B{target_row}", [[key, value]])
    else:
        ws.append_row([key, value], value_input_option="RAW")

def read_users_from_config() -> List[Dict[str, Any]]:
    raw = get_config_value("users_json", "[]")
    try:
        users = json.loads(raw)
        if isinstance(users, list):
            return users
    except Exception:
        pass
    return []

# -------- bets --------
BET_HEADERS = ["key","gw","user","match_id","match","pick","stake","odds","placed_at","status","result","payout","net","settled_at"]

def ensure_bets_headers() -> None:
    ws = _get_ws("bets")
    vals = ws.get_all_values()
    if not vals:
        ws.update(f"A1:N1", [BET_HEADERS])
        return
    header = [(c or "").strip().lower() for c in vals[0]]
    if len(header) < len(BET_HEADERS) or any(h1 != h2 for h1, h2 in zip(header, [h.lower() for h in BET_HEADERS])):
        # 上書き（既存データがある場合は必要に応じて移行して下さい）
        ws.clear()
        ws.update(f"A1:N1", [BET_HEADERS])

def list_bets(user: Optional[str] = None, gw: Optional[str] = None) -> List[Dict[str, Any]]:
    ws = _get_ws("bets")
    vals = ws.get_all_values()
    if not vals or len(vals) == 1:
        return []
    header = [c.strip() for c in vals[0]]
    rows = [dict(zip(header, r)) for r in vals[1:]]
    if user:
        rows = [r for r in rows if (r.get("user") or "").strip() == user]
    if gw:
        rows = [r for r in rows if (r.get("gw") or "").strip() == gw]
    return rows

def upsert_bet_record(record: Dict[str, Any]) -> None:
    """key=gw|user|match_id で upsert"""
    ensure_bets_headers()
    ws = _get_ws("bets")
    vals = ws.get_all_values()
    header = [c.strip() for c in vals[0]]
    data = [dict(zip(header, r)) for r in vals[1:]]
    key = str(record.get("key",""))
    target_row = None
    for idx, row in enumerate(data, start=2):
        if (row.get("key") or "") == key:
            target_row = idx
            break
    ordered = [str(record.get(h, "")) for h in header]
    if target_row:
        ws.update(f"A{target_row}:{chr(64+len(header))}{target_row}", [ordered])
    else:
        ws.append_row(ordered, value_input_option="USER_ENTERED")
