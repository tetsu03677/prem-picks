# app.py  ―――――――――――――――――――――――――――――――――――――――――――――
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Tuple

import streamlit as st

# ✅ ページ設定はアプリ起動ごとに「一度だけ」
if "page_config_set" not in st.session_state:
    st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")
    st.session_state.page_config_set = True

# 以降は自由に import（下で使っている既存モジュールはそのまま）
from google_sheets_client import read_config, ws, read_rows, upsert_row, read_rows_by_sheet
from football_api import (
    fetch_matches_window,            # 7日ウィンドウなどでの試合取得（football-data.org）
    simplify_matches,                # 表示用に整形
)

# ---------------------------
# 共通ユーティリティ
# ---------------------------
TZ_UTC = timezone.utc

def get_conf() -> Dict[str, Any]:
    return read_config()

def get_user_dict(conf: Dict[str, Any]) -> Dict[str, Any]:
    raw = conf.get("users_json", "[]")
    try:
        users = json.loads(raw)
    except Exception:
        users = []
    # username をキーに
    return {u["username"]: u for u in users if "username" in u}

def ensure_auth(conf: Dict[str, Any]) -> None:
    """
    ログインフォーム表示と認証。
    ※ set_page_config はここでは呼びません（先頭で一度だけ呼ぶ方針）
    """
    users = get_user_dict(conf)

    # 既にログイン済みなら何もしない
    if st.session_state.get("auth_user"):
        return

    st.markdown("## 🔐 ログイン")
    with st.form("login"):
        col1, col2 = st.columns(2)
        with col1:
            username = st.text_input("ユーザー名", value="", placeholder="Tetsu など")
        with col2:
            password = st.text_input("パスワード", value="", type="password")
        submitted = st.form_submit_button("ログイン")
    if submitted:
        u = users.get(username)
        if u and password == u.get("password"):
            st.session_state.auth_user = u
            st.success(f"ログイン成功：{u['username']}（{u.get('role','user')}）")
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが正しくありません。")
    st.stop()  # ログイン完了までここで停止

def top_nav(active_key: str) -> str:
    """
    画面上部のタブ風ナビ。
    return: 選択ページキー
    """
    tabs = {
        "home": "🏠 トップ",
        "bets": "🎯 試合とベット",
        "history": "📁 履歴",
        "realtime": "⏱️ リアルタイム",
        "odds": "🛠 オッズ管理",
    }
    # 管理者のみ「オッズ管理」を表示
    if (st.session_state.get("auth_user", {}).get("role") != "admin") and "odds" in tabs:
        tabs.pop("odds")

    # ラジオ風のタブ（iPhoneでも押しやすい）
    st.markdown(" ")
    choice = st.radio(
        label="",
        options=list(tabs.keys()),
        format_func=lambda k: tabs[k],
        horizontal=True,
        index=list(tabs.keys()).index(active_key) if active_key in tabs else 0,
        key="__top_nav__",
        label_visibility="collapsed",
    )
    return choice

def header_bar(conf: Dict[str, Any]) -> None:
    u = st.session_state.get("auth_user", {})
    left, right = st.columns([1,1])
    with left:
        if st.button("ログアウト", type="secondary"):
            for k in ("auth_user",):
                st.session_state.pop(k, None)
            st.success("ログアウトしました。")
            st.rerun()
    with right:
        st.write(f"**ログイン中：{u.get('username','-')}（{u.get('role','user')}）**")

# ---------------------------
# ページ：トップ
# ---------------------------
def page_home(conf: Dict[str, Any]) -> None:
    st.markdown("## 🏡 トップ")
    st.write(f"ようこそ **{st.session_state['auth_user']['username']}** さん！")
    st.info("ここにはアナウンスやルール抜粋などを表示できます。")

# ---------------------------
# ページ：試合とベット
# ---------------------------
def _gw_window_days() -> int:
    """常に 7 日固定の表示ウィンドウ"""
    return 7

