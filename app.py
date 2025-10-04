# app.py
from __future__ import annotations

import json
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import streamlit as st

from google_sheets_client import read_config, read_rows_by_sheet, upsert_row, now_iso_utc
from football_api import fetch_matches_next_gw

# ------------------------------------------------------------
#  ページ設定
# ------------------------------------------------------------
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

# 便利関数
def _tz(conf: Dict[str, str]) -> ZoneInfo:
    tz = conf.get("timezone", "Asia/Tokyo")
    st.session_state["app_tz"] = tz
    return ZoneInfo(tz)

def _to_utc(dt_local: datetime) -> datetime:
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=timezone.utc)
    return dt_local.astimezone(timezone.utc)

# ------------------------------------------------------------
#  ログイン（上部固定）
# ------------------------------------------------------------
def parse_users(conf: Dict[str, str]) -> List[Dict]:
    raw = conf.get("users_json", "").strip()
    if not raw:
        return [{"username": "guest", "password": "", "role": "user", "team": ""}]
    try:
        users = json.loads(raw)
        # safety
        for u in users:
            u.setdefault("role", "user")
            u.setdefault("team", "")
        return users
    except Exception:
        st.warning("config の users_json が不正です。一時的に guest のみ表示しています。")
        return [{"username": "guest", "password": "", "role": "user", "team": ""}]

def login_box(conf: Dict[str, str]) -> Dict:
    users = parse_users(conf)
    usernames = [u["username"] for u in users]
    with st.container(border=True):
        st.markdown("### Premier Picks")
        c1, c2 = st.columns([1,1])
        with c1:
            user_sel = st.selectbox("ユーザー", usernames, key="login_user")
        with c2:
            pwd = st.text_input("パスワード", type="password", key="login_pwd")

        if st.button("ログイン", use_container_width=True, key="btn_login"):
            me = next((u for u in users if u["username"] == user_sel), None)
            if me and (me.get("password", "") == pwd):
                st.session_state["me"] = me
                st.success(f"ようこそ {me['username']} さん！")
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います。")

    me = st.session_state.get("me")
    if me:
        st.success(f"ようこそ {me['username']} さん！", icon="🙌")
    return me or {}

# ------------------------------------------------------------
#  データアクセス
# ------------------------------------------------------------
def bets_rows() -> List[Dict]:
    return read_rows_by_sheet("bets")

def odds_rows() -> List[Dict]:
    return read_rows_by_sheet("odds")

def odds_map_for_gw(gw: str) -> Dict[str, Dict]:
    out = {}
    for r in odds_rows():
        if str(r.get("gw", "")).strip() == str(gw):
            out[str(r.get("match_id"))] = r
    return out

# ------------------------------------------------------------
#  画面：試合とベット
# ------------------------------------------------------------
def lock_info(conf: Dict[str, str], matches: List[Dict]) -> Tuple[bool, Optional[datetime]]:
    if not matches:
        return False, None
    tz = _tz(conf)
    earliest = min(m["utc_kickoff"] for m in matches)
    # ロックは「最初の試合の2時間前（config.lock_minutes_before_earliest）」
    minutes = int(conf.get("lock_minutes_before_earliest", "120") or "120")
    lock_at_utc = earliest - timedelta(minutes=minutes)
    now_utc = datetime.now(timezone.utc)
    return now_utc >= lock_at_utc, lock_at_utc

def _bet_key(gw: str, user: str, match_id: str) -> str:
    return f"{gw}:{user}:{match_id}"

