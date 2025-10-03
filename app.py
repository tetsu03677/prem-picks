from __future__ import annotations
import streamlit as st
from streamlit_option_menu import option_menu
from datetime import datetime, timedelta
import pandas as pd

from google_sheets_client import read_config, read_users_from_config, load_odds_df, load_bets_df
from football_api import fixtures_by_date_range, simplify_match

# ─────────────────────────────────────────────────────────────────────
# 共通外観
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

PRIMARY = "#E91E63"

def _pill(text: str):
    st.markdown(f"<div style='display:inline-block;background:{PRIMARY}15;color:{PRIMARY};padding:.25rem .5rem;border-radius:999px;font-size:.8rem'>{text}</div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────────────────────────────
def do_login():
    st.markdown("### 🔐 ログイン")
    conf = read_config()
    users = {u["username"]: u for u in read_users_from_config(conf)}
    col1, col2 = st.columns(2)
    with col1:
        user = st.text_input("ユーザー名")
    with col2:
        pw = st.text_input("パスワード", type="password")
    if st.button("ログイン", use_container_width=True):
        u = users.get(user)
        if u and pw == u.get("password"):
            st.session_state.user = u
            st.session_state.is_auth = True
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが違います。")

def top_nav(is_admin: bool) -> str:
    with st.container():
        selected = option_menu(
            None,
            ["トップ","試合とベット","履歴","リアルタイム","ルール"] + (["オッズ管理"] if is_admin else []),
            icons=["house","bullseye","clock-history","stopwatch","book"] + (["gear"] if is_admin else []),
            orientation="horizontal",
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "nav-link": {"font-size":"0.95rem","--hover-color":"#f8f8f8"},
                "nav-link-selected": {"background-color": PRIMARY, "color":"#fff"},
            }
        )
    return selected

# ─────────────────────────────────────────────────────────────────────
# 各ビュー
# ─────────────────────────────────────────────────────────────────────
def view_home(conf):
    st.markdown("## 🏠 トップ")
    _pill(f"GW: {conf.get('current_gw','-')}")
    st.write("まずは『試合とベット』から。管理者は『オッズ管理』でオッズ入力ができます。")

def view_bets(conf, user):
    st.markdown("## 🎯 試合とベット")
    league = conf.get("API_FOOTBALL_LEAGUE_ID","39")
    days = st.slider("何日先まで表示するか", 3, 21, 14)
    now = datetime.utcnow().date()
    date_from = now
    date_to   = now + timedelta(days=days)

    try:
        matches = fixtures_by_date_range(conf, league, datetime.combine(date_from, datetime.min.time()), datetime.combine(date_to, datetime.min.time()))
        simp = [simplify_match(m) for m in matches]
    except Exception as e:
        st.error(f"試合データ取得エラー: {e}")
        simp = []

    odds_df = load_odds_df()
    if odds_df.empty:
        st.info("オッズが未入力です（管理者が『オッズ管理』で入力してください）。")

    # マッチカード表示（簡易）
    for m in simp:
        oid = str(m["match_id"])
        card = st.container(border=True)
        with card:
            st.markdown(f"**{m['home']} vs {m['away']}** 　`#{oid}`")
            st.caption(f"status: {m['status']} / kick-off(UTC): {m['utcDate']}")
            row = odds_df[odds_df["match_id"].astype(str)==oid]
            if not row.empty:
                r = row.iloc[0]
                st.write(f"オッズ: Home **{r['home_win']}** / Draw **{r['draw']}** / Away **{r['away_win']}**  {'🔒' if str(r.get('locked','')).lower()=='true' else ''}")
            else:
                st.write("オッズ: ―")
            st.button("この試合にベット", key=f"bet_{oid}", disabled=True)  # まずは土台（次段で実装）

def view_history(conf, user):
    st.markdown("## 🧾 履歴")
    df = load_bets_df()
    if df.empty:
        st.info("まだベットはありません。")
        return
    me = df[df["user"]==user["username"]] if user else df
    st.dataframe(me, use_container_width=True)

def view_realtime(conf, user):
    st.markdown("## ⏱ リアルタイム")
    st.info("スコアの自動反映は次段で有効化します。まずは API と画面の土台を安定化させます。")

def view_rules(conf):
    st.markdown("## 📖 ルール")
    st.markdown("""
- 1X2 のみ（Home/Draw/Away）
- ベット締切: 最初の試合の **{} 分前**で凍結
- 1GWの合計ステーク上限: **{}**
- ステーク刻み: **{}**
    """.format(conf.get("odds_freeze_minutes_before_first","120"),
               conf.get("max_total_stake_per_gw","5000"),
               conf.get("stake_step","100")))

def view_odds_admin(conf):
    st.markdown("## ⚙ オッズ管理（手入力）")
    st.caption("※ まずは `odds` シートへ直接追記でもOK。ここは次段でUI化します。")
    st.dataframe(load_odds_df(), use_container_width=True)

# ─────────────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────────────
def main():
    conf = read_config()
    user = st.session_state.get("user")
    is_auth = st.session_state.get("is_auth", False)

    if not is_auth:
        do_login()
        return

    # 上部タブ
    selected = top_nav(is_admin=(user.get("role")=="admin"))

    # 右上: ログアウト
    st.sidebar.success(f"ログイン中: {user.get('username')}")
    if st.sidebar.button("ログアウト", use_container_width=True):
        for k in ["user","is_auth"]:
            st.session_state.pop(k, None)
        st.rerun()

    if selected == "トップ":
        view_home(conf)
    elif selected == "試合とベット":
        view_bets(conf, user)
    elif selected == "履歴":
        view_history(conf, user)
    elif selected == "リアルタイム":
        view_realtime(conf, user)
    elif selected == "ルール":
        view_rules(conf)
    elif selected == "オッズ管理":
        view_odds_admin(conf)

if __name__ == "__main__":
    main()
