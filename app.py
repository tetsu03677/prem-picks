# app.py — Premier Picks (final, stable)
# ※他ファイルは変更不要。既存モジュールとの整合を保った最小確実修正版。
# - ログイン後はフォーム非表示
# - ヘッダ見切れ解消（安全な最小CSS）
# - 既存タブ構成とUIは固定（見た目はスタイリッシュ/最小）

from __future__ import annotations
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any

import requests
import streamlit as st

# 既存モジュール（変更不要）
from google_sheets_client import read_rows_by_sheet, read_rows, read_config, upsert_row
from football_api import fetch_matches_next_gw  # 7日で次GW取得（既存実装を利用）

# ===== ページ設定 =====
st.set_page_config(page_title="Premier Picks", layout="wide")

# ===== 最小限の安全CSS（ヘッダ非表示はしない）=====
st.markdown("""
<style>
.block-container { padding-top: 1.0rem; padding-bottom: 2rem; }
.pp-login-card { padding: 1rem 1rem 0.5rem 1rem; border: 0; background: transparent; }
h1 + .stAlert { margin-top: 0.5rem; }
.kpi { display:flex; gap:1rem; flex-wrap:wrap; }
.kpi > div { padding: 0.75rem 1rem; border: 1px solid var(--secondary-background-color);
             border-radius: 8px; min-width: 140px; text-align: center; }
.kpi .v { font-size: 1.4rem; font-weight: 700; }
.badge { display:inline-block; padding: .1rem .5rem; border-radius: .5rem;
         background: var(--secondary-background-color); }
.card { border: 1px solid var(--secondary-background-color); border-radius: 10px; padding: 1rem; }
.dim { color: var(--text-color); opacity: .75; }
hr.soft { border:none; height:1px; background: var(--secondary-background-color); margin: .75rem 0; }
</style>
""", unsafe_allow_html=True)


