from __future__ import annotations
from typing import Dict, Any
from datetime import datetime

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SHEET_NAMES = {"config", "odds", "bets"}

def _client():
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

def _ws(name: str):
    assert name in SHEET_NAMES, f"unknown sheet: {name}"
    ssid = st.secrets["sheets"]["sheet_id"]
    return _client().open_by_key(ssid).worksheet(name)

def read_config_map() -> Dict[str, str]:
    ws = _ws("config")
    rows = ws.get_all_records()
    conf = {}
    for r in rows:
        k = str(r.get("key","")).strip()
        v = "" if r.get("value") is None else str(r.get("value"))
        if k: conf[k] = v
    return conf

def read_sheet_as_df(name: str) -> pd.DataFrame:
    ws = _ws(name)
    values = ws.get_all_values()
    if not values: return pd.DataFrame()
    header, data = values[0], values[1:]
    df = pd.DataFrame(data, columns=header)
    if name == "bets" and not df.empty:
        for c in ["stake","odds","payout","net"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    if name == "odds" and not df.empty:
        for c in ["home_win","draw","away_win"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def upsert_bet_row(payload: Dict[str, Any]):
    """
    必須列は提示どおり固定:
    bets: key, gw, user, match_id, match, pick, stake, odds, placed_at, status, result, payout, net, settled_at
    """
    ws = _ws("bets")
    df = read_sheet_as_df("bets")
    key = f"{payload.get('gw','')}:{payload.get('user','')}:{payload.get('match_id','')}"
    row = {
        "key": key,
        "gw": payload.get("gw",""),
        "user": payload.get("user",""),
        "match_id": str(payload.get("match_id","")),
        "match": payload.get("match",""),
        "pick": payload.get("pick",""),
        "stake": payload.get("stake",""),
        "odds": payload.get("odds",""),
        "placed_at": payload.get("placed_at", datetime.utcnow().isoformat(timespec="seconds")),
        "status": payload.get("status","OPEN"),
        "result": payload.get("result",""),
        "payout": payload.get("payout",""),
        "net": payload.get("net",""),
        "settled_at": payload.get("settled_at",""),
    }

    if df.empty:
        ws.append_row(list(row.values()))
        return

    # 既存上書き or 追加
    if "key" in df.columns:
        idx = df.index[df["key"] == key].tolist()
        if idx:
            row_index = idx[0] + 2  # header offset
            for i, col in enumerate(df.columns, start=1):
                ws.update_cell(row_index, i, row.get(col, ""))
        else:
            ws.append_row([row.get(col, "") for col in df.columns])
    else:
        ws.append_row([row.get(col, "") for col in df.columns])
