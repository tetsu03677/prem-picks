from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Tuple
import requests
import pytz

FD_BASE = "https://api.football-data.org/v4"

def _tz(tz_name: str):
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return timezone.utc

def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def fetch_matches_window(days_ahead: int, competition: str, season: str, token: str, tz_name: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Return upcoming matches within next `days_ahead` days for competition.
    Each match dict: id, gw, utc_kickoff, local_kickoff, home, away, status.
    GWは API の matchday があれば GW{n}、なければ season の current_gw を使う想定で、空なら "GW?"。
    """
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    date_from = _iso(now_utc)
    date_to = _iso(now_utc + timedelta(days=days_ahead))

    url = f"{FD_BASE}/competitions/{competition}/matches"
    params = {"dateFrom": date_from, "dateTo": date_to, "season": season}
    headers = {"X-Auth-Token": token}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()

    results = []
    gw_label = None
    for m in (data.get("matches") or []):
        mid = str(m.get("id"))
        status = m.get("status")
        utc_iso = m.get("utcDate")
        try:
            utc_dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        except Exception:
            continue
        home = (m.get("homeTeam") or {}).get("name")
        away = (m.get("awayTeam") or {}).get("name")
        matchday = m.get("matchday")
        gw = f"GW{matchday}" if matchday else "GW?"
        if gw_label is None:
            gw_label = gw

        local = utc_dt.astimezone(_tz(tz_name))
        results.append({
            "id": mid,
            "gw": gw,
            "utc_kickoff": utc_dt,
            "local_kickoff": local,
            "home": home,
            "away": away,
            "status": status,
        })

    # sort
    results.sort(key=lambda x: x["utc_kickoff"])
    return results, (gw_label or "GW?")
