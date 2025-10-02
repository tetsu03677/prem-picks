from __future__ import annotations
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# サービスアカウントは Secrets の JSON を使用（←これは従来どおり）
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource(show_spinner=False)
def _client():
    sa_keys = [
        "type","project_id","private_key_id","private_key","client_email","client_id",
        "auth_uri","token_uri","auth_provider_x509_cert_url","client_x509_cert_url",
    ]
    info = {k: st.secrets[k] for k in sa_keys if k in st.secrets}
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def _open_by_key():
    sid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(sid)

def worksheet(name: str):
    return _open_by_key().worksheet(name)

@st.cache_data(ttl=300, show_spinner=False)
def read_config_dict(sheet_name: str = "config") -> dict:
    try:
        ws = worksheet(sheet_name)
        rows = ws.get_all_records()
    except Exception:
        return {}
    cfg = {}
    for r in rows:
        k = str(r.get("key","")).strip()
        v = str(r.get("value","")).strip()
        if k:
            cfg[k] = v
    return cfg

def get_config_value(key: str, default: str | None = None) -> str | None:
    return read_config_dict().get(key, default)
