# google_sheets_client.py
from __future__ import annotations
from typing import Dict, Any
import gspread
import streamlit as st

# ── 接続 ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _gc():
    creds_dict = st.secrets["gcp_service_account"]
    return gspread.service_account_from_dict(creds_dict)

@st.cache_resource(show_spinner=False)
def _sh():
    sheet_id = st.secrets["sheets"]["sheet_id"]
    return _gc().open_by_key(sheet_id)

def ws(name: str):
    return _sh().worksheet(name)

# ── config 読み込み ─────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def read_config() -> Dict[str, str]:
    rows = ws("config").get_all_records()
    conf = {}
    for row in rows:
        k = str(row.get("key", "")).strip()
        v = str(row.get("value", "")).strip()
        if k:
            conf[k] = v
    return conf

# ── odds 読み込み（map: match_id -> dict）────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def read_odds_map_for_gw(gw: int) -> Dict[str, Dict[str, float]]:
    """
    odds シートの該当GWを辞書化
    { str(match_id): {"home": float, "draw": float, "away": float, "locked": bool} }
    """
    try:
        rows = ws("odds").get_all_records()
    except Exception:
        rows = []
    m: Dict[str, Dict[str, float]] = {}
    for r in rows:
        try:
            if str(r.get("gw")).strip() != str(gw):
                continue
            match_id = str(r.get("match_id")).strip()
            if not match_id:
                continue
            m[match_id] = {
                "home": float(r.get("home_win") or 0) or 0.0,
                "draw": float(r.get("draw") or 0) or 0.0,
                "away": float(r.get("away_win") or 0) or 0.0,
                "locked": str(r.get("locked") or "").strip().lower() in ("1", "true", "yes"),
            }
        except Exception:
            # 変な行はスキップ
            pass
    return m
