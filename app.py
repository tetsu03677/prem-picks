# app.py
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple

import streamlit as st

from google_sheets_client import (
    read_config, read_rows_by_sheet, upsert_row,
    bets_for_match, user_bet_for_match, user_total_stake_for_gw,
    odds_for_match, aggregate_others
)
from football_api import fetch_matches_window

# 先頭で 1 回だけ
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

# ---------------- Config / Auth ----------------
def get_conf() -> Dict[str, Any]:
    conf = read_config()
    conf.setdefault("timezone", "Asia/Tokyo")
    conf.setdefault("FOOTBALL_DATA_COMPETITION", "PL")
    conf.setdefault("API_FOOTBALL_SEASON", "2025")
    conf.setdefault("current_gw", "GW?")
    conf["lock_minutes_before_earliest"] = int(conf.get("odds_freeze_minutes_before_first") or 120)
    conf["max_total_stake_per_gw"] = int(conf.get("max_total_stake_per_gw") or 5000)
    conf["stake_step"] = int(conf.get("stake_step") or 100)
    return conf

def ensure_auth(conf: Dict[str, Any]) -> str:
    users = json.loads(conf.get("users_json") or "[]")
    users_map = {u["username"]: u for u in users}
    if "user" not in st.session_state:
        st.session_state.user = None

    header = st.container()
    with header:
        st.markdown(
            '<div style="display:flex;gap:14px;align-items:center;font-size:1.05rem">'
            '🏠 トップ  🎯 試合とベット  📁 履歴  ⏱️ リアルタイム  🛠️ オッズ管理'
            '</div>',
            unsafe_allow_html=True
        )

    if not st.session_state.user:
        st.markdown("### ログイン")
        u = st.text_input("ユーザー名")
        p = st.text_input("パスワード", type="password")
        if st.button("ログイン"):
            me = users_map.get(u)
            if me and str(me.get("password")) == p:
                st.session_state.user = me
                st.success(f"ようこそ {me['username']} さん！"); st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います")
        st.stop()

    right = st.container()
    with right:
        st.markdown(f"ログイン中：**{st.session_state.user['username']}**（{st.session_state.user.get('role','user')}）")
        if st.button("ログアウト"):
            st.session_state.clear(); st.rerun()

    return st.session_state.user["username"]

# --------------- football-data fetch ---------------
@st.cache_data(ttl=120, show_spinner=False)
def get_upcoming(conf: Dict[str, Any], days: int = 7) -> Tuple[List[Dict[str, Any]], str]:
    token  = conf.get("FOOTBALL_DATA_API_TOKEN") or conf.get("FOOTBALL_DATA_API_TOKEN".lower())
    comp   = conf.get("FOOTBALL_DATA_COMPETITION") or conf.get("API_FOOTBALL_LEAGUE_ID", "PL")
    season = str(conf.get("API_FOOTBALL_SEASON") or "2025")
    matches, gw = fetch_matches_window(days, str(comp), season, token, conf["timezone"])
    return matches, gw

