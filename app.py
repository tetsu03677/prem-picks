from __future__ import annotations
from typing import Dict, List
from datetime import datetime, timedelta
from dateutil import tz

import streamlit as st

from google_sheets_client import (
    read_config, read_odds, upsert_odds_row,
    read_bets, upsert_bet, user_total_stake_in_gw, other_bets_for_match
)
from football_api import fetch_matches_window

# ============ 共通UI ============
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="centered")

def pill(text: str, ok=True):
    if ok:
        st.success(text)
    else:
        st.error(text)

def h3(text: str):
    st.markdown(f"<h3 style='margin:0.2rem 0 0.6rem 0'>{text}</h3>", unsafe_allow_html=True)

def small_mono(text: str):
    st.markdown(f"<div style='font-size:0.85rem;opacity:0.85'>{text}</div>", unsafe_allow_html=True)

def big_team_label(home: str, away: str):
    st.markdown(
        f"""
        <div style="font-size:1.05rem;line-height:1.5">
            <b>{home}</b> <span style="opacity:.7">vs</span> {away}
        </div>
        """,
        unsafe_allow_html=True
    )

# ============ ログイン ============
def parse_users(conf: Dict[str, str]) -> List[Dict]:
    import json
    try:
        return json.loads(conf.get("users_json","[]"))
    except Exception:
        return [{"username":"guest","password":"guest","role":"user","team":"-"}]

def show_login():
    st.markdown("## ログイン")
    conf = read_config()
    users = parse_users(conf)
    usernames = [u["username"] for u in users]

    with st.form("login"):
        u = st.selectbox("ユーザー", usernames, index=0)
        p = st.text_input("パスワード", type="password")
        ok = st.form_submit_button("ログイン")
    if ok:
        user = next((x for x in users if x["username"]==u and x["password"]==p), None)
        if user:
            st.session_state["user"] = user
            st.success(f"ようこそ {u} さん！")
            st.rerun()
        else:
            st.error("ユーザー名 or パスワードが違います。")

def need_login() -> bool:
    return "user" not in st.session_state

# ============ 試合 & ベット ============
def page_matches_and_bets():
    conf = read_config()
    user = st.session_state["user"]["username"]
    role = st.session_state["user"]["role"]
    tzname = conf.get("timezone","Asia/Tokyo")
    tzinfo = tz.gettz(tzname)

    current_gw = conf.get("current_gw","GW?")
    st.markdown("### 🎯 試合とベット")
    used = user_total_stake_in_gw(user, current_gw)
    max_total = int(conf.get("max_total_stake_per_gw","5000"))
    st.caption(f"このGWのあなたの投票合計: {used} / 上限 {max_total}（残り {max_total - used}）")

    # 次節＝7日以内ロジック
    matches, debug_url = fetch_matches_window(7, conf.get("API_FOOTBALL_LEAGUE_ID","39"), conf.get("API_FOOTBALL_SEASON","2025"))
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    # 取得時刻 / デバッグ
    with st.expander("取得情報"):
        st.code(debug_url, language="text")

    odds_map = read_odds()
    stake_step = int(conf.get("stake_step","100"))
    lock_before = int(conf.get("lock_minutes_before_earliest","120"))

    # 最も早いKO
    earliest = None
    for m in matches:
        dt = datetime.fromisoformat(m["utcDate"].replace("Z","+00:00"))
        earliest = dt if earliest is None else min(earliest, dt)
    lock_threshold = earliest - timedelta(minutes=lock_before) if earliest else None

    h3(f"試合一覧（{current_gw}）")
    for m in sorted(matches, key=lambda x: x["utcDate"]):
        mid = m["match_id"]
        ko_utc = datetime.fromisoformat(m["utcDate"].replace("Z","+00:00"))
        ko_local = ko_utc.astimezone(tzinfo)
        match_locked = lock_threshold is not None and datetime.utcnow() >= lock_threshold

        st.container()
        with st.container(border=True):
            # 行頭バッジ
            st.markdown(f"**{current_gw}** ・ {ko_local.strftime('%m/%d %H:%M')}")
            big_team_label(m["home"], m["away"])

            # 状態バッジ（式ではなく文で）
            if not match_locked:
                st.success("OPEN", icon="✅")
            else:
                st.error("LOCKED", icon="🔒")

            # オッズ
            rec = odds_map.get(mid)
            if rec and (rec["home_win"] and rec["draw"] and rec["away_win"]):
                home_o, draw_o, away_o = rec["home_win"], rec["draw"], rec["away_win"]
            else:
                home_o = draw_o = away_o = 1.0
                st.info("オッズ未入力のため仮オッズ（=1.0）を表示中。管理者は『オッズ管理』で設定してください。")

            st.markdown(f"Home: **{home_o:.2f}** ・ Draw: **{draw_o:.2f}** ・ Away: **{away_o:.2f}**")

            # 既存ベット（自分）
            my_key = f"{current_gw}__{user}__{mid}"
            my_bet = None
            for r in read_bets():
                if r.get("key")==my_key:
                    my_bet = r
                    break

            # ピック 3分割
            cols = st.columns(3)
            with cols[0]:
                pick_home = st.toggle(f"HOME WIN\n({m['home']})", value=(my_bet and my_bet.get("pick")=="H"), key=f"pickH_{mid}")
            with cols[1]:
                pick_draw = st.toggle("DRAW", value=(my_bet and my_bet.get("pick")=="D"), key=f"pickD_{mid}")
            with cols[2]:
                pick_away = st.toggle(f"AWAY WIN\n({m['away']})", value=(my_bet and my_bet.get("pick")=="A"), key=f"pickA_{mid}")

            # 排他化
            pick_val = None
            if pick_home: 
                pick_val = "H"
                st.session_state[f"pickD_{mid}"] = False
                st.session_state[f"pickA_{mid}"] = False
            elif pick_draw:
                pick_val = "D"
                st.session_state[f"pickH_{mid}"] = False
                st.session_state[f"pickA_{mid}"] = False
            elif pick_away:
                pick_val = "A"
                st.session_state[f"pickH_{mid}"] = False
                st.session_state[f"pickD_{mid}"] = False

            # ステーク
            default_stake = int(my_bet.get("stake")) if my_bet else stake_step*4
            stake = st.number_input("ステーク", min_value=0, max_value=max_total, step=stake_step, value=default_stake, key=f"stake_{mid}", help="この試合に賭ける金額")

            # 他ユーザーのベット
            others = other_bets_for_match(mid, user)
            if others:
                chips = " / ".join([f"**{o['user']}**: {o['pick']}×{o['stake']}" for o in others])
                st.caption(f"他ユーザーのベット状況: {chips}")

            disabled = match_locked or (pick_val is None) or (stake<=0)
            if st.button("この内容でベット", key=f"betbtn_{mid}", disabled=disabled):
                # 上限チェック
                already = user_total_stake_in_gw(user, current_gw) - (int(my_bet.get("stake")) if my_bet else 0)
                if already + stake > max_total:
                    st.error("このGWの投票上限を超えます。金額を調整してください。")
                else:
                    sel_odds = {"H":home_o, "D":draw_o, "A":away_o}.get(pick_val, 1.0)
                    upsert_bet(
                        gw=current_gw,
                        user=user,
                        match_id=mid,
                        match_label=f"{m['home']} vs {m['away']}",
                        pick=pick_val,
                        stake=int(stake),
                        odds=float(sel_odds),
                        status="placed"
                    )
                    st.success("ベットを記録しました！")
                    st.rerun()

