# =========================
# Premier Picks (single-file tabs)
# =========================
from __future__ import annotations
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pytz
import requests
import streamlit as st

from google_sheets_client import (
    read_config, read_rows_by_sheet, upsert_row, read_bets, read_odds,
)
from football_api import (
    fetch_matches_next_gw, simplify_matches, fetch_match_results_for_ids,
    outcome_from_score,
)
from util import (
    gw_label, to_local, fmt_yen, safe_int, outcome_text_jp,
    calc_payout_and_net, gw_sort_key, safe_userlist_from_config
)

# ---------- Basic page config (once) ----------
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

# ---------- Cache wrappers ----------
@st.cache_data(ttl=180)
def _cached_config():
    return read_config()

@st.cache_data(ttl=90)
def _cached_bets():
    return read_bets()

@st.cache_data(ttl=90)
def _cached_odds():
    return read_odds()

# ---------- Auth ----------
def ensure_auth(conf: Dict) -> Optional[Dict]:
    users = safe_userlist_from_config(conf.get("users_json", "[]"))
    names = [u["username"] for u in users]
    if not names:
        st.warning("config の users_json が空です。いったん guest のみで表示します。")
        users = [{"username":"guest","password":"", "role":"user", "team":""}]
        names = ["guest"]

    if "me" in st.session_state:
        return st.session_state["me"]

    st.title("Premier Picks")
    with st.form("login_form", clear_on_submit=False):
        col1, col2 = st.columns([1,1])
        with col1:
            username = st.selectbox("ユーザー", options=names, index=0, key="login_user")
        with col2:
            pwd = st.text_input("パスワード", type="password", value="", key="login_pwd")
        submitted = st.form_submit_button("ログイン", use_container_width=True)
        if submitted:
            user = next((u for u in users if u["username"] == username), None)
            if user and (user.get("password", "") == pwd):
                st.session_state["me"] = user
                st.success("ログインに成功しました。")
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います。")
    return None

# ---------- Helpers (data) ----------
def get_conf() -> Dict:
    conf_rows = _cached_config()
    conf = {row["key"]: row["value"] for row in conf_rows if row.get("key")}
    # 型補正
    conf["lock_minutes_before_earliest"] = safe_int(conf.get("lock_minutes_before_earliest", 120), 120)
    conf["max_total_stake_per_gw"] = safe_int(conf.get("max_total_stake_per_gw", 5000), 5000)
    conf["stake_step"] = safe_int(conf.get("stake_step", 100), 100)
    conf["ODDS_MARKET"] = safe_int(conf.get("ODDS_MARKET", 1), 1)
    conf["ODDS_BOOKMAKER_ID"] = safe_int(conf.get("ODDS_BOOKMAKER_ID", 8), 8)
    return conf

def gw_lock_threshold(matches: List[Dict], conf: Dict) -> Optional[datetime]:
    """GW 全体のロック時刻（最初の試合のキックオフの X 分前 / UTC）"""
    if not matches:
        return None
    first = min(m["utc_kickoff"] for m in matches)
    return first - timedelta(minutes=conf.get("lock_minutes_before_earliest", 120))

def can_bet_now(locked_at_utc: Optional[datetime]) -> bool:
    if locked_at_utc is None:
        return False
    return datetime.now(timezone.utc) < locked_at_utc

def odds_for_match(odds_rows: List[Dict], match_id: int) -> Tuple[float, float, float, bool]:
    row = next((o for o in odds_rows if str(o.get("match_id")) == str(match_id)), None)
    if not row:
        return 1.0, 1.0, 1.0, True
    try:
        h = float(row.get("home", 1.0))
        d = float(row.get("draw", 1.0))
        a = float(row.get("away", 1.0))
    except Exception:
        h, d, a = 1.0, 1.0, 1.0
    missing = any(x == 1.0 for x in (h, d, a))
    return h, d, a, missing

def my_gw_stake_sum(bets: List[Dict], username: str, gw: str) -> int:
    return int(sum(safe_int(b.get("stake", 0), 0) for b in bets if b.get("username")==username and str(b.get("gw",""))==gw))

