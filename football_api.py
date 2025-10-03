from datetime import datetime, timedelta, timezone
from typing import Dict, List
import requests

# 39(PL) などのID→コードの簡易マップ（必要に応じて拡張）
LEAGUE_ID_TO_CODE = {
    "39": "PL",     # Premier League
    39: "PL",
}

def _league_code(league_id_or_code) -> str:
    s = str(league_id_or_code)
    return LEAGUE_ID_TO_CODE.get(s, s)

def _iso_date(d: datetime) -> str:
    return d.date().isoformat()

def fetch_matches_window(days: int, league_id_or_code: str, season: str, token: str) -> List[Dict]:
    """
    football-data.org から「今日～days日先」までの試合を取得。
    """
    headers = {"X-Auth-Token": token}
    base = "https://api.football-data.org/v4/matches"
    code = _league_code(league_id_or_code)
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    params = {
        "competitions": code,
        "dateFrom": _iso_date(start),
        "dateTo": _iso_date(end),
        "status": "SCHEDULED",  # 予定のみ
    }
    r = requests.get(base, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("matches", [])

def simplify_matches(matches: List[Dict]) -> List[Dict]:
    """
    UI用に最小限へ整形
    """
    out = []
    for m in matches:
        mid = m.get("id")
        utc = m.get("utcDate","")
        home = m.get("homeTeam",{}).get("name","")
        away = m.get("awayTeam",{}).get("name","")
        # ローカル表示用（UTC→JST相当などはStreamlit上で表示だけ文字列でOK）
        dt = utc.replace("Z","+00:00")
        try:
            local_str = datetime.fromisoformat(dt).astimezone().strftime("%m/%d %H:%M")
        except:
            local_str = utc
        out.append({
            "id": mid,
            "utcDate": utc,
            "home": home,
            "away": away,
            "kickoff_local": local_str,
        })
    # kickoff順
    out.sort(key=lambda x: x["utcDate"])
    return out
