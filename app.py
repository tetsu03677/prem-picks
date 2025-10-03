from __future__ import annotations

import datetime as dt
from typing import Dict, Any, List, Tuple

import streamlit as st
from dateutil.tz import gettz

from google_sheets_client import read_config, read_rows_by_sheet, upsert_row, append_row
from football_api import fetch_matches_next_window, simplify_matches

st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

# ===================== Utils & State =====================
def get_conf() -> Dict[str, str]:
    return read_config()

def tz_now(tzname: str) -> dt.datetime:
    tz = gettz(tzname) or gettz("UTC")
    return dt.datetime.now(tz)

def ensure_auth(conf: Dict[str, str]) -> Dict[str, Any]:
    users_json = conf.get("users_json", "[]")
    import json
    try:
        users = json.loads(users_json)
    except Exception:
        users = []

    if "user" in st.session_state and st.session_state["user"]:
        return st.session_state["user"]

    st.title("ログイン")
    col1, col2 = st.columns(2)
    with col1:
        u = st.text_input("ユーザー名")
    with col2:
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

def section_header(title: str, icon: str = "🎯"):
    st.markdown(f"### {icon} {title}")

def load_odds_map() -> Dict[str, Dict[str, float]]:
    """odds シート → {match_id: {'home':..,'draw':..,'away':..}}"""
    recs = read_rows_by_sheet("odds")
    m: Dict[str, Dict[str, float]] = {}
    for r in recs:
        mid = str(r.get("match_id", "")).strip()
        if not mid:
            continue
        def _f(v):
            try:
                return float(v)
            except:
                return 1.0
        m[mid] = {
            "home": _f(r.get("home_win", "")),
            "draw": _f(r.get("draw", "")),
            "away": _f(r.get("away_win", "")),
            "locked": (str(r.get("locked", "")).lower() in {"1","true","yes"}),
        }
    return m

def user_bets_map() -> List[Dict[str, Any]]:
    return read_rows_by_sheet("bets")

# ===================== Pages =====================
def page_home(conf: Dict[str, str], me: Dict[str, Any]):
    st.subheader("トップ")
    st.write(f"ようこそ **{me['username']}** さん！")