# ---------- Pages ----------
def page_matches_and_bets(conf: Dict, me: Dict):
    tz = pytz.timezone(conf.get("timezone", "Asia/Tokyo"))
    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("7日以内に次節はありません。")
        return

    matches = simplify_matches(matches_raw, tz)
    st.subheader("試合とベット")
    st.caption(f"このGWのあなたの投票合計: {fmt_yen(my_gw_stake_sum(_cached_bets(), me['username'], gw))} / 上限 {fmt_yen(conf['max_total_stake_per_gw'])}")

    # GWロック判定（最初の試合の2時間前にGW内すべてロック）
    threshold = gw_lock_threshold(matches, conf)
    locked = not can_bet_now(threshold)
    # 表示
    if not locked:
        st.success("OPEN", icon="✅")
    else:
        st.error("LOCKED", icon="🔒")
    if threshold:
        st.caption(f"ロック基準時刻（最初の試合の120分前・UTC基準）: {threshold.isoformat()}")

    # データ
    bets = _cached_bets()
    odds_rows = _cached_odds()

    # 各試合カード
    for m in matches:
        match_id = int(m["id"])
        home, away = m["home"], m["away"]
        h, d, a, missing = odds_for_match(odds_rows, match_id)

        with st.container(border=True):
            # ヘッダ
            st.markdown(f"**{gw_label(m['gw'])}**  ・  {m['local_kickoff'].strftime('%m/%d %H:%M')}")
            st.markdown(f"**{home}** vs {away}")

            if missing:
                st.info("オッズ未入力のため仮オッズ(=1.0)を表示中。管理者は『オッズ管理』で設定してください。")

            st.caption(f"Home: {h:.2f} ・ Draw: {d:.2f} ・ Away: {a:.2f}")

            # 他ユーザーのベット状況（現時点）
            this_bets = [b for b in bets if str(b.get("match_id"))==str(match_id)]
            agg = {"HOME":0, "DRAW":0, "AWAY":0}
            for b in this_bets:
                pick = (b.get("pick") or "").upper()
                agg[pick] = agg.get(pick,0) + safe_int(b.get("stake",0),0)
            st.caption(f"現在のベット状況： HOME {agg['HOME']} / DRAW {agg['DRAW']} / AWAY {agg['AWAY']}")

            # 自分の既存ベット
            my_bet = next((b for b in this_bets if b.get("username")==me["username"]), None)
            default_pick = (my_bet.get("pick") if my_bet else "HOME").upper()
            default_stake = safe_int(my_bet.get("stake", conf["stake_step"]) if my_bet else conf["stake_step"], conf["stake_step"])

            # 入力UI（キー重複回避）
            pick = st.radio(
                "ピック", options=["HOME","DRAW","AWAY"],
                index=["HOME","DRAW","AWAY"].index(default_pick),
                horizontal=True, key=f"pick_{match_id}", disabled=locked
            )
            stake = st.number_input(
                "ステーク", min_value=conf["stake_step"], step=conf["stake_step"],
                value=default_stake, key=f"stake_{match_id}", disabled=locked
            )
            btn = st.button("この内容でベット", key=f"bet_{match_id}", use_container_width=True, disabled=locked)

            if btn:
                # GW上限チェック
                current_sum = my_gw_stake_sum(bets, me["username"], gw)
                new_sum = current_sum - (safe_int(my_bet.get("stake",0),0) if my_bet else 0) + stake
                if new_sum > conf["max_total_stake_per_gw"]:
                    st.error(f"このGWの上限 {fmt_yen(conf['max_total_stake_per_gw'])} を超えています。現在 {fmt_yen(current_sum)}。")
                else:
                    payload = {
                        "gw": gw, "match_id": match_id,
                        "username": me["username"], "pick": pick,
                        "stake": int(stake), "home": home, "away": away,
                        "odds_home": h, "odds_draw": d, "odds_away": a,
                        "ts": datetime.utcnow().isoformat()
                    }
                    upsert_row("bets", keys=["gw","match_id","username"], row=payload)
                    st.success("ベットを記録しました！")
                    _cached_bets.clear()
                    st.rerun()