def load_next_window_matches(conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """次節を 7 日固定ウィンドウで取得（見つからなければ空配列）"""
    league = conf.get("FOOTBALL_DATA_COMPETITION", "PL")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    days = _gw_window_days()
    try:
        matches_raw, _ = fetch_matches_window(days, league, season)
        matches = simplify_matches(matches_raw)
        return matches
    except Exception as e:
        st.warning(f"試合データ取得に失敗しました（{e}）。")
        return []

def _is_match_locked(kickoff_utc: datetime, conf: Dict[str, Any]) -> bool:
    """キックオフ何分前でロックするか（configの minutes 値）。"""
    minutes = int(conf.get("lock_minutes_before_earliest", 120))
    lock_threshold = kickoff_utc - timedelta(minutes=minutes)
    # UTCで比較（football-data はUTC前提）
    return datetime.utcnow().replace(tzinfo=TZ_UTC) >= lock_threshold

def _read_my_gw_total(conf: Dict[str, Any], gw: str) -> int:
    user = st.session_state["auth_user"]["username"]
    rows = read_rows_by_sheet("bets")
    total = 0
    for r in rows:
        if str(r.get("gw","")) == gw and r.get("user") == user:
            try:
                total += int(r.get("stake", 0))
            except Exception:
                pass
    return total

def page_matches_and_bets(conf: Dict[str, Any]) -> None:
    st.markdown("## 🎯 試合とベット")
    gw = conf.get("current_gw", "GW?")
    my_total = _read_my_gw_total(conf, gw)
    limit_total = int(conf.get("max_total_stake_per_gw", 5000))
    st.caption(f"このGWのあなたの投票合計: **{my_total}** / 上限 **{limit_total}**（残り **{limit_total - my_total}**）")

    matches = load_next_window_matches(conf)
    if not matches:
        st.info("**7日以内に次節はありません。**")
        return

    for m in matches:
        # m: {id, gw, utc (datetime), home, away, status, score, ...}
        with st.container(border=True):
            # ヘッダ
            ko_local = m["utc"].astimezone(timezone(timedelta(hours=0)))  # UTC表示（必要ならTZ調整）
            st.markdown(f"**{m.get('gw','GW?')}** ・ {ko_local:%m/%d %H:%M}")
            st.markdown(f"<span style='font-size:1.05rem; font-weight:700;'>{m['home']}</span> vs <span style='font-size:1.05rem;'>{m['away']}</span>", unsafe_allow_html=True)

            # ロック判定
            locked = _is_match_locked(m["utc"], conf)
            st.success("OPEN", icon="✅") if not locked else st.error("LOCKED", icon="🔒")

            # オッズ（未入力なら仮=1.0）
            # ここでは既存の odds シート読み取りロジックを利用している前提。
            # 読めなければ fallback=1.0 を表示。
            home_odds = m.get("odds_home") or 1.0
            draw_odds = m.get("odds_draw") or 1.0
            away_odds = m.get("odds_away") or 1.0

            st.write(f"Home: **{home_odds:.2f}** ・ Draw: **{draw_odds:.2f}** ・ Away: **{away_odds:.2f}**")

            # ピックの 3 分割ラジオ（HOME / DRAW / AWAY）
            cols = st.columns(3)
            with cols[0]:
                pick_home = st.radio("ピック", ["HOME"], horizontal=True, key=f"pick_home_label_{m['id']}", label_visibility="collapsed")
                pick_choice = "HOME"  # 表示用ラベル行なので値は使わない
            with cols[1]:
                st.markdown("<div style='text-align:center; opacity:.6'>DRAW</div>", unsafe_allow_html=True)
            with cols[2]:
                st.markdown("<div style='text-align:right; opacity:.6'>AWAY</div>", unsafe_allow_html=True)

            # 実際の選択（1行にまとめて見栄え良く）
            pick = st.radio(
                "ピックを選択",
                options=["HOME", "DRAW", "AWAY"],
                index=0,
                key=f"pick_{m['id']}",
                horizontal=True,
                format_func=lambda x: {"HOME": f"HOME（{m['home']}）", "DRAW": "DRAW", "AWAY": f"AWAY（{m['away']}）"}[x],
            )

            # ステーク
            step = int(conf.get("stake_step", 100))
            stake = st.number_input("ステーク", min_value=0, step=step, value=step, key=f"stake_{m['id']}")

            # 送信
            disabled = locked or (my_total + stake > limit_total)
            if st.button("この内容でベット", key=f"betbtn_{m['id']}", disabled=disabled):
                # 既存の保存ロジックを流用（bets シートに upsert）
                row = {
                    "gw": gw,
                    "user": st.session_state["auth_user"]["username"],
                    "match_id": m["id"],
                    "match": f"{m['home']} vs {m['away']}",
                    "pick": pick,
                    "stake": int(stake),
                    "odds": {"HOME": home_odds, "DRAW": draw_odds, "AWAY": away_odds}[pick],
                    "placed_at": datetime.utcnow().isoformat(),
                    "status": "open",
                    "result": "",
                    "payout": "",
                    "net": "",
                    "settled_at": "",
                }
                upsert_row("bets", row, keys=["gw","user","match_id"])  # 既存関数：キー一致で更新 or 追加
                st.success("ベットを記録しました！")
                st.rerun()

            # 他ユーザーのベット状況（簡易）
            with st.expander("他ユーザーのベット状況", expanded=False):
                rows = read_rows_by_sheet("bets")
                peers = [
                    r for r in rows
                    if str(r.get("gw","")) == gw and str(r.get("match_id","")) == str(m["id"])
                ]
                if not peers:
                    st.caption("まだ誰もベットしていません。")
                else:
                    # HOME / DRAW / AWAY の合計額をバッジで
                    total_home = sum(int(r.get("stake",0)) for r in peers if r.get("pick")=="HOME")
                    total_draw = sum(int(r.get("stake",0)) for r in peers if r.get("pick")=="DRAW")
                    total_away = sum(int(r.get("stake",0)) for r in peers if r.get("pick")=="AWAY")
                    st.markdown(
                        f"""
                        <div style="display:flex; gap:.5rem; flex-wrap:wrap;">
                          <span style="padding:.25rem .5rem; border-radius:.5rem; background:#eef;">HOME 合計: {total_home}</span>
                          <span style="padding:.25rem .5rem; border-radius:.5rem; background:#efe;">DRAW 合計: {total_draw}</span>
                          <span style="padding:.25rem .5rem; border-radius:.5rem; background:#fee;">AWAY 合計: {total_away}</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

# ---------------------------
# ページ：履歴（簡易）
# ---------------------------
def page_history(conf: Dict[str, Any]) -> None:
    st.markdown("## 📁 履歴")
    rows = read_rows_by_sheet("bets")
    me = st.session_state["auth_user"]["username"]
    mine = [r for r in rows if r.get("user")==me]
    if not mine:
        st.caption("まだベットはありません。")
        return
    for r in mine:
        with st.container(border=True):
            st.write(f"{r.get('match','')} / {r.get('pick','')} / {r.get('stake','')} / {r.get('odds','')}")
            st.caption(f"placed: {r.get('placed_at','-')}  status: {r.get('status','open')}")

# ---------------------------
# ページ：リアルタイム（プレースホルダ）
# ---------------------------
def page_realtime(conf: Dict[str, Any]) -> None:
    st.markdown("## ⏱️ リアルタイム")
    st.caption("将来拡張：ライブスコアなど")

# ---------------------------
# ページ：オッズ管理（管理者のみ）
# ---------------------------
def page_odds_admin(conf: Dict[str, Any]) -> None:
    st.markdown("## 🛠 オッズ管理（管理者）")
    if st.session_state["auth_user"].get("role") != "admin":
        st.error("このページは管理者専用です。")
        return

    st.caption("次節（7日ウィンドウ）の試合に対する 1X2 オッズを入力します。")
    matches = load_next_window_matches(conf)
    if not matches:
        st.info("**7日以内に次節はありません。**")
        return

    for m in matches:
        with st.container(border=True):
            st.markdown(f"**{m['home']} vs {m['away']}**")
            c1,c2,c3 = st.columns(3)
            with c1:
                h = st.number_input("Home", min_value=1.0, step=0.01, value=float(m.get("odds_home") or 1.0), key=f"odds_h_{m['id']}")
            with c2:
                d = st.number_input("Draw", min_value=1.0, step=0.01, value=float(m.get("odds_draw") or 1.0), key=f"odds_d_{m['id']}")
            with c3:
                a = st.number_input("Away", min_value=1.0, step=0.01, value=float(m.get("odds_away") or 1.0), key=f"odds_a_{m['id']}")
            if st.button("保存", key=f"saveodds_{m['id']}"):
                # 既存の odds シートに保存する実装に合わせて upsert
                row = {
                    "gw": m.get("gw",""),
                    "match_id": m["id"],
                    "home": m["home"],
                    "away": m["away"],
                    "home_win": float(h),
                    "draw": float(d),
                    "away_win": float(a),
                    "locked": "",  # freeze ロジックは別途
                    "updated_at": datetime.utcnow().isoformat(),
                }
                upsert_row("odds", row, keys=["gw","match_id"])
                st.success("オッズを保存しました。")

# ---------------------------
# メイン
# ---------------------------
def main() -> None:
    conf = get_conf()
    ensure_auth(conf)  # ← set_page_config は呼ばない

    header_bar(conf)
    current = st.session_state.get("__top_nav__", "home")
    current = top_nav(current)

    pages = {
        "home": lambda: page_home(conf),
        "bets": lambda: page_matches_and_bets(conf),
        "history": lambda: page_history(conf),
        "realtime": lambda: page_realtime(conf),
    }
    if st.session_state["auth_user"].get("role") == "admin":
        pages["odds"] = lambda: page_odds_admin(conf)

    pages[current]()

if __name__ == "__main__":
    main()
# ―――――――――――――――――――――――――――――――――――――――――――――
