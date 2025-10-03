# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests
import streamlit as st

FD_BASE = "https://api.football-data.org/v4"


def _bearer_headers() -> Dict[str, str]:
    tok = st.secrets.get("FOOTBALL_DATA_API_TOKEN") or st.secrets.get("football_data_api_token")
    if not tok:
        # 旧仕様: シートから読む
        try:
            from google_sheets_client import read_config  # 遅延インポート
            tok = read_config().get("FOOTBALL_DATA_API_TOKEN")
        except Exception:
            tok = None
    if not tok:
        raise RuntimeError("FOOTBALL_DATA_API_TOKEN が見つかりません。secrets または config シートを確認してください。")
    return {"X-Auth-Token": tok}


def _comp_from_conf(raw: str | int | None) -> str:
    """
    competitions の指定を安全に整形。
    - "PL" / "pl" はそのまま PL
    - 39 など数値 → PL に変換（プレミアの公式コードは PL）
    - 未指定も PL
    """
    if raw is None:
        return "PL"
    s = str(raw).strip().upper()
    if s == "PL":
        return "PL"
    # 39 を含む数値などは PL に寄せる（プレミア固定要件）
    if s.isdigit():
        return "PL"
    return "PL"


def _iso_utc_range(days: int) -> Tuple[str, str]:
    """
    今日(UTC) 00:00 から days 日後の 23:59:59Z までのISO文字列を返す
    """
    now_utc = datetime.now(timezone.utc)
    start = datetime(year=now_utc.year, month=now_utc.month, day=now_utc.day, tzinfo=timezone.utc)
    end = start + timedelta(days=days)
    # end はその日の終わりまで含める
    end = end.replace(hour=23, minute=59, second=59, microsecond=0)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _call_fd(path: str, params: Dict[str, str]) -> Tuple[dict, str]:
    url = f"{FD_BASE}{path}"
    r = requests.get(url, headers=_bearer_headers(), params=params, timeout=30)
    # 4xx の本文をデバッグ表示できるよう raise 前に URL を返す
    debug_url = r.url
    r.raise_for_status()
    return r.json(), debug_url


def _normalize_matches(fd_json: dict) -> List[Dict]:
    """
    football-data.org v4 の /matches 応答をアプリ内部フォーマットに整形
    """
    items = []
    for m in fd_json.get("matches", []):
        match_id = m.get("id")
        home = (m.get("homeTeam") or {}).get("name")
        away = (m.get("awayTeam") or {}).get("name")
        utc_dt = m.get("utcDate")
        status = m.get("status")  # SCHEDULED / TIMED / IN_PLAY / FINISHED など
        comp = (m.get("competition") or {}).get("code") or (m.get("competition") or {}).get("name")
        gw = None
        # 節情報（matchday）があれば拾う
        season = m.get("season") or {}
        gw = m.get("matchday") or season.get("currentMatchday")

        items.append(
            {
                "match_id": match_id,
                "home": home,
                "away": away,
                "utcDate": utc_dt,
                "status": status,
                "competition": comp,
                "gw": gw,
            }
        )
    return items


def fetch_matches_window(days: int, league_conf_value: str | int | None, season_conf: str | int | None) -> Tuple[List[Dict], str]:
    """
    直近 days 日分のプレミアの試合を取得して返す。
    まず season 付きで検索し、0件なら season 無しでフォールバック。
    competitions は PL を使用（conf が数値でも PL に寄せる）。
    戻り値: (matches: list[dict], debug_url: str)
    """
    comp = _comp_from_conf(league_conf_value)
    date_from, date_to = _iso_utc_range(days)

    # 1st try: season を付けて SCHEDULED/TIMED で検索
    base_params = {
        "competitions": comp,                # 例: PL
        "dateFrom": date_from[:10],          # v4 は YYYY-MM-DD でもOK
        "dateTo": date_to[:10],
        "status": "SCHEDULED,TIMED",         # 予定のみ
        "limit": "200",
    }

    debug_url_last = ""
    # season 指定（文字列でもOK）
    if season_conf:
        p1 = dict(base_params)
        p1["season"] = str(season_conf)
        try:
            js, debug_url_last = _call_fd("/matches", p1)
            data = _normalize_matches(js)
            if data:
                return data, debug_url_last
        except requests.HTTPError:
            # 404/400などはフォールバックへ
            pass

    # 2nd try: season なし（期間だけで取得）
    try:
        js, debug_url_last = _call_fd("/matches", base_params)
        data = _normalize_matches(js)
        return data, debug_url_last
    except requests.HTTPError as e:
        # 上位で詳細を出せるように再送出
        e.args = (f"{e} | URL={getattr(e.response, 'url', debug_url_last)}",)
        raise