def page_matches_and_bets(conf: Dict[str, str], me: Dict):
    st.markdown("## 試合とベット")

    # API 取得（7日以内 & 直近GW）
    try:
        matches, gw = fetch_matches_next_gw(conf, day_window=7)
    except Exception as e:
        st.warning("試合データの取得に失敗しました（HTTP 403 など）。直近の試合が出ない場合は後で再試行してください。")
        matches, gw = [], ""

    # ロック表示
    locked, lock_at_utc = lock_info(conf, matches)
    if locked:
        st.error("LOCKED", icon="🔒")
    else:
        st.success("OPEN", icon="✅")
    if lock_at_utc:
        st.caption(f"ロック基準時刻（最初の試合の 120 分前・UTC基準）: {lock_at_utc.isoformat()}")

    if not matches:
        st.info("7日以内に表示できる試合がありません。")
        return

    # 既存ベット
    all_bets = bets_rows()
    my_bets_by_match = {
        str(b.get("match_id")): b for b in all_bets
        if str(b.get("gw")) == str(gw) and b.get("user") == me.get("username")
    }

    # オッズ
    omap = odds_map_for_gw(gw)

    # 合計制限
    step = int(conf.get("stake_step", "100") or "100")
    max_total = int(conf.get("max_total_stake_per_gw", "5000") or "5000")
    my_total = sum(int(b.get("stake", 0) or 0) for b in all_bets if b.get("user") == me.get("username") and str(b.get("gw")) == str(gw))
    st.caption(f"このGWのあなたの投票合計: {my_total} / 上限 {max_total}（残り {max_total - my_total}）")

    for m in matches:
        match_id = str(m["id"])
        title = f"**{m['home']}** vs **{m['away']}**"
        with st.container(border=True):
            c_head = st.columns([1,1,1,1])
            with c_head[0]:
                st.markdown(f"**{m['gw']}**")
            with c_head[1]:
                local = m["local_kickoff"].strftime("%m/%d %H:%M")
                st.caption(local)
            with c_head[2]:
                st.markdown(title)
            with c_head[3]:
                st.caption(m.get("status",""))

            # オッズ
            o = omap.get(match_id, {})
            h = float(o.get("home_win") or 1)
            d = float(o.get("draw") or 1)
            a = float(o.get("away_win") or 1)
            if not (o.get("home_win") and o.get("draw") and o.get("away_win")):
                st.info("オッズ未入力のため仮オッズ(=1.0)を表示中。管理者は『オッズ管理』で設定してください。")
            st.caption(f"Home: {h:.2f} ・ Draw: {d:.2f} ・ Away: {a:.2f}")

            # 既存ベットの既定値
            my_prev = my_bets_by_match.get(match_id, {})
            default_pick = my_prev.get("pick", "HOME")
            default_stake = int(my_prev.get("stake") or step)

            pick = st.radio(
                "ピック", options=["HOME","DRAW","AWAY"],
                index=["HOME","DRAW","AWAY"].index(default_pick) if default_pick in ["HOME","DRAW","AWAY"] else 0,
                horizontal=True, key=f"pick_{match_id}_{me.get('username','')}",
                disabled=locked
            )
            stake = st.number_input(
                "ステーク", min_value=step, step=step, value=default_stake,
                key=f"stake_{match_id}_{me.get('username','')}", disabled=locked
            )

            # 他人のベッティング概要
            match_bets = [b for b in all_bets if str(b.get("match_id")) == match_id and str(b.get("gw")) == str(gw)]
            cnt = {"HOME":0,"DRAW":0,"AWAY":0}
            for b in match_bets:
                cnt[str(b.get("pick","")).upper()] = cnt.get(str(b.get("pick","")).upper(), 0) + int(b.get("stake") or 0)
            st.caption(f"現在のベット状況： HOME {cnt['HOME']} / DRAW {cnt['DRAW']} / AWAY {cnt['AWAY']}")

            # 送信
            can_place = (not locked) and (my_total - int(my_prev.get("stake") or 0) + stake <= max_total)
            if st.button("この内容でベット", key=f"bet_{match_id}_{me.get('username','')}", disabled=not can_place):
                my_total = my_total - int(my_prev.get("stake") or 0) + stake
                odds = {"HOME": h, "DRAW": d, "AWAY": a}.get(pick, 1.0)
                row = {
                    "key": _bet_key(m["gw"], me["username"], match_id),
                    "gw": m["gw"],
                    "user": me["username"],
                    "match_id": match_id,
                    "match": f"{m['home']} vs {m['away']}",
                    "pick": pick,
                    "stake": stake,
                    "odds": odds,
                    "placed_at": now_iso_utc(),
                    "status": "OPEN",
                    "result": "",
                    "payout": "",
                    "net": "",
                    "settled_at": "",
                }
                upsert_row("bets", row["key"], row)
                st.success("保存しました。")
                st.rerun()

# ------------------------------------------------------------
#  履歴
# ------------------------------------------------------------
def page_history(conf: Dict[str, str], me: Dict):
    st.markdown("## 履歴")

    all_bets = bets_rows()
    gw_list = sorted(list({str(b.get("gw")) for b in all_bets if b.get("gw")}), key=lambda x: (len(x), x))
    if not gw_list:
        st.info("履歴はまだありません。")
        return

    gw_sel = st.selectbox("表示するGW", gw_list, index=len(gw_list)-1)

    target = [b for b in all_bets if str(b.get("gw")) == str(gw_sel)]
    if not target:
        st.info("該当の履歴がありません。")
        return

    def row_view(b: Dict):
        left = f"{b.get('match','')}"
        right = f"{b.get('pick','')} / {b.get('stake','')} at {b.get('odds','')}"
        st.markdown(f"- **{b.get('user','?')}** ：{left} → {right}")

    for b in target:
        row_view(b)

