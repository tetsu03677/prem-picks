# /app.py
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import streamlit as st

from google_sheets_client import (
    read_config,
    ws,
    read_rows_by_sheet,
    upsert_odds_row,
    upsert_bet_row,
    list_bets_by_gw,
    list_bets_by_gw_and_user,
)
from football_api import fetch_matches_window, simplify_matches, get_match_result_symbol

# ───────────────────────────────
# ページ設定（最初に一度だけ）
# ───────────────────────────────
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

# ───────────────────────────────
# 共通ユーティリティ
# ───────────────────────────────
JST = timezone(timedelta(hours=9))

def jst(dt_utc_iso: str) -> datetime:
    """UTC ISO文字列→JSTのdatetime"""
    return datetime.fromisoformat(dt_utc_iso.replace("Z", "+00:00")).astimezone(JST)

def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")

def read_users(conf: Dict[str, str]) -> List[Dict]:
    try:
        return json.loads(conf.get("users_json", "[]"))
    except Exception:
        return []

def current_user_dict(conf: Dict[str, str], username: str) -> Dict:
    users = read_users(conf)
    for u in users:
        if u.get("username") == username:
            return u
    return {}

def earliest_ko_in_gw(matches: List[Dict]) -> datetime | None:
    if not matches:
        return None
    kos = [jst(m["utcDate"]) for m in matches if m.get("utcDate")]
    return min(kos) if kos else None

def calc_lock_time(earliest_ko: datetime | None, lock_minutes: int) -> datetime | None:
    if earliest_ko is None:
        return None
    return earliest_ko - timedelta(minutes=lock_minutes)

def get_conf() -> Dict[str, str]:
    return read_config()

