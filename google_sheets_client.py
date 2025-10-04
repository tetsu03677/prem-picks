from __future__ import annotations
from typing import Dict, Any, List
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime

# シート固定: config / odds / bets
SHEET_NAMES = {"config", "odds", "bets"}

def _client():
    info = st.secrets["gcp_service_account"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def _ws(sheet_name: str):
    assert sheet_name in SHEET_NAMES, f"unknown sheet: {sheet_name}"
    gc = _client()
    ssid = st.secrets["sheets"]["sheet_id"]
    sh = gc.open_by_key(ssid)
    return sh.worksheet(sheet_name)

def read_config_map() -> Dict[str, str]:
    ws = _ws("config")
    rows = ws.get_all_records()
    conf = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = "" if r.get("value") is None else str(r.get("value"))
        if k:
            conf[k] = v
    return conf

def read_sheet_as_df(sheet_name: str) -> pd.DataFrame:
    ws = _ws(sheet_name)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()
    header, data = values[0], values[1:]
    df = pd.DataFrame(data, columns=header)
    # 型整形（存在すれば）
    if sheet_name == "bets" and not df.empty:
        for col in ["stake", "odds", "payout", "net"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    if sheet_name == "odds" and not df.empty:
        for col in ["home_win", "draw", "away_win"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

def upsert_bet_row(payload: Dict[str, Any]):
    """
    payload 例:
    {
        "gw":"GW7","user":"Tetsu","match_id":"537845","match":"A vs B",
        "pick":"HOME","stake":200,"odds":1.95,"placed_at":"...","status":"OPEN",...
    }
    key = f"{gw}:{user}:{match_id}"
    """
    ws = _ws("bets")
    df = read_sheet_as_df("bets")
    key = f"{payload.get('gw','')}:{payload.get('user','')}:{payload.get('match_id','')}"
    payload_key = {"key": key}
    row_dict = {
        "key": key,
        "gw": payload.get("gw", ""),
        "user": payload.get("user", ""),
        "match_id": str(payload.get("match_id", "")),
        "match": payload.get("match", ""),
        "pick": payload.get("pick", ""),
        "stake": payload.get("stake", ""),
        "odds": payload.get("odds", ""),
        "placed_at": payload.get("placed_at", datetime.utcnow().isoformat(timespec="seconds")),
        "status": payload.get("status", "OPEN"),
        "result": payload.get("result", ""),
        "payout": payload.get("payout", ""),
        "net": payload.get("net", ""),
        "settled_at": payload.get("settled_at", ""),
    }

    if df.empty:
        # ヘッダーがある前提だが、空なら append_row
        ws.append_row(list(row_dict.values()))
        return

    if "key" in df.columns:
        idx = df.index[df["key"] == key].tolist()
        if idx:
            # 上書き
            row_index_1based = idx[0] + 2  # header行を加味
            for i, col in enumerate(df.columns, start=1):
                ws.update_cell(row_index_1based, i, row_dict.get(col, ""))
        else:
            ws.append_row([row_dict.get(col, "") for col in df.columns])
    else:
        # 安全フォールバック：列順で追加
        ws.append_row([row_dict.get(col, "") for col in df.columns])
