# app.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime, timedelta, timezone
import json
import pytz
import streamlit as st

from google_sheets_client import (
    read_config, read_odds, read_bets, upsert_odds_row, upsert_bet
)
from football_api import (
    get_upcoming, get_matches_range, get_matches_by_ids, winner_from_score
)

# ============== 共通ユーティリティ ==============
def get_conf() -> Dict[str, Any]:
    conf = read_config()
    conf["odds_freeze_minutes_before_first"] = int(conf.get("odds_freeze_minutes_before_first", "120"))
    conf["stake_step"] = int(conf.get("stake_step", "100"))
    conf["max_total_stake_per_gw"] = int(conf.get("max_total_stake_per_gw", "5000"))
    return conf

def ensure_auth(conf: Dict[str, Any]) -> Dict[str, Any]:
    st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

    users = json.loads(conf.get("users_json", "[]"))
    user_map = {u["username"]: u for u in users}

    # 右上ナビっぽく
    st.write(
        """
        <div style="display:flex;gap:16px;align-items:center;justify-content:flex-end;">
          <span>ログイン中 :</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "me" not in st.session_state:
        st.session_state["me"] = None

    if st.session_state["me"] is None:
        st.title("🏠 トップ")
        with st.form("login"):
            name = st.text_input("ユーザー名")
            pw = st.text_input("パスワード", type="password")
            ok = st.form_submit_button("ログイン")
        if ok:
            u = user_map.get(name)
            if not u or u.get("password") != pw:
                st.error("認証に失敗しました。")
            else:
                st.session_state["me"] = u
                st.rerun()
        st.stop()

    me = st.session_state["me"]
    with st.sidebar:
        st.write(f"ログイン中 : **{me['username']}** ({me['role']})")
        if st.button("ログアウト"):
            st.session_state.clear()
            st.rerun()
    return me

def compute_lock(matches: List[Dict[str, Any]], conf: Dict[str, Any]):
    if not matches:
        return False, None
    first = min(m["utc_kickoff"] for m in matches)
    lock_at = first - timedelta(minutes=conf["odds_freeze_minutes_before_first"])
    locked = datetime.utcnow().replace(tzinfo=timezone.utc) >= lock_at
    return locked, lock_at

def agg_bets(bets: List[Dict[str, Any]]):
    total = {"HOME":0, "DRAW":0, "AWAY":0}
    for b in bets:
        try:
            total[b.get("pick","")] += int(b.get("stake","0") or 0)
        except Exception:
            pass
    return total

# ============== 試合とベット ==============
def page_matches_and_bets(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("🎯 試合とベット")
    matches, gw = get_upcoming(conf, days=7)
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    locked, lock_at = compute_lock(matches, conf)
    if lock_at:
        jst = pytz.timezone(conf.get("timezone","Asia/Tokyo"))
        st.caption(f"このGWのロック時刻: {lock_at.astimezone(jst).strftime('%Y-%m-%d %H:%M')}")

    odds_map = read_odds(gw)
    all_bets = read_bets(gw)

    my_total = sum(int(b.get("stake","0") or 0) for b in all_bets if b.get("user")==me["username"])
    st.caption(f"このGWのあなたの投票合計: **{my_total}** / 上限 **{conf['max_total_stake_per_gw']}**")

    for m in sorted(matches, key=lambda x: x["utc_kickoff"]):
        home, away, mid = m["home"], m["away"], m["id"]
        local_str = m["local_kickoff"].strftime("%m/%d %H:%M")
        st.subheader(f"**{home}** vs {away}  ・ {local_str}")

        om = odds_map.get(mid, {})
        o_home = float(om.get("home_win") or 1.0)
        o_draw = float(om.get("draw") or 1.0)
        o_away = float(om.get("away_win") or 1.0)
        st.write(f"Home: **{o_home:.2f}** ・ Draw: **{o_draw:.2f}** ・ Away: **{o_away:.2f}**")
        if not om:
            st.info("オッズ未入力のため仮オッズ（=1.0）を表示中。管理者は『オッズ管理』で設定してください。")

        bets_this = [b for b in all_bets if b.get("match_id")==mid]
        agg = agg_bets(bets_this)
        mine = next((b for b in bets_this if b.get("user")==me["username"]), None)
        if mine:
            st.caption(f"あなたの現状: **{mine.get('pick')} {mine.get('stake')}**")
        st.caption(f"全体：HOME {agg['HOME']} / DRAW {agg['DRAW']} / AWAY {agg['AWAY']}")

        if locked:
            st.warning("このGWはロックされています。ベットの変更・新規はできません。")
            st.divider()
            continue

        pick_default = (mine.get("pick") if mine else "HOME")
        pick = st.radio("ピック", ["HOME","DRAW","AWAY"],
                        index=["HOME","DRAW","AWAY"].index(pick_default),
                        horizontal=True, key=f"pick_{mid}")
        stake_default = int(mine.get("stake") or conf["stake_step"]) if mine else conf["stake_step"]
        stake = st.number_input("ステーク", min_value=conf["stake_step"],
                                step=conf["stake_step"], value=stake_default, key=f"stake_{mid}")

        if st.button("この内容でベット", key=f"bet_{mid}"):
            new_total = my_total - (int(mine.get("stake") or 0) if mine else 0) + int(stake)
            if new_total > conf["max_total_stake_per_gw"]:
                st.error("このGWの上限を超えます。")
            else:
                odds_pick = {"HOME": o_home, "DRAW": o_draw, "AWAY": o_away}[pick]
                upsert_bet(gw, me["username"], mid, f"{home} vs {away}", pick, int(stake), float(odds_pick))
                st.success("ベットを記録 / 更新しました。")
                st.rerun()
        st.divider()

# ============== オッズ管理 ==============
def page_odds_admin(conf: Dict[str, Any], me: Dict[str, Any]):
    if me.get("role") != "admin":
        st.warning("管理者専用ページです。")
        return
    st.header("🛠 オッズ管理（1X2）")
    matches, gw = get_upcoming(conf, days=14)
    st.caption(f"対象GW: {gw}")
    locked, _ = compute_lock(matches, conf)
    if locked:
        st.warning("ロック中のため、編集できません。")
        return

    odds_map = read_odds(gw)
    for m in sorted(matches, key=lambda x: x["utc_kickoff"]):
        mid, home, away = m["id"], m["home"], m["away"]
        st.subheader(f"{home} vs {away}")
        base = odds_map.get(mid, {})
        h = float(base.get("home_win") or 1.0)
        d = float(base.get("draw") or 1.0)
        a = float(base.get("away_win") or 1.0)

        c1, c2, c3, c4 = st.columns([1,1,1,1])
        with c1: h = st.number_input("Home", min_value=1.0, step=0.01, value=h, key=f"h_{mid}")
        with c2: d = st.number_input("Draw", min_value=1.0, step=0.01, value=d, key=f"d_{mid}")
        with c3: a = st.number_input("Away", min_value=1.0, step=0.01, value=a, key=f"a_{mid}")
        with c4:
            if st.button("保存", key=f"save_{mid}"):
                upsert_odds_row(gw, mid, home, away, f"{h}", f"{d}", f"{a}", "0")
                st.success("保存しました。")
                st.rerun()
        st.divider()

# ============== ダッシュボード ==============
def page_dashboard(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("📊 ダッシュボード")
    # 全期間のbetsを読み、総投票/回収など（result/payoutが入力されていれば確定、なければ未確定）
    # ここでは簡易に “確定行のみ” を合算
    # ※将来、決済バッチが入ればここを置換
    all_bets = read_bets("")  # 全件読み（関数はGWフィルタ無視で全行返すよう仕様、空GWなら単純に全件になるよう実装している想定）
    # フィルタ（OPEN以外を確定とみなす）
    settled = [b for b in all_bets if (b.get("status") or "").upper() in ("WIN","LOSE","VOID","SETTLED")]
    total_stake = sum(int(b.get("stake") or 0) for b in settled)
    total_payout = sum(float(b.get("payout") or 0) for b in settled)
    total_net = sum(float(b.get("net") or 0) for b in settled)

    c1,c2,c3,c4 = st.columns(4)
    with c1: st.metric("累計ステーク", f"{total_stake:,}")
    with c2: st.metric("累計ペイアウト", f"{total_payout:,.0f}")
    with c3: st.metric("累計損益", f"{total_net:,.0f}")
    with c4: st.metric("今GWのブックメーカー", conf.get("bookmaker_username","未設定"))

    st.subheader("みんなの今GW 投票合計（速報）")
    matches, gw = get_upcoming(conf, days=7)
    bets_now = read_bets(gw)
    by_user = {}
    for b in bets_now:
        by_user.setdefault(b["user"], 0)
        by_user[b["user"]] += int(b.get("stake") or 0)
    st.write({k: f"{v:,}" for k,v in by_user.items()} or "（データなし）")

# ============== 履歴 ==============
def page_history(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("📁 履歴（過去GW）")
    # bets から存在する GW を収集
    all_bets = read_bets("")  # 全件
    gws = sorted({b.get("gw","") for b in all_bets if b.get("gw")}, key=lambda x: (len(x), x))
    if not gws:
        st.info("履歴がまだありません。")
        return
    sel_gw = st.selectbox("GWを選択", gws, index=len(gws)-1)

    bets = [b for b in all_bets if b.get("gw")==sel_gw]
    if not bets:
        st.info("このGWの履歴はありません。")
        return

    # APIから結果を取得し、試合単位で損益を集計（他人のも同様に閲覧）
    matches = get_matches_by_ids(conf, [b["match_id"] for b in bets])
    rows = []
    per_user = {}
    for b in bets:
        m = matches.get(b["match_id"], {})
        result_pick = winner_from_score(m.get("score",{}))
        stake = int(b.get("stake") or 0)
        odds = float(b.get("odds") or 1.0)
        payout = stake*odds if result_pick and result_pick == (b.get("pick") or "") else 0.0
        net = payout - stake
        rows.append({
            "user": b.get("user"),
            "match": b.get("match"),
            "pick": b.get("pick"),
            "stake": stake,
            "odds": odds,
            "status": m.get("status",""),
            "result": result_pick or "-",
            "payout": round(payout,2),
            "net": round(net,2),
        })
        per_user.setdefault(b["user"], 0.0)
        per_user[b["user"]] += net

    st.subheader(f"{sel_gw} 損益（ユーザー別合計）")
    st.write({u: f"{v:,.0f}" for u,v in per_user.items()})
    st.subheader("試合別の明細（全員分）")
    for r in rows:
        st.write(f"・{r['match']} | {r['user']} | {r['pick']} {r['stake']} @ {r['odds']} → [{r['result']}]  損益 {r['net']:,.0f}")

# ============== リアルタイム ==============
def page_realtime(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("⏱ リアルタイム")
    # 次節の全期間を対象に status/score を都度取得
    matches_sched, gw = get_upcoming(conf, days=7)
    if not matches_sched:
        st.info("7日以内に次節はありません。")
        return
    start = min(m["utc_kickoff"] for m in matches_sched)
    end = max(m["utc_kickoff"] for m in matches_sched) + timedelta(hours=3)

    matches_rt = get_matches_range(conf, start - timedelta(days=1), end + timedelta(days=1))
    # 次節に該当する試合のみフィルタ（idの照合）
    ids = {m["id"] for m in matches_sched}
    matches_rt = [m for m in matches_rt if m["id"] in ids]

    bets = read_bets(gw)
    bets_by_mid = {}
    for b in bets:
        bets_by_mid.setdefault(b["match_id"], []).append(b)

    per_user = {}
    st.caption(f"対象GW: {gw}  （初戦 {matches_sched[0]['local_kickoff'].strftime('%m/%d %H:%M')} 〜 最終戦後まで）")
    for m in sorted(matches_rt, key=lambda x: x["utc_kickoff"]):
        mid = m["id"]
        home, away = m["home"], m["away"]
        status = m.get("status","")
        res_pick = winner_from_score(m.get("score",{}))
        st.subheader(f"{home} vs {away}  [{status}]  結果: {res_pick or '-'}")
        bts = bets_by_mid.get(mid, [])
        if not bts:
            st.caption("ベットなし")
            continue
        # 試合単位の収支（確定は計算、未確定は0 とするシンプル運用）
        total_net = 0.0
        for b in bts:
            stake = int(b.get("stake") or 0)
            odds = float(b.get("odds") or 1.0)
            net = 0.0
            if status == "FINISHED" and res_pick:
                net = stake*odds - stake if res_pick == b.get("pick") else -stake
            total_net += net
            per_user.setdefault(b["user"], 0.0)
            per_user[b["user"]] += net
            st.write(f"・{b['user']:>8s} : {b['pick']} {stake} @ {odds} → 損益 {net:,.0f}")
        st.write(f"**試合合計 損益: {total_net:,.0f}**")
        st.divider()

    st.subheader("今GWの暫定損益（ユーザー別）")
    st.write({u: f"{v:,.0f}" for u,v in per_user.items()} or "（データなし）")

# ============== main ==============
def main():
    conf = get_conf()
    me = ensure_auth(conf)

    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📊 ダッシュボード", "📁 履歴", "⏱ リアルタイム", "🛠 オッズ管理"])
    with tabs[0]:
        st.write(f"ようこそ **{me['username']}** さん！")
    with tabs[1]:
        page_matches_and_bets(conf, me)
    with tabs[2]:
        page_dashboard(conf, me)
    with tabs[3]:
        page_history(conf, me)
    with tabs[4]:
        page_realtime(conf, me)
    with tabs[5]:
        page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
