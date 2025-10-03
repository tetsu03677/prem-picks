from __future__ import annotations
import json, uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import streamlit as st

from google_sheets_client import read_config, load_users, read_odds, upsert_odds, read_bets, append_bet
from football_api import fetch_fixtures_fd, simplify_matches

# ===== Common =====
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

def tz(conf: Dict[str,str]) -> timezone:
    # 表示用は常にJST相当でOK（詳細は省略）
    return timezone(timedelta(hours=9))

def guard_login():
    if not st.session_state.get("user"):
        st.stop()

def is_admin() -> bool:
    u = st.session_state.get("user")
    return u and u.get("role") == "admin"

# ===== Login View =====
def show_login():
    st.markdown("### ログイン")
    users = load_users()
    if "login_message" in st.session_state:
        st.info(st.session_state.pop("login_message"))
    with st.form("login"):
        col1, col2 = st.columns(2)
        username = col1.text_input("ユーザー名")
        password = col2.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン", use_container_width=True)
    if submitted:
        hit = next((u for u in users if u.get("username")==username and u.get("password")==password), None)
        if not hit:
            st.error("ユーザー名またはパスワードが違います。")
        else:
            st.session_state["user"] = hit
            st.session_state["login_message"] = f"{hit['username']} としてログインしました。"
            st.rerun()

# ===== Top Nav Tabs =====
def top_tabs() -> int:
    tabs = st.tabs(["🏠 トップ","🎯 試合とベット","🗂 履歴","⏱ リアルタイム","🛠 オッズ管理"])
    # 返り値のために index を保持
    for i, t in enumerate(tabs):
        with t:
            st.session_state["_active_tab"] = i
    return st.session_state.get("_active_tab", 0)

# ===== Cards =====
def match_card(m: Dict[str,Any], odds: Optional[Dict[str,Any]]=None):
    h, a = m["home"], m["away"]
    dt_utc = datetime.fromisoformat(m["utc"].replace("Z","+00:00"))
    dt_local = dt_utc.astimezone(tz({}))
    st.markdown(f"**GW{m.get('matchday','?')}** 　{dt_local:%m/%d %H:%M} 　{h} vs {a}")
    if odds:
        st.caption(f"オッズ: H {odds.get('home_win','-')} / D {odds.get('draw','-')} / A {odds.get('away_win','-')}"
                   + ("　🔒Locked" if str(odds.get("locked","")).lower() in ("1","true","yes") else ""))

# ====== Views ======
def view_home():
    st.markdown("## Premier Picks")
    st.success("ログイン済みです。上部のタブから操作してください。")

def view_bets():
    conf = read_config()
    col = st.slider("何日先まで表示するか", 3, 21, 14)
    try:
        raw = fetch_fixtures_fd(conf, col)
        matches = simplify_matches(raw)
    except Exception as e:
        st.error(f"試合データ取得エラー: {e}")
        return

    gw = conf.get("current_gw","")
    odds_all = { (str(o.get("gw")), str(o.get("match_id"))) : o for o in read_odds(gw) }
    st.markdown("### 試合一覧")
    for m in matches:
        key = (str(gw), str(m["id"]))
        o = odds_all.get(key)
        with st.container(border=True):
            match_card(m, o)
            # オッズがある時だけベットフォーム
            if o and str(o.get("locked","")).lower() not in ("1","true","yes"):
                with st.form(f"bet_{m['id']}"):
                    pick = st.selectbox("Pick", ["Home","Draw","Away"], key=f"p_{m['id']}")
                    stake = st.number_input("Stake", min_value=0, step=int(conf.get("stake_step","100")), value=0, key=f"s_{m['id']}")
                    submitted = st.form_submit_button("ベットする", use_container_width=True)
                if submitted and stake>0:
                    odds_val = {"Home": o.get("home_win"), "Draw": o.get("draw"), "Away": o.get("away_win")}[pick]
                    rec = {
                        "key": str(uuid.uuid4())[:8],
                        "gw": gw,
                        "user": st.session_state["user"]["username"],
                        "match_id": m["id"],
                        "match": f"{m['home']} vs {m['away']}",
                        "pick": pick,
                        "stake": stake,
                        "odds": odds_val,
                        "placed_at": datetime.utcnow().isoformat(timespec="seconds")+"Z",
                        "status": "open",
                        "result": "",
                        "payout": "",
                        "net": "",
                        "settled_at": "",
                    }
                    append_bet(rec)
                    st.success("ベットを記録しました。")
            else:
                st.info("オッズが未入力です（管理者が『オッズ管理』で入力してください）。")

