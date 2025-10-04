from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import streamlit as st

from google_sheets_client import (
    read_config, parse_users_from_config,
    read_bets, read_odds, upsert_row
)
from football_api import fetch_matches_window, simplify_matches, gw_lock_times

# -----------------------------------------------------------------------------
# Page setup (一度だけ)
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

PRIMARY = "#f03a5f"   # アクセント色（控えめ）
MUTED = "#7a7a7a"

# ちょっとしたCSSで黒い大枠は使わず、軽いカードデザインに
st.markdown(
    f"""
    <style>
      .light-card {{
        padding: 1rem 1.2rem; border: 1px solid #ececec; border-radius: 12px;
        background: rgba(255,255,255,0.66);
      }}
      .subtle {{
        color: {MUTED};
        font-size: 0.9rem;
      }}
      .bigtitle {{
        font-size: 1.6rem; font-weight: 700; margin-bottom: .2rem;
      }}
      .team-line {{
        font-size: 1.05rem;
      }}
      .team-line b {{ font-weight: 800; }}
      .pill {{
        display:inline-block; padding:.2rem .6rem; border-radius:999px; 
        border:1px solid #e6e6e6; background:#f6f6f6; font-size:.85rem;
      }}
    </style>
    """,
    unsafe_allow_html=True
)

# -----------------------------------------------------------------------------
# Helpers
def get_conf() -> Dict[str, str]:
    cfg = read_config()
    return cfg

def ensure_auth(conf: Dict[str, str]) -> Optional[Dict[str, str]]:
    """ログイン（users_json からユーザーを選択）"""
    users = parse_users_from_config(conf)
    if not users:
        st.warning("config の users_json が空/不正のため、一時的に guest のみ表示します。")
        users = [{"username": "guest", "password": "", "role": "user", "team": ""}]

    if "me" in st.session_state and st.session_state.me:
        return st.session_state.me

    st.markdown('<div class="light-card">', unsafe_allow_html=True)
    st.markdown('<div class="bigtitle">Premier Picks</div>', unsafe_allow_html=True)
    st.caption("ログインしてください")
    usernames = [u["username"] for u in users]
    sel = st.selectbox("ユーザー", usernames, index=0, key="login_user_sel")
    pwd = st.text_input("パスワード", type="password")

    col1, col2 = st.columns([1,2])
    with col1:
        login = st.button("ログイン", type="primary", use_container_width=True)
    with col2:
        st.write("")  # spacing

    st.markdown("</div>", unsafe_allow_html=True)

    if login:
        u = next((x for x in users if x["username"] == sel), None)
        if u and (u["password"] == pwd):
            st.session_state.me = u
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが違います。")
            return None
    return None

def header_bar(me: Dict[str, str]):
    left, mid, right = st.columns([1.5, 5, 1.5])
    with left:
        st.write("**🏠 トップ**  /  **🎯 試合とベット**  /  **📁 履歴**  /  **⏱️ リアルタイム**")
    with right:
        st.caption(f"ログイン中：**{me['username']}** ({me.get('role','user')})")
        if st.button("ログアウト", use_container_width=True):
            for k in ["me"]:
                if k in st.session_state: del st.session_state[k]
            st.rerun()