# ===== ユーティリティ =====
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def parse_users(conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = conf.get("users_json", "") or conf.get("users", "")
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []

def gw_sort_key(gw: str) -> Tuple[int, str]:
    """'GW7' -> (7, 'GW7')、'7' -> (7,'7')、その他は(999,原文)"""
    if gw is None:
        return (999, "")
    s = str(gw)
    m = re.search(r"(\d+)", s)
    if m:
        return (int(m.group(1)), s)
    return (999, s)

def money(v: Any) -> str:
    try:
        n = float(v)
    except Exception:
        return "0"
    if n.is_integer():
        return f"{int(n):,}"
    return f"{n:,.2f}"

def read_conf() -> Dict[str, Any]:
    conf_rows = read_config()  # Google Sheet 'config' -> [{key, value}, ...]
    conf = {}
    for r in conf_rows:
        k = r.get("key")
        v = r.get("value")
        if k:
            conf[k] = v
    # 使い勝手用の別名
    conf["users"] = parse_users(conf)
    return conf

def read_bets() -> List[Dict[str, Any]]:
    return read_rows_by_sheet("bets") or []

def read_odds() -> List[Dict[str, Any]]:
    return read_rows_by_sheet("odds") or []

def odds_for_match(odds_rows: List[Dict[str, Any]], mid: str) -> Dict[str, Any]:
    for r in odds_rows:
        if str(r.get("match_id", "")) == str(mid):
            return r
    return {}

def current_user() -> Dict[str, Any] | None:
    return st.session_state.get("me")

def logout_button():
    me = current_user()
    if me:
        if st.button("ログアウト", key="logout_btn"):
            st.session_state.pop("me", None)
            st.rerun()


# ===== 認証UI（ログイン後は出さない） =====
def render_login(conf: Dict[str, Any]):
    if current_user():
        return

    users = parse_users(conf)
    usernames = [u.get("username", "") for u in users] or ["guest"]

    with st.container():
        st.markdown('<div class="pp-login-card">', unsafe_allow_html=True)
        st.subheader("Premier Picks")
        user = st.selectbox("ユーザー", usernames, index=0, key="login_user_select")
        pwd = st.text_input("パスワード", type="password", key="login_pwd_input")
        if st.button("ログイン", use_container_width=True, key="login_btn"):
            target = next((u for u in users if u.get("username") == user), None)
            if target and pwd == target.get("password"):
                st.session_state["me"] = {
                    "username": target["username"],
                    "role": target.get("role", "user"),
                    "team": target.get("team", ""),
                }
                st.success(f"ようこそ {target['username']} さん！")
                st.rerun()
            else:
                st.warning("ユーザー名またはパスワードが違います。")
        st.markdown('</div>', unsafe_allow_html=True)


# ====== ページ：トップ ======
def page_home(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("トップ")
    st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
    st.markdown(f"<span class='dim'>ログイン中： <b>{me.get('username','')}</b> ({me.get('role','user')})</span>", unsafe_allow_html=True)
    st.write("")
    logout_button()


# ====== ページ：試合とベット ======
def page_matches_and_bets(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("試合とベット")

    # 次GWの試合をAPIから（7日窓）
    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)  # 既存実装
    if not matches_raw:
        st.warning("試合データの取得に失敗しました（HTTP 403 など）。直近の試合が出ない場合は後でもう一度お試しください。")
        st.markdown("<div class='card dim'>7日以内に表示できる試合がありません。</div>", unsafe_allow_html=True)
        return

    # ロック判定（GW内の最初の試合の 2 時間前で固定）
    earliest_utc = None
    for m in matches_raw:
        k = m.get("utc_kickoff")
        if isinstance(k, datetime):
            if earliest_utc is None or k < earliest_utc:
                earliest_utc = k
    lock_minutes = int(conf.get("lock_minutes_before_earliest", 120))
    locked = False
    if earliest_utc:
        locked = now_utc() >= (earliest_utc - timedelta(minutes=lock_minutes))

    st.markdown(
        f"<div class='card'>"
        f"<span class='badge'>{gw or ''}</span>　"
        f"{'🔒 LOCKED' if locked else '🟢 OPEN'}"
        f"　<small class='dim'>（最初の試合の {lock_minutes} 分前でロック）</small>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.write("")

    odds_rows = read_odds()
    bets_rows = read_bets()

    # 1ユーザーあたりGW上限管理 & すでに自分が賭けている分
    mine = [b for b in bets_rows if b.get("user") == me.get("username")]
    my_tot_this_gw = sum(float(b.get("stake", 0) or 0) for b in mine if (str(b.get("gw","")) == str(gw)))
    max_total = float(conf.get("max_total_stake_per_gw", 5000) or 5000)
    step = int(conf.get("stake_step", 100) or 100)

    st.markdown(
        f"<div class='card dim'>このGWのあなたの投票合計: <b>{money(my_tot_this_gw)}</b> / 上限 <b>{money(max_total)}</b> "
        f"（残り <b>{money(max_total - my_tot_this_gw)}</b>）</div>",
        unsafe_allow_html=True,
    )

    # 各試合カード
    for m in matches_raw:
        mid = str(m.get("id"))
        home = m.get("home") or m.get("homeTeam") or ""
        away = m.get("away") or m.get("awayTeam") or ""
        local_kick = m.get("local_kickoff") or m.get("utc_kickoff")

        st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
        with st.container():
            st.markdown(
                f"<div class='card'><span class='badge'>{gw or ''}</span>　"
                f"{local_kick}　"
                f"<b>{home}</b> vs <b>{away}</b></div>",
                unsafe_allow_html=True,
            )

            # オッズ（未入力なら仮=1.0を表示）
            o = odds_for_match(odds_rows, mid)
            oh = float(o.get("home_win") or 1.0)
            od = float(o.get("draw") or 1.0)
            oa = float(o.get("away_win") or 1.0)
            if (o.get("home_win") is None) and (o.get("draw") is None) and (o.get("away_win") is None):
                st.info("オッズ未入力のため仮オッズ(=1.0)を表示中。管理者は「オッズ管理」で設定してください。")

            st.markdown(f"<span class='dim'>Home: {oh:.2f} ・ Draw: {od:.2f} ・ Away: {oa:.2f}</span>", unsafe_allow_html=True)

            # すでに自分が賭けている内容
            my_bet = next((b for b in bets_rows if b.get("user")==me.get("username") and str(b.get("match_id"))==mid), None)
            current_txt = ""
            if my_bet:
                current_txt = f"{my_bet.get('pick','')} {money(my_bet.get('stake',0))}"
            st.markdown(f"<div class='dim'>現在のベット状況： {current_txt or 'HOME 0 / DRAW 0 / AWAY 0'}</div>", unsafe_allow_html=True)

            # ピックとステーク（ログインユーザーのみ、ロック後は編集不可）
            cols = st.columns([1,1,1,2])
            with cols[0]:
                default_pick = (my_bet or {}).get("pick") or "HOME"
                pick = st.radio(
                    "ピック", options=["HOME","DRAW","AWAY"],
                    index=["HOME","DRAW","AWAY"].index(default_pick),
                    horizontal=True, key=f"pick_{mid}",
                    disabled=locked
                )
            with cols[1]:
                default_stake = int((my_bet or {}).get("stake") or step)
                stake = st.number_input("ステーク", min_value=step, max_value=int(max_total),
                                        step=step, value=default_stake, key=f"stake_{mid}",
                                        disabled=locked)
            with cols[2]:
                st.write("") ; st.write("")
                if st.button("この内容でベット", key=f"bet_{mid}", disabled=locked):
                    new_total = my_tot_this_gw - float((my_bet or {}).get("stake",0)) + float(stake)
                    if new_total > max_total + 1e-9:
                        st.warning("このGWの上限を超えています。")
                    else:
                        # bets へ upsert
                        payload = {
                            "key": f"{gw}:{me.get('username')}:{mid}",
                            "gw": gw,
                            "user": me.get("username"),
                            "match_id": mid,
                            "match": f"{home} vs {away}",
                            "pick": pick,
                            "stake": int(stake),
                            "odds": {"HOME": oh, "DRAW": od, "AWAY": oa}.get(pick, 1.0),
                            "placed_at": now_utc().strftime("%Y-%m-%d %H:%M:%S"),
                            "status": "OPEN",
                        }
                        upsert_row("bets", "key", payload)
                        st.success("ベットを保存しました。")
                        st.rerun()
            with cols[3]:
                pass


# ====== ページ：履歴 ======
def page_history(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("履歴")
    all_bets = read_bets()

    # 表示対象GWのプルダウン
    gw_set = sorted(list({str(b.get("gw","")) for b in all_bets if b.get("gw")}), key=gw_sort_key)
    if not gw_set:
        st.info("履歴がまだありません。")
        return

    gw = st.selectbox("表示するGW", gw_set, index=len(gw_set)-1, key="hist_gw")
    target = [b for b in all_bets if str(b.get("gw","")) == str(gw)]

    # 収支（確定済みフィールドがあれば使う／なければ 0）
    def row_view(b: Dict[str, Any]):
        u = b.get("user") or b.get("username") or "-"
        left = f"{b.get('match','')}"
        right = f"{b.get('pick','')} / {money(b.get('stake',0))}"
        st.markdown(f"- **{u}**：{left} → {right}")

    for b in target:
        row_view(b)

    # 参考：総ステーク/想定払戻はダッシュボードに集約しているので、ここは軽量の明細表示に留める


# ====== ページ：リアルタイム ======
def page_realtime(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("リアルタイム")
    st.caption("更新ボタンで最新スコアを手動取得。自動更新はしません。")

    # 試合（次GW）を取得
    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.warning("スコア取得対象の試合が見つかりません。")
        return

    # IDリスト
    match_ids = [str(m.get("id")) for m in matches_raw if m.get("id")]

    # 手動更新ボタン
    if st.button("スコアを更新", key="rt_update"):
        try:
            scores = fetch_scores_snapshot_via_api(conf, match_ids)
            st.session_state["scores_snapshot"] = scores
        except requests.HTTPError as e:
            # football-data はレートやプランで 403 が出やすい
            code = e.response.status_code if e.response is not None else 0
            st.warning(f"スコア取得に失敗（HTTP {code}）。再試行してください。")

    scores = st.session_state.get("scores_snapshot", {})

    # ベット & オッズ
    bets_rows = read_bets()
    odds_rows = read_odds()

    # KPI（GW内トータルの現在時点収支の概算表示：結果確定ではない）
    kpi = []
    users = sorted({b.get("user") for b in bets_rows if b.get("user")})
    for u in users:
        net = 0.0
        for b in bets_rows:
            if b.get("user") != u or str(b.get("gw","")) != str(gw):
                continue
            mid = str(b.get("match_id"))
            pick = b.get("pick")
            stake = float(b.get("stake", 0) or 0)
            o = odds_for_match(odds_rows, mid)
            oh = float(o.get("home_win") or 1.0)
            od = float(o.get("draw") or 1.0)
            oa = float(o.get("away_win") or 1.0)
            odds_map = {"HOME": oh, "DRAW": od, "AWAY": oa}
            # スコアから「現時点の勝ち側」を推定
            res = scores.get(mid, {})
            hsc = int(res.get("home",0))
            asc = int(res.get("away",0))
            winning = "DRAW" if hsc==asc else ("HOME" if hsc>asc else "AWAY")
            payout = stake * (odds_map.get(winning, 1.0) if pick==winning else 0)
            net += (payout - stake)
        kpi.append((u, net))

    if kpi:
        st.markdown("<div class='kpi'>", unsafe_allow_html=True)
        for u, v in kpi:
            st.markdown(f"<div><div class='dim'>{u}</div><div class='v'>{money(v)}</div></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # 試合ごとの現在状況
    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    for m in matches_raw:
        mid = str(m.get("id"))
        home = m.get("home") or m.get("homeTeam") or ""
        away = m.get("away") or m.get("awayTeam") or ""
        sc = scores.get(mid, {"home": 0, "away": 0, "status": "N/A"})
        st.markdown(f"**{home} {sc.get('home',0)} - {sc.get('away',0)} {away}**  <span class='dim'>({sc.get('status','')})</span>", unsafe_allow_html=True)

        # この試合に対する全ユーザーのベット一覧（盛り上げ用）
        bs = [b for b in bets_rows if str(b.get("match_id")) == mid]
        if not bs:
            st.caption("ベットなし")
            continue
        for b in bs:
            st.markdown(f"- {b.get('user')}: {b.get('pick')} / {money(b.get('stake',0))}")


# ===== 実スコアのスナップショット取得（football-data.org） =====
def fetch_scores_snapshot_via_api(conf: Dict[str, Any], match_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    必要最小のスコア取得。403は呼び出し側でハンドリング。
    """
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "")
    if not match_ids:
        return {}
    url = "https://api.football-data.org/v4/matches"
    params = {"ids": ",".join(match_ids)}
    headers = {"X-Auth-Token": token} if token else {}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    out = {}
    for m in (data.get("matches") or []):
        mid = str(m.get("id"))
        s = (m.get("score") or {})
        full = (s.get("fullTime") or {})
        # ライブ時は live score が別に載ることも。ここでは最も直近の値を拾う。
        home = full.get("home", s.get("halfTime", {}).get("home", 0)) or 0
        away = full.get("away", s.get("halfTime", {}).get("away", 0)) or 0
        status = m.get("status", "")
        out[mid] = {"home": int(home or 0), "away": int(away or 0), "status": status}
    return out


# ====== ページ：ダッシュボード ======
def page_dashboard(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("ダッシュボード")

    bets_rows = read_bets()

    total_stake = sum(float(b.get("stake",0) or 0) for b in bets_rows)
    # payout/net は確定処理時に書き込まれる前提。なければ 0。
    total_payout = sum(float(b.get("payout",0) or 0) for b in bets_rows)
    total_net = sum(float(b.get("net",0) or 0) for b in bets_rows)

    st.markdown("<div class='kpi'>", unsafe_allow_html=True)
    for title, val in [("総支出額", total_stake), ("トータル収入額", total_payout), ("トータル収支", total_net)]:
        st.markdown(f"<div><div class='dim'>{title}</div><div class='v'>{money(val)}</div></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # 各ユーザーの「的中率が高いチームTOP3」
    st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
    st.subheader("ユーザー別・相性の良いチームTOP3（暫定）")
    # payout/netがbetsに反映されている場合に意味を持つ。なければステーク勝率ベースの簡易推定。
    by_user_team = {}
    for b in bets_rows:
        u = b.get("user") or "-"
        m = b.get("match","")
        # チーム抽出（"Home vs Away" の Home 側/ Away 側に分けず、文字列上の pick 対象チーム名に簡易寄与）
        team = None
        if " vs " in m:
            home, away = m.split(" vs ", 1)
            team = home if b.get("pick") == "HOME" else (away if b.get("pick")=="AWAY" else "DRAW")
        else:
            team = m
        by_user_team.setdefault(u, {}).setdefault(team, {"bet":0.0, "payout":0.0, "win":0, "cnt":0})
        by_user_team[u][team]["bet"] += float(b.get("stake",0) or 0)
        by_user_team[u][team]["payout"] += float(b.get("payout",0) or 0)
        by_user_team[u][team]["cnt"] += 1
        # winカウント（確定時に result=WIN が入っていれば使う）
        if str(b.get("result","")).upper() == "WIN":
            by_user_team[u][team]["win"] += 1

    for u, teams in by_user_team.items():
        # 指標： (win率 or payout/bet) の合成でソート
        scored = []
        for t, agg in teams.items():
            cnt = max(1, agg["cnt"])
            wr = agg["win"]/cnt
            roi = (agg["payout"]/agg["bet"]) if agg["bet"] else 0
            score = 0.6*wr + 0.4*roi
            scored.append((score, t, wr, roi))
        scored.sort(reverse=True)
        top3 = scored[:3]
        st.markdown(f"**{u}**")
        if not top3:
            st.caption("データ不足")
            continue
        for _, t, wr, roi in top3:
            st.markdown(f"- {t}: 勝率 {wr:.0%}, ROI {roi:.0%}")


# ====== ページ：オッズ管理（管理者のみ） ======
def page_odds_admin(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("オッズ管理")
    st.caption("ロック機能は廃止。必要に応じていつでも更新可能。")

    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("編集対象の試合がありません。")
        return

    odds_rows = read_odds()
    for m in matches_raw:
        mid = str(m.get("id"))
        home = m.get("home") or ""
        away = m.get("away") or ""

        st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
        st.markdown(f"**{home} vs {away}**")

        o = odds_for_match(odds_rows, mid)
        oh = float(o.get("home_win") or 1.0)
        od = float(o.get("draw") or 1.0)
        oa = float(o.get("away_win") or 1.0)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            oh = st.number_input("Home", min_value=1.0, step=0.01, value=float(oh), key=f"adm_h_{mid}")
        with c2:
            od = st.number_input("Draw", min_value=1.0, step=0.01, value=float(od), key=f"adm_d_{mid}")
        with c3:
            oa = st.number_input("Away", min_value=1.0, step=0.01, value=float(oa), key=f"adm_a_{mid}")
        with c4:
            st.write("") ; st.write("")
            if st.button("保存", key=f"save_{mid}"):
                payload = {
                    "gw": gw, "match_id": mid,
                    "home": m.get("home",""), "away": m.get("away",""),
                    "home_win": float(oh), "draw": float(od), "away_win": float(oa),
                    "updated_at": now_utc().strftime("%Y-%m-%d %H:%M:%S"),
                }
                # 主キーは (gw, match_id) の想定。シート側は 'match_id' をキーにしてもOK。
                upsert_row("odds", "match_id", payload)
                st.success("保存しました。")


# ===== メイン =====
def main():
    conf = read_conf()

    # 1) ログインUI（未ログイン時のみ表示）
    render_login(conf)

    me = current_user()
    if not me:
        # 未ログイン：ここで終了（タブは描画しない）
        return

    # 2) ログイン後のタブ
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱️ リアルタイム", "📊 ダッシュボード", "🛠 オッズ管理"])
    with tabs[0]: page_home(conf, me)
    with tabs[1]: page_matches_and_bets(conf, me)
    with tabs[2]: page_history(conf, me)
    with tabs[3]: page_realtime(conf, me)
    with tabs[4]: page_dashboard(conf, me)
    with tabs[5]:
        if me.get("role") == "admin":
            page_odds_admin(conf, me)
        else:
            st.info("管理者のみがアクセスできます。")


if __name__ == "__main__":
    main()