# ------------------------------------------------------------
#  リアルタイム（簡易）
# ------------------------------------------------------------
def page_realtime(conf: Dict[str, str], me: Dict):
    st.markdown("## リアルタイム")
    st.caption("更新ボタンで最新スコアを手動取得。自動更新はしません。")
    if st.button("スコアを更新", key="btn_refresh_scores"):
        pass  # ボタンでリランだけ促す
        st.rerun()

    try:
        matches, gw = fetch_matches_next_gw(conf, day_window=7)
    except Exception:
        st.warning("スコア取得に失敗（HTTP 403 など）。再試行してください。")
        return

    if not matches:
        st.info("対象期間に試合がありません。")
        return

    rows = []
    for m in matches:
        rows.append({
            "GW": m["gw"],
            "Kickoff(Local)": m["local_kickoff"].strftime("%m/%d %H:%M"),
            "Match": f"{m['home']} vs {m['away']}",
            "Status": m.get("status",""),
            "Score": f"{m.get('home_score','')}-{m.get('away_score','')}",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

# ------------------------------------------------------------
#  ダッシュボード（シンプル KPI）
# ------------------------------------------------------------
def page_dashboard(conf: Dict[str, str], me: Dict):
    st.markdown("## ダッシュボード")
    all_bets = bets_rows()
    total_stake = sum(int(b.get("stake") or 0) for b in all_bets)
    my_stake = sum(int(b.get("stake") or 0) for b in all_bets if b.get("user") == me.get("username"))
    st.metric("総ベット額（全期間）", f"{total_stake}")
    st.metric("あなたの総ベット額", f"{my_stake}")

# ------------------------------------------------------------
#  オッズ管理（管理者のみ）
# ------------------------------------------------------------
def page_odds_admin(conf: Dict[str, str], me: Dict):
    st.markdown("## オッズ管理")
    if me.get("role") != "admin":
        st.info("管理者のみが利用できます。")
        return

    try:
        matches, gw = fetch_matches_next_gw(conf, day_window=7)
    except Exception:
        st.warning("試合データの取得に失敗（HTTP 403 など）。")
        return
    if not matches:
        st.info("対象期間に試合がありません。")
        return

    st.caption(f"対象GW: {gw}")

    # freeze（最初の試合のX分前は編集不可）
    freeze_min = int(conf.get("odds_freeze_minutes_before_first", "120") or "120")
    earliest = min(m["utc_kickoff"] for m in matches)
    freeze_at = earliest - timedelta(minutes=freeze_min)
    is_frozen = datetime.now(timezone.utc) >= freeze_at
    if is_frozen:
        st.error("オッズは編集不可（凍結中）", icon="🧊")
    else:
        st.success("オッズは編集可能", icon="📝")
        st.caption(f"凍結予定: {freeze_at.isoformat()}")

    # 既存オッズ
    omap = odds_map_for_gw(gw)

    for m in matches:
        match_id = str(m["id"])
        o = omap.get(match_id, {})
        with st.container(border=True):
            st.markdown(f"**{m['home']} vs {m['away']}**")
            c1, c2, c3 = st.columns(3)
            with c1:
                home_win = st.number_input("Home", min_value=1.0, step=0.1,
                                           value=float(o.get("home_win") or 1.0),
                                           key=f"odds_h_{match_id}", disabled=is_frozen)
            with c2:
                draw = st.number_input("Draw", min_value=1.0, step=0.1,
                                       value=float(o.get("draw") or 1.0),
                                       key=f"odds_d_{match_id}", disabled=is_frozen)
            with c3:
                away_win = st.number_input("Away", min_value=1.0, step=0.1,
                                           value=float(o.get("away_win") or 1.0),
                                           key=f"odds_a_{match_id}", disabled=is_frozen)

            if st.button("保存", key=f"odds_save_{match_id}", disabled=is_frozen):
                row = {
                    "gw": gw,
                    "match_id": match_id,
                    "home": m["home"],
                    "away": m["away"],
                    "home_win": home_win,
                    "draw": draw,
                    "away_win": away_win,
                    "locked": "TRUE" if is_frozen else "",
                    "updated_at": now_iso_utc(),
                }
                upsert_row("odds", f"{gw}:{match_id}", row, key_col="match_id")  # match_id で上書き
                st.success("保存しました。")
                st.rerun()

# ------------------------------------------------------------
#  メイン
# ------------------------------------------------------------
def main():
    conf = read_config()
    tz = _tz(conf)  # set session tz

    me = login_box(conf)

    st.markdown("---")
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱️ リアルタイム", "📊 ダッシュボード", "🛠️ オッズ管理"])

    with tabs[0]:
        st.markdown("## トップ")
        st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
        if me:
            role = me.get("role", "user")
            st.caption(f"ログイン中： **{me.get('username')}** ({role})")

    with tabs[1]:
        if me:
            page_matches_and_bets(conf, me)
        else:
            st.info("ログインしてください。")

    with tabs[2]:
        if me:
            page_history(conf, me)
        else:
            st.info("ログインしてください。")

    with tabs[3]:
        if me:
            page_realtime(conf, me)
        else:
            st.info("ログインしてください。")

    with tabs[4]:
        if me:
            page_dashboard(conf, me)
        else:
            st.info("ログインしてください。")

    with tabs[5]:
        if me:
            page_odds_admin(conf, me)
        else:
            st.info("ログインしてください。")

if __name__ == "__main__":
    main()
