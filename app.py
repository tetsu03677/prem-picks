# app.py
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional

import streamlit as st

from google_sheets_client import read_config, read_odds_map_for_gw
from football_api import fetch_next_round_fd

# ─────────────────────────────────────────────────────────────────────
# ページ設定
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

TZ_UTC = timezone.utc

# ─────────────────────────────────────────────────────────────────────
# 共通ユーティリティ
def _localize(dt_utc: datetime, tz_name: str) -> datetime:
    from zoneinfo import ZoneInfo
    return dt_utc.astimezone(ZoneInfo(tz_name))

def _current_user() -> Optional[dict]:
    return st.session_state.get("user")

def _logout():
    for k in ("user",):
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# ─────────────────────────────────────────────────────────────────────
# ログイン画面
def show_login():
    st.markdown("### 🔐 ログイン")
    conf = read_config()

    # users_json は config シートの JSON 文字列
    users_json = conf.get("users_json", "").strip()
    user_list = []
    try:
        user_list = json.loads(users_json) if users_json else []
    except Exception:
        st.error("configシートの users_json が不正です。JSON配列にしてください。")
        return

    if not user_list:
        st.error("ログインユーザーが定義されていません（configシート users_json）。")
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        usernames = [u.get("username", "") for u in user_list]
        sel = st.selectbox("ユーザー", usernames, index=0)
    with col2:
        pw = st.text_input("パスワード", type="password")

    if st.button("ログイン", type="primary", use_container_width=True):
        # 照合
        record = next((u for u in user_list if u.get("username") == sel), None)
        if record and pw == record.get("password"):
            st.session_state["user"] = {
                "username": record.get("username"),
                "role": record.get("role", "user"),
                "team": record.get("team", ""),
            }
            st.success("ログインしました。")
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが違います。")

    st.caption("※ユーザー定義は Google スプレッドシート config!B7 の users_json にあります。")

# ─────────────────────────────────────────────────────────────────────
# 画面: トップ
def render_home():
    u = _current_user()
    st.markdown("### 🏠 トップ")
    st.write(f"ようこそ **{u['username']}** さん！")

# 画面: 試合とベット（次のGWのみ表示。7日超なら注意表示。オッズ未入力は仮=1.0）
def render_matches_and_bets():
    st.header("🎯 試合とベット")

    conf = read_config()
    api_token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    league_id = conf.get("API_FOOTBALL_LEAGUE_ID", "39")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    tzname = conf.get("timezone", "Asia/Tokyo")

    if not api_token:
        st.error("FOOTBALL_DATA_API_TOKEN が未設定です（config シート）。")
        return

    with st.spinner("試合データ取得中…"):
        try:
            resp = fetch_next_round_fd(api_token, league_id, season)
        except Exception as e:
            st.error(f"試合データ取得エラー: {e}")
            return

    fixtures = resp.get("fixtures") or []
    first_utc: datetime | None = resp.get("earliest_utc")
    gw = resp.get("matchday")

    if not fixtures or not first_utc or not gw:
        st.info("予定された試合が見つかりません。")
        return

    now_utc = datetime.now(TZ_UTC)
    delta_days = (first_utc - now_utc).total_seconds() / 86400.0

    if delta_days > 7.0:
        first_local = _localize(first_utc, tzname)
        st.warning(
            f"7日以内に次のGWはありません。次のGW({gw})の最初のキックオフ: "
            f"{first_local.strftime('%m/%d %H:%M')}"
        )
        return

    odds_map = read_odds_map_for_gw(int(gw))

    st.subheader(f"試合一覧（GW{gw}）")
    for m in fixtures:
        match_id = str(m["match_id"])
        ko_local = _localize(datetime.fromisoformat(m["utc"]), tzname)
        home = m["home"]
        away = m["away"]

        od = odds_map.get(match_id, {"home": 1.0, "draw": 1.0, "away": 1.0, "locked": False})
        is_placeholder = (od["home"] == 1.0 and od["draw"] == 1.0 and od["away"] == 1.0)

        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1:
                st.markdown(f"**GW{gw}**")
                st.caption(ko_local.strftime("%m/%d %H:%M"))
            with c2:
                st.markdown(f"**{home} vs {away}**")
                if is_placeholder:
                    st.info("オッズ未入力のため仮オッズ（=1.0）を表示中。管理者は『オッズ管理』で設定してください。")
                st.markdown(
                    f"- Home: **{od['home']:.2f}**"
                    f"　• Draw: **{od['draw']:.2f}**"
                    f"　• Away: **{od['away']:.2f}**"
                )
                # （v1）ここにベットUIは未配置。今は閲覧優先。

# 画面: 履歴（プレースホルダ）
def render_history():
    st.header("📁 履歴")
    st.info("履歴ページは今後実装します。まずは試合一覧とオッズ管理を先に仕上げます。")

# 画面: リアルタイム（プレースホルダ）
def render_realtime():
    st.header("⏱ リアルタイム")
    st.info("リアルタイムページは今後実装します。")

# 画面: オッズ管理（管理者のみ・プレースホルダ）
def render_odds_admin():
    st.header("🛠 オッズ管理（管理者）")
    st.info("このページから次のGWの各試合にオッズを入力・ロックできるようにします。（次のステップで実装）")

# ─────────────────────────────────────────────────────────────────────
# メイン
def main():
    user = _current_user()
    if not user:
        show_login()
        return

    # 右上にログアウト
    with st.container():
        st.markdown(
            f"<div style='text-align:right'>"
            f"ログイン中：<b>{user['username']}</b>（{user.get('role','user')}） "
            f"<button onclick='window.location.reload()' style='display:none'></button>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.button("ログアウト", on_click=_logout)

    # 上部タブ（日本語）
    admin = (user.get("role") == "admin")
    if admin:
        tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱ リアルタイム", "🛠 オッズ管理"])
        pages = [render_home, render_matches_and_bets, render_history, render_realtime, render_odds_admin]
    else:
        tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱ リアルタイム"])
        pages = [render_home, render_matches_and_bets, render_history, render_realtime]

    for tab, page in zip(tabs, pages):
        with tab:
            page()

# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
