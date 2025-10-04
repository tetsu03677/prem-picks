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

def fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M")

def read_users(conf: Dict[str, str]) -> List[Dict]:
    try:
        return json.loads(conf.get("users_json", "[]"))
    except Exception:
        return []

def current_user_dict(conf: Dict[str, str], username: str) -> Dict:
    for u in read_users(conf):
        if u.get("username") == username:
            return u
    return {}

def earliest_ko_in_gw(matches: List[Dict]) -> datetime | None:
    kos = [jst(m["utcDate"]) for m in matches if m.get("utcDate")]
    return min(kos) if kos else None

def calc_lock_time(earliest_ko: datetime | None, lock_minutes: int) -> datetime | None:
    if earliest_ko is None:
        return None
    return earliest_ko - timedelta(minutes=lock_minutes)

def get_conf() -> Dict[str, str]:
    conf = read_config()
    # football_api 側でも参照できるよう、セッションにも置く
    st.session_state["_conf_cache"] = conf
    return conf

# ───────────────────────────────
# ログイン（合意の“カード風・中央寄せ UI”、ユーザーは config の JSON からプルダウン）
# ───────────────────────────────
def ensure_auth(conf: Dict[str, str]) -> Dict:
    if st.session_state.get("is_authenticated"):
        return st.session_state.get("me", {})

    st.markdown("<div style='display:flex;justify-content:center;'>", unsafe_allow_html=True)
    with st.container():
        st.markdown(
            "<div style='max-width:420px;width:100%;background:#111418;padding:24px 24px 16px;border-radius:12px;border:1px solid #2a2f36;'>"
            "<h2 style='margin:0 0 16px 0;text-align:center;color:#fff;'>Premier Picks</h2>"
            "<p style='margin:0 0 12px 0;text-align:center;color:#c9d1d9;font-size:13px;'>ログインしてください</p>",
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
            st.session_state.clear()
            st.session_state["is_authenticated"] = True
            st.session_state["me"] = user
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが違います。")
    return {}

# ───────────────────────────────
# サイドバー（ログアウトのみ）
# ───────────────────────────────
def sidebar_logout():
    with st.sidebar:
        st.markdown("### メニュー")
        if st.button("ログアウト", use_container_width=True):
            st.session_state.clear()
            st.rerun()

# ───────────────────────────────
# GW 取得（直近7日で“次のGW”）＋ ロック判定
# ───────────────────────────────
def load_next_gw_matches(conf: Dict[str, str]) -> Tuple[int | None, List[Dict], datetime | None, bool]:
    """
    直近7日以内に開始する“次のGW”の試合を football-data から取得し、
    (gw, gw_matches, earliest_ko, locked) を返す
    """
    try:
        days = 7
        comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")  # PL
        season = conf.get("API_FOOTBALL_SEASON", "2025")
        lock_minutes = int(conf.get("lock_minutes_before_earliest", "120"))
        data, _ = fetch_matches_window(days, competition=comp, season=season)
        matches = simplify_matches(data)

        # 次のGW（matchday の最小）
        gws = sorted({m["matchday"] for m in matches if m.get("matchday") is not None})
        if not gws:
            return (None, [], None, False)
        active_gw = gws[0]
        gw_matches = [m for m in matches if m.get("matchday") == active_gw]
        earliest = earliest_ko_in_gw(gw_matches)
        lock_dt = calc_lock_time(earliest, lock_minutes) if earliest else None

        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        locked = (now_utc >= lock_dt.astimezone(timezone.utc)) if lock_dt else False
        return (active_gw, gw_matches, earliest, locked)
    except Exception:
        return (None, [], None, False)

def gw_window_message(active_gw: int | None, earliest_ko: datetime | None, locked: bool, conf: Dict[str, str]):
    if active_gw is None:
        st.info("7日以内に対象のゲームウィークはありません。", icon="ℹ️")
        return
    lock_min = conf.get("lock_minutes_before_earliest", "120")
    st.markdown(
        f"**GW {active_gw}** / 最初のKO: {fmt_dt(earliest_ko)} / "
        f"ロック: 最初のKOの{lock_min}分前（GW一括ロック）"
    )
    st.success("受付中（ベット/オッズ編集 可）", icon="✅") if not locked else st.error("ロック中（編集不可）", icon="🔒")

# ───────────────────────────────
# ページ：トップ
# ───────────────────────────────
def page_top(conf: Dict[str, str], me: Dict):
    st.markdown("#### ようこそ！")
    st.caption("上部のタブから操作してください。")

# ───────────────────────────────
# ページ：試合とベット
# ───────────────────────────────
def _odds_for(match_id: int, gw: int) -> tuple[float, float, float]:
    try:
        odds_rows = ws("odds").get_all_records()
    except Exception:
        odds_rows = []
    hv, dv, av = 1.0, 1.0, 1.0
    for r in odds_rows:
        if str(r.get("match_id")) == str(match_id) and str(r.get("gw")) == str(gw):
            hv = float(r.get("home_win", 1) or 1)
            dv = float(r.get("draw", 1) or 1)
            av = float(r.get("away_win", 1) or 1)
            break
    return hv, dv, av

def page_matches_and_bets(conf: Dict[str, str], me: Dict):
    st.markdown("### 試合とベット")
    active_gw, matches, eko, locked = load_next_gw_matches(conf)
    gw_window_message(active_gw, eko, locked, conf)
    if not matches:
        st.stop()

    # 自分の既存ベット、全体ベット
    my_bets = list_bets_by_gw_and_user(active_gw, me["username"])
    all_bets = list_bets_by_gw(active_gw)

    max_total = int(conf.get("max_total_stake_per_gw", "5000"))
    step = int(conf.get("stake_step", "100"))
    my_total = sum(int(b.get("stake", 0) or 0) for b in my_bets)

    st.caption(f"あなたの今GW合計：{my_total} / 上限 {max_total}")

    for m in matches:
        match_id = int(m["id"])
        home = m["homeTeam"]; away = m["awayTeam"]
        hv, dv, av = _odds_for(match_id, active_gw)

        colA, colB, colC, colD = st.columns([2.8, 2.3, 2.9, 2.0])

        # カード左：試合情報
        with colA:
            st.markdown(
                f"""
                <div style='padding:10px;border:1px solid #2a2f36;border-radius:12px;'>
                  <div style='font-weight:800;font-size:16px;'>{home}</div>
                  <div style='opacity:.8;'>vs</div>
                  <div style='font-size:15px;'>{away}</div>
                  <div style='font-size:12px;opacity:.8;margin-top:6px;'>KO: {fmt_dt(jst(m['utcDate']))}（JST）</div>
                </div>
                """, unsafe_allow_html=True
            )

        # オッズ表示
        with colB:
            st.markdown("**オッズ**")
            st.markdown(f"HOME: {hv} / DRAW: {dv} / AWAY: {av}")

        # 自分の入力
        with colC:
            mine = next((b for b in my_bets if str(b.get("match_id")) == str(match_id)), None)
            default_pick = mine.get("pick") if mine else "HOME"
            default_stake = int(mine.get("stake", 0) or 0) if mine else 0

            st.markdown("**ピック**")
            pick = st.radio(
                key=f"pick_{match_id}",
                label="",
                options=["HOME WIN","DRAW","AWAY WIN"],
                horizontal=True,
                index=["HOME","DRAW","AWAY"].index(default_pick) if default_pick in ["HOME","DRAW","AWAY"] else 0
            )
            # 内部値を HOME/DRAW/AWAY に戻す
            pick_val = {"HOME WIN":"HOME","DRAW":"DRAW","AWAY WIN":"AWAY"}[pick]

            stake = st.number_input(
                "ベット額",
                key=f"stake_{match_id}",
                min_value=0, max_value=max_total,
                step=step, value=default_stake
            )

        # みんなの合計（テーブル禁止 → ラベル羅列）
        with colD:
            home_sum = sum(int(b.get("stake", 0) or 0) for b in all_bets if str(b.get("match_id")) == str(match_id) and b.get("pick")=="HOME")
            draw_sum = sum(int(b.get("stake", 0) or 0) for b in all_bets if str(b.get("match_id")) == str(match_id) and b.get("pick")=="DRAW")
            away_sum = sum(int(b.get("stake", 0) or 0) for b in all_bets if str(b.get("match_id")) == str(match_id) and b.get("pick")=="AWAY")
            st.markdown("**みんなの合計**")
            st.caption(f"HOME: {home_sum}")
            st.caption(f"DRAW: {draw_sum}")
            st.caption(f"AWAY: {away_sum}")

        # 保存／ロック
        c1, c2 = st.columns([1.2, 3.8])
        with c1:
            if locked:
                st.error("LOCKED", icon="🔒")
            else:
                if st.button("保存", key=f"save_{match_id}", use_container_width=True):
                    prev = default_stake
                    new_total = my_total - prev + int(stake)
                    if new_total > max_total:
                        st.warning("今GWの上限を超えています。", icon="⚠️")
                    else:
                        odds_val = {"HOME": hv, "DRAW": dv, "AWAY": av}[pick_val]
                        upsert_bet_row(
                            gw=active_gw,
                            match_id=match_id,
                            username=me["username"],
                            match=f"{home} vs {away}",
                            pick=pick_val,
                            stake=int(stake),
                            odds=float(odds_val)
                        )
                        st.success("保存しました。", icon="💾")
                        st.rerun()
        st.divider()

# ───────────────────────────────
# ページ：ダッシュボード（最小KPI）
# ───────────────────────────────
def page_dashboard(conf: Dict[str, str], me: Dict):
    st.markdown("### ダッシュボード")
    bets = read_rows_by_sheet("bets")
    total_stake = sum(int(b.get("stake", 0) or 0) for b in bets)

    # 直近14日で結果参照
    comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
    season = conf.get("API_FOOTBALL_SEASON", "2025")
    data, _ = fetch_matches_window(14, competition=comp, season=season)
    ms = simplify_matches(data)
    by_id = {str(m["id"]): m for m in ms}

    total_payout = 0.0
    for b in bets:
        m = by_id.get(str(b.get("match_id", "")))
        if not m:
            continue
        symbol = get_match_result_symbol(m)
        if symbol is None:
            continue
        stake = float(b.get("stake", 0) or 0)
        odds = float(b.get("odds", 1.0) or 1.0)
        total_payout += (stake * odds) if (symbol == b.get("pick")) else 0.0
    total_net = total_payout - total_stake

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("累計ステーク", f"{int(total_stake)}")
    with c2: st.metric("累計ペイアウト（確定）", f"{int(total_payout)}")
    with c3: st.metric("累計損益", f"{int(total_net)}")
    with c4: st.metric("今GWブックメーカー役", conf.get("bookmaker_username", "-"))

# ───────────────────────────────
# ページ：履歴（過去GW）
# ───────────────────────────────
def page_history(conf: Dict[str, str], me: Dict):
    st.markdown("### 履歴")
    bets_all = read_rows_by_sheet("bets")
    if not bets_all:
        st.info("まだベット履歴がありません。")
        return
    gws = sorted({int(b.get("gw")) for b in bets_all if str(b.get("gw")).isdigit()})
    gw_pick = st.selectbox("GWを選択", gws[::-1], index=0)
    target = [b for b in bets_all if str(b.get("gw")) == str(gw_pick)]
    if not target: st.stop()

    data, _ = fetch_matches_window(28, competition=conf.get("FOOTBALL_DATA_COMPETITION","2021"),
                                   season=conf.get("API_FOOTBALL_SEASON","2025"))
    ms = simplify_matches(data)
    by_id = {str(m["id"]): m for m in ms}

    groups: Dict[str, List[Dict]] = {}
    for b in target:
        groups.setdefault(str(b.get("match_id")), []).append(b)

    for mid, rows in groups.items():
        m = by_id.get(mid)
        header = rows[0].get("match","") if rows else f"Match {mid}"
        st.markdown(f"**{header}**")
        if m: st.caption(f"ステータス: {m.get('status','-')} / スコア: {m.get('score','')}")
        for r in rows:
            pick = r.get("pick")
            stake = int(r.get("stake", 0) or 0)
            odds = float(r.get("odds", 1.0) or 1.0)
            symbol = get_match_result_symbol(m) if m else None
            payout = (stake * odds) if (symbol is not None and symbol == pick) else 0
            net = payout - stake if symbol is not None else 0
            st.markdown(f"- {r.get('user')}: {pick} / {stake} @ {odds} → {'確定' if symbol is not None else '未確定'} / 収支 {int(net)}")
        st.divider()

# ───────────────────────────────
# ページ：リアルタイム（手動更新のみ）
# ───────────────────────────────
def page_realtime(conf: Dict[str, str], me: Dict):
    st.markdown("### リアルタイム")
    active_gw, matches, eko, _ = load_next_gw_matches(conf)
    if not matches:
        st.info("7日以内に対象のゲームウィークはありません。")
        return

    kos = [jst(m["utcDate"]) for m in matches if m.get("utcDate")]
    start = min(kos) if kos else None
    end = (max(kos) + timedelta(hours=3)) if kos else None  # 安全に +3h
    now_jst = datetime.now(JST)

    st.caption(f"対象GW: {active_gw} / 開始: {fmt_dt(start)} / 終了: {fmt_dt(end)}")
    refresh = st.button("更新（手動）", icon="🔄")
    if not refresh and not (start and end and start <= now_jst <= end):
        st.info("試合時間帯以外です。開始後に更新してください。")
        return

    with st.spinner("ライブ取得中…"):
        comp = conf.get("FOOTBALL_DATA_COMPETITION", "2021")
        season = conf.get("API_FOOTBALL_SEASON", "2025")
        data, _ = fetch_matches_window(14, competition=comp, season=season)
        ms = simplify_matches(data)
        gw_ms = [m for m in ms if m.get("matchday") == active_gw]

    bets = list_bets_by_gw(active_gw)
    by_match: Dict[str, List[Dict]] = {}
    for b in bets:
        by_match.setdefault(str(b.get("match_id")), []).append(b)

    total_by_user: Dict[str, int] = {}
    for m in gw_ms:
        mid = str(m["id"]); rows = by_match.get(mid, [])
        status = m.get("status"); score = m.get("score", "")
        symbol = get_match_result_symbol(m, treat_inplay_as_provisional=True)

        st.markdown(
            f"<div style='padding:10px;border:1px solid #2a2f36;border-radius:12px;'>"
            f"<div style='font-weight:800;'>{m['homeTeam']} vs {m['awayTeam']}</div>"
            f"<div style='opacity:.8;'>ステータス: {status} / スコア: {score}</div>"
            f"</div>", unsafe_allow_html=True
        )
        if not rows:
            st.caption("この試合へのベットはまだありません。")
        else:
            for r in rows:
                user = r.get("user")
                pick = r.get("pick")
                stake = int(r.get("stake", 0) or 0)
                odds = float(r.get("odds", 1.0) or 1.0)
                payout = (stake * odds) if (symbol is not None and pick == symbol) else 0
                net = payout - stake if symbol is not None else 0
                st.markdown(f"- {user}: {pick} / {stake} @ {odds} → 暫定 {int(net)}")
                total_by_user[user] = total_by_user.get(user, 0) + int(net)
        st.write("")

    st.subheader("GW暫定トータル（ユーザー別）")
    if total_by_user:
        for u, v in total_by_user.items():
            st.markdown(f"- **{u}**: {v}")
    else:
        st.caption("暫定損益はありません。")

# ───────────────────────────────
# ページ：オッズ管理（admin）
# ───────────────────────────────
def page_odds_admin(conf: Dict[str, str], me: Dict):
    if me.get("role") != "admin":
        st.warning("管理者のみアクセスできます。")
        return
    st.markdown("### オッズ管理（管理者）")
    active_gw, matches, eko, locked = load_next_gw_matches(conf)
    gw_window_message(active_gw, eko, locked, conf)
    if not matches:
        st.stop()

    # 既存オッズ
    try:
        odds_rows = ws("odds").get_all_records()
    except Exception:
        odds_rows = []

    for m in matches:
        match_id = int(m["id"])
        home_name = m["homeTeam"]; away_name = m["awayTeam"]
        exist = next((r for r in odds_rows if str(r.get("gw")) == str(active_gw) and str(r.get("match_id")) == str(match_id)), None)
        hv = float(exist.get("home_win", 1) or 1) if exist else 1.0
        dv = float(exist.get("draw", 1) or 1) if exist else 1.0
        av = float(exist.get("away_win", 1) or 1) if exist else 1.0

        colA, colB, colC, colD = st.columns([3, 2, 2, 2])
        with colA: st.markdown(f"**{home_name} vs {away_name}**")
        with colB: home_o = st.number_input("HOME", min_value=1.0, step=0.01, value=hv, key=f"home_{match_id}")
        with colC: draw_o = st.number_input("DRAW", min_value=1.0, step=0.01, value=dv, key=f"draw_{match_id}")
        with colD: away_o = st.number_input("AWAY", min_value=1.0, step=0.01, value=av, key=f"away_{match_id}")

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

    sidebar_logout()

    # タブ（合意の固定順）
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📊 ダッシュボード", "📁 履歴", "⏱ リアルタイム", "🛠 オッズ管理"])
    with tabs[0]: page_top(conf, me)
    with tabs[1]: page_matches_and_bets(conf, me)
    with tabs[2]: page_dashboard(conf, me)
    with tabs[3]: page_history(conf, me)
    with tabs[4]: page_realtime(conf, me)
    with tabs[5]: page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