def ensure_auth(conf: Dict[str, str]) -> Dict:
    """ログイン処理。成功時はユーザdictを返す。未ログインならフォーム表示してreturn {}"""
    if st.session_state.get("is_authenticated"):
        return st.session_state.get("me", {})

    st.markdown("<div style='display:flex;justify-content:center;'>", unsafe_allow_html=True)
    with st.container():
        st.markdown(
            "<div style='max-width:420px;width:100%;background:#111418;padding:24px 24px 16px;border-radius:12px;border:1px solid #2a2f36;'>"
            "<h2 style='margin:0 0 16px 0;text-align:center;color:#fff;'>Premier Picks</h2>",
            unsafe_allow_html=True
        )
        users = read_users(conf)
        user_names = [u["username"] for u in users] if users else ["guest"]
        username = st.selectbox("ユーザー", options=user_names, index=0, label_visibility="visible")
        password = st.text_input("パスワード", type="password")
        st.write("")  # spacing
        login_ok = st.button("ログイン", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if login_ok:
        user = current_user_dict(conf, username)
        if user and password == user.get("password"):
            st.session_state["is_authenticated"] = True
            st.session_state["me"] = user
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが違います。")
    return {}

def logout_button():
    with st.sidebar:
        st.markdown("### メニュー")
        if st.button("ログアウト", use_container_width=True):
            st.session_state.clear()
            st.rerun()

def gw_window_message(active_gw: int | None, earliest_ko: datetime | None, locked: bool, conf: Dict[str, str]):
    if active_gw is None:
        st.info("7日以内に対象のゲームウィークはありません。", icon="ℹ️")
        return
    st.markdown(
        f"**GW {active_gw}** / 最初のKO: {fmt_dt(earliest_ko) if earliest_ko else '-'} / "
        f"ロック: 最初のKOの{conf.get('lock_minutes_before_earliest','120')}分前（= 一括ロック）"
    )
    if locked:
        st.error("このGWはロック済み（ベットとオッズは編集不可）", icon="🔒")
    else:
        st.success("このGWは受付中（ベットとオッズを編集できます）", icon="✅")

def load_next_gw_matches(conf: Dict[str, str]) -> Tuple[int | None, List[Dict], datetime | None, bool]:
    """7日以内の“次のGW”の試合を取得し、(gw, matches, earliest_ko, locked) を返す。"""
    try:
        days = 7
        comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")  # PL
        season = conf.get("API_FOOTBALL_SEASON", "2025")
        lock_minutes = int(conf.get("lock_minutes_before_earliest", "120"))
        data, _ = fetch_matches_window(days, competition=comp, season=season)
        matches = simplify_matches(data)
        # 次のGW（matchdayの最小）
        gws = sorted({m["matchday"] for m in matches if m.get("matchday") is not None})
        if not gws:
            return (None, [], None, False)
        active_gw = gws[0]
        gw_matches = [m for m in matches if m.get("matchday") == active_gw]
        eko = earliest_ko_in_gw(gw_matches)
        lock_dt = calc_lock_time(eko, lock_minutes) if eko else None
        locked = (datetime.now(tz=JST).astimezone(timezone.utc) >= lock_dt.astimezone(timezone.utc)) if lock_dt else False
        return (active_gw, gw_matches, eko, locked)
    except Exception:
        return (None, [], None, False)

# ───────────────────────────────
# 各タブ描画
# ───────────────────────────────
def page_top(conf: Dict[str, str], me: Dict):
    st.markdown("#### ようこそ！")
    st.write("上部のタブから操作してください。")

def page_matches_and_bets(conf: Dict[str, str], me: Dict):
    st.markdown("### 試合とベット")
    active_gw, matches, eko, locked = load_next_gw_matches(conf)
    gw_window_message(active_gw, eko, locked, conf)

    if not matches:
        st.stop()

    # そのGWの自分の既存ベット
    my_bets = list_bets_by_gw_and_user(active_gw, me["username"])

    # 他ユーザーの集計（HOME/DRAW/AWAYごと合計）
    all_bets = list_bets_by_gw(active_gw)

    # ベット上限
    max_total = int(conf.get("max_total_stake_per_gw", "5000"))
    step = int(conf.get("stake_step", "100"))
    my_total = sum(b.get("stake", 0) for b in my_bets if isinstance(b.get("stake", 0), (int, float)))

    st.markdown(f"**あなたの今GW合計**：{my_total} / 上限 {max_total}")

    # カード群
    for m in matches:
        match_id = str(m["id"])
        colA, colB, colC, colD = st.columns([2.6, 2.2, 2.6, 1.6])
        with colA:
            st.markdown(
                f"<div style='padding:8px;border:1px solid #2a2f36;border-radius:10px;'>"
                f"<div style='font-weight:700;'>{m['homeTeam']}</div>"
                f"<div style='opacity:.8;'>vs</div>"
                f"<div>{m['awayTeam']}</div>"
                f"<div style='font-size:12px;opacity:.8;margin-top:6px;'>KO: {fmt_dt(jst(m['utcDate']))}</div>"
                f"</div>", unsafe_allow_html=True
            )
        with colB:
            # オッズ（oddsシートから取得、未設定は1.0）
            odds_ws = ws("odds")
            try:
                odds_rows = odds_ws.get_all_records()
            except Exception:
                odds_rows = []
            home_o, draw_o, away_o = 1.0, 1.0, 1.0
            for r in odds_rows:
                if str(r.get("match_id")) == match_id and str(r.get("gw")) == str(active_gw):
                    home_o = float(r.get("home_win", 1) or 1)
                    draw_o = float(r.get("draw", 1) or 1)
                    away_o = float(r.get("away_win", 1) or 1)
                    break
            st.markdown("**オッズ**")
            st.markdown(f"HOME: {home_o} / DRAW: {draw_o} / AWAY: {away_o}")
        with colC:
            # 自分の既存ベット
            mine = next((b for b in my_bets if str(b.get("match_id")) == match_id), None)
            default_pick = mine.get("pick") if mine else "HOME"
            default_stake = int(mine.get("stake", 0)) if mine else 0

            st.markdown("**ピック**")
            pick = st.radio(
                key=f"pick_{match_id}",
                label="",
                options=["HOME", "DRAW", "AWAY"],
                horizontal=True,
                index=["HOME","DRAW","AWAY"].index(default_pick) if default_pick in ["HOME","DRAW","AWAY"] else 0
            )
            stake = st.number_input(
                "ベット額",
                key=f"stake_{match_id}",
                min_value=0, max_value=max_total,
                step=step, value=default_stake
            )
        with colD:
            # 他ユーザー合計（その試合）
            home_sum = sum(b.get("stake", 0) for b in all_bets if str(b.get("match_id")) == match_id and b.get("pick")=="HOME")
            draw_sum = sum(b.get("stake", 0) for b in all_bets if str(b.get("match_id")) == match_id and b.get("pick")=="DRAW")
            away_sum = sum(b.get("stake", 0) for b in all_bets if str(b.get("match_id")) == match_id and b.get("pick")=="AWAY")
            st.markdown("**みんなの合計**")
            st.caption(f"HOME: {home_sum}")
            st.caption(f"DRAW: {draw_sum}")
            st.caption(f"AWAY: {away_sum}")

        # 右下にSAVE/LOCK表示
        colS1, colS2 = st.columns([1, 3])
        with colS1:
            if locked:
                st.error("LOCKED", icon="🔒")
            else:
                if st.button("保存", key=f"save_{match_id}", use_container_width=True):
                    # 上限チェック（この試合の変更差分を加味してGW合計を計算）
                    prev = default_stake
                    new_total = my_total - prev + stake
                    if new_total > max_total:
                        st.warning("今GWの上限を超えています。", icon="⚠️")
                    else:
                        # oddsをこの時点の値で固定保存
                        odds_val = {"HOME": home_o, "DRAW": draw_o, "AWAY": away_o}.get(pick, 1.0)
                        upsert_bet_row(
                            gw=active_gw,
                            match_id=int(match_id),
                            username=me["username"],
                            match=f"{m['homeTeam']} vs {m['awayTeam']}",
                            pick=pick,
                            stake=int(stake),
                            odds=float(odds_val)
                        )
                        st.success("保存しました。", icon="💾")
                        st.rerun()
        st.divider()

def page_dashboard(conf: Dict[str, str], me: Dict):
    st.markdown("### ダッシュボード")
    bets = read_rows_by_sheet("bets")
    total_stake = sum(int(b.get("stake", 0) or 0) for b in bets)

    # 結果参照用
    days = 14
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    all_data, _ = fetch_matches_window(days, competition=comp, season=season)
    ms = simplify_matches(all_data)
    result_by_id = {str(m["id"]): m for m in ms}

    total_payout = 0.0
    for b in bets:
        mid = str(b.get("match_id", ""))
        pick = b.get("pick")
        stake = float(b.get("stake", 0) or 0)
        odds = float(b.get("odds", 1.0) or 1.0)
        m = result_by_id.get(mid)
        if not m:
            continue
        symbol = get_match_result_symbol(m)  # "HOME"/"DRAW"/"AWAY" or None
        if symbol is None:
            continue
        total_payout += (stake * odds) if (symbol == pick) else 0.0
    total_net = total_payout - total_stake

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("累計ステーク", f"{int(total_stake)}")
    with c2:
        st.metric("累計ペイアウト（確定のみ）", f"{int(total_payout)}")
    with c3:
        st.metric("累計損益", f"{int(total_net)}")
    with c4:
        st.metric("今GWブックメーカー役", conf.get("bookmaker_username", "-"))

def page_history(conf: Dict[str, str], me: Dict):
    st.markdown("### 履歴")
    bets_all = read_rows_by_sheet("bets")
    if not bets_all:
        st.info("まだベット履歴がありません。")
        return
    gws = sorted({int(b.get("gw")) for b in bets_all if str(b.get("gw")).isdigit()})
    gw_pick = st.selectbox("GWを選択", gws[::-1], index=0)
    target = [b for b in bets_all if str(b.get("gw")) == str(gw_pick)]
    if not target:
        st.info("選択したGWにデータがありません。")
        return

    # 試合ヘッダごとに表示
    groups = {}
    for b in target:
        groups.setdefault(str(b.get("match_id")), []).append(b)

    days = 28
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    all_data, _ = fetch_matches_window(days, competition=comp, season=season)
    ms = simplify_matches(all_data)
    by_id = {str(m["id"]): m for m in ms}

    for mid, rows in groups.items():
        m = by_id.get(mid)
        header = f"{rows[0].get('match','')}" if rows else f"Match {mid}"
        st.markdown(f"**{header}**")
        if m:
            st.caption(f"ステータス: {m.get('status','-')} / スコア: {m.get('score','')}")
        for r in rows:
            pick = r.get("pick")
            stake = int(r.get("stake", 0) or 0)
            odds = float(r.get("odds", 1.0) or 1.0)
            symbol = get_match_result_symbol(m) if m else None
            payout = (stake * odds) if (symbol is not None and symbol == pick) else 0
            net = payout - stake if symbol is not None else 0
            st.markdown(
                f"- {r.get('user')}：{pick} / {stake} @ {odds} → "
                f"{'確定' if symbol is not None else '未確定'} / 収支 {int(net)}"
            )
        st.divider()

def page_realtime(conf: Dict[str, str], me: Dict):
    st.markdown("### リアルタイム")
    active_gw, matches, eko, _ = load_next_gw_matches(conf)
    if not matches:
        st.info("7日以内に対象のゲームウィークはありません。")
        return
    kos = [jst(m["utcDate"]) for m in matches if m.get("utcDate")]
    start = min(kos) if kos else None
    end = max(kos) + timedelta(hours=3) if kos else None  # 安全に+3hで終了時刻カバー
    now_jst = datetime.now(JST)

    st.caption(f"対象GW: {active_gw} / 開始: {fmt_dt(start) if start else '-'} / 終了: {fmt_dt(end) if end else '-'}")

    refresh = st.button("更新（手動）", icon="🔄")
    if not refresh and not (start and end and start <= now_jst <= end):
        st.info("試合時間帯以外です。開始後に更新してください。")
        return

    with st.spinner("ライブ取得中…"):
        comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
        season = conf.get("API_FOOTBALL_SEASON", "2025")
        days = 14
        all_data, _ = fetch_matches_window(days, competition=comp, season=season)
        ms = simplify_matches(all_data)
        gw_ms = [m for m in ms if m.get("matchday") == active_gw]

    bets = list_bets_by_gw(active_gw)
    by_match = {}
    for b in bets:
        by_match.setdefault(str(b.get("match_id")), []).append(b)

    total_by_user = {}
    for m in gw_ms:
        mid = str(m["id"])
        rows = by_match.get(mid, [])
        status = m.get("status")
        score = m.get("score", "")
        symbol = get_match_result_symbol(m, treat_inplay_as_provisional=True)

        box = st.container()
        with box:
            st.markdown(
                f"<div style='padding:8px;border:1px solid #2a2f36;border-radius:10px;'>"
                f"<div style='font-weight:700;'>{m['homeTeam']} vs {m['awayTeam']}</div>"
                f"<div style='opacity:.8;'>ステータス: {status} / スコア: {score}</div>",
                unsafe_allow_html=True
            )
            if not rows:
                st.caption("この試合へのベットはまだありません。")
            else:
                for r in rows:
                    user = r.get("user")
                    pick = r.get("pick")
                    stake = int(r.get("stake", 0) or 0)
                    odds = float(r.get("odds", 1.0) or 1.0)
                    if symbol is None:
                        payout = 0
                    else:
                        payout = stake * odds if (pick == symbol) else 0
                    net = payout - stake if symbol is not None else 0
                    st.markdown(f"- {user}: {pick} / {stake} @ {odds} → 暫定 {int(net)}")
                    total_by_user[user] = total_by_user.get(user, 0) + int(net)
        st.markdown("</div>", unsafe_allow_html=True)
        st.write("")

    st.subheader("GW暫定トータル（ユーザー別）")
    if total_by_user:
        for u, v in total_by_user.items():
            st.markdown(f"- **{u}**: {v}")
    else:
        st.caption("暫定損益はありません。")

def page_odds_admin(conf: Dict[str, str], me: Dict):
    if me.get("role") != "admin":
        st.warning("管理者のみアクセスできます。")
        return
    st.markdown("### オッズ管理（管理者）")
    active_gw, matches, eko, locked = load_next_gw_matches(conf)
    gw_window_message(active_gw, eko, locked, conf)
    if not matches:
        st.stop()

    odds_rows = ws("odds").get_all_records()

    for m in matches:
        match_id = int(m["id"])
        home_name = m["homeTeam"]
        away_name = m["awayTeam"]

        exist = next(
            (r for r in odds_rows if str(r.get("gw")) == str(active_gw) and str(r.get("match_id")) == str(match_id)),
            None
        )
        hv = float(exist.get("home_win", 1) or 1) if exist else 1.0
        dv = float(exist.get("draw", 1) or 1) if exist else 1.0
        av = float(exist.get("away_win", 1) or 1) if exist else 1.0

        colA, colB, colC, colD = st.columns([3, 2, 2, 2])
        with colA:
            st.markdown(f"**{home_name} vs {away_name}**")
        with colB:
            home_o = st.number_input("HOME", min_value=1.0, step=0.01, value=hv, key=f"home_{match_id}")
        with colC:
            draw_o = st.number_input("DRAW", min_value=1.0, step=0.01, value=dv, key=f"draw_{match_id}")
        with colD:
            away_o = st.number_input("AWAY", min_value=1.0, step=0.01, value=av, key=f"away_{match_id}")

        if locked:
            st.caption("ロック中のため編集できません。")
        else:
            if st.button("保存", key=f"save_odds_{match_id}"):
                upsert_odds_row(
                    gw=active_gw,
                    match_id=match_id,
                    home_team=home_name,
                    away_team=away_name,
                    home_win=float(home_o),
                    draw=float(draw_o),
                    away_win=float(away_o),
                )
                st.success("保存しました。", icon="💾")
                st.rerun()
        st.divider()

# ───────────────────────────────
# メイン
# ───────────────────────────────
def main():
    conf = get_conf()
    me = ensure_auth(conf)
    if not me:
        return

    logout_button()

    # タブ（固定の並び）
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📊 ダッシュボード", "📁 履歴", "⏱ リアルタイム", "🛠 オッズ管理"])
    with tabs[0]:
        page_top(conf, me)
    with tabs[1]:
        page_matches_and_bets(conf, me)
    with tabs[2]:
        page_dashboard(conf, me)
    with tabs[3]:
        page_history(conf, me)
    with tabs[4]:
        page_realtime(conf, me)
    with tabs[5]:
        page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