def section_title(title: str, subtitle: Optional[str] = None):
    st.markdown(f'<div class="bigtitle">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="subtle">{subtitle}</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Pages
def page_home(conf: Dict[str, str], me: Dict[str, str]):
    section_title("トップ", f"ようこそ {me['username']} さん！")
    st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")

def _is_locked_for_gw(matches: List[Dict[str, Any]], conf: Dict[str, str]) -> bool:
    lock_start, _ = gw_lock_times(matches, conf)
    if lock_start is None:
        return False
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    return now_utc >= lock_start

def page_matches_and_bets(conf: Dict[str, str], me: Dict[str, str]):
    # 次節（最大7日先）を取得
    raw = fetch_matches_window(days=7, conf=conf)
    matches = simplify_matches(raw, conf)

    if not matches:
        st.info("7日以内に次節はありません。")
        return

    locked = _is_locked_for_gw(matches, conf)
    total_limit = int(conf.get("max_total_stake_per_gw", "5000") or "5000")

    # 既存ベット（このGWのものだけ）
    bets = [b for b in read_bets() if (b.get("gw") or "").upper() == (conf.get("current_gw") or "").upper()
            and b.get("user") == me["username"]]
    my_total = sum(int(b.get("stake") or 0) for b in bets)

    section_title("試合とベット", f"このGWのあなたの投票合計: {my_total} / 上限 {total_limit} （残り {max(0,total_limit-my_total)}）")

    # オッズ（管理者が未入力なら仮=1.0）
    odds_rows = read_odds()
    odds_map = {(o.get("match_id"), o.get("gw")): o for o in odds_rows}

    for m in matches:
        orec = odds_map.get((str(m["id"]), m["gw"]))
        if orec and not orec.get("locked"):
            home_odds = float(orec.get("home_win") or 1)
            draw_odds = float(orec.get("draw") or 1)
            away_odds = float(orec.get("away_win") or 1)
        else:
            home_odds = draw_odds = away_odds = 1.0

        with st.container(border=True):
            st.markdown(
                f'<div class="team-line"><span class="pill">{m["gw"]}</span> '
                f'{m["local_kickoff"].strftime("%m/%d %H:%M")} &nbsp; '
                f'<b>{m["home"]}</b> vs {m["away"]}</div>', unsafe_allow_html=True
            )
            if not orec or (orec and not orec.get("locked") and (home_odds,draw_odds,away_odds) == (1.0,1.0,1.0)):
                st.info("オッズ未入力のため仮オッズ(=1.0)を表示中。管理者は『オッズ管理』で設定してください。")

            st.caption(f"Home: {home_odds:.2f} ・ Draw: {draw_odds:.2f} ・ Away: {away_odds:.2f}")

            # すでに自分がこの試合にベットしていれば初期値に反映
            my_bet = next((b for b in bets if str(b.get("match_id")) == str(m["id"])), None)
            default_pick = my_bet.get("pick") if my_bet else "AWAY"
            default_stake = int(my_bet.get("stake", 0)) if my_bet else int(conf.get("stake_step","100") or "100")

            cols = st.columns(3)
            with cols[0]:
                pick = st.radio("ピック", options=["HOME", "DRAW", "AWAY"], index=["HOME","DRAW","AWAY"].index(default_pick), horizontal=True)
            with cols[1]:
                stake = st.number_input("ステーク", min_value=0, step=int(conf.get("stake_step","100") or "100"), value=default_stake)
            with cols[2]:
                st.write("")
                disabled = locked
                if disabled:
                    st.button("ロック中", disabled=True, use_container_width=True)
                else:
                    if st.button("この内容でベット", use_container_width=True):
                        # 上限チェック
                        new_total = my_total - (int(my_bet.get("stake",0)) if my_bet else 0) + int(stake)
                        if new_total > total_limit:
                            st.error("このGWの投票合計が上限を超えます。")
                        else:
                            payload = {
                                "key": f"{conf.get('current_gw')}-{me['username']}-{m['id']}",
                                "gw": conf.get("current_gw"),
                                "user": me["username"],
                                "match_id": str(m["id"]),
                                "match": f"{m['home']} vs {m['away']}",
                                "pick": pick,
                                "stake": int(stake),
                                "odds": {"HOME":home_odds, "DRAW":draw_odds, "AWAY":away_odds}[pick],
                                "placed_at": datetime.utcnow().isoformat(),
                                "status": "OPEN",
                                "result": "",
                                "payout": "",
                                "net": "",
                                "settled_at": ""
                            }
                            upsert_row("bets", "key", payload["key"], payload)
                            st.success("ベットを記録しました。")
                            st.rerun()

            # 他ユーザーのベット状況（集計）
            all_bets = [b for b in read_bets() if str(b.get("match_id")) == str(m["id"]) and (b.get("gw") or "").upper()==(conf.get("current_gw") or "").upper()]
            def _sum_pick(p): 
                return sum(int(b.get("stake") or 0) for b in all_bets if (b.get("pick") or "") == p)
            st.caption(f"現在のベット状況：HOME { _sum_pick('HOME') } / DRAW { _sum_pick('DRAW') } / AWAY { _sum_pick('AWAY') }")

def page_history(conf: Dict[str, str], me: Dict[str, str]):
    section_title("履歴", "過去GWの明細（試合単位の結果）を確認できます。")
    st.info("いまは雛形です。確定処理が走った bets の結果を表形式で表示する想定です。")

def page_realtime(conf: Dict[str, str], me: Dict[str, str]):
    section_title("リアルタイム", "手動更新ボタンで最新スコアを取得し、時点収支を試合単位/合計で確認します。")
    st.button("最新に更新（手動）", type="primary")

def page_odds_admin(conf: Dict[str, str], me: Dict[str, str]):
    if me.get("role") != "admin":
        st.warning("管理者のみが利用できます。")
        return

    section_title("オッズ管理", "管理者が節ごとに 1X2 オッズを手入力・ロックできます。")

    raw = fetch_matches_window(days=7, conf=conf)
    matches = simplify_matches(raw, conf)
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    for m in matches:
        with st.container(border=True):
            st.markdown(
                f'<div class="team-line"><span class="pill">{m["gw"]}</span> '
                f'{m["local_kickoff"].strftime("%m/%d %H:%M")} &nbsp; '
                f'<b>{m["home"]}</b> vs {m["away"]}</div>', unsafe_allow_html=True
            )
            # 既存オッズ
            existing = None
            for o in read_odds():
                if o.get("match_id") == str(m["id"]) and o.get("gw") == m["gw"]:
                    existing = o
                    break
            c1, c2, c3, c4 = st.columns([1,1,1,1])
            with c1:
                home = st.number_input("HOME", min_value=1.0, value=float(existing.get("home_win", 1)) if existing else 1.0, step=0.01, format="%.2f", key=f"h_{m['id']}")
            with c2:
                draw = st.number_input("DRAW", min_value=1.0, value=float(existing.get("draw", 1)) if existing else 1.0, step=0.01, format="%.2f", key=f"d_{m['id']}")
            with c3:
                away = st.number_input("AWAY", min_value=1.0, value=float(existing.get("away_win", 1)) if existing else 1.0, step=0.01, format="%.2f", key=f"a_{m['id']}")
            with c4:
                lock = st.checkbox("ロック", value=bool(existing.get("locked")) if existing else False, key=f"lk_{m['id']}")

            if st.button("保存", key=f"save_{m['id']}"):
                payload = {
                    "gw": m["gw"],
                    "match_id": str(m["id"]),
                    "home": m["home"],
                    "away": m["away"],
                    "home_win": float(home),
                    "draw": float(draw),
                    "away_win": float(away),
                    "locked": "TRUE" if lock else "",
                    "updated_at": datetime.utcnow().isoformat()
                }
                upsert_row("odds", "match_id", str(m["id"]), payload)
                st.success("保存しました。")
                st.rerun()

# -----------------------------------------------------------------------------
# Main
def main():
    conf = get_conf()
    me = ensure_auth(conf)
    if not me:
        return

    # 上部タブ（UIは現状維持）
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱️ リアルタイム", "🛠️ オッズ管理"])
    with tabs[0]: page_home(conf, me)
    with tabs[1]: page_matches_and_bets(conf, me)
    with tabs[2]: page_history(conf, me)
    with tabs[3]: page_realtime(conf, me)
    with tabs[4]: page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
