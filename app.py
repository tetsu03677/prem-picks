import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple

import streamlit as st
import pytz

from google_sheets_client import (
    read_config, read_rows_by_sheet, read_odds_map_by_match_id,
    upsert_odds, upsert_bet
)
from football_api import fetch_matches_window, fetch_live_snapshot

# ---------- 共通 ----------
def get_conf() -> Dict[str,str]:
    conf = read_config()
    required = ["FOOTBALL_DATA_API_TOKEN","FOOTBALL_DATA_COMPETITION","API_FOOTBALL_SEASON","timezone","lock_minutes_before_earliest"]
    for k in required:
        if k not in conf or not conf[k]:
            st.error(f"config の必須キーが不足：{k}")
            st.stop()
    return conf

def tz(conf):
    return pytz.timezone(conf.get("timezone","Asia/Tokyo"))

def local_now(conf):
    return datetime.now(tz(conf))

def parse_users(conf) -> List[Dict[str,Any]]:
    raw = conf.get("users_json","").strip()
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []

def earliest_kickoff(matches: List[Dict[str,Any]]):
    times = [m["local_kickoff"] for m in matches]
    return min(times) if times else None

def is_gw_locked(matches: List[Dict[str,Any]], conf) -> bool:
    first_kick = earliest_kickoff(matches)
    if not first_kick:
        return False
    mins = int(conf.get("lock_minutes_before_earliest","120"))
    lock_at = first_kick - timedelta(minutes=mins)
    return local_now(conf) >= lock_at

def fmt_money(x) -> str:
    try:
        return f"{int(float(x)):,}"
    except:
        return "0"

def odds_for_match(odds_map: Dict[str,Dict[str,Any]], match_id: str) -> Tuple[float,float,float,bool]:
    r = odds_map.get(str(match_id))
    if not r:
        return 1.0, 1.0, 1.0, False
    def f(v):
        try: return float(v)
        except: return 1.0
    return f(r.get("home_win","1")), f(r.get("draw","1")), f(r.get("away_win","1")), True

# ---------- 認証 ----------
def ensure_auth(conf) -> Dict[str,Any] | None:
    st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

    users = parse_users(conf)
    if not users:
        st.warning("config の users_json が空です。暫定で guest のみ選択可。")
        users = [{"username":"guest","password":"", "role":"user", "team":""}]

    if "me" not in st.session_state:
        st.session_state["me"] = None
    if st.session_state["me"]:
        return st.session_state["me"]

    colA, colB, colC = st.columns([1,2,1])
    with colB:
        st.markdown("<h2 style='margin: 12px 0 6px;'>Premier Picks</h2>", unsafe_allow_html=True)
        names = [u["username"] for u in users]
        user_sel = st.selectbox("ユーザー", names, index=0)
        pwd = st.text_input("パスワード", type="password")
        if st.button("ログイン", use_container_width=True):
            u = next((x for x in users if x["username"]==user_sel), None)
            if u and (u.get("password","")==pwd):
                st.session_state["me"] = u
                st.experimental_rerun()
            else:
                st.error("ユーザー名またはパスワードが違います。")
    return None

