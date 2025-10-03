# app.py
# -*- coding: utf-8 -*-

import streamlit as st
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from google_sheets_client import read_config, upsert_row, read_rows_by_sheet
from football_api import get_upcoming
import pytz

# -----------------------------------------------------
# 認証
# -----------------------------------------------------
def ensure_auth(conf: Dict[str, Any]):
    if "me" not in st.session_state:
        st.session_state["me"] = None
    users = conf["users"]
    if st.session_state["me"] is None:
        st.title("ログイン")
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        if st.button("ログイン"):
            user = next((u for u in users if u["username"] == username and u["password"] == password), None)
            if user:
                st.session_state["me"] = user["username"]
                st.session_state["role"] = user["role"]
                st.success(f"ようこそ {user['username']} さん！")
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います")
        st.stop()
    else:
        st.sidebar.write(f"ログイン中: {st.session_state['me']} ({st.session_state['role']})")
        if st.sidebar.button("ログアウト"):
            st.session_state["me"] = None
            st.rerun()

# -----------------------------------------------------
# データ取得
# -----------------------------------------------------
def get_conf():
    conf_rows = read_config()
    conf = {row["key"]: row["value"] for row in conf_rows}
    conf["users"] = eval(conf["users_json"])
    conf["max_total_stake_per_gw"] = int(conf["max_total_stake_per_gw"])
    conf["stake_step"] = int(conf["stake_step"])
    conf["lock_minutes_before_earliest"] = int(conf["lock_minutes_before_earliest"])
    return conf

def bets_for_match(gw: str, match_id: str):
    rows = read_rows_by_sheet("bets")
    return [r for r in rows if r.get("gw") == gw and r.get("match_id") == str(match_id)]

def user_bet_for_match(gw: str, match_id: str, me: str):
    bets = bets_for_match(gw, match_id)
    return next((b for b in bets if b.get("user") == me), None)

def user_total_stake_for_gw(gw: str, me: str):
    rows = read_rows_by_sheet("bets")
    return sum(int(float(r["stake"])) for r in rows if r.get("gw") == gw and r.get("user") == me)

def odds_for_match(gw: str, match_id: str):
    rows = read_rows_by_sheet("odds")
    for r in rows:
        if r.get("gw") == gw and r.get("match_id") == str(match_id):
            return {
                "home_win": float(r.get("home_win", 1)),
                "draw": float(r.get("draw", 1)),
                "away_win": float(r.get("away_win", 1)),
            }
    return {"home_win": 1.0, "draw": 1.0, "away_win": 1.0}

def aggregate_others(bets, me: str):
    agg = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    for b in bets:
        if b["user"] != me:
            agg[b["pick"]] += int(float(b["stake"]))
    return agg

# -----------------------------------------------------
# ページ: 試合とベット
# -----------------------------------------------------
def page_matches_and_bets(conf: Dict[str, Any], me: str):
    matches, gw = get_upcoming(conf, days=7)
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    # GW全体ロック判定
    earliest_utc = min(m["utc_kickoff"] for m in matches)
    lock_threshold = earliest_utc - timedelta(minutes=conf["lock_minutes_before_earliest"])
    gw_locked = datetime.utcnow().replace(tzinfo=timezone.utc) >= lock_threshold

    # 上部：総投票とロック表示
    total = user_total_stake_for_gw(gw, me)
    remain = max(conf["max_total_stake_per_gw"] - total, 0)
    st.markdown(f"このGWのあなたの投票合計: **{total}** / 上限 **{conf['max_total_stake_per_gw']}**（残り **{remain}**）")
    if gw_locked:
        st.error("このGWはロックされています（最初の試合の2時間前を過ぎました）", icon="🔒")
    else:
        st.success("OPEN", icon="✅")

    st.markdown(f"## 試合一覧（{gw}）")
    for m in matches:
        match_id = m["id"]
        local_str = m["local_kickoff"].strftime("%m/%d %H:%M")
        home = m["home"] or "HOME"
        away = m["away"] or "AWAY"
        odds = odds_for_match(gw, match_id)

        with st.container(border=True):
            st.markdown(
                f"<div style='font-size:1.15rem'><b>{home}</b> vs <span style='font-weight:500'>{away}</span> "
                f"({local_str})</div>",
                unsafe_allow_html=True
            )
            st.markdown(
                f"Home: **{odds['home_win']:.2f}** ・ Draw: **{odds['draw']:.2f}** ・ Away: **{odds['away_win']:.2f}**"
            )

            # 他ユーザーの合計
            others = aggregate_others(bets_for_match(gw, match_id), me)
            st.caption(f"現在のベット状況（他ユーザー合計）:  HOME {others['HOME']} / DRAW {others['DRAW']} / AWAY {others['AWAY']}")

            # 自分の既存ベット
            mine = user_bet_for_match(gw, match_id, me)
            default_pick = (mine.get("pick") if mine else "") or "HOME"
            default_stake = int(float(mine.get("stake"))) if mine and str(mine.get("stake")).strip() else 0

            labels = [f"HOME（{home}）", "DRAW", f"AWAY（{away}）"]
            codes  = ["HOME", "DRAW", "AWAY"]
            chosen = st.radio("ピック", labels, horizontal=True,
                              index=codes.index(default_pick) if default_pick in codes else 0,
                              key=f"pick_{match_id}")
            pick = codes[labels.index(chosen)]
            stake = st.number_input("ステーク", min_value=0, step=conf["stake_step"], value=default_stake, key=f"stake_{match_id}")

            if st.button("この内容でベット" + ("（更新）" if mine else ""), key=f"bet_{match_id}", disabled=gw_locked):
                new_total = user_total_stake_for_gw(gw, me) - default_stake + stake
                if new_total > conf["max_total_stake_per_gw"]:
                    st.error("このGWの上限を超えます。ステークを調整してください。")
                else:
                    snap = {"HOME": odds["home_win"], "DRAW": odds["draw"], "AWAY": odds["away_win"]}[pick]
                    upsert_row("bets", f"{gw}:{me}:{match_id}", {
                        "gw": gw, "user": me, "match_id": match_id,
                        "match": f"{home} vs {away}", "pick": pick, "stake": stake,
                        "odds": snap, "status": "open", "placed_at": datetime.utcnow().isoformat(),
                    })
                    st.success("ベットを記録しました！")
                    st.rerun()

# -----------------------------------------------------
# メイン
# -----------------------------------------------------
def main():
    conf = get_conf()
    ensure_auth(conf)
    me = st.session_state["me"]

    st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

    tabs = {
        "🏠 トップ": lambda: st.write("ようこそ", me, "さん！"),
        "🎯 試合とベット": lambda: page_matches_and_bets(conf, me),
    }
    selected = st.sidebar.radio("ページ選択", list(tabs.keys()))
    tabs[selected]()

if __name__ == "__main__":
    main()
