import json
from typing import Dict, List, Any, Optional

import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _client() -> gspread.Client:
    info = dict(st.secrets["gcp_service_account"])
    pk = info.get("private_key", "")
    if "\\n" in pk and "\n" not in pk:
        info["private_key"] = pk.replace("\\n", "\n")
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def ws(sheet_name: str):
    gc = _client()
    sh = gc.open_by_key(st.secrets["sheets"]["sheet_id"])
    return sh.worksheet(sheet_name)

def _records(worksheet) -> List[Dict[str, Any]]:
    return worksheet.get_all_records()

def read_rows_by_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    return _records(ws(sheet_name))

def read_config() -> Dict[str, str]:
    rows = read_rows_by_sheet("config")
    kv = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = str(r.get("value", "")).strip()
        if k:
            kv[k] = v
    return kv

def upsert_row(sheet_name: str, key_field: str, key_value: Any, row_data: Dict[str, Any]) -> None:
    w = ws(sheet_name)
    headers = w.row_values(1)
    key_col_idx = headers.index(key_field) + 1
    all_vals = w.get_all_values()
    target_row = None
    for i in range(2, len(all_vals) + 1):
        cell_val = w.cell(i, key_col_idx).value
        if str(cell_val) == str(key_value):
            target_row = i
            break
    values_row = [row_data.get(h, "") for h in headers]
    if target_row is None:
        w.append_row(values_row)
    else:
        import gspread
        rng = gspread.utils.rowcol_to_a1(target_row, 1) + ":" + gspread.utils.rowcol_to_a1(target_row, len(headers))
        w.update(rng, [values_row])

def append_row(sheet_name: str, row_data: Dict[str, Any]) -> None:
    w = ws(sheet_name)
    headers = w.row_values(1)
    values_row = [row_data.get(h, "") for h in headers]
    w.append_row(values_row)

def read_odds_map_by_match_id(gw: str) -> Dict[str, Dict[str, Any]]:
    odds_rows = read_rows_by_sheet("odds")
    m = {}
    for r in odds_rows:
        if str(r.get("gw","")).strip() == str(gw).strip():
            mid = str(r.get("match_id","")).strip()
            if mid:
                m[mid] = r
    return m

def upsert_odds(gw: str, match_id: str, home: str, draw: str, away: str, locker: str) -> None:
    data = {
        "gw": gw,
        "match_id": match_id,
        "home": "",                 # 見出し互換フィールド（未使用だが残す）
        "away": "",                 # 見出し互換フィールド（未使用だが残す）
        "home_win": home,
        "draw": draw,
        "away_win": away,
        "locked": "",
        "updated_at": locker,
    }
    upsert_row("odds", "match_id", match_id, data)

def upsert_bet(row: Dict[str, Any]) -> None:
    upsert_row("bets", "key", row["key"], row)
