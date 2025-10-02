# football_api.py  --- football-data.orgからPLの直近試合を取得（JST & フォールバック）
from __future__ import annotations
import os, requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st

# ---- helpers ----
def _strip_token(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    return v or None

def _read_token_from_gsheet() -> str | None:
    """configシートからFOOTBALL_DATA_API_TOKENを読む（あれば）。"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        # Secretsにあるサービスアカウント情報（前のシート書き込みで動いていたもの）を再利用
        sa_keys = [
            "type","project_id","private_key_id","private_key","client_email",
            "client_id","auth_uri","token_uri","auth_provider_x509_cert_url","client_x509_cert_url"
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

        # タブ名は大小区別せずに "config" を探す
        ws = None
        for w in sh.worksheets():
            if w.title.strip().lower() == "config":
                ws = w
                break
        if not ws:
            return None

        vals = ws.get_all_values()
        if not vals:
            return None
        header = [c.strip().lower() for c in vals[0]]
        rows = [dict(zip(header, row)) for row in vals[1:]]
        for r in rows:
            k = (r.get("key") or "").strip().upper()
            if k == "FOOTBALL_DATA_API_TOKEN":
                return _strip_token(r.get("value"))
    except Exception:
        return None
    return None

def _load_token() -> str | None:
    # 0) 画面からの一時オーバーライド（後述の app.py 変更で利用）
    t = st.session_state.get("DEV_TOKEN_OVERRIDE")
    if t:
        return _strip_token(t)

    # 1) Secrets
    t = _strip_token(st.secrets.get("FOOTBALL_DATA_API_TOKEN"))
    if t:
        return t

    # 2) 環境変数（保険）
    t = _strip_token(os.getenv("FOOTBALL_DATA_API_TOKEN"))
    if t:
        return t

    # 3) Googleシート 'config'
    return _read_token_from_gsheet()

BASE = "https://api.football-data.org/v4"

@st.cache_data(ttl=600)  # 10分キャッシュ（無料枠セーフ）
def get_pl_fixtures_next_days(days_ahead: int = 7) -> list[dict]:
    token = _load_token()
    if not token:
        raise RuntimeError("APIトークンが見つかりません（Secrets か config シートを確認）。")

    today = datetime.now(timezone.utc).date()
    url = f"{BASE}/competitions/PL/matches"
    params = {
        "status": "SCHEDULED",
        "dateFrom": today.isoformat(),
        "dateTo": (today + timedelta(days=days_ahead)).isoformat(),
    }
    headers = {"X-Auth-Token": token}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    fixtures = []
    for m in data.get("matches", []):
        utc_raw = m.get("utcDate")
        if not utc_raw:
            continue
        dt_utc = datetime.fromisoformat(utc_raw.replace("Z", "+00:00"))
        dt_jst = dt_utc.astimezone(ZoneInfo("Asia/Tokyo"))
        fixtures.append({
            "id": m.get("id"),
            "matchday": m.get("matchday"),
            "kickoff_jst": dt_jst.strftime("%Y-%m-%d %H:%M"),
            "home": (m.get("homeTeam") or {}).get("name"),
            "away": (m.get("awayTeam") or {}).get("name"),
            "stage": m.get("stage"),
        })
    fixtures.sort(key=lambda x: x["kickoff_jst"])
    return fixtures
