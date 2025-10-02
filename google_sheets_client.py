# /google_sheets_client.py
from __future__ import annotations
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

def _get_or_create_ws(title: str, headers: list[str] | None = None):
    sh = _spreadsheet()
    for ws in sh.worksheets():
        if ws.title.strip().lower() == title.strip().lower():
            return ws
    ws = sh.add_worksheet(title=title, rows=2000, cols=26)
    if headers:
        ws.update(f"A1:{chr(64+len(headers))}1", [headers])
    return ws

def ensure_basics():
    # users
    ws_u = _get_or_create_ws("users", ["username","password","role","team","created_at"])
    if len(ws_u.get_all_values()) <= 1:
        ws_u.append_row(["Tetsu","password","admin","Arsenal", _now_jst_str()])
        ws_u.append_row(["Toshiya","password","user","Liverpool", _now_jst_str()])
        ws_u.append_row(["Koki","password","user","Manchester United", _now_jst_str()])
    # config
    ws_c = _get_or_create_ws("config", ["key","value"])
    cfg = {r[0]: r[1] for r in ws_c.get_all_values()[1:]} if len(ws_c.get_all_values())>1 else {}
    defaults = {
        "current_gw": "GW7",
        "bookmaker_username": "Tetsu",
        "lock_minutes_before_earliest": "120",      # 節の最も早いKOの◯分前にロック
        "max_total_stake_per_gw": "5000",           # 1人あたり節の合計上限
        "stake_step": "100",
    }
    to_add = []
    for k,v in defaults.items():
        if k not in cfg:
            to_add.append([k,v])
    if to_add:
        ws_c.append_rows(to_add, value_input_option="RAW")
    # fixtures
    _get_or_create_ws(
        "fixtures",
        ["gw","match_id","kickoff_jst","home_team","away_team","odds_home","odds_draw","odds_away"]
    )
    # bets
    _get_or_create_ws(
        "bets",
        ["key","gw","match_id","match","user","pick","stake","odds","timestamp"]
    )
    # results（勝敗結果 H/D/A を手入力する想定）
    _get_or_create_ws(
        "results",
        ["gw","match_id","result","settled_at"]
    )

def _now_jst_str():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

def read_config() -> dict:
    ws = _get_or_create_ws("config", ["key","value"])
    values = ws.get_all_values()
    if not values:
        return {}
    header = [ (c or "").strip().lower() for c in values[0] ]
    ki = header.index("key") if "key" in header else 0
    vi = header.index("value") if "value" in header else 1
    out = {}
    for row in values[1:]:
        if len(row) <= max(ki,vi): 
            continue
        k = (row[ki] or "").strip()
        v = (row[vi] or "").strip()
        if k: out[k]=v
    return out

def list_users() -> list[dict]:
    ws = _get_or_create_ws("users", ["username","password","role","team","created_at"])
    rows = ws.get_all_records()
    return rows

def get_user(username: str) -> dict | None:
    users = list_users()
    for u in users:
        if (u.get("username") or "").strip() == username:
            return u
    return None

def list_fixtures(gw: str) -> list[dict]:
    ws = _get_or_create_ws("fixtures", ["gw","match_id","kickoff_jst","home_team","away_team","odds_home","odds_draw","odds_away"])
    rows = ws.get_all_records()
    return [r for r in rows if str(r.get("gw")).strip()==gw]

def list_bets(user: str | None = None) -> list[dict]:
    ws = _get_or_create_ws("bets", ["key","gw","match_id","match","user","pick","stake","odds","timestamp"])
    rows = ws.get_all_records()
    if user:
        rows = [r for r in rows if (r.get("user") or "").strip()==user]
    return rows

def upsert_bet(record: dict):
    """key=gw|user|match_id で更新/追加"""
    ws = _get_or_create_ws("bets", ["key","gw","match_id","match","user","pick","stake","odds","timestamp"])
    values = ws.get_all_values()
    header = [ (c or "").strip().lower() for c in values[0] ] if values else []
    if not header:
        header = ["key","gw","match_id","match","user","pick","stake","odds","timestamp"]
        ws.update("A1:I1", [header])
        values = ws.get_all_values()
    data = [dict(zip(header, r)) for r in values[1:]]
    key = record.get("key","")
    target_row = None
    for idx, row in enumerate(data, start=2):
        if (row.get("key") or "") == key:
            target_row = idx
            break
    ordered = [str(record.get(h,"")) for h in header]
    if target_row:
        ws.update(f"A{target_row}:{chr(64+len(header))}{target_row}", [ordered])
    else:
        ws.append_row(ordered, value_input_option="USER_ENTERED")

def list_results() -> dict[tuple[str,str], str]:
    """返り値: {(gw, match_id): result(H/D/A)}"""
    ws = _get_or_create_ws("results", ["gw","match_id","result","settled_at"])
    rows = ws.get_all_records()
    out = {}
    for r in rows:
        gw = (r.get("gw") or "").strip()
        mid= (r.get("match_id") or "").strip()
        res= (r.get("result") or "").strip().upper()
        if gw and mid and res:
            out[(gw,mid)] = res
    return out