# ---------- 試合とベット ----------
def page_matches_and_bets(conf, me):
    st.subheader("試合とベット")

    matches, gw = fetch_matches_window(7, conf["FOOTBALL_DATA_COMPETITION"], conf)
    matches = [m for m in matches if m.get("gw")==conf.get("current_gw","")]
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    odds_map = read_odds_map_by_match_id(conf.get("current_gw",""))
    locked = is_gw_locked(matches, conf)

    bets_all = read_rows_by_sheet("bets")
    my_sum = sum(
        int(float(b.get("stake","0") or 0))
        for b in bets_all
        if str(b.get("gw"))==conf.get("current_gw","") and str(b.get("user"))==me["username"]
    )
    st.caption(f"このGWのあなたの投票合計: {fmt_money(my_sum)} / 上限 {fmt_money(conf.get('max_total_stake_per_gw','5000'))}")

    for m in matches:
        mid = m["id"]
        with st.container(border=True):
            left, right = st.columns([3,1])
            with left:
                st.markdown(f"**{conf.get('current_gw','')}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')}")
                st.markdown(f"**{m['home']}** vs {m['away']}")
            with right:
                # ★ ここを if/else に変更（ワンライナー禁止）
                if not locked:
                    st.success("OPEN", icon="✅")
                else:
                    st.error("LOCKED", icon="🔒")

            h, d, a, has = odds_for_match(odds_map, mid)
            if not has:
                st.info("オッズ未入力のため仮オッズ(=1.0)を表示中。 管理者は『オッズ管理』で設定してください。")
            st.caption(f"Home: {h:.2f}　・　Draw: {d:.2f}　・　Away: {a:.2f}")

            sum_home = sum(int(float(b.get("stake","0") or 0)) for b in bets_all if b.get("match_id")==mid and b.get("pick")=="HOME")
            sum_draw = sum(int(float(b.get("stake","0") or 0)) for b in bets_all if b.get("match_id")==mid and b.get("pick")=="DRAW")
            sum_away = sum(int(float(b.get("stake","0") or 0)) for b in bets_all if b.get("match_id")==mid and b.get("pick")=="AWAY")
            st.caption(f"現在のベット状況：HOME {fmt_money(sum_home)} / DRAW {fmt_money(sum_draw)} / AWAY {fmt_money(sum_away)}")

            if not locked:
                mine = next((b for b in bets_all if b.get("gw")==conf.get("current_gw","") and b.get("user")==me["username"] and b.get("match_id")==mid), None)
                default_pick = mine.get("pick","HOME") if mine else "HOME"
                try:
                    default_stake = int(float(mine.get("stake","100"))) if mine else int(conf.get("stake_step","100"))
                except:
                    default_stake = int(conf.get("stake_step","100"))

                pick = st.radio(
                    "ピック",
                    options=["HOME","DRAW","AWAY"],
                    index=["HOME","DRAW","AWAY"].index(default_pick),
                    horizontal=True,
                    key=f"pick_{mid}",
                )
                cc1, cc2 = st.columns([4,1])
                with cc1:
                    stake = st.number_input(
                        "ステーク",
                        min_value=0,
                        step=int(conf.get("stake_step","100")),
                        value=default_stake,
                        key=f"stake_{mid}"
                    )
                with cc2:
                    st.write("")
                    if st.button("この内容でベット", use_container_width=True, key=f"bet_{mid}"):
                        key = f"{conf.get('current_gw','')}-{me['username']}-{mid}"
                        row = {
                            "key": key,
                            "gw": conf.get("current_gw",""),
                            "user": me["username"],
                            "match_id": mid,
                            "match": f"{m['home']} vs {m['away']}",
                            "pick": pick,
                            "stake": str(stake),
                            "odds": {"HOME":h,"DRAW":d,"AWAY":a}[pick],
                            "placed_at": local_now(conf).strftime("%Y-%m-%d %H:%M:%S"),
                            "status": "OPEN",
                            "result": "",
                            "payout": "",
                            "net": "",
                            "settled_at": ""
                        }
                        upsert_bet(row)
                        st.success("ベットを記録しました！", icon="✅")
                        st.rerun()
            else:
                st.info("このGWはロック中です。")

