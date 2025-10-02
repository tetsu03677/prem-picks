# football_api.py  --- football-data.org からPLの直近試合を取得（JST & フォールバック）
from __future__ import annotations
import os
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st

# --- gspreadを使わずに最小限でconfigシートを読む（既存のSecrets認証情報を再利用） ---
def _read_token_from_gsheet() -> str | None:
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        # Secretsに入っているサービスアカウントJSONを復元
        sa_keys = ["type","project_id","private_key_id","private_key","client_email",
                   "client_id","auth_uri","token_uri","auth_provider_x509_cert_url","client_x509_cert_url"]
        sa_info = {k: st.secrets[k] for k in sa_keys if k in st.secrets}
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        gc = gspread.authorize(creds)

        sheet_id = st.secrets["sheets"]["sheet_id"]
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet("config")  # 無ければ例外になる
        rows = ws.get_all_records()  # [{'key': 'FOOTBALL_DATA_API_TOKEN', 'value': 'xxxxx'}, ...]
        for r in rows:
            if str(r.get("key")).strip() == "FOOTBALL_DATA_API_TOKEN":
                v = str(r.get("value")).strip()
                return v if v else None
    except Exception:
        return None
    return None

def _load_token() -> str | None:
    # 1) Secrets
    token = st.secrets.get("FOOTBALL_DATA_API_TOKEN")
    if token:
        return str(token).strip()
    # 2) 環境変数（将来の保険）
    token = os.getenv("FOOTBALL_DATA_API_TOKEN")
    if token:
        return token.strip()
    # 3) Googleシート 'config'
    return _read_token_from_gsheet()

BASE = "https://api.football-data.org/v4"

@st.cache_data(ttl=600)  # 10分キャッシュで無料枠を節約
def get_pl_fixtures_next_days(days_ahead: int = 7) -> list[dict]:
    """今日から days_ahead 日先までのPLのSCHEDULED試合を返す（JST整形済み）。"""
    token = _load_token()
    if not token:
        raise RuntimeError("APIトークンが見つかりません（Secrets か config シートを確認）。")

    today = datetime.now(timezone.utc).date()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()

    url = f"{BASE}/competitions/PL/matches"
    params = {"status": "SCHEDULED", "dateFrom": date_from, "dateTo": date_to}
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
