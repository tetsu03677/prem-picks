# app.py
# --- Premier Picks (single-file main app) ---
# 要件:
# - ログイン: config.users_json からプルダウン。UIはシンプル。
# - タブ: トップ / 試合とベット / 履歴 / リアルタイム / ダッシュボード / オッズ管理(管理者のみ)
# - オッズ/ベットのロックは「当GWの最初の試合のキックオフ2時間前(=config.odds_freeze_minutes_before_first)」
# - ロック後は「次GW」を7日先までで探索して表示。無ければ「7日以内に次節はありません」
# - Football-Data API のトークンは config シートから読む（Secrets 非依存）
# - Google Sheets 連携は Secrets の service account と sheet_id を使用（従来通り）
# - DuplicateWidgetID を避けるため、全ウィジェットに match_id を含む key を付与

import json
from datetime import datetime, timedelta, timezone
from dateutil import tz
import streamlit as st

from google_sheets_client import read_config, read_rows_by_sheet, upsert_row
from football_api import (
    fetch_matches_current_gw,
    fetch_matches_next_gw,
    simplify_matches,
    compute_gw_lock_threshold,
    fetch_match_snapshots_by_ids,
)

APP_TITLE = "Premier Picks"

# --- Page config は一番最初に ---
st.set_page_config(page_title=APP_TITLE, page_icon="⚽", layout="wide")

# ---------- Utility ----------
def get_conf() -> dict:
    rows = read_config()
    conf = {r["key"]: str(r["value"]).strip() for r in rows if r.get("key")}
    # デフォルト
    conf.setdefault("timezone", "Asia/Tokyo")
    conf.setdefault("current_gw", "GW1")
    conf.setdefault("odds_freeze_minutes_before_first", "120")
    conf.setdefault("max_total_stake_per_gw", "5000")
    conf.setdefault("stake_step", "100")
    conf.setdefault("FOOTBALL_DATA_COMPETITION", "PL")  # 'PL' でも '2021' でもOK
    conf.setdefault("FOOTBALL_DATA_SEASON", "2025")
    return conf


def parse_users(conf: dict):
    raw = conf.get("users_json", "").strip()
    try:
        users = json.loads(raw) if raw else []
        assert isinstance(users, list)
        return users
    except Exception:
        return []


def get_tz(conf: dict):
    return tz.gettz(conf.get("timezone", "Asia/Tokyo"))


def money(n: float) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return "0"


# ---------- Auth ----------
def ensure_auth(conf: dict):
    if "user" in st.session_state and st.session_state["user"]:
        return st.session_state["user"]

    users = parse_users(conf)
    if not users:
        # フォールバック: guest のみ
        users = [{"username": "guest", "password": "", "role": "user", "team": "-"}]
        st.warning("config の users_json が空または不正です。暫定的に guest のみ表示しています。")

    st.markdown("### Premier Picks")
    with st.container():
        col1, col2 = st.columns([2, 1])
        with col1:
            name = st.selectbox(
                "ユーザー",
                options=[u["username"] for u in users],
                index=0,
                key="login_username",
            )
            pwd = st.text_input("パスワード", type="password", key="login_password")
            if st.button("ログイン", use_container_width=True):
                user = next((u for u in users if u["username"] == name), None)
                if user and (user.get("password", "") == pwd):
                    st.session_state["user"] = user
                    st.success(f"ようこそ {name} さん！")
                    st.rerun()
                else:
                    st.error("ユーザー名またはパスワードが違います。")
    st.stop()


def logout_button():
    with st.sidebar:
        if st.button("ログアウト", type="secondary"):
            st.session_state.pop("user", None)
            st.rerun()


# ---------- Sheets helpers ----------
def read_odds_for_gw(gw: str):
    odds_rows = read_rows_by_sheet("odds")
    return [r for r in odds_rows if str(r.get("gw", "")).strip() == gw]


def read_bets_for_gw(gw: str):
    bets_rows = read_rows_by_sheet("bets")
    return [r for r in bets_rows if str(r.get("gw", "")).strip() == gw]


