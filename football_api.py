# football_api.py
# RapidAPI 経由で API-FOOTBALL から試合・オッズを取得するラッパー
# 必須: requirements.txt に requests を記載済みであること
# 参照: Google スプレッドシートの config シート（read_config()）

from __future__ import annotations
import datetime as dt
from typing import Any, Dict, List, Optional

import requests

from google_sheets_client import read_config


# -------- 基本設定（404回避のため host/URL を必ず -v1 付きにする） --------
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
HOST = "api-football-v1.p.rapidapi.com"


def _headers(conf: Dict[str, str]) -> Dict[str, str]:
    key = conf.get("RAPIDAPI_KEY", "").strip()
    if not key:
        raise ValueError("RAPIDAPI_KEY が config シートにありません。")
    return {
        "x-rapidapi-key": key,
        "x-rapidapi-host": HOST,
    }


# 代表的ブックメーカー名→API-FOOTBALL bookmaker ID の簡易マップ
BOOKMAKER_ID_MAP = {
    # 主要どころのみ収録（必要に応じて拡張可）
    "Bet365": 6,
    "Pinnacle": 3,
    "William Hill": 2,
    "Bwin": 5,
    "Unibet": 11,
}

def _bookmaker_id(conf: Dict[str, str]) -> int:
    name = (conf.get("bookmaker_username") or "").strip()
    if name in BOOKMAKER_ID_MAP:
        return BOOKMAKER_ID_MAP[name]
    # 未設定は Bet365 にフォールバック
    return 6


# 1X2（勝ち・引分け・負け）のマーケットIDは 1
def _odds_market_id(conf: Dict[str, str]) -> int:
    try:
        return int(conf.get("ODDS_MARKET", "1"))
    except Exception:
        return 1


# -------- API 呼び出し --------

def get_fixtures_by_league_and_season(
    league_id: Optional[int] = None,
    season: Optional[int] = None,
    date_from: Optional[str] = None,  # "YYYY-MM-DD"
    date_to: Optional[str] = None,    # "YYYY-MM-DD"
) -> List[Dict[str, Any]]:
    """
    プレミア等のリーグとシーズンで fixtures を取得（必要に応じて日付絞り込み可）
    """
    conf = read_config()
    headers = _headers(conf)
    league = league_id or int(conf.get("API_FOOTBALL_LEAGUE_ID", "39"))
    y = season or int(conf.get("API_FOOTBALL_SEASON", "2025"))

    params: Dict[str, Any] = {"league": league, "season": y}
    if date_from:
        params["from"] = date_from
    if date_to:
        params["to"] = date_to

    url = f"{BASE_URL}/fixtures"
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("response", [])


def get_fixtures_next_days(days: int = 7) -> List[Dict[str, Any]]:
    """
    今日から days 日先までの fixtures を（config のリーグ/シーズンで）取得
    """
    today = dt.date.today()
    date_from = today.isoformat()
    date_to = (today + dt.timedelta(days=days)).isoformat()
    return get_fixtures_by_league_and_season(date_from=date_from, date_to=date_to)


def get_odds_for_fixture(fixture_id: int) -> Dict[str, Any]:
    """
    単一 fixture のオッズ（1X2 中心）を取得。
    返り値はAPIの JSON（dict）そのまま（必要に応じて呼び出し側で整形）
    """
    conf = read_config()
    headers = _headers(conf)
    bookmaker = _bookmaker_id(conf)
    bet_market = _odds_market_id(conf)  # 1 = 1X2

    url = f"{BASE_URL}/odds"
    params = {"fixture": fixture_id, "bookmaker": bookmaker, "bet": bet_market}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ヘッドトゥヘッド例（必要なら）
def get_head_to_head(team1_id: int, team2_id: int, last: int = 5) -> Dict[str, Any]:
    conf = read_config()
    headers = _headers(conf)
    url = f"{BASE_URL}/fixtures/headtohead"
    params = {"h2h": f"{team1_id}-{team2_id}", "last": last}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()
