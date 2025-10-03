# app.py
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import streamlit as st

from google_sheets_client import (
    read_config,
    read_odds_map_for_gw,
    user_total_stake_for_gw,
    get_user_bet_for_match,
    open_bets_for_match,
    upsert_bet_row,
)
from football_api import fetch_next_round_fd

st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")
TZ_UTC = timezone.utc

# ── スタイル（ピック3分割セグメント/タイトル強調/バッジ等） ────────
st.markdown(
    """
    <style>
    .match-title {font-size: 1.08rem; line-height: 1.45;}
    .match-title .home {font-weight: 800;}
    .match-odds {font-size: .95rem;}
    .subtle {opacity:.75;}
    .small {font-size:.86rem;}
    .capline {margin-top:-8px;margin-bottom:18px;}

    /* Radio を3分割の等幅ボタン風に */
    div[role="radiogroup"] {display:flex; gap:.5rem; }
    div[role="radiogroup"] > label {
        flex: 1 1 0;
        border: 1px solid var(--secondary-background-color);
        border-radius: 10px; padding:.5rem .75rem;
        text-align:center; cursor:pointer;
        background: var(--background-color);
        transition: all .15s ease;
    }
    div[role="radiogroup"] > label:hover {
        transform: translateY(-1px);
        box-shadow: 0 1px 6px rgba(0,0,0,.08);
    }
    div[role="radiogroup"] input:checked + div > p {
        font-weight: 700;
    }

    /* ユーザー別ベットのバッジ */
    .bet-badges {display:flex; gap:.4rem; flex-wrap:wrap;}
    .bet-badge {
        border-radius: 999px; padding:.25rem .6rem;
        background: rgba(255,105,180,.10); /* ピンク系の淡色 */
        border: 1px solid rgba(255,105,180,.25);
        font-size:.80rem;
    }
    .bet-badge.me {background: rgba(65,105,225,.12); border-color: rgba(65,105,225,.28);} /* 自分は青系 */
    </style>
    """,
    unsafe_allow_html=True,
)

def _localize(dt_utc: datetime, tz_name: str) -> datetime:
    from zoneinfo import ZoneInfo
    return dt_utc.astimezone(ZoneInfo(tz_name))

def _current_user() -> Optional[dict]:
    return st.session_state.get("user")

def _logout():
    for k in ("user",):
        st.session_state.pop(k, None)
    st.rerun()