# ============ オッズ管理（管理者） ============
def page_odds_admin():
    conf = read_config()
    role = st.session_state["user"]["role"]
    if role != "admin":
        st.warning("管理者のみ利用できます。")
        return

    st.markdown("### 🛠 オッズ管理")
    matches, _ = fetch_matches_window(14, conf.get("API_FOOTBALL_LEAGUE_ID","39"), conf.get("API_FOOTBALL_SEASON","2025"))
    if not matches:
        st.info("対象期間に試合がありません。")
        return

    current_gw = conf.get("current_gw","GW?")
    odds_map = read_odds()

    for m in sorted(matches, key=lambda x:x["utcDate"]):
        mid = m["match_id"]
        rec = odds_map.get(mid, {})
        st.divider()
        st.write(f"**{m['home']} vs {m['away']}**  (match_id: `{mid}`)")
        c1,c2,c3,c4,c5 = st.columns([1,1,1,1,1])
        with c1:
            home_o = st.number_input("Home", value=float(rec.get("home_win",1.0)), step=0.01, key=f"h_{mid}")
        with c2:
            draw_o = st.number_input("Draw", value=float(rec.get("draw",1.0)), step=0.01, key=f"d_{mid}")
        with c3:
            away_o = st.number_input("Away", value=float(rec.get("away_win",1.0)), step=0.01, key=f"a_{mid}")
        with c4:
            locked = st.checkbox("Locked", value=bool(rec.get("locked", False)), key=f"l_{mid}")
        with c5:
            if st.button("保存", key=f"save_{mid}"):
                upsert_odds_row(
                    gw=current_gw, match_id=mid, home=m["home"], away=m["away"],
                    home_win=float(home_o), draw=float(draw_o), away_win=float(away_o),
                    locked=locked
                )
                st.success("保存しました")
                st.rerun()

# ============ ヘッダ & ルーティング ============
def main():
    if need_login():
        show_login()
        return

    user = st.session_state["user"]
    st.sidebar.success(f"ログイン中: {user['username']} ({user['role']})")
    if st.sidebar.button("ログアウト"):
        st.session_state.clear()
        st.rerun()

    tabs = st.tabs(["🏠 トップ","🎯 試合とベット","📁 履歴","⏱ リアルタイム","🛠 オッズ管理"])
    with tabs[0]:
        st.markdown("## トップ")
        st.write(f"ようこそ **{user['username']}** さん！")

    with tabs[1]:
        page_matches_and_bets()
    with tabs[2]:
        st.info("履歴は今後追加予定。")
    with tabs[3]:
        st.info("リアルタイムは今後追加予定。")
    with tabs[4]:
        page_odds_admin()

if __name__ == "__main__":
    main()