def view_history():
    conf = read_config()
    gw = conf.get("current_gw","")
    bets = read_bets(gw)
    mine = [b for b in bets if b.get("user")==st.session_state["user"]["username"]]
    others = [b for b in bets if b.get("user")!=st.session_state["user"]["username"]]

    st.markdown("### あなたのベット")
    if not mine:
        st.info("まだありません。")
    for b in mine:
        with st.container(border=True):
            st.markdown(f"**{b['match']}**　Pick: {b['pick']}　Stake: {b['stake']}　Odds: {b['odds']}")
            st.caption(f"{b['placed_at']} ／ Status: {b.get('status','open')}")

    st.markdown("### みんなのベット")
    for b in others:
        with st.container(border=True):
            st.markdown(f"**{b['user']}**　{b['match']}　Pick: {b['pick']}　Stake: {b['stake']}")

def view_realtime():
    st.markdown("### リアルタイム")
    st.info("更新ボタンで最新状況を反映します。自動更新はしません。")
    if st.button("更新", use_container_width=True):
        st.success("（将来拡張）現在はプレースホルダです。")

def view_odds_admin():
    if not is_admin():
        st.warning("管理者のみ利用できます。")
        return

    conf = read_config()
    days = st.slider("何日先まで下書き取得するか（試合リスト用）", 3, 21, 14, key="odds_days")
    try:
        raw = fetch_fixtures_fd(conf, days)
        matches = simplify_matches(raw)
    except Exception as e:
        st.error(f"試合データ取得エラー: {e}")
        return

    gw = conf.get("current_gw","")
    st.markdown(f"#### GW {gw} のオッズ編集")
    current = {(str(o.get("match_id"))): o for o in read_odds(gw)}
    edited_rows: List[Dict[str,Any]] = []

    for m in matches:
        mid = str(m["id"])
        o = current.get(mid, {})
        with st.expander(f"{m['home']} vs {m['away']}"):
            c1,c2,c3,c4 = st.columns([1,1,1,1])
            home = c1.number_input("Home", min_value=0.0, step=0.01, value=float(o.get("home_win",0) or 0), key=f"h_{mid}")
            draw = c2.number_input("Draw", min_value=0.0, step=0.01, value=float(o.get("draw",0) or 0), key=f"d_{mid}")
            away = c3.number_input("Away", min_value=0.0, step=0.01, value=float(o.get("away_win",0) or 0), key=f"a_{mid}")
            locked = c4.checkbox("Locked（確定）", value=str(o.get("locked","")).lower() in ("1","true","yes"), key=f"l_{mid}")
            edited_rows.append({
                "gw": gw,
                "match_id": mid,
                "home": m["home"],
                "away": m["away"],
                "home_win": home or "",
                "draw": draw or "",
                "away_win": away or "",
                "locked": "1" if locked else "",
                "updated_at": datetime.utcnow().isoformat(timespec="seconds")+"Z",
            })

    if st.button("この内容で保存", use_container_width=True, type="primary"):
        upsert_odds(edited_rows, gw)
        st.success("odds シートを更新しました。")
        st.cache_data.clear()  # odds のキャッシュを一掃
        st.rerun()

# ===== main =====
def main():
    st.markdown(
        """
        <style>
          /* モバイル向けに少し文字小さめ＆上タブをくっきり */
          .stTabs [data-baseweb="tab"] div {font-size:0.9rem}
          .stButton>button {height: 2.4rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 未ログインならログイン画面
    if not st.session_state.get("user"):
        show_login()
        return

    # ログアウトボタン
    with st.sidebar:
        st.markdown(f"**User:** {st.session_state['user']['username']}")
        if st.button("ログアウト", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    # タブ表示
    t1, t2, t3, t4, t5 = st.tabs(["🏠 トップ","🎯 試合とベット","🗂 履歴","⏱ リアルタイム","🛠 オッズ管理"])

    with t1:  # Home
        view_home()
    with t2:  # Bets
        view_bets()
    with t3:  # History
        view_history()
    with t4:  # Realtime
        view_realtime()
    with t5:  # Odds Admin
        view_odds_admin()

if __name__ == "__main__":
    main()