# ---------- オッズ管理（管理者） ----------
def page_odds_admin(conf, me):
    st.subheader("オッズ管理")
    if me.get("role") != "admin":
        st.info("管理者のみアクセス可能です。")
        return

    matches, _ = fetch_matches_window(7, conf["FOOTBALL_DATA_COMPETITION"], conf)
    matches = [m for m in matches if m.get("gw")==conf.get("current_gw","")]
    if not matches:
        st.info("現在編集対象の試合がありません。")
        return

    odds_map = read_odds_map_by_match_id(conf.get("current_gw",""))
    for m in matches:
        mid = m["id"]
        h, d, a, has = odds_for_match(odds_map, mid)
        with st.container(border=True):
            st.markdown(f"**{m['home']} vs {m['away']}**")
            col1, col2, col3, col4 = st.columns([1,1,1,1])
            with col1:
                nh = st.text_input("Home Win", value=f"{h:.2f}", key=f"odds_h_{mid}")
            with col2:
                nd = st.text_input("Draw", value=f"{d:.2f}", key=f"odds_d_{mid}")
            with col3:
                na = st.text_input("Away Win", value=f"{a:.2f}", key=f"odds_a_{mid}")
            with col4:
                st.write("")
                if st.button("保存", key=f"save_odds_{mid}"):
                    upsert_odds(conf.get("current_gw",""), mid, nh, nd, na, locker=me["username"])
                    st.success("保存しました")
                    st.rerun()

# ---------- 履歴 ----------
def page_history(conf, me):
    st.subheader("履歴")
    bets = read_rows_by_sheet("bets")
    rows = []
    for b in bets:
        rows.append({
            "GW": b.get("gw",""),
            "ユーザー": b.get("user",""),
            "試合": b.get("match",""),
            "ピック": b.get("pick",""),
            "ステーク": b.get("stake",""),
            "オッズ": b.get("odds",""),
            "ステータス": b.get("status",""),
            "結果": b.get("result",""),
            "払戻": b.get("payout",""),
            "損益": b.get("net",""),
            "日時": b.get("placed_at","")
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("履歴はまだありません。")

# ---------- リアルタイム ----------
def page_realtime(conf, me):
    st.subheader("リアルタイム")
    if st.button("最新に更新"):
        st.rerun()
    matches = fetch_live_snapshot(conf["FOOTBALL_DATA_COMPETITION"], conf)
    matches = [m for m in matches if m.get("gw")==conf.get("current_gw","")]
    odds_map = read_odds_map_by_match_id(conf.get("current_gw",""))
    bets = read_rows_by_sheet("bets")

    if not matches:
        st.info("対象GWの試合が見つかりません。")
        return

    for m in matches:
        mid = m["id"]
        h,d,a,_ = odds_for_match(odds_map, mid)
        with st.container(border=True):
            st.markdown(f"**{m['home']} vs {m['away']}** 　[{m['status']}]")
            st.caption(f"Kickoff: {m['local_kickoff'].strftime('%m/%d %H:%M')} 　Score(FT): {m.get('score_home')} - {m.get('score_away')}")
            res = None
            if m.get("score_home") is not None and m.get("score_away") is not None:
                if m["score_home"] > m["score_away"]:
                    res = "HOME"
                elif m["score_home"] < m["score_away"]:
                    res = "AWAY"
                else:
                    res = "DRAW"
            agg = {}
            for b in bets:
                if b.get("match_id") != mid:
                    continue
                user = b.get("user","?")
                stake = float(b.get("stake","0") or "0")
                pick = b.get("pick","HOME")
                odds = {"HOME":h,"DRAW":d,"AWAY":a}[pick]
                payout = stake * odds if (res is not None and pick == res) else 0.0
                net = payout - stake
                agg[user] = agg.get(user, 0.0) + net
            if agg:
                st.write({u: round(v,1) for u,v in agg.items()})
            else:
                st.caption("まだベットはありません。")

# ---------- メイン ----------
def main():
    conf = get_conf()
    me = ensure_auth(conf)
    if not me:
        return

    tabs = st.tabs(["🏠 トップ","🎯 試合とベット","📁 履歴","⏱️ リアルタイム","🛠 オッズ管理"])
    with tabs[0]:
        st.subheader("トップ")
        st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
        st.caption(f"ログイン中：{me['username']}（{me.get('role','user')}）")

    with tabs[1]:
        page_matches_and_bets(conf, me)
    with tabs[2]:
        page_history(conf, me)
    with tabs[3]:
        page_realtime(conf, me)
    with tabs[4]:
        page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
