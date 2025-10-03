# football_api.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import requests

UTC = timezone.utc
FD_BASE = "https://api.football-data.org/v4"

class FDClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": token})

    def get(self, path: str, params: dict) -> dict:
        url = f"{FD_BASE}{path}"
        r = self.session.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

def fetch_scheduled_between(
    token: str,
    competition: str,   # ← PL / 2021 など（football-data.org のID or code）
    date_from: datetime,
    date_to: datetime,
    season: Optional[str] = None,
) -> dict:
    """
    football-data.org の対戦を期間指定で取得
    """
    cli = FDClient(token)
    params = {
        "dateFrom": date_from.date().isoformat(),
        "dateTo": date_to.date().isoformat(),
        "status": "SCHEDULED",
    }
    if season:
        params["season"] = season

    data = cli.get(f"/competitions/{competition}/matches", params)
    return data

def fetch_next_round_fd(
    token: str,
    competition: str,
    season: str,
    horizon_days: int = 21,
) -> dict:
    """
    直近のSCHEDULED試合から“最も早いキックオフ日時”のラウンド(=GW)を特定し、
    そのラウンドに属する試合だけを返す。
    返却: {"matchday": <GW>, "earliest_utc": datetime, "fixtures": [ ... ]}
    """
    now = datetime.now(UTC)
    date_from = now
    date_to = now + timedelta(days=horizon_days)

    raw = fetch_scheduled_between(
        token=token,
        competition=competition,
        date_from=date_from,
        date_to=date_to,
        season=season,
    )

    matches: List[dict] = raw.get("matches") or []
    if not matches:
        return {"matchday": None, "earliest_utc": None, "fixtures": []}

    # 最も早いキックオフ（UTC）
    def ko_utc(m: dict) -> datetime:
        # APIはZつきISO。strptimeでUTCに。
        return datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(UTC)

    matches_sorted = sorted(matches, key=ko_utc)
    earliest = matches_sorted[0]
    earliest_utc = ko_utc(earliest)
    target_round = earliest.get("matchday") or earliest.get("season", {}).get("currentMatchday")

    # 同じ round のみ抽出
    same_round = [m for m in matches_sorted if (m.get("matchday") == target_round)]

    fixtures = []
    for m in same_round:
        fixtures.append({
            "match_id": str(m["id"]),
            "utc": ko_utc(m).isoformat(),
            "home": m["homeTeam"]["shortName"] or m["homeTeam"]["name"],
            "away": m["awayTeam"]["shortName"] or m["awayTeam"]["name"],
        })

    return {
        "matchday": target_round,
        "earliest_utc": earliest_utc,
        "fixtures": fixtures,
    }
