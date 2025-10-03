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

# ----- page config (最初に一回だけ) -----
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

# ====== config & auth ======
def get_conf() -> Dict[str, Any]:
    conf = read_config()
    # 軽く型補正
    conf.setdefault("timezone", "Asia/Tokyo")
    conf.setdefault("FOOTBALL_DATA_COMPETITION", "PL")  # 例: 39 / PL
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

    placeholder = st.empty()
    if not st.session_state.user:
        with placeholder.container():
            st.markdown("### ログイン")
            username = st.text_input("ユーザー名")
            password = st.text_input("パスワード", type="password")
            if st.button("ログイン"):
                u = users_map.get(username)
                if u and str(u.get("password")) == password:
                    st.session_state.user = u
                    st.success(f"ようこそ {u['username']} さん！")
                    st.rerun()
                else:
                    st.error("ユーザー名またはパスワードが違います")
        st.stop()

    placeholder.empty()
    return st.session_state.user["username"]

# ====== football-data fetch ======
@st.cache_data(ttl=120, show_spinner=False)
def get_upcoming(conf: Dict[str, Any], days: int = 7) -> Tuple[List[Dict[str, Any]], str]:
    token = conf.get("FOOTBALL_DATA_API_TOKEN") or conf.get("FOOTBALL_DATA_API_TOKEN".lower())
    comp  = conf.get("FOOTBALL_DATA_COMPETITION") or conf.get("API_FOOTBALL_LEAGUE_ID", "PL")
    season = str(conf.get("API_FOOTBALL_SEASON") or "2025")
    matches, gw = fetch_matches_window(days, str(comp), season, token, conf["timezone"])
    return matches, gw

# ====== UI parts ======
def header_bar(me: str, conf: Dict[str, Any]):
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;">'
        f'<div>🏠 トップ &nbsp; 🎯 試合とベット &nbsp; 📁 履歴 &nbsp; ⏱️ リアルタイム &nbsp; 🛠️ オッズ管理</div>'
        f'<div>ログイン中：<b>{me}</b> ({st.session_state.user.get("role","user")}) '
        f'<form action="" method="post" style="display:inline;"><button name="logout" formmethod="dialog"></button></form></div>'
        f'</div>',
        unsafe_allow_html=True
    )
    if st.button("ログアウト", key="logout_btn"):
        st.session_state.clear()
        st.rerun()

def page_matches_and_bets(conf: Dict[str, Any], me: str):
    matches, gw = get_upcoming(conf, days=7)
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    # earliest kickoff -> lock threshold (全試合共通)
    earliest_utc = min(m["utc_kickoff"] for m in matches)
    lock_threshold = earliest_utc - timedelta(minutes=conf["lock_minutes_before_earliest"])
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)

    # 上部：総投票
    user_total = user_total_stake_for_gw(gw, me)
    remain = max(conf["max_total_stake_per_gw"] - user_total, 0)
    st.markdown(f"このGWのあなたの投票合計: **{user_total}** / 上限 **{conf['max_total_stake_per_gw']}**（残り **{remain}**）")

    st.markdown(f"### 試合一覧（{gw}）")
    for m in matches:
        match_id = m["id"]
        local_str = m["local_kickoff"].strftime("%m/%d %H:%M")
        home = m["home"] or "HOME"
        away = m["away"] or "AWAY"

        odds = odds_for_match(gw, match_id)
        locked = now_utc >= lock_threshold or odds.get("locked", False)

        with st.container(border=True):
            # ヘッダ
            col_a, col_b = st.columns([1, 4])
            with col_a:
                st.markdown(f"**{gw}**  \n{local_str}")
                st.success("OPEN", icon="✅") if not locked else st.error("LOCKED", icon="🔒")
            with col_b:
                st.markdown(
                    f"<span style='font-size:1.1rem;font-weight:700'>{home}</span> vs "
                    f"<span style='font-size:1.05rem'>{away}</span>",
                    unsafe_allow_html=True
                )
                if all(v == 1.0 for v in (odds["home_win"], odds["draw"], odds["away_win"])):
                    st.info("オッズ未入力のため **仮オッズ (=1.0)** を表示中。管理者は『オッズ管理』で設定してください。")
                st.markdown(f"Home: **{odds['home_win']:.2f}** ・ Draw: **{odds['draw']:.2f}** ・ Away: **{odds['away_win']:.2f}**")

            # 他ユーザーのベット状況
            others = aggregate_others(bets_for_match(gw, match_id), me)
            st.caption(f"現在のベット状況（他ユーザー合計）:  HOME {others['HOME']} / DRAW {others['DRAW']} / AWAY {others['AWAY']}")

            # 自分の既存ベット
            mine = user_bet_for_match(gw, match_id, me)
            default_pick = (mine.get("pick") if mine else "") or "HOME"
            default_stake = int(float(mine.get("stake"))) if mine and str(mine.get("stake")).strip() else 0

            # 入力UI（横並びのラジオ＋数値）
            opt_labels = [f"HOME（{home}）", "DRAW", f"AWAY（{away}）"]
            opt_codes = ["HOME", "DRAW", "AWAY"]
            col1, col2 = st.columns([2, 1])
            with col1:
                pick_label = st.radio(
                    "ピック", options=opt_labels, horizontal=True,
                    index=opt_codes.index(default_pick) if default_pick in opt_codes else 0,
                    key=f"pick_{match_id}"
                )
                pick = opt_codes[opt_labels.index(pick_label)]
            with col2:
                stake = st.number_input(
                    "ステーク", min_value=0, step=conf["stake_step"],
                    value=default_stake, key=f"stake_{match_id}"
                )

            # 保存
            save_col, _ = st.columns([1, 3])
            with save_col:
                disabled = locked
                if st.button("この内容でベット" + ("（更新）" if mine else ""), key=f"bet_{match_id}", disabled=disabled):
                    # 上限チェック
                    new_total = user_total_stake_for_gw(gw, me) - default_stake + stake
                    if new_total > conf["max_total_stake_per_gw"]:
                        st.error("このGWの上限を超えます。ステークを調整してください。")
                    else:
                        key_val = f"{gw}:{me}:{match_id}"
                        snapshot_odds = {"HOME": odds["home_win"], "DRAW": odds["draw"], "AWAY": odds["away_win"]}[pick]
                        upsert_row("bets", key_val, {
                            "gw": gw,
                            "user": me,
                            "match_id": match_id,
                            "match": f"{home} vs {away}",
                            "pick": pick,
                            "stake": stake,
                            "odds": snapshot_odds,
                            "status": "open",
                            "placed_at": datetime.utcnow().isoformat(),
                        })
                        st.success("ベットを記録しました！")
                        st.rerun()

