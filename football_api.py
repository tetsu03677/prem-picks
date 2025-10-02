# football_api.py
from __future__ import annotations

import requests
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ===== 内部ユーティリティ =====
def _to_jst_str(utc_iso: str) -> str:
    # '2025-10-20T15:30:00Z' -> 'YYYY-MM-DD HH:MM' (JST)
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M")

def _get_token_from_config_sheet() -> str | None:
    """Googleシートの 'config' シートから key/value を読み、FOOTBALL_DATA_API_TOKEN を返す。"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        sa_keys = [
            "type","project_id","private_key_id","private_key","client_email",
            "client_id","auth_uri","token_uri","auth_provider_x509_cert_url","client_x509_cert_url",
        ]
        sa_info = {k: st.secrets[k] for k in sa_keys if k in st.secrets}
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        gc = gspread.authorize(creds)

        sheet_id = st.secrets["sheets"]["sheet_id"]
        sh = gc.open_by_key(sheet_id)
        try:
            ws = sh.worksheet("config")
        except Exception:
            return None

        rows = ws.get_all_records()  # 1行目は header: key / value
        for r in rows:
            k = str(r.get("key") or r.get("Key") or r.get("KEY") or "").strip()
            v = str(r.get("value") or r.get("Value") or r.get("VALUE") or "").strip()
            if k.upper() == "FOOTBALL_DATA_API_TOKEN" and v:
                return v
        return None
    except Exception:
        return None

def _get_api_token() -> str:
    # 1) 画面からの一時トークン最優先
    ov = st.session_state.get("DEV_TOKEN_OVERRIDE")
    if isinstance(ov, str) and ov.strip():
        return ov.strip()
    # 2) Secrets
    tok = st.secrets.get("FOOTBALL_DATA_API_TOKEN")
    if isinstance(tok, str) and tok.strip():
        return tok.strip()
    # 3) config シート
    tok = _get_token_from_config_sheet()
    if tok:
        return tok
    raise RuntimeError("APIトークンが見つかりません（Secrets か config シートを確認）。")

def _call_football_data(path: str, params: dict | None = None) -> dict:
    url = f"https://api.football-data.org/v4{path}"
    headers = {"X-Auth-Token": _get_api_token()}
    r = requests.get(url, headers=headers, params=params or {}, timeout=15)

    if r.status_code == 401:
        raise RuntimeError("APIトークンが無効（401）。FOOTBALL_DATA_API_TOKEN を見直してください。")
    if r.status_code == 403:
        raise RuntimeError("レート制限/権限制限（403）。時間をおいて再実行してください。")
    if r.status_code >= 400:
        # 返却本文を少しだけ添える
        snippet = r.text[:200].replace("\n", " ")
        raise RuntimeError(f"APIエラー: {r.status_code} {snippet}")
    return r.json()

# ===== 公開関数 =====
def get_pl_fixtures_next_days(days: int = 7) -> list[dict]:
    """
    直近 days 日のプレミアリーグ公式日程を返す。
    返却: [{'kickoff_jst','matchday','home','away','stage'}, ...]
    """
    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    date_from = now_jst.date().isoformat()
    date_to = (now_jst + timedelta(days=days)).date().isoformat()

    data = _call_football_data(
        "/competitions/PL/matches",
        params={
            "dateFrom": date_from,
            "dateTo": date_to,
            # SCHEDULED と TIMED を含めて将来試合を拾う
            "status": "SCHEDULED,TIMED",
        },
    )
    matches = data.get("matches", [])
    out = []
    for m in matches:
        out.append(
            {
                "kickoff_jst": _to_jst_str(m.get("utcDate", "")),
                "matchday": m.get("matchday"),
                "home": (m.get("homeTeam") or {}).get("name"),
                "away": (m.get("awayTeam") or {}).get("name"),
                "stage": m.get("stage"),
            }
        )
    out.sort(key=lambda x: x["kickoff_jst"])
    return out
