from __future__ import annotations
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _client():
    sa_keys = [
        "type","project_id","private_key_id","private_key","client_email","client_id",
        "auth_uri","token_uri","auth_provider_x509_cert_url","client_x509_cert_url",
    ]
    info = {k: st.secrets[k] for k in sa_keys if k in st.secrets}
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)

def _open_by_key():
    sid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(sid)

def worksheet(name: str):
    return _open_by_key().worksheet(name)

def read_config_dict(sheet_name: str = "config") -> dict:
    """キャッシュなし・ヘッダ自動検出で堅牢に読む"""
    try:
        ws = worksheet(sheet_name)
        values = ws.get_all_values()
    except Exception:
        return {}

    if not values:
        return {}

    # ヘッダ列位置を case-insensitive で探す。見つからなければ 0/1 列目
    header = [ (h or "").strip().lower() for h in values[0] ]
    try:
        ki = header.index("key")
    except ValueError:
        ki = 0
    try:
        vi = header.index("value")
    except ValueError:
        vi = 1

    cfg = {}
    for row in values[1:]:
        if len(row) <= max(ki, vi):
            continue
        k = (row[ki] or "").strip()
        v = (row[vi] or "").strip()
        if k:
            cfg[k] = v
    return cfg

def get_config_value(key: str, default: str | None = None) -> str | None:
    return read_config_dict().get(key, default)
