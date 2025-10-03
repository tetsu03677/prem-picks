from __future__ import annotations

import datetime as dt
from typing import Dict, Any, List

import streamlit as st
from dateutil.tz import gettz

from google_sheets_client import read_config, read_rows_by_sheet, upsert_row
from football_api import fetch_matches_next_window, simplify_matches

# 最上段で設定
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")


# ---------- Helpers ----------
def get_conf() -> Dict[str, str]:
    return read_config()

def ensure_auth(conf: Dict[str, str]) -> Dict[str, Any]:
    import json
    users_json = conf.get("users_json", "[]")
    try:
        users = json.loads(users_json)
    except Exception:
        users = []

    if "user" in st.session_state and st.session_state["user"]:
        return st.session_state["user"]

    st.title("ログイン")
    u = st.text_input("ユーザー名")
    p = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        for x in users:
            if x.get("username") == u and x.get("password") == p:
                st.session_state["user"] = {
                    "username": x.get("username"),
                    "role": x.get("role", "user"),
                    "team": x.get("team", ""),
                }
                st.rerun()
        st.error("認証に失敗しました。")
    st.stop()

def section(title: str, icon: str = "🎯"):
    st.markdown(f"### {icon} {title}")

def load_odds() -> Dict[str, Dict[str, float]]:
    """odds → {match_id: {'home','draw','away','locked'}}"""
    out: Dict[str, Dict[str, float]] = {}
    for r in read_rows_by_sheet("odds"):
        mid = str(r.get("match_id", "")).strip()
        if not mid:
            continue
        def f(v):
            try: return float(v)
            except: return 1.0
        out[mid] = {
            "home": f(r.get("home_win","")),
            "draw": f(r.get("draw","")),
            "away": f(r.get("away_win","")),
            "locked": (str(r.get("locked","")).lower() in {"1","true","yes"}),
        }
    return out

def read_bets() -> List[Dict[str, Any]]:
    return read_rows_by_sheet("bets")


# ---------- Pages ----------
def page_home(conf: Dict[str, str], me: Dict[str, Any]):
    st.subheader("トップ")
    st.write(f"ようこそ **{me['username']}** さん！")

def page_matches_and_bets(conf: Dict[str, str], me: Dict[str, Any]):
    section("試合とベット", "🎯")

    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "PL")
    season = conf.get("API_FOOTBALL_SEASON", str(dt.date.today().year))

    raw, _ = fetch_matches_next_window(7, comp, season, token)
    if not raw:
        st.info("**7日以内に次節はありません。**")
        return

    tzname = conf.get("timezone", "Asia/Tokyo")
    matches = simplify_matches(raw, tzname)

    # 凍結閾値（最初のKOの N 分前）
    first_ko_utc = matches[0]["utc_kickoff"] if matches else dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    freeze_min = int(conf.get("odds_freeze_minutes_before_first", conf.get("odds_freeze_minutes_before_first", "120")) or 120)
    freeze_utc = first_ko_utc - dt.timedelta(minutes=freeze_min)
    now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

    st.caption(f"このGWのあなたの投票合計: 0 / 上限 {conf.get('max_total_stake_per_gw','5000')}")

    odds_map = load_odds()
    all_bets = read_bets()

    for m in matches:
        with st.container(border=True):
            st.markdown(f"**{m['gw']}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')}")
            locked = now_utc >= freeze_utc
            # ★ ここを if/else に変更（Streamlit の “魔法” による自動 write を回避）
            if not locked:
                st.success("OPEN", icon="✅")
            else:
                st.error("LOCKED", icon="🔒")

            # ホーム太字＆少し大きく
            st.markdown(
                f"<div style='font-size:1.1rem'><b>{m['home']}</b> vs {m['away']}</div>",
                unsafe_allow_html=True,
            )

            om = odds_map.get(m["id"], {"home": 1.0, "draw": 1.0, "away": 1.0})
            if om["home"] == om["draw"] == om["away"] == 1.0:
                st.info("オッズ未入力のため**仮オッズ (=1.0)** を表示中。管理者は『オッズ管理』で設定してください。")
            st.write(f"Home: {om['home']:.2f} ・ Draw: {om['draw']:.2f} ・ Away: {om['away']:.2f}")

            # 他ユーザーのベット状況
            others = [b for b in all_bets if b.get("match_id")==m["id"]]
            if others:
                chips = [f"{b.get('user')}: {b.get('pick')} {b.get('stake')}" for b in others]
                st.caption("現在のベット状況：" + " ｜ ".join(chips))

            # 自分の既存ベット
            my_key = f"{m['gw']}|{me['username']}|{m['id']}"
            mine = None
            for b in others:
                if b.get("key")==my_key and b.get("user")==me["username"]:
                    mine = b
                    break

            # Segmented control
            default_pick = (mine or {}).get("pick", "HOME")
            pick = st.segmented_control("ピック", options=["HOME","DRAW","AWAY"], default=default_pick)
            step = int(conf.get("stake_step","100") or 100)
            stake = st.number_input("ステーク", min_value=0, step=step, value=int((mine or {}).get("stake", 0)))
            if st.button("この内容でベット", disabled=locked, key=f"bet_{m['id']}"):
                odds_val = om["home"] if pick=="HOME" else (om["draw"] if pick=="DRAW" else om["away"])
                row = {
                    "key": my_key,
                    "gw": m["gw"],
                    "user": me["username"],
                    "match_id": m["id"],
                    "match": f"{m['home']} vs {m['away']}",
                    "pick": pick,
                    "stake": str(stake),
                    "odds": str(odds_val),
                    "placed_at": dt.datetime.utcnow().isoformat(timespec="seconds"),
                    "status": "pending",
                    "result": "",
                    "payout": "",
                    "net": "",
                    "settled_at": "",
                }
                upsert_row("bets", "key", my_key, row)
                st.success("ベットを記録しました！")
                st.rerun()