def upsert_bet(
    gw: str,
    username: str,
    match_id: str,
    match_label: str,
    pick: str,
    stake: int,
    odds_value: float,
):
    key = f"{gw}-{match_id}-{username}"
    upsert_row(
        sheet_name="bets",
        key_col="key",
        key_val=key,
        row_dict={
            "key": key,
            "gw": gw,
            "user": username,
            "match_id": str(match_id),
            "match": match_label,
            "pick": pick,
            "stake": int(stake),
            "odds": float(odds_value),
            "placed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            # 以下は読み取り計算派なので基本空欄のまま
            "status": "",
            "result": "",
            "payout": "",
            "net": "",
            "settled_at": "",
        },
    )


def upsert_odds(gw: str, match_id: str, home: str, away: str, h: float, d: float, a: float, locked: bool):
    upsert_row(
        sheet_name="odds",
        key_col="match_id",
        key_val=str(match_id),
        row_dict={
            "gw": gw,
            "match_id": str(match_id),
            "home": home,
            "away": away,
            "home_win": float(h),
            "draw": float(d),
            "away_win": float(a),
            "locked": "1" if locked else "0",
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
    )


# ---------- Pages ----------
def page_home(me):
    st.subheader("トップ")
    st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
    st.caption(f"ログイン中：**{me['username']}** ({me.get('role','user')})")


def _load_current_or_next_matches(conf, tzinfo, me):
    """現在のGW（ロック前）または、ロック済なら次GWを返す。"""
    # 現在GWの候補を取得（最大7日先）
    matches_raw, gw = fetch_matches_current_gw(conf, day_window=7)
    matches = simplify_matches(matches_raw, tzinfo)

    if not matches:
        # そもそも7日以内に試合が無い
        return [], gw, None, True

    lock_threshold = compute_gw_lock_threshold(matches, conf, tzinfo)
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    is_locked = (now_utc >= lock_threshold) if lock_threshold else False

    if not is_locked:
        return matches, gw, lock_threshold, False

    # ロック後 → 次GW（7日先まで）を探す
    next_raw, next_gw = fetch_matches_next_gw(conf, day_window=7)
    next_matches = simplify_matches(next_raw, tzinfo)
    if not next_matches:
        return [], next_gw, None, True
    next_lock = compute_gw_lock_threshold(next_matches, conf, tzinfo)
    return next_matches, next_gw, next_lock, False


def page_matches_and_bets(conf, me):
    st.subheader("試合とベット")
    tzinfo = get_tz(conf)

    # GW試合リストの決定（ロック判定を含む）
    matches, gw, lock_threshold, no_gw = _load_current_or_next_matches(conf, tzinfo, me)

    # ユーザーの当GW投票合計
    bets_rows_all = read_rows_by_sheet("bets")
    my_gw_bets = [b for b in bets_rows_all if b.get("gw") == gw and b.get("user") == me["username"]]
    my_total = sum(int(b.get("stake", 0) or 0) for b in my_gw_bets)
    max_total = int(conf.get("max_total_stake_per_gw", "5000") or 5000)
    st.caption(f"このGWのあなたの投票合計: **{money(my_total)}** / 上限 **{money(max_total)}** （残り **{money(max_total - my_total)}**）")

    if no_gw:
        st.info("7日以内に次節はありません。")
        return

    # ロック表示（GW 全体で1箇所だけ）
    if lock_threshold:
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        locked = now >= lock_threshold
        st.success("OPEN", icon="✅") if not locked else st.error("LOCKED", icon="🔒")
        st.caption(f"ロック基準時刻（最初の試合の {conf.get('odds_freeze_minutes_before_first','120')} 分前・UTC基準）：{lock_threshold.isoformat()}")

    # 当GWのオッズ行を読み込み
    odds_rows = read_odds_for_gw(gw)
    odds_by_id = {str(r.get("match_id")): r for r in odds_rows}

    # 試合カード
    for m in matches:
        mid = str(m["id"])
        home = m["home"]
        away = m["away"]
        kickoff_local = m["local_kickoff"]
        status = m["status"]
        gw_label = m.get("gw", gw)

        card = st.container(border=True)
        with card:
            st.markdown(f"**{gw_label}** ・ {kickoff_local.strftime('%m/%d %H:%M')}")
            # タイトル（ホーム太字・やや大きめ）
            st.markdown(f"<div style='font-size:1.05rem'><b>{home}</b> vs {away}</div>", unsafe_allow_html=True)

            # オッズ
            o = odds_by_id.get(mid, {})
            h = float(o.get("home_win", 1) or 1)
            d = float(o.get("draw", 1) or 1)
            a = float(o.get("away_win", 1) or 1)
            show_temp = (o == {})
            if show_temp:
                st.info("オッズ未入力のため仮オッズ(=1.0) を表示中。管理者は『オッズ管理』で設定してください。")
            st.caption(f"Home: {h:.2f} ・ Draw: {d:.2f} ・ Away: {a:.2f}")

            # 現在のベット集計（他ユーザー含む）
            match_bets = [b for b in bets_rows_all if b.get("gw")==gw and str(b.get("match_id"))==mid]
            sum_home = sum(int(b.get("stake",0) or 0) for b in match_bets if (b.get("pick")=="HOME"))
            sum_draw = sum(int(b.get("stake",0) or 0) for b in match_bets if (b.get("pick")=="DRAW"))
            sum_away = sum(int(b.get("stake",0) or 0) for b in match_bets if (b.get("pick")=="AWAY"))
            st.caption(f"現在のベット状況： HOME {money(sum_home)} / DRAW {money(sum_draw)} / AWAY {money(sum_away)}")

            # ロック判定（GWベース）
            gw_locked = False
            if lock_threshold:
                gw_locked = datetime.utcnow().replace(tzinfo=timezone.utc) >= lock_threshold

            # 既存ベット（自分）
            my_bet = next((b for b in match_bets if b.get("user")==me["username"]), None)
            default_pick = my_bet.get("pick") if my_bet else "HOME"
            default_stake = int(my_bet.get("stake", conf.get("stake_step","100")) or 0) if my_bet else int(conf.get("stake_step","100") or 100)

            # ピック
            pick = st.radio(
                "ピック",
                options=["HOME", "DRAW", "AWAY"],
                index=["HOME","DRAW","AWAY"].index(default_pick) if default_pick in ("HOME","DRAW","AWAY") else 0,
                horizontal=True,
                key=f"pick_{mid}",
                disabled=gw_locked,
            )
            # ステーク
            stake = st.number_input(
                "ステーク",
                step=int(conf.get("stake_step","100") or 100),
                min_value=0,
                value=max(0, default_stake),
                key=f"stake_{mid}",
                disabled=gw_locked,
            )

            # 送信
            if st.button("この内容でベット", key=f"bet_{mid}", disabled=gw_locked):
                # 上限チェック（当GWトータル）
                already = sum(int(b.get("stake",0) or 0) for b in my_gw_bets if b.get("match_id")!=mid)
                if already + int(stake) > max_total:
                    st.error("当GWの投票合計が上限を超えます。ステークを調整してください。")
                else:
                    upsert_bet(
                        gw=gw,
                        username=me["username"],
                        match_id=mid,
                        match_label=f"{home} vs {away}",
                        pick=pick,
                        stake=int(stake),
                        odds_value=h if pick=="HOME" else d if pick=="DRAW" else a,
                    )
                    st.success("ベットを記録しました！")
                    st.rerun()


def _calc_result_from_score(score_dict):
    """Football-Data v4 の score から 'HOME' | 'DRAW' | 'AWAY' | '' を返す"""
    try:
        ft = score_dict.get("fullTime") or {}
        h = ft.get("home")
        a = ft.get("away")
        if h is None or a is None:
            return ""
        if h > a:
            return "HOME"
        if a > h:
            return "AWAY"
        return "DRAW"
    except Exception:
        return ""


def page_history(conf, me):
    st.subheader("履歴")
    # bets から存在する GW を拾って選択
    all_bets = read_rows_by_sheet("bets")
    gw_list = sorted(list({b.get("gw","") for b in all_bets if b.get("gw")}), key=lambda x: (len(x), x))
    if not gw_list:
        st.info("まだベット履歴がありません。")
        return
    gw = st.selectbox("ゲームウィークを選択", options=gw_list, index=len(gw_list)-1)
    bets = [b for b in all_bets if b.get("gw")==gw]

    if not bets:
        st.info("選択したGWのベットはありません。")
        return

    # 対象試合のスコアを取得 → 読み取り計算で payout/net を算出
    ids = list({str(b.get("match_id")) for b in bets if b.get("match_id")})
    snapshots = fetch_match_snapshots_by_ids(conf, ids)
    snap_by_id = {str(s["id"]): s for s in snapshots}

    # 集計
    rows = []
    total_net_by_user = {}
    for b in bets:
        mid = str(b.get("match_id"))
        snap = snap_by_id.get(mid, {})
        result = _calc_result_from_score(snap.get("score", {})) if snap else ""
        won = (result == b.get("pick")) if result else None  # None=未確定
        stake = int(b.get("stake",0) or 0)
        odds_val = float(b.get("odds",1) or 1)

        payout = stake * odds_val if won else (0 if won is not None else None)
        net = (payout - stake) if won is not None else None

        rows.append({
            "user": b.get("user"),
            "match": b.get("match"),
            "pick": b.get("pick"),
            "stake": stake,
            "odds": odds_val,
            "result": result or "-",
            "payout": "" if payout is None else int(payout),
            "net": "" if net is None else int(net),
        })
        if net is not None:
            total_net_by_user[b.get("user")] = total_net_by_user.get(b.get("user"), 0) + int(net)

    st.write("### ユーザー別損益（確定分）")
    if total_net_by_user:
        st.table({u: money(v) for u, v in sorted(total_net_by_user.items(), key=lambda x: -x[1])})
    else:
        st.caption("まだ確定した試合がありません。")

    st.write("### 明細（読み取り計算）")
    st.dataframe(rows, use_container_width=True)


def page_realtime(conf, me):
    st.subheader("リアルタイム（手動更新）")
    tzinfo = get_tz(conf)

    # 現在GWを取得（ロック有無に関わらず「今節」）
    current_raw, gw = fetch_matches_current_gw(conf, day_window=7)
    matches = simplify_matches(current_raw, tzinfo)
    if not matches:
        st.info("7日以内に対象試合がありません。")
        return

    # 手動更新ボタン
    if st.button("更新", icon="🔄"):
        st.rerun()

    # このGWの bets と スコア
    ids = [str(m["id"]) for m in matches]
    snaps = fetch_match_snapshots_by_ids(conf, ids)
    snap_by_id = {str(s["id"]): s for s in snaps}
    bets = read_bets_for_gw(gw)

    # 試合単位の時点損益
    user_pnl = {}
    match_rows = []
    for m in matches:
        mid = str(m["id"])
        s = snap_by_id.get(mid, {})
        score = s.get("score", {})
        status = s.get("status", m.get("status"))

        # 現在の暫定勝敗
        res = _calc_result_from_score(score)

        # この試合のベット
        bs = [b for b in bets if str(b.get("match_id")) == mid]
        sum_by_pick = {"HOME":0, "DRAW":0, "AWAY":0}
        for b in bs:
            pick = b.get("pick")
            stake = int(b.get("stake",0) or 0)
            odds_val = float(b.get("odds",1) or 1)
            sum_by_pick[pick] = sum_by_pick.get(pick,0) + stake

            # 暫定損益
            if res:
                won = (pick == res)
                pnl = stake * (odds_val - 1) if won else -stake
                user_pnl[b.get("user")] = user_pnl.get(b.get("user"), 0) + pnl

        match_rows.append({
            "kickoff": m["local_kickoff"].strftime("%m/%d %H:%M"),
            "match": f"{m['home']} vs {m['away']}",
            "status": status,
            "score_ft": f"{(score.get('fullTime') or {}).get('home','-')} - {(score.get('fullTime') or {}).get('away','-')}",
            "now_pot_HOME": sum_by_pick["HOME"],
            "now_pot_DRAW": sum_by_pick["DRAW"],
            "now_pot_AWAY": sum_by_pick["AWAY"],
            "provisional_result": res or "-",
        })

    st.write("### 試合別（現在）")
    st.dataframe(match_rows, use_container_width=True)

    st.write("### ユーザー別（現在の暫定損益）")
    if user_pnl:
        st.table({u: money(int(v)) for u, v in sorted(user_pnl.items(), key=lambda x: -x[1])})
    else:
        st.caption("まだ暫定損益はありません。")


def page_dashboard(conf, me):
    st.subheader("ダッシュボード")
    # 全 bets を読み、確定済みを Football-Data の最終スコアで読み取り計算
    all_bets = read_rows_by_sheet("bets")
    # 対象試合のスナップショット
    ids = list({str(b.get("match_id")) for b in all_bets if b.get("match_id")})
    snaps = fetch_match_snapshots_by_ids(conf, ids)
    snap_by_id = {str(s["id"]): s for s in snaps}

    total_net_by_user = {}
    team_hit_by_user = {}  # {user: {team: {"count":x,"net":y}}}

    for b in all_bets:
        mid = str(b.get("match_id"))
        s = snap_by_id.get(mid, {})
        result = _calc_result_from_score(s.get("score", {})) if s else ""
        if not result:
            continue  # 確定のみKPI
        pick = b.get("pick")
        stake = int(b.get("stake",0) or 0)
        odds_val = float(b.get("odds",1) or 1)
        won = (pick == result)
        net = stake * (odds_val - 1) if won else -stake

        user = b.get("user")
        total_net_by_user[user] = total_net_by_user.get(user, 0) + int(net)

        # チーム別 当たりランキング
        # 試合情報（team は pick側のチーム名とする）
        match_label = b.get("match", "")
        # "HomeTeam vs AwayTeam" -> pick側チーム名を抽出
        team = None
        if " vs " in match_label:
            home, away = match_label.split(" vs ", 1)
            team = home if pick=="HOME" else away if pick=="AWAY" else "DRAW"
        team_hit_by_user.setdefault(user, {})
        team_hit_by_user[user].setdefault(team, {"count":0, "net":0})
        team_hit_by_user[user][team]["count"] += 1
        team_hit_by_user[user][team]["net"] += int(net)

    c1, c2 = st.columns(2)
    with c1:
        st.write("#### 通算損益（確定分）")
        if total_net_by_user:
            st.table({u: money(v) for u, v in sorted(total_net_by_user.items(), key=lambda x: -x[1])})
        else:
            st.caption("まだ確定データがありません。")

    with c2:
        st.write("#### あなたの当たりやすいチーム（Top5）")
        mine = team_hit_by_user.get(me["username"], {})
        if not mine:
            st.caption("まだ実績がありません。")
        else:
            top = sorted(mine.items(), key=lambda x: (-x[1]["net"], -x[1]["count"]))[:5]
            st.table([{ "team": t or "-", "bets": v["count"], "net": money(v["net"]) } for t, v in top])


def page_odds_admin(conf, me):
    st.subheader("オッズ管理（管理者）")
    if me.get("role") != "admin":
        st.warning("管理者のみ利用できます。")
        return

    tzinfo = get_tz(conf)
    matches, gw, lock_threshold, no_gw = _load_current_or_next_matches(conf, tzinfo, me)

    if no_gw:
        st.info("7日以内に編集対象のGWがありません。")
        return

    gw_locked = False
    if lock_threshold:
        gw_locked = datetime.utcnow().replace(tzinfo=timezone.utc) >= lock_threshold

    st.caption(f"対象GW: {gw}")
    st.success("OPEN", icon="✅") if not gw_locked else st.error("LOCKED", icon="🔒")
    if gw_locked:
        st.caption("ロック中は編集できません。")

    # 既存オッズ
    odds_by_id = {str(o.get("match_id")): o for o in read_odds_for_gw(gw)}

    for m in matches:
        mid = str(m["id"])
        home = m["home"]
        away = m["away"]

        with st.container(border=True):
            st.markdown(f"**{home}** vs {away}")
            old = odds_by_id.get(mid, {})
            h = st.number_input("Home", min_value=1.0, step=0.01, value=float(old.get("home_win", 1) or 1), key=f"odd_h_{mid}", disabled=gw_locked)
            d = st.number_input("Draw", min_value=1.0, step=0.01, value=float(old.get("draw", 1) or 1), key=f"odd_d_{mid}", disabled=gw_locked)
            a = st.number_input("Away", min_value=1.0, step=0.01, value=float(old.get("away_win", 1) or 1), key=f"odd_a_{mid}", disabled=gw_locked)

            if st.button("保存", key=f"save_{mid}", disabled=gw_locked):
                upsert_odds(gw, mid, home, away, h, d, a, locked=gw_locked)
                st.success("保存しました！")
                st.rerun()


# ---------- Main ----------
def main():
    conf = get_conf()
    me = ensure_auth(conf)
    logout_button()

    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱️ リアルタイム", "📊 ダッシュボード", "🛠 オッズ管理"])
    with tabs[0]:
        page_home(me)
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
