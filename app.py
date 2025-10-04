# app.py
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

import pytz
import streamlit as st

from google_sheets_client import (
    read_config_map,
    read_rows_by_sheet,
    upsert_row,
)
from football_api import (
    fetch_matches_next_gw,
    fetch_scores_for_match_ids,
)

# ------------------------------------------------------------
# スタイル（アイコンは使わない・落ち着いた最小限）
# ------------------------------------------------------------
CSS = """
<style>
/* ← タブ上部が切れないように上マージンを増量 */
.block-container {padding-top:3.2rem; padding-bottom:3rem;}

.app-card{border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:18px; background:rgba(255,255,255,.02);}
.subtle{color:rgba(255,255,255,.6); font-size:.9rem}
.kpi-row{display:flex; gap:12px; flex-wrap:wrap}
.kpi{flex:1 1 140px; border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:10px 14px}
.kpi .h{font-size:.8rem; color:rgba(255,255,255,.55)}
.kpi .v{font-size:1.3rem; font-weight:700; margin-top:2px}
.section{margin:16px 0 10px}
table {width:100%}
.login-hidden {display:none}

/* トップの3分割カード（BM=赤、その他=グレー） */
.role-cards{display:flex; gap:12px; flex-wrap:wrap}
.role-card{flex:1 1 0; min-width:120px; border:1px solid rgba(120,120,120,.25); border-radius:12px; padding:12px 14px; background:rgba(255,255,255,.02)}
.role-card.bm{border-color:rgba(255,0,0,.35); background:rgba(255,0,0,.08)}
.role-card .name{font-weight:700; font-size:1.05rem}
.role-card .role{font-size:.9rem; color:rgba(255,255,255,.7)}
.badges{display:flex; gap:8px; flex-wrap:wrap; margin-top:6px}
.badge{display:inline-block; padding:3px 8px; border-radius:999px; font-size:.85rem;
       border:1px solid rgba(120,120,120,.25); background:rgba(255,255,255,.06)}

/* ログイン見出し（枠なし・少し大きめ。安全策） */
.login-title{font-size:1.5rem; font-weight:700; margin:0 0 8px 2px;}
.login-area{padding:2px 0 0;} /* 余白のみ。枠は出さない */
</style>
"""
st.set_page_config(page_title="Premier Picks", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

# ------------------------------------------------------------
# ユーティリティ
# ------------------------------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def parse_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def parse_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def _gw_sort_key(x):
    """GWの並び替え用：GW7 / 7 / None / '' が混在しても安全にソート"""
    s = "" if x is None else str(x).strip()
    n = 999999
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        elif num:
            break
    if num:
        try:
            n = int(num)
        except Exception:
            n = 999999
    return (n, s)

# ------------------------------------------------------------
# 設定読込
# ------------------------------------------------------------
@st.cache_data(ttl=60)
def get_conf() -> Dict[str, str]:
    return read_config_map()

def get_users(conf: Dict[str, str]) -> List[Dict]:
    users_json = conf.get("users_json", "").strip()
    if not users_json:
        return [{"username": "guest", "password": "guest", "role": "user", "team": ""}]
    try:
        return json.loads(users_json)
    except Exception:
        return [{"username": "guest", "password": "guest", "role": "user", "team": ""}]

# ------------------------------------------------------------
# 認証（ログイン後はUIを描画しない） ★ここだけ変更：枠ナシ見出し
# ------------------------------------------------------------
def login_ui(conf: Dict[str, str]) -> Dict:
    # すでにログイン済ならフォームは描画しないでそのまま返す
    if st.session_state.get("signed_in") and st.session_state.get("me"):
        return st.session_state.get("me")

    # 未ログイン時のみフォームを表示（枠なし、安全）
    with st.container():
        st.markdown('<div class="login-area">', unsafe_allow_html=True)

        # 見出しをやや大きく。boxやborderは使わない
        st.markdown('<div class="login-title">Premier Picks</div>', unsafe_allow_html=True)

        users = get_users(conf)
        usernames = [u["username"] for u in users]
        default_idx = 0

        c1, c2 = st.columns([1, 1])
        with c1:
            user_sel = st.selectbox("ユーザー", usernames, index=default_idx, key="login_user_sel")
        with c2:
            pwd = st.text_input("パスワード", type="password", key="login_pwd")

        if st.button("ログイン", use_container_width=True, key="btn_login"):
            selected = next((u for u in users if u["username"] == user_sel), None)
            if selected and pwd == selected.get("password", ""):
                st.session_state["signed_in"] = True
                st.session_state["me"] = selected
                st.success(f"ようこそ {selected['username']} さん！")
                st.rerun()
            else:
                st.warning("ユーザー名またはパスワードが違います。")

        st.markdown("</div>", unsafe_allow_html=True)

    return st.session_state.get("me")

# ------------------------------------------------------------
# 共通: GW の判定とロック
# ------------------------------------------------------------
def gw_and_lock_state(conf: Dict[str, str], matches: List[Dict]) -> Tuple[str, bool, datetime]:
    if not matches:
        return conf.get("current_gw", ""), False, None
    earliest = min(m["utc_kickoff"] for m in matches if m.get("utc_kickoff"))
    minutes_before = parse_int(conf.get("lock_minutes_before_earliest", conf.get("odds_freeze_minutes_before_first", 120)), 120)
    lock_at_utc = earliest - timedelta(minutes=minutes_before)
    locked = now_utc() >= lock_at_utc
    gw_name = matches[0].get("gw") or conf.get("current_gw", "")
    return gw_name, locked, lock_at_utc

# ------------------------------------------------------------
# トップ専用：BMカウントと次回担当
# ------------------------------------------------------------
def _get_bm_counts(users: List[str]) -> Dict[str, int]:
    """bm_log シートの user カラムを単純集計。シートが無ければ 0。"""
    counts = {u: 0 for u in users}
    try:
        rows = read_rows_by_sheet("bm_log") or []
        for r in rows:
            u = str(r.get("user", "")).strip()
            if u in counts:
                counts[u] += 1
    except Exception:
        pass
    return counts

def _pick_next_bm(users: List[str], counts: Dict[str, int]) -> str:
    """最小回数 → ユーザーリストの順で安定選出（表示のみ。記録はしない）。"""
    order = {u: i for i, u in enumerate(users)}
    return sorted(users, key=lambda u: (counts.get(u, 0), order[u]))[0] if users else ""

# ------------------------------------------------------------
# UI: トップ（BM表示＋カウンタ）
# ------------------------------------------------------------
def page_home(conf: Dict[str, str], me: Dict):
    st.markdown("## トップ")
    st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
    if me:
        st.caption(f"ログイン中： {me['username']} ({me.get('role','')})")

    # 表示用：users とカウンタ
    users_conf = get_users(conf)
    users = [u["username"] for u in users_conf]
    counts = _get_bm_counts(users)
    next_bm = _pick_next_bm(users, counts)
    players = [u for u in users if u != next_bm]

    # 3分割カード（BM=赤、その他=グレー）
    st.markdown('<div class="section">次節のメンバー</div>', unsafe_allow_html=True)
    st.markdown('<div class="role-cards">', unsafe_allow_html=True)
    for u in users:
        is_bm = (u == next_bm)
        role_txt = "Bookmaker" if is_bm else "Player"
        card_class = "role-card bm" if is_bm else "role-card"
        html = (
            f'<div class="{card_class}">'
            f'<div class="name">{u}</div>'
            f'<div class="role">{role_txt}</div>'
            f'</div>'
        )
        st.markdown(html, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # プレイヤー（安全策でテキスト表示も）
    st.markdown('<div class="section">プレイヤー</div>', unsafe_allow_html=True)
    st.write(", ".join(players) if players else "-")

    # 担当回数
    st.markdown('<div class="section">ブックメーカー担当回数（これまで）</div>', unsafe_allow_html=True)
    badges = " ".join([f'<span class="badge">{u}: {counts.get(u,0)}</span>' for u in users])
    st.markdown(f'<div class="badges">{badges}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------
# UI: 試合とベット
# ------------------------------------------------------------
def page_matches_and_bets(conf: Dict[str, str], me: Dict):
    st.markdown("## 試合とベット")

    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    gw_name, locked, _ = gw_and_lock_state(conf, matches_raw)

    bets_all = read_rows_by_sheet("bets")
    my_gw_bets = [b for b in bets_all if (b.get("user") == me["username"] and (b.get("gw") == gw_name or b.get("gw") == gw_name.replace("GW","")))]
    my_total = sum(parse_int(b.get("stake", 0)) for b in my_gw_bets)
    max_total = parse_int(conf.get("max_total_stake_per_gw", 5000), 5000)
    st.markdown(f'<div class="kpi-row"><div class="kpi"><div class="h">このGWのあなたの投票合計</div><div class="v">{my_total:,} / 上限 {max_total:,}</div></div></div>', unsafe_allow_html=True)

    if locked:
        st.error("ロック済み（このGWの最初の試合 2 時間前で締切）")
    else:
        st.success("現在は投票可能です")

    if not matches_raw:
        st.info("7日以内に表示できる試合がありません。")
        return

    odds_rows = read_rows_by_sheet("odds")
    odds_by_match = {str(r.get("match_id")): r for r in odds_rows if r.get("match_id")}

    step = parse_int(conf.get("stake_step", 100), 100)

    for m in matches_raw:
        match_id = str(m["id"])
        teams_line = f"{m['home']} vs {m['away']}"
        with st.container(border=True):
            st.markdown(f"**{gw_name}**　・　{m['local_kickoff'].strftime('%m/%d %H:%M')}")
            st.markdown(f"### {teams_line}")

            od = odds_by_match.get(match_id, {})
            home_odds = parse_float(od.get("home_win"), 1.0)
            draw_odds = parse_float(od.get("draw"), 1.0)
            away_odds = parse_float(od.get("away_win"), 1.0)
            if od:
                st.caption(f"Home: {home_odds:.2f} / Draw: {draw_odds:.2f} / Away: {away_odds:.2f}")
            else:
                st.info("オッズ未入力のため仮オッズ (=1.0) を表示中。管理者は『オッズ管理』で設定してください。")
                st.caption(f"Home: {home_odds:.2f} / Draw: {draw_odds:.2f} / Away: {away_odds:.2f}")

            mine = [b for b in my_gw_bets if str(b.get("match_id")) == match_id]
            summary = {"HOME":0,"DRAW":0,"AWAY":0}
            for b in mine:
                summary[b.get("pick","")] = summary.get(b.get("pick",""),0) + parse_int(b.get("stake",0))
            st.caption(f"現在のベット状況（あなた）: HOME {summary['HOME']} / DRAW {summary['DRAW']} / AWAY {summary['AWAY']}")

            pick_key = f"pick_{match_id}"
            stake_key = f"stake_{match_id}"
            pick = st.radio("ピック", ["HOME","DRAW","AWAY"], key=pick_key, horizontal=True, disabled=locked)
            stake = st.number_input("ステーク", min_value=step, step=step, value=step, key=stake_key, disabled=locked)

            btn_key = f"bet_{match_id}"
            if st.button("この内容でベット", key=btn_key, disabled=locked):
                if my_total + stake > max_total:
                    st.warning("このGWの投票上限を超えます。金額を調整してください。")
                else:
                    use_odds = {"HOME": home_odds, "DRAW": draw_odds, "AWAY": away_odds}[pick]
                    row = {
                        "key": f"{gw_name}:{me['username']}:{match_id}:{datetime.utcnow().isoformat()}",
                        "gw": gw_name,
                        "user": me["username"],
                        "match_id": match_id,
                        "match": m["home"],  # 列構成準拠
                        "pick": pick,
                        "stake": str(int(stake)),
                        "odds": str(use_odds),
                        "placed_at": datetime.utcnow().date().isoformat(),
                        "status": "OPEN",
                        "result": "", "payout": "", "net": "", "settled_at": "",
                    }
                    upsert_row("bets", row, key_col="key")
                    st.success("ベットを登録しました。")
                    st.rerun()

# ------------------------------------------------------------
# UI: 履歴（収支明示）
# ------------------------------------------------------------
def page_history(conf: Dict[str, str], me: Dict):
    st.markdown("## 履歴")

    bets = read_rows_by_sheet("bets")
    if not bets:
        st.info("履歴はまだありません。")
        return

    gw_vals = {(b.get("gw") if b.get("gw") not in (None, "") else "") for b in bets}
    gw_set = sorted(gw_vals, key=_gw_sort_key)
    sel_gw = st.selectbox("表示するGW", gw_set, index=0 if gw_set else None, key="hist_gw")

    target = [b for b in bets if (b.get("gw") == sel_gw)]
    if not target:
        st.info("対象のデータがありません。")
        return

    total_stake = sum(parse_int(b.get("stake", 0)) for b in target)
    total_payout = sum(parse_float(b.get("payout"), 0.0) or 0.0 for b in target if (b.get("result") in ["WIN","LOSE"]))
    total_net = total_payout - total_stake
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="h">合計ステーク</div><div class="v">{total_stake:,}</div></div>
      <div class="kpi"><div class="h">合計ペイアウト</div><div class="v">{total_payout:,.2f}</div></div>
      <div class="kpi"><div class="h">合計収支</div><div class="v">{total_net:,.2f}</div></div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)

    def row_view(b):
        stake = parse_int(b.get("stake", 0))
        odds = parse_float(b.get("odds"), 1.0) or 1.0
        result = (b.get("result") or "").upper()
        if result in ["WIN", "LOSE"]:
            payout = parse_float(b.get("payout"), stake * odds if result == "WIN" else 0.0)
            net = payout - stake
            tail = f"｜結果：{result} ｜ payout {payout:.2f} ｜ net {net:.2f}"
        else:
            tail = "｜結果：- ｜ payout - ｜ net -"
        st.markdown(f"- **{b.get('user','')}**：{b.get('match','')} → {b.get('pick','')} / {stake} at {odds} {tail}")

    for b in target:
        row_view(b)

# ------------------------------------------------------------
# UI: リアルタイム
# ------------------------------------------------------------
def page_realtime(conf: Dict[str, str], me: Dict):
    st.markdown("## リアルタイム")
    st.caption("更新ボタンで最新スコアを手動取得。自動更新はしません。")

    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("試合が見つかりません（APIが403の場合は時間をおいて再試行ください）。")
        return

    match_ids = [str(m["id"]) for m in matches_raw]
    scores = fetch_scores_for_match_ids(conf, match_ids)

    bets = read_rows_by_sheet("bets")
    odds_rows = read_rows_by_sheet("odds")
    odds_by_match = {str(r.get("match_id")): r for r in odds_rows if r.get("match_id")}

    def current_payout(b):
        mid = str(b.get("match_id"))
        stake = parse_int(b.get("stake", 0))
        pick = b.get("pick", "")
        odds = parse_float(b.get("odds"), None) or parse_float(odds_by_match.get(mid, {}).get(
            {"HOME":"home_win","DRAW":"draw","AWAY":"away_win"}[pick]
        ), 1.0)

        sc = scores.get(mid)
        if not sc:
            return 0.0

        status = sc.get("status")
        hs, as_ = sc.get("home_score", 0), sc.get("away_score", 0)

        if status in ("SCHEDULED", "TIMED", "POSTPONED"):
            return 0.0
        if status in ("FINISHED", "AWARDED"):
            winner = "DRAW" if hs == as_ else ("HOME" if hs > as_ else "AWAY")
            return stake * odds if pick == winner else 0.0
        if hs == as_:
            return stake * odds if pick == "DRAW" else 0.0
        winner_now = "HOME" if hs > as_ else "AWAY"
        return stake * odds if pick == winner_now else 0.0

    this_gw_bets = [b for b in bets if (b.get("gw") == gw)]
    total_stake = sum(parse_int(b.get("stake", 0)) for b in this_gw_bets)
    total_curr = sum(current_payout(b) for b in this_gw_bets)
    total_net = total_curr - total_stake

    st.markdown(
        f"""
        <div class="kpi-row">
          <div class="kpi"><div class="h">このGW ステーク合計</div><div class="v">{total_stake:,}</div></div>
          <div class="kpi"><div class="h">想定ペイアウト</div><div class="v">{total_curr:,.2f}</div></div>
          <div class="kpi"><div class="h">この時点の想定収支</div><div class="v">{total_net:,.2f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    users = sorted(list({b.get("user") for b in this_gw_bets if b.get("user")}))
    if users:
        st.markdown('<div class="section">ユーザー別の時点収支</div>', unsafe_allow_html=True)
        cols = st.columns(max(2, min(4, len(users))))
        for i, u in enumerate(users):
            ub = [b for b in this_gw_bets if b.get("user") == u]
            ustake = sum(parse_int(b.get("stake", 0)) for b in ub)
            upayout = sum(current_payout(b) for b in ub)
            unat = upayout - ustake
            with cols[i % len(cols)]:
                st.markdown(f'<div class="kpi"><div class="h">{u}</div><div class="v">{unat:,.2f}</div><div class="h">stake {ustake:,} / payout {upayout:,.2f}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="section">試合別（現在スコアに基づく暫定）</div>', unsafe_allow_html=True)
    for m in matches_raw:
        mid = str(m["id"])
        s = scores.get(mid, {})
        hs, as_ = s.get("home_score", 0), s.get("away_score", 0)
        st.markdown(f"**{m['home']} vs {m['away']}**　（{s.get('status','-')}　{hs}-{as_}）")
        rows = [b for b in this_gw_bets if str(b.get("match_id")) == mid]
        if not rows:
            st.caption("（ベットなし）")
            continue
        for b in rows:
            cp = current_payout(b)
            st.caption(f"- {b.get('user')}：{b.get('pick')} / {b.get('stake')} at {b.get('odds')} → 時点 {cp:,.2f}")

    if st.button("スコアを更新", use_container_width=True):
        st.rerun()

# ------------------------------------------------------------
# UI: ダッシュボード
# ------------------------------------------------------------
def page_dashboard(conf: Dict[str, str], me: Dict):
    st.markdown("## ダッシュボード")

    bets = read_rows_by_sheet("bets")
    if not bets:
        st.info("データがありません。")
        return

    total_stake = sum(parse_int(b.get("stake", 0)) for b in bets)
    total_payout = sum(parse_float(b.get("payout"), 0.0) or 0.0 for b in bets if b.get("result") in ["WIN","LOSE"])
    total_net = total_payout - total_stake

    st.markdown(
        f"""
        <div class="kpi-row">
          <div class="kpi"><div class="h">トータル収支</div><div class="v">{total_net:,.2f}</div></div>
          <div class="kpi"><div class="h">総支出額（stake）</div><div class="v">{total_stake:,}</div></div>
          <div class="kpi"><div class="h">トータル収入額（payout）</div><div class="v">{total_payout:,.2f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section">ユーザー別：的中率が高いチーム TOP3（最低3ベット）</div>', unsafe_allow_html=True)

    by_user_team = {}
    for b in bets:
        if (b.get("result") or "").upper() not in ["WIN", "LOSE"]:
            continue
        pick = b.get("pick")
        team = ""
        if pick == "HOME":
            team = b.get("match", "")
        elif pick == "AWAY":
            team = "AWAY"
        else:
            continue

        u = b.get("user", "")
        by_user_team.setdefault(u, {}).setdefault(team, {"n": 0, "win": 0, "net": 0.0})
        by_user_team[u][team]["n"] += 1
        if (b.get("result") or "").upper() == "WIN":
            by_user_team[u][team]["win"] += 1
            by_user_team[u][team]["net"] += (parse_float(b.get("payout"), 0.0) or 0.0) - parse_int(b.get("stake", 0))
        else:
            by_user_team[u][team]["net"] -= parse_int(b.get("stake", 0))

    for u, teams in by_user_team.items():
        st.markdown(f"**{u}**")
        stats = []
        for t, v in teams.items():
            if v["n"] >= 3:
                acc = v["win"] / v["n"]
                stats.append((t, acc, v["n"], v["net"]))
        if not stats:
            st.caption("　対象データ不足（3ベット未満）")
            continue
        stats.sort(key=lambda x: (-x[1], -x[3]))
        for t, acc, n, net in stats[:3]:
            st.caption(f"　- {t}: 的中率 {acc*100:.1f}%（{n}件）／ 累計net {net:,.2f}")

# ------------------------------------------------------------
# UI: オッズ管理（入力は横並び・フォーム化・刻み0.1）
# ------------------------------------------------------------
def page_odds_admin(conf: Dict[str, str], me: Dict):
    st.markdown("## オッズ管理")
    is_admin = (me.get("role") == "admin")
    if not is_admin:
        st.info("閲覧のみ（管理者のみ編集可能）")

    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("対象の試合が見つかりません。")
        return

    odds_rows = read_rows_by_sheet("odds")
    odds_by_match = {str(r.get("match_id")): r for r in odds_rows if r.get("match_id")}

    for m in matches_raw:
        mid = str(m["id"])
        od = odds_by_match.get(mid, {})
        with st.container(border=True):
            st.markdown(f"**{m['home']} vs {m['away']}**　（{gw}）")

            # フォームで包み、保存時のみ反映＆rerun
            with st.form(f"odds_form_{mid}", clear_on_submit=False):
                c1, c2, c3, c4 = st.columns([1,1,1,0.6])
                with c1:
                    home = st.number_input("Home", min_value=1.0, step=0.1,
                                           value=parse_float(od.get("home_win"), 1.0),
                                           key=f"od_h_{mid}", disabled=not is_admin)
                with c2:
                    draw = st.number_input("Draw", min_value=1.0, step=0.1,
                                           value=parse_float(od.get("draw"), 1.0),
                                           key=f"od_d_{mid}", disabled=not is_admin)
                with c3:
                    away = st.number_input("Away", min_value=1.0, step=0.1,
                                           value=parse_float(od.get("away_win"), 1.0),
                                           key=f"od_a_{mid}", disabled=not is_admin)
                with c4:
                    submitted = st.form_submit_button("保存", disabled=not is_admin, use_container_width=True)

                if submitted and is_admin:
                    row = {
                        "gw": gw,
                        "match_id": mid,
                        "home": m["home"],
                        "away": m["away"],
                        "home_win": str(home),
                        "draw": str(draw),
                        "away_win": str(away),
                        "locked": "",
                        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
                    }
                    upsert_row("odds", row, key_cols=["match_id", "gw"])
                    st.success("保存しました。")
                    st.rerun()

# ------------------------------------------------------------
# メイン
# ------------------------------------------------------------
def main():
    conf = get_conf()

    me = login_ui(conf)
    if not me:
        st.stop()

    tabs = st.tabs(["トップ", "試合とベット", "履歴", "リアルタイム", "ダッシュボード", "オッズ管理"])

    with tabs[0]:
        page_home(conf, me)
    with tabs[1]:
        page_matches_and_bets(conf, me)
    with tabs[2]:
        page_history(conf, me)
    with tabs[3]:
        page_realtime(conf, me)
    with tabs[4]:
        page_dashboard(conf, me)
    with tabs[5]:
        page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