def page_history(conf: Dict[str, str], me: Dict[str, Any]):
    section("履歴", "📂")
    recs = read_bets()
    mine = [r for r in recs if r.get("user")==me["username"]]
    if not mine:
        st.info("まだ履歴がありません。")
        return
    for r in mine[::-1]:
        with st.container(border=True):
            st.write(f"{r.get('gw')} / {r.get('match')} / {r.get('pick')} / stake {r.get('stake')} / odds {r.get('odds')} / status {r.get('status')}")

def page_realtime(conf: Dict[str, str], me: Dict[str, Any]):
    section("リアルタイム", "⏱️")
    st.caption("更新ボタンで手動更新（自動更新なし）。")
    if st.button("更新"):
        st.success("OK（将来拡張）")

def page_odds_admin(conf: Dict[str, str], me: Dict[str, Any]):
    if me.get("role") != "admin":
        st.info("このページは管理者専用です。")
        return
    section("オッズ管理", "🛠️")

    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "PL")
    season = conf.get("API_FOOTBALL_SEASON", str(dt.date.today().year))

    raw, _ = fetch_matches_next_window(7, comp, season, token)
    if not raw:
        st.info("7日以内に次節はありません。")
        return

    tzname = conf.get("timezone", "Asia/Tokyo")
    matches = simplify_matches(raw, tzname)

    st.caption("各カードの 1X2 オッズを入力（未入力なら=1.0 として扱います）")
    for m in matches:
        with st.container(border=True):
            st.markdown(f"**{m['gw']}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')}  —  **{m['home']}** vs {m['away']}")
            c1, c2, c3 = st.columns(3)
            with c1:  h = st.text_input("Home", key=f"h_{m['id']}")
            with c2:  d = st.text_input("Draw", key=f"d_{m['id']}")
            with c3:  a = st.text_input("Away", key=f"a_{m['id']}")
            if st.button("保存", key=f"save_{m['id']}"):
                upsert_row("odds", "match_id", m["id"], {
                    "gw": m["gw"],
                    "match_id": m["id"],
                    "home": m["home"],
                    "away": m["away"],
                    "home_win": h or "1",
                    "draw": d or "1",
                    "away_win": a or "1",
                    "locked": "",
                    "updated_at": dt.datetime.utcnow().isoformat(timespec="seconds"),
                })
                st.success("保存しました。")

# ---------- Main ----------
def main():
    conf = get_conf()
    me = ensure_auth(conf)

    st.sidebar.write(f"ログイン中：**{me['username']}** ({me.get('role','user')})")
    if st.sidebar.button("ログアウト"):
        st.session_state.pop("user", None)
        st.rerun()

    tabs = ["🏠 トップ", "🎯 試合とベット", "📂 履歴", "⏱️ リアルタイム", "🛠️ オッズ管理"]
    pages = [lambda: page_home(conf, me),
             lambda: page_matches_and_bets(conf, me),
             lambda: page_history(conf, me),
             lambda: page_realtime(conf, me),
             lambda: page_odds_admin(conf, me)]
    t = st.tabs(tabs)
    for tab, page in zip(t, pages):
        with tab:
            page()

if __name__ == "__main__":
    main()