def page_history(conf: Dict, me: Dict):
    st.subheader("履歴")
    all_bets = _cached_bets()

    # GW 候補（必ず文字列化して安定ソート）
    gws = sorted(
        {str(b.get("gw","")) for b in all_bets if b.get("gw")},
        key=gw_sort_key
    )
    if not gws:
        st.info("履歴なし。")
        return

    gw = st.selectbox("ゲームウィーク", options=gws, index=len(gws)-1)
    bets_gw = [b for b in all_bets if str(b.get("gw","")) == gw]
    if not bets_gw:
        st.info("このGWの履歴はありません。")
        return

    # 結果取得（API）
    match_ids = sorted({int(b["match_id"]) for b in bets_gw if b.get("match_id")})
    results = fetch_match_results_for_ids(conf, match_ids)  # {match_id: {"homeScore":..,"awayScore":..}}
    odds_rows = _cached_odds()

    # 自分と他人の明細
    def row_view(b):
        oid = int(b["match_id"])
        home, away = b.get("home",""), b.get("away","")
        h,d,a,_ = odds_for_match(odds_rows, oid)
        res = results.get(oid)
        outcome = outcome_from_score(res) if res else None
        payout, net = calc_payout_and_net(b["pick"], outcome, b.get("stake",0), h,d,a)
        left = f"{home} vs {away}"
        right = f"{outcome_text_jp(outcome)} / 払戻 {fmt_yen(payout)} / 収支 {fmt_yen(net)}"
        st.markdown(f"- **{b['username']}**：{left} → {b['pick']} / {right}")

    for b in sorted(bets_gw, key=lambda x: (x.get("username",""), int(x.get("match_id", 0)))):
        row_view(b)

def page_realtime(conf: Dict, me: Dict):
    st.subheader("リアルタイム")
    st.caption("このページは自動更新しません。『最新に更新』で必要時だけAPIにアクセスします。")
    refresh = st.button("最新に更新", use_container_width=True)
    if not refresh and "realtime_cache" in st.session_state:
        data = st.session_state["realtime_cache"]
    else:
        # 次節の試合（7日枠）を対象に、現在スコアを取得
        matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
        if not matches_raw:
            st.info("次節はまだ先のようです。")
            return
        ids = [int(m["id"]) for m in matches_raw]
        results = fetch_match_results_for_ids(conf, ids, realtime=True)
        st.session_state["realtime_cache"] = (gw, matches_raw, results)
        data = st.session_state["realtime_cache"]

    gw, matches_raw, results = data
    st.markdown(f"**{gw_label(gw)}** 現在の途中結果")

    odds_rows = _cached_odds()
    bets = _cached_bets()

    # 集計
    for m in simplify_matches(matches_raw, pytz.timezone(get_conf().get("timezone","Asia/Tokyo"))):
        oid = int(m["id"]); home, away = m["home"], m["away"]
        h,d,a,_ = odds_for_match(odds_rows, oid)
        res = results.get(oid)  # 途中スコアも入る
        outcome = outcome_from_score(res) if res else None
        with st.container(border=True):
            st.markdown(f"**{home}** vs {away}")
            st.caption(f"スコア: {res.get('home',0)} - {res.get('away',0)}" if res else "スコア: -")
            # 各人の時点収支
            these = [b for b in bets if int(b.get("match_id", -1)) == oid]
            if not these:
                st.caption("ベットなし")
            else:
                for b in sorted(these, key=lambda x: x.get("username","")):
                    payout, net = calc_payout_and_net(b["pick"], outcome, b.get("stake",0), h,d,a)
                    st.markdown(f"- **{b['username']}**: {b['pick']} / 払戻 {fmt_yen(payout)} / 収支 {fmt_yen(net)}")