def page_matches_and_bets(conf: Dict[str, str], me: Dict[str, Any]):
    section_header("試合とベット", "🎯")

    # 7日ルール：7日以内の SCHEDULED を取得
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "PL")  # 例: 'PL' or '39'
    season = conf.get("API_FOOTBALL_SEASON", str(dt.date.today().year))
    raw, reason = fetch_matches_next_window(7, comp, season, token)
    if not raw:
        st.info("**7日以内に次節はありません。**")
        return

    tzname = conf.get("timezone", "Asia/Tokyo")
    matches = simplify_matches(raw, tzname)

    # 最初のKO の 2h 前でオッズ凍結（管理者が事前ロック可能）
    if matches:
        first_ko = matches[0]["utc_kickoff"]
    else:
        first_ko = dt.datetime.utcnow()

    freeze_min = int(conf.get("odds_freeze_minutes_before_first", conf.get("odds_freeze_minutes_before_first", "120")) or 120)
    odds_freeze_utc = first_ko - dt.timedelta(minutes=freeze_min)

    st.caption(f"このGWのあなたの投票合計: 0 / 上限 {conf.get('max_total_stake_per_gw','5000')}")

    odds_map = load_odds_map()
    bets = user_bets_map()

    for m in matches:
        with st.container(border=True):
            # Header
            st.markdown(
                f"**{m['gw']}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')}",
            )
            # Status pill
            now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
            locked = now_utc >= odds_freeze_utc
            st.success("OPEN", icon="✅") if not locked else st.error("LOCKED", icon="🔒")

            # Teams (ホーム太字・少し大きめ)
            st.markdown(
                f"<div style='font-size:1.1rem'><b>{m['home']}</b> vs {m['away']}</div>",
                unsafe_allow_html=True,
            )

            # Odds （未入力のときは仮 = 1.0）
            om = odds_map.get(m["id"], {"home": 1.0, "draw": 1.0, "away": 1.0})
            if om.get("home", 1.0) == 1.0 and om.get("draw", 1.0) == 1.0 and om.get("away", 1.0) == 1.0:
                st.info("オッズ未入力のため**仮オッズ (=1.0)** を表示中。管理者は『オッズ管理』で設定してください。")

            st.write(f"Home: {om['home']:.2f} ・ Draw: {om['draw']:.2f} ・ Away: {om['away']:.2f}")

            # 他ユーザーのベット状況（表は使わずチップで）
            others = [b for b in bets if b.get("match_id") == m["id"]]
            if others:
                chips = []
                for b in others:
                    chips.append(f"{b.get('user')}: {b.get('pick')} {b.get('stake')}")
                st.caption("現在のベット状況：" + " ｜ ".join(chips))

            # 自分のベット（修正可）
            my_key = f"{m['gw']}|{me['username']}|{m['id']}"
            my_existing = None
            for b in others:
                if b.get("key") == my_key and b.get("user") == me["username"]:
                    my_existing = b
                    break

            pick_default = {"HOME":"HOME","DRAW":"DRAW","AWAY":"AWAY"}.get((my_existing or {}).get("pick","HOME"), "HOME")
            stake_step = int(conf.get("stake_step","100") or 100)
            st.write("**ピック**")
            c1, c2, c3 = st.columns(3)
            with c1:
                p1 = st.radio(" ", ["HOME"], horizontal=True, label_visibility="collapsed")
            with c2:
                p2 = st.radio(" ", ["DRAW"], horizontal=True, label_visibility="collapsed")
            with c3:
                p3 = st.radio(" ", ["AWAY"], horizontal=True, label_visibility="collapsed")
            chosen = "HOME" if p1 == "HOME" else ("DRAW" if p2 == "DRAW" else "AWAY")
            # 既存があればそれを優先表示
            chosen = (my_existing or {}).get("pick", chosen)

            stake = st.number_input("ステーク", min_value=0, step=stake_step, value=int((my_existing or {}).get("stake", 0)))
            if st.button("この内容でベット", disabled=locked):
                row = {
                    "key": my_key,
                    "gw": m["gw"],
                    "user": me["username"],
                    "match_id": m["id"],
                    "match": f"{m['home']} vs {m['away']}",
                    "pick": chosen,
                    "stake": str(stake),
                    "odds": str(om["home"] if chosen=="HOME" else om["draw"] if chosen=="DRAW" else om["away"]),
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
    section_header("履歴", "📂")
    recs = read_rows_by_sheet("bets")
    mine = [r for r in recs if r.get("user")==me["username"]]
    if not mine:
        st.info("まだ履歴がありません。")
        return
    for r in mine[::-1]:
        with st.container(border=True):
            st.write(f"{r.get('gw')} / {r.get('match')} / {r.get('pick')} / stake {r.get('stake')} / odds {r.get('odds')} / status {r.get('status')}")

def page_realtime(conf: Dict[str, str], me: Dict[str, Any]):
    section_header("リアルタイム", "⏱️")
    st.caption("更新ボタンで手動更新。自動ポーリングは行いません。")
    if st.button("更新"):
        st.success("（将来拡張）")

def page_odds_admin(conf: Dict[str, str], me: Dict[str, Any]):
    if me.get("role") != "admin":
        st.info("このページは管理者専用です。")
        return
    section_header("オッズ管理", "🛠️")

    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "PL")
    season = conf.get("API_FOOTBALL_SEASON", str(dt.date.today().year))
    raw, _ = fetch_matches_next_window(7, comp, season, token)
    if not raw:
        st.info("7日以内に次節はありません。")
        return

    tzname = conf.get("timezone", "Asia/Tokyo")
    matches = simplify_matches(raw, tzname)

    st.caption("各カードの 1X2 オッズを入力してください（未入力時は=1.0 として扱います）")
    for m in matches:
        with st.container(border=True):
            st.markdown(f"**{m['gw']}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')}  —  **{m['home']}** vs {m['away']}")
            c1, c2, c3 = st.columns(3)
            with c1:
                h = st.text_input("Home", key=f"h_{m['id']}")
            with c2:
                d = st.text_input("Draw", key=f"d_{m['id']}")
            with c3:
                a = st.text_input("Away", key=f"a_{m['id']}")
            if st.button("保存", key=f"save_{m['id']}"):
                data = {
                    "gw": m["gw"],
                    "match_id": m["id"],
                    "home": m["home"],
                    "away": m["away"],
                    "home_win": h or "1",
                    "draw": d or "1",
                    "away_win": a or "1",
                    "locked": "",
                    "updated_at": dt.datetime.utcnow().isoformat(timespec="seconds"),
                }
                upsert_row("odds", "match_id", m["id"], data)
                st.success("保存しました。")

# ===================== Main =====================
def main():
    conf = get_conf()
    user = ensure_auth(conf)

    st.sidebar.write(f"ログイン中：**{user['username']}** ({user.get('role','user')})")
    if st.sidebar.button("ログアウト"):
        st.session_state.pop("user", None)
        st.rerun()

    tabs = ["🏠 トップ", "🎯 試合とベット", "📂 履歴", "⏱️ リアルタイム", "🛠️ オッズ管理"]
    pages = [lambda: page_home(conf, user),
             lambda: page_matches_and_bets(conf, user),
             lambda: page_history(conf, user),
             lambda: page_realtime(conf, user),
             lambda: page_odds_admin(conf, user)]
    st.markdown("---")
    t = st.tabs(tabs)
    for tab, page in zip(t, pages):
        with tab:
            page()

if __name__ == "__main__":
    main()
