# google_sheets_client.py  ─────────────────────────────────────────────
from __future__ import annotations
from typing import Dict, List, Any, Iterable, Optional
import json
import re
import time

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ===== 基本接続 =====
def _client() -> gspread.Client:
    # Streamlit Cloud の secrets を利用
    # st.secrets["gcp_service_account"] … Service Account JSON
    # st.secrets["SPREADSHEET_ID"]     … 対象スプレッドシートID
    info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def _spreadsheet():
    gc = _client()
    ssid = st.secrets["SPREADSHEET_ID"]
    return gc.open_by_key(ssid)

def ws(sheet_name: str):
    """ワークシート取得（存在しなければ作成）"""
    sh = _spreadsheet()
    try:
        return sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=sheet_name, rows=1000, cols=26)

# ===== 共通ユーティリティ =====
def _normalize_key(s: str) -> str:
    return (s or "").strip()

def _to_value(v: str) -> Any:
    s = (v if v is not None else "").strip()
    # JSON（配列/オブジェクト）判定
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        try:
            return json.loads(s)
        except Exception:
            pass
    # int/float 変換
    if re.fullmatch(r"-?\d+", s or ""):
        try:
            return int(s)
        except Exception:
            pass
    if re.fullmatch(r"-?\d+\.\d+", s or ""):
        try:
            return float(s)
        except Exception:
            pass
    return s

def _headers(ws_) -> List[str]:
    values = ws_.get_values("A1:1")
    if not values:
        return []
    return [c.strip() for c in values[0]]

def _records(ws_) -> List[Dict[str, Any]]:
    """ヘッダー付きレコードとして全件取得"""
    rows = ws_.get_all_values()
    if not rows:
        return []
    headers = [c.strip() for c in rows[0]]
    out: List[Dict[str, Any]] = []
    for r in rows[1:]:
        rec = {}
        for i, h in enumerate(headers):
            rec[h] = _to_value(r[i]) if i < len(r) else ""
        # 空行スキップ（全部空）
        if any(str(v).strip() != "" for v in rec.values()):
            out.append(rec)
    return out

# ===== 読み取り系 =====
def read_rows_by_sheet(sheet_name: str) -> List[Dict[str, Any]]:
    """任意シートをレコード化して返す"""
    return _records(ws(sheet_name))

def read_rows(sheet_name: str) -> List[Dict[str, Any]]:
    """エイリアス（互換）"""
    return read_rows_by_sheet(sheet_name)

def read_config() -> Dict[str, Any]:
    """config シートを key/value で辞書化"""
    data = read_rows_by_sheet("config")
    conf: Dict[str, Any] = {}
    for r in data:
        k = _normalize_key(str(r.get("key", "")))
        if not k:
            continue
        conf[k] = _to_value(str(r.get("value", "")))
    return conf

# ===== 書き込み（UPSERT） =====
def upsert_row(
    sheet_name: str,
    row: Dict[str, Any],
    keys: Iterable[str],
    append_when_missing: bool = True,
) -> int:
    """
    keys で一致する行があれば更新、無ければ末尾に追加。
    戻り値：更新/追加した行番号（1始まり）
    """
    ws_ = ws(sheet_name)
    headers = _headers(ws_)
    # ヘッダ未作成なら生成
    if not headers:
        headers = list(row.keys())
        ws_.append_row(headers)
    else:
        # 新しい列が来たら右端に追加
        missing = [k for k in row.keys() if k not in headers]
        if missing:
            ws_.add_cols(len(missing))
            headers.extend(missing)
            ws_.update("A1", [headers])

    # 全件読んで一致行を探索
    recs = _records(ws_)
    key_list = [str(k) for k in keys]
    target_idx: Optional[int] = None  # 0-based（データ部）
    for i, rec in enumerate(recs):
        if all(str(rec.get(k, "")) == str(row.get(k, "")) for k in key_list):
            target_idx = i
            break

    # 書き込み配列作成（ヘッダ順）
    write_values = []
    for h in headers:
        v = row.get(h, "")
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        write_values.append(v)

    if target_idx is None:
        if not append_when_missing:
            return -1
        # 追加：A2 が1行目なので +2
        ws_.append_row(write_values)
        return len(recs) + 2
    else:
        # 更新：対象はデータ部 i → シート上は i+2 行目
        row_num = target_idx + 2
        cell_range = f"A{row_num}:{_col_letter(len(headers))}{row_num}"
        ws_.update(cell_range, [write_values])
        return row_num

# ヘルパ：列番号 → 文字（1->A, 27->AA）
def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
# ───────────────────────────────────────────────────────────────────
