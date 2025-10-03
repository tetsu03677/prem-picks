import time
from typing import Dict, List, Any, Optional
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ====== Google Sheets base ======
def _client():
    info = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def _spreadsheet():
    gc = _client()
    ssid = st.secrets["sheets"]["sheet_id"]
    return gc.open_by_key(ssid)

def ws(sheet_name: str):
    return _spreadsheet().worksheet(sheet_name)

# ====== helpers ======
def _records(w):
    rows = w.get_all_records()
    return rows

@st.cache_data(ttl=15, show_spinner=False)
def read_rows_by_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    return _records(ws(sheet_name))

def read_config() -> Dict[str, Any]:
    kv = {}
    for r in read_rows_by_sheet("config"):
        k = str(r.get("key") or "").strip()
        v = r.get("value")
        if k:
            kv[k] = v
    return kv

def read_rows(sheet_name: str, where: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = read_rows_by_sheet(sheet_name)
    res = []
    for r in rows:
        ok = True
        for k, v in where.items():
            if str(r.get(k)) != str(v):
                ok = False
                break
        if ok:
            res.append(r)
    return res

def _find_row_index(w, key_value: str, key_field: str = "key") -> Optional[int]:
    # returns 1-based row index (including header)
    header = w.row_values(1)
    try:
        key_col = header.index(key_field) + 1
    except ValueError:
        raise RuntimeError(f"'{key_field}' column not found in {w.title}")
    cell = w.find(key_value, in_column=key_col)
    return cell.row if cell else None

def upsert_row(sheet_name: str, key_value: str, data: Dict[str, Any], key_field: str = "key") -> None:
    w = ws(sheet_name)
    header = w.row_values(1)
    if key_field not in header:
        header.append(key_field)
        w.update("A1", [header])

    row_idx = None
    try:
        row_idx = _find_row_index(w, key_value, key_field)
    except gspread.exceptions.APIError:
        # find may rate-limit; ignore -> treat as new
        row_idx = None

    # ensure columns
    for k in data.keys():
        if k not in header:
            header.append(k)
    w.update("A1", [header])  # update header if changed

    values = ["" for _ in header]
    for i, col in enumerate(header):
        if col == key_field:
            values[i] = key_value
        elif col in data:
            values[i] = data[col]

    if row_idx:
        w.update(f"A{row_idx}", [values])
    else:
        w.append_row(values, value_input_option="USER_ENTERED")

    # bust caches
    read_rows_by_sheet.clear()

# ===== Domain helpers for bets/odds =====
def bets_for_match(gw: str, match_id: str) -> List[Dict[str, Any]]:
    return read_rows("bets", {"gw": gw, "match_id": match_id})

def user_bet_for_match(gw: str, match_id: str, user: str) -> Optional[Dict[str, Any]]:
    for r in bets_for_match(gw, match_id):
        if str(r.get("user")) == str(user):
            return r
    return None

def user_total_stake_for_gw(gw: str, user: str) -> int:
    total = 0
    for r in read_rows("bets", {"gw": gw, "user": user}):
        try:
            total += int(float(r.get("stake") or 0))
        except Exception:
            pass
    return total

def odds_for_match(gw: str, match_id: str) -> Dict[str, Any]:
    rows = read_rows("odds", {"gw": gw, "match_id": match_id})
    if rows:
        r = rows[0]
        return {
            "home_win": float(r.get("home_win") or 1.0),
            "draw": float(r.get("draw") or 1.0),
            "away_win": float(r.get("away_win") or 1.0),
            "locked": str(r.get("locked") or "").lower() in ("1", "true", "yes"),
            "home": r.get("home"),
            "away": r.get("away"),
            "updated_at": r.get("updated_at"),
        }
    return {"home_win": 1.0, "draw": 1.0, "away_win": 1.0, "locked": False}

def aggregate_others(bets: List[Dict[str, Any]], me: str) -> Dict[str, int]:
    res = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    for r in bets:
        if str(r.get("user")) == str(me):
            continue
        pick = str(r.get("pick") or "").upper()
        try:
            amt = int(float(r.get("stake") or 0))
        except Exception:
            amt = 0
        if pick in res:
            res[pick] += amt
    return res
