from datetime import datetime, timedelta, timezone
from typing import Tuple, List, Dict
import requests
import streamlit as st

PL_COMP_ID = 2021  # Premier League (football-data.org)

def _tz(conf):
    tzname = conf.get("timezone","Asia/Tokyo")
    return timezone(timedelta(0)) if tzname=="UTC" else None

def _fmt_local(dt_utc: datetime, conf) -> str:
    # 表示はローカルタイム（Asia/Tokyoなど）
    import pytz
    tz = pytz.timezone(conf.get("timezone","Asia/Tokyo"))
    return dt_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M")

def get_next_fixtures(days_ahead: int, conf) -> Tuple[bool, List[Dict] | str]:
    """
    football-data.org を使用。
    成功: (True, fixtures list)
    失敗: (False, message)
    """
    token = conf.get("FOOTBALL_DATA_API_TOKEN","").strip()
    if not token:
        return False, "APIトークンが未設定です。config の FOOTBALL_DATA_API_TOKEN を設定してください。"

    try:
        # 期間（UTC基準）
        import pytz
        tz = pytz.timezone(conf.get("timezone","Asia/Tokyo"))
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=days_ahead)
        date_from = start.astimezone(pytz.utc).strftime("%Y-%m-%d")
        date_to = end.astimezone(pytz.utc).strftime("%Y-%m-%d")

        url = f"https://api.football-data.org/v4/competitions/{PL_COMP_ID}/matches"
        params = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"}
        headers = {"X-Auth-Token": token}
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            return False, f"APIエラー: {r.status_code} {r.text[:120]}"

        data = r.json()
        fixtures = []
        for m in data.get("matches", []):
            utc = datetime.fromisoformat(m["utcDate"].replace("Z","+00:00"))
            fixtures.append({
                "home": m["homeTeam"]["name"],
                "away": m["awayTeam"]["name"],
                "kickoff_dt": utc,
                "kickoff_local": _fmt_local(utc, conf),
                "matchday": m.get("matchday","?"),
                "odds": 1.90,  # （簡易）固定オッズ。後で別APIに差し替え可
            })
        fixtures.sort(key=lambda x: x["kickoff_dt"])
        return True, fixtures
    except Exception as e:
        return False, f"取得失敗: {e}"