def show_login():
    st.markdown("### 🔐 ログイン")
    conf = read_config()
    users_json = conf.get("users_json", "").strip()
    try:
        users = json.loads(users_json) if users_json else []
    except Exception:
        st.error("config!users_json が不正なJSONです。")
        return
    if not users:
        st.error("ユーザーが未設定です。")
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        name = st.selectbox("ユーザー", [u["username"] for u in users])
    with col2:
        pw = st.text_input("パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        u = next((u for u in users if u["username"] == name), None)
        if u and pw == u.get("password"):
            st.session_state["user"] = {
                "username": u["username"],
                "role": u.get("role","user"),
                "team": u.get("team",""),
            }
            st.success("ログインしました。"); st.rerun()
        else:
            st.error("ユーザー名またはパスワードが違います。")

def render_home():
    u = _current_user()
    st.markdown("### 🏠 トップ")
    st.write(f"ようこそ **{u['username']}** さん！")

def _is_globally_locked(conf: dict, earliest_utc: datetime) -> bool:
    try:
        freeze_min = int(conf.get("odds_freeze_minutes_before_first", conf.get("lock_minutes_before_earliest", "120")))
    except Exception:
        freeze_min = 120
    now = datetime.now(TZ_UTC)
    return now >= (earliest_utc - timedelta(minutes=freeze_min))

def _pretty_pick_name(key: str, home: str, away: str) -> str:
    key = (key or "").upper()
    if key == "HOME": return f"Home Win（{home}）"
    if key == "AWAY": return f"Away Win（{away}）"
    return "Draw"

def render_matches_and_bets():
    st.header("🎯 試合とベット")
    conf = read_config()

    api_token   = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    competition = conf.get("FOOTBALL_DATA_COMPETITION", "PL")
    season      = conf.get("API_FOOTBALL_SEASON", "2025")
    tzname      = conf.get("timezone", "Asia/Tokyo")

    if not api_token:
        st.error("FOOTBALL_DATA_API_TOKEN が未設定です")
        return

    with st.spinner("試合データ取得中…"):
        resp = fetch_next_round_fd(api_token, competition, season)
    fixtures = resp.get("fixtures") or []
    first_utc: datetime | None = resp.get("earliest_utc")
    gw = resp.get("matchday")

    if not fixtures or not first_utc or not gw:
        st.info("予定された試合が見つかりません。")
        return

    if (first_utc - datetime.now(TZ_UTC)) > timedelta(days=7):
        first_local = _localize(first_utc, tzname)
        st.warning(f"7日以内に次のGWはありません。次のGW({gw})の最初のキックオフ: {first_local:%m/%d %H:%M}")
        return

    odds_map = read_odds_map_for_gw(int(gw))
    globally_locked = _is_globally_locked(conf, first_utc)

    try:
        step = int(conf.get("stake_step", "100"))
    except Exception:
        step = 100
    try:
        max_total = int(conf.get("max_total_stake_per_gw", "5000"))
    except Exception:
        max_total = 5000

    user = _current_user()["username"]
    placed_total = user_total_stake_for_gw(user, int(gw))
    remaining = max(0, max_total - placed_total)

    st.caption(f"このGWのあなたの投票合計: **{placed_total}** / 上限 **{max_total}**（残り **{remaining}**）")

    st.subheader(f"試合一覧（GW{gw}）")
    for m in fixtures:
        match_id = str(m["match_id"])
        ko_local = _localize(datetime.fromisoformat(m["utc"]), tzname)
        home, away = m["home"], m["away"]

        od = odds_map.get(match_id, {"home": 1.0, "draw": 1.0, "away": 1.0, "locked": False})
        placeholder = (od["home"] == 1.0 and od["draw"] == 1.0 and od["away"] == 1.0)
        match_locked = od.get("locked", False) or globally_locked

        my_bet = get_user_bet_for_match(user, int(gw), match_id)
        existing_stake = 0
        existing_pick = None
        if my_bet:
            _, r = my_bet
            existing_stake = int(float(r.get("stake", 0) or 0))
            existing_pick = str(r.get("pick","")).upper()

        with st.container(border=True):
            # タイトル
            left, right = st.columns([3, 1])
            with left:
                st.markdown(
                    f"""<div class="match-title">
                        <span class="small subtle">GW{gw}・{ko_local:%m/%d %H:%M}</span><br>
                        <span class="home">{home}</span> vs <span>{away}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )
            with right:
                if not match_locked:
                    st.success("OPEN", icon="✅")
                else:
                    st.error("LOCKED", icon="🔒")
                    
                st.success("OPEN", icon="✅") if not match_locked else st.error("LOCKED", icon="🔒")

            st.markdown(
                f"""<div class="match-odds">
                    Home: <b>{od['home']:.2f}</b>　• Draw: <b>{od['draw']:.2f}</b>　• Away: <b>{od['away']:.2f}</b>
                </div>""",
                unsafe_allow_html=True,
            )
            if placeholder:
                st.info("オッズ未入力のため仮オッズ（=1.0）を表示中。管理者は『オッズ管理』で設定してください。")

            # 3分割セグメント（Radio）
            options = [f"Home Win（{home}）", "Draw", f"Away Win（{away}）"]
            if   existing_pick == "HOME": default_idx = 0
            elif existing_pick == "DRAW": default_idx = 1
            elif existing_pick == "AWAY": default_idx = 2
            else:                         default_idx = 0

            pick_label = st.radio(
                "ピック",
                options,
                horizontal=True,
                index=default_idx,
                key=f"pick-{match_id}",
            )

            cap = max(0, max_total - placed_total + existing_stake)
            stake_val = existing_stake if existing_stake > 0 else 0
            stake = st.number_input(
                "ステーク",
                min_value=0, max_value=cap, step=step, value=stake_val,
                key=f"stake-{match_id}",
                help=f"このカードで使える上限: {cap}（既存ベット分 {existing_stake} を含む）"
            )

            # 他ユーザーのベット状況（OPENのみ）
            bets = open_bets_for_match(int(gw), match_id)
            if bets:
                st.caption("他ユーザーのベット状況（OPEN）")
                # バッジ化
                badges_html = ['<div class="bet-badges">']
                for b in bets:
                    uname = str(b.get("user",""))
                    pk = _pretty_pick_name(str(b.get("pick","")), home, away)
                    stv = int(float(b.get("stake", 0) or 0))
                    cls = "bet-badge me" if uname == user else "bet-badge"
                    badges_html.append(f'<span class="{cls}">{uname}: {pk} / {stv}</span>')
                badges_html.append("</div>")
                st.markdown("".join(badges_html), unsafe_allow_html=True)

            btn_disabled = match_locked or stake <= 0 or cap <= 0
            action_label = "ベットを更新" if my_bet else "この内容でベット"
            if st.button(action_label, key=f"bet-{match_id}", disabled=btn_disabled):
                if pick_label.startswith("Home"):
                    pkey, o = "HOME", float(od["home"])
                elif pick_label.startswith("Draw"):
                    pkey, o = "DRAW", float(od["draw"])
                else:
                    pkey, o = "AWAY", float(od["away"])

                try:
                    upsert_bet_row(
                        gw=int(gw),
                        user=user,
                        match_id=match_id,
                        match_label=f"{home} vs {away}",
                        pick=pkey,
                        stake=int(stake),
                        odds=o,
                    )
                    st.success("ベットを記録しました！")
                    st.rerun()
                except Exception as e:
                    st.error(f"書き込みに失敗しました: {e}")

def render_history():
    st.header("📁 履歴")
    st.info("履歴ページは今後実装します。")

def render_realtime():
    st.header("⏱ リアルタイム")
    st.info("リアルタイムページは今後実装します。")

def render_odds_admin():
    st.header("🛠 オッズ管理（管理者）")
    st.info("次のステップで実装します。")

def main():
    user = _current_user()
    if not user:
        show_login(); return

    with st.container():
        st.button("ログアウト", on_click=_logout)
        st.markdown(f"<div style='text-align:right'>ログイン中：<b>{user['username']}</b>（{user.get('role','user')}）</div>", unsafe_allow_html=True)

    admin = (user.get("role") == "admin")
    if admin:
        tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱ リアルタイム", "🛠 オッズ管理"])
        pages = [render_home, render_matches_and_bets, render_history, render_realtime, render_odds_admin]
    else:
        tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱ リアルタイム"])
        pages = [render_home, render_matches_and_bets, render_history, render_realtime]
    for tab, page in zip(tabs, pages):
        with tab: page()

if __name__ == "__main__":
    main()