# ---------------- Pages ----------------
def page_matches_and_bets(conf: Dict[str, Any], me: str):
    matches, gw = get_upcoming(conf, days=7)
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    # ロック判定（最初の試合のキックオフ X 分前）
    earliest_utc = min(m["utc_kickoff"] for m in matches)
    lock_threshold = earliest_utc - timedelta(minutes=conf["lock_minutes_before_earliest"])
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)

    # 上部：総投票
    total = user_total_stake_for_gw(gw, me)
    remain = max(conf["max_total_stake_per_gw"] - total, 0)
    st.markdown(f"このGWのあなたの投票合計: **{total}** / 上限 **{conf['max_total_stake_per_gw']}**（残り **{remain}**）")

    st.markdown(f"## 試合一覧（{gw}）")
    for m in matches:
        match_id = m["id"]
        local_str = m["local_kickoff"].strftime("%m/%d %H:%M")
        home = m["home"] or "HOME"
        away = m["away"] or "AWAY"

        odds = odds_for_match(gw, match_id)
        locked = (now_utc >= lock_threshold) or bool(odds.get("locked", False))

        with st.container(border=True):
            top_l, top_r = st.columns([1, 5], vertical_alignment="center")
            with top_l:
                st.markdown(f"**{gw}**  \n{local_str}")
            with top_r:
                # ここを if 文にして DeltaGenerator を画面に“値として”出さない
                if not locked:
                    st.success("OPEN", icon="✅")
                else:
                    st.error("LOCKED", icon="🔒")

            st.markdown(
                f"<div style='font-size:1.15rem'><b>{home}</b> vs <span style='font-weight:500'>{away}</span></div>",
                unsafe_allow_html=True
            )

            if all(v == 1.0 for v in (odds["home_win"], odds["draw"], odds["away_win"])):
                st.info("オッズ未入力のため **仮オッズ (=1.0)** を表示中。管理者は『オッズ管理』で設定してください。")

            st.markdown(
                f"Home: **{odds['home_win']:.2f}** ・ Draw: **{odds['draw']:.2f}** ・ Away: **{odds['away_win']:.2f}**"
            )

            # 他ユーザーの合計
            others = aggregate_others(bets_for_match(gw, match_id), me)
            st.caption(f"現在のベット状況（他ユーザー合計）:  HOME {others['HOME']} / DRAW {others['DRAW']} / AWAY {others['AWAY']}")

            # 自分の既存
            mine = user_bet_for_match(gw, match_id, me)
            default_pick = (mine.get("pick") if mine else "") or "HOME"
            default_stake = int(float(mine.get("stake"))) if mine and str(mine.get("stake")).strip() else 0

            # 入力 UI（横並び）
            labels = [f"HOME（{home}）", "DRAW", f"AWAY（{away}）"]
            codes  = ["HOME", "DRAW", "AWAY"]
            c1, c2 = st.columns([2, 1])
            with c1:
                idx = codes.index(default_pick) if default_pick in codes else 0
                chosen = st.radio("ピック", labels, horizontal=True, index=idx, key=f"pick_{match_id}")
                pick = codes[labels.index(chosen)]
            with c2:
                stake = st.number_input("ステーク", min_value=0, step=conf["stake_step"], value=default_stake, key=f"stake_{match_id}")

            btn_col, _ = st.columns([1, 3])
            with btn_col:
                if st.button("この内容でベット" + ("（更新）" if mine else ""), key=f"bet_{match_id}", disabled=locked):
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
                        st.success("ベットを記録しました！"); st.rerun()

def page_odds_admin(conf: Dict[str, Any], me: str):
    if st.session_state.user.get("role") != "admin":
        st.info("管理者のみ利用可能です。"); return
    matches, gw = get_upcoming(conf, days=7)
    if not matches:
        st.info("7日以内に次節はありません。"); return

    st.markdown(f"## オッズ管理（{gw}）")
    for m in matches:
        match_id = m["id"]
        local_str = m["local_kickoff"].strftime("%m/%d %H:%M")
        home = m["home"] or "HOME"
        away = m["away"] or "AWAY"
        odds = odds_for_match(gw, match_id)

        with st.container(border=True):
            st.markdown(f"**{local_str}** — **{home}** vs **{away}**")
            a,b,c,d = st.columns([1,1,1,1])
            with a: h = st.number_input("HOME", min_value=1.00, step=0.01, value=float(odds["home_win"]), key=f"oh_{match_id}")
            with b: d_ = st.number_input("DRAW", min_value=1.00, step=0.01, value=float(odds["draw"]), key=f"od_{match_id}")
            with c: aw = st.number_input("AWAY", min_value=1.00, step=0.01, value=float(odds["away_win"]), key=f"oa_{match_id}")
            with d: lk = st.toggle("ロック", value=bool(odds.get("locked", False)), key=f"lk_{match_id}")
            if st.button("保存", key=f"save_{match_id}"):
                upsert_row("odds", f"{gw}:{match_id}", {
                    "gw": gw, "match_id": match_id, "home": home, "away": away,
                    "home_win": h, "draw": d_, "away_win": aw,
                    "locked": lk, "updated_at": datetime.utcnow().isoformat(),
                })
                st.success("保存しました"); st.rerun()

# ---------------- Main ----------------
def main():
    conf = get_conf()
    me = ensure_auth(conf)

    tabs = st.tabs(["トップ", "試合とベット", "履歴", "リアルタイム", "オッズ管理"])
    with tabs[0]:
        st.markdown(f"### ようこそ {me} さん！")
    with tabs[1]:
        page_matches_and_bets(conf, me)
    with tabs[2]:
        st.info("履歴ページは後日実装")
    with tabs[3]:
        st.info("手動更新のみ（更新ボタン予定）")
    with tabs[4]:
        page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