def page_dashboard(conf: Dict, me: Dict):
    st.subheader("ダッシュボード")
    bets = _cached_bets()
    odds_rows = _cached_odds()

    # 直近N GW の結果ベース KPI（確定結果= API の FINISHED を使用）
    all_match_ids = sorted({int(b["match_id"]) for b in bets if b.get("match_id")})
    results = fetch_match_results_for_ids(conf, all_match_ids, finished_only=True)
    # user -> totals
    kpi = {}
    for b in bets:
        uid = b.get("username","")
        oid = int(b.get("match_id", -1))
        res = results.get(oid)
        if not res:
            continue
        outcome = outcome_from_score(res)
        h,d,a,_ = odds_for_match(odds_rows, oid)
        payout, net = calc_payout_and_net(b.get("pick"), outcome, b.get("stake",0), h,d,a)
        agg = kpi.setdefault(uid, {"stake":0, "payout":0, "net":0})
        agg["stake"] += safe_int(b.get("stake",0),0)
        agg["payout"] += payout
        agg["net"] += net

    # KPI cards
    col1, col2, col3 = st.columns(3)
    my = kpi.get(me["username"], {"stake":0,"payout":0,"net":0})
    col1.metric("あなたの総投資", fmt_yen(my["stake"]))
    col2.metric("あなたの総払戻", fmt_yen(my["payout"]))
    col3.metric("あなたの総収支", fmt_yen(my["net"]))

    st.divider()
    st.markdown("#### ユーザー別 収支ランキング")
    ranking = sorted(((u, v["net"]) for u,v in kpi.items()), key=lambda x: x[1], reverse=True)
    for i,(u,net) in enumerate(ranking, start=1):
        st.markdown(f"{i}. **{u}** : {fmt_yen(net)}")

    st.divider()
    st.markdown("#### ユーザー別『的中チーム』ランキング")
    # チーム別的中率（払戻金額合計）上位
    team_win = {}
    for b in bets:
        oid = int(b.get("match_id",-1))
        res = results.get(oid)
        if not res:
            continue
        outcome = outcome_from_score(res)
        h,d,a,_ = odds_for_match(_cached_odds(), oid)
        payout, net = calc_payout_and_net(b.get("pick"), outcome, b.get("stake",0), h,d,a)
        if payout <= 0:
            continue
        team = b.get("home") if b.get("pick")=="HOME" else (b.get("away") if b.get("pick")=="AWAY" else "DRAW")
        key = (b.get("username",""), team)
        team_win[key] = team_win.get(key, 0) + payout

    # 表示（上位）
    top = sorted(team_win.items(), key=lambda x: x[1], reverse=True)[:10]
    if not top:
        st.caption("まだデータが十分ではありません。")
    else:
        for (u,team), amt in top:
            st.markdown(f"- **{u}** が良く当てているチーム：**{team}**（払戻 {fmt_yen(amt)}）")

def page_odds_admin(conf: Dict, me: Dict):
    st.subheader("オッズ管理")
    if (me.get("role","user") != "admin"):
        st.warning("管理者のみが利用できます。")
        return

    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("7日以内に次節はありません。")
        return
    tz = pytz.timezone(conf.get("timezone","Asia/Tokyo"))
    matches = simplify_matches(matches_raw, tz)
    odds_rows = _cached_odds()

    for m in matches:
        mid = int(m["id"])
        h,d,a,missing = odds_for_match(odds_rows, mid)
        with st.container(border=True):
            st.markdown(f"**{m['home']}** vs {m['away']}  （{m['local_kickoff'].strftime('%m/%d %H:%M')}）")
            c1,c2,c3, c4 = st.columns([1,1,1,1])
            oh = c1.number_input("Home", value=float(h), step=0.01, key=f"oh_{mid}")
            od = c2.number_input("Draw", value=float(d), step=0.01, key=f"od_{mid}")
            oa = c3.number_input("Away", value=float(a), step=0.01, key=f"oa_{mid}")
            if c4.button("保存", key=f"save_{mid}"):
                upsert_row("odds", keys=["match_id"], row={
                    "match_id": mid, "home": oh, "draw": od, "away": oa,
                    "gw": m["gw"], "home_team": m["home"], "away_team": m["away"]
                })
                _cached_odds.clear()
                st.success("保存しました。")

# ---------- Main ----------
def main():
    conf = get_conf()
    me = ensure_auth(conf)
    if not me:
        return

    # Header nav
    st.sidebar.empty()
    st.caption(f"ログイン中： {me['username']} ({me.get('role','user')})")
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱️ リアルタイム", "📊 ダッシュボード", "🛠 オッズ管理"])

    with tabs[0]:
        st.subheader("トップ")
        st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")

    with tabs[1]:
        page_matches_and_bets(conf, me)

    with tabs[2]:
        page_history(conf, me)

    with tabs[3]:
        page_realtime(conf, me)

    with tabs[4]:
        page_dashboard(conf, me)

    with tabs[5]:
        page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