# --- Admin: odds management ---
def page_odds_admin(conf: Dict[str, Any], me: str):
    if st.session_state.user.get("role") != "admin":
        st.info("管理者のみ利用可能です。")
        return

    matches, gw = get_upcoming(conf, days=7)
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    st.markdown(f"### オッズ管理（{gw}）")
    for m in matches:
        match_id = m["id"]
        local_str = m["local_kickoff"].strftime("%m/%d %H:%M")
        home = m["home"] or "HOME"
        away = m["away"] or "AWAY"

        odds = odds_for_match(gw, match_id)
        with st.container(border=True):
            st.markdown(f"**{local_str}**  —  **{home}** vs **{away}**")
            c1, c2, c3, c4 = st.columns([1,1,1,1])
            with c1: h = st.number_input("HOME", min_value=1.00, step=0.01, value=float(odds["home_win"]), key=f"oh_{match_id}")
            with c2: d = st.number_input("DRAW", min_value=1.00, step=0.01, value=float(odds["draw"]), key=f"od_{match_id}")
            with c3: a = st.number_input("AWAY", min_value=1.00, step=0.01, value=float(odds["away_win"]), key=f"oa_{match_id}")
            with c4: locked = st.toggle("ロック", value=bool(odds.get("locked", False)), key=f"lk_{match_id}")

            if st.button("保存", key=f"save_{match_id}"):
                key_val = f"{gw}:{match_id}"
                upsert_row("odds", key_val, {
                    "gw": gw, "match_id": match_id, "home": home, "away": away,
                    "home_win": h, "draw": d, "away_win": a,
                    "locked": locked, "updated_at": datetime.utcnow().isoformat(),
                })
                st.success("保存しました")
                st.rerun()

# ====== main ======
def main():
    conf = get_conf()
    me = ensure_auth(conf)
    header_bar(me, conf)

    tabs = {
        "トップ": lambda: st.markdown(f"### ようこそ {me} さん！"),
        "試合とベット": lambda: page_matches_and_bets(conf, me),
        "履歴": lambda: st.info("履歴ページは後日実装"),
        "リアルタイム": lambda: st.info("手動更新のみ（更新ボタンを設置予定）"),
        "オッズ管理": lambda: page_odds_admin(conf, me),
    }

    # シンプルな見た目のタブ
    selected = st.tabs(list(tabs.keys()))
    for tab, page in zip(selected, tabs.values()):
        with tab:
            page()

if __name__ == "__main__":
    main()
