import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any

import pandas as pd
import streamlit as st

from google_sheets_client import (
    read_config_map,
    read_sheet_as_df,
    upsert_bet_row,
)
from football_api import (
    fetch_matches_next_gw,
    calc_gw_lock_threshold,
    simplify_match_row,
)

APP_TITLE = "Premier Picks"

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def get_conf() -> Dict[str, str]:
    conf = read_config_map()  # {"key": "value"} 形式
    # 必須キーのデフォルト
    conf.setdefault("timezone", "Asia/Tokyo")
    conf.setdefault("lock_minutes_before_earliest", "120")
    conf.setdefault("max_total_stake_per_gw", "5000")
    conf.setdefault("stake_step", "100")
    return conf

def get_users(conf: Dict[str, str]) -> List[Dict[str, str]]:
    raw = conf.get("users_json", "").strip()
    if not raw:
        return [{"username": "guest", "password": "guest", "role": "user", "team": "-"}]
    try:
        data = json.loads(raw)
        # 想定フィールド: username/password/role/team
        norm = []
        for u in data:
            norm.append({
                "username": str(u.get("username", "")),
                "password": str(u.get("password", "")),
                "role": str(u.get("role", "user")),
                "team": str(u.get("team", "-")),
            })
        return norm
    except Exception:
        # 壊れている場合は安全にフォールバック
        return [{"username": "guest", "password": "guest", "role": "user", "team": "-"}]

def tz(conf: Dict[str, str]):
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(conf.get("timezone", "Asia/Tokyo"))
    except Exception:
        return timezone(timedelta(hours=9))  # JST 代替

def ensure_auth(conf: Dict[str, str]) -> Dict[str, str]:
    st.session_state.setdefault("me", None)

    users = get_users(conf)
    user_names = [u["username"] for u in users]

    st.title("Premier Picks")
    with st.container(border=True):
        st.caption("ログインしてください")
        ui_user = st.selectbox("ユーザー", options=user_names, index=0, key="login_user_select")
        ui_pass = st.text_input("パスワード", type="password", key="login_pass")
        login = st.button("ログイン", use_container_width=True)

        if login:
            user = next((u for u in users if u["username"] == ui_user), None)
            if user and ui_pass == user["password"]:
                st.session_state.me = user
                # experimental_rerun を使わずに、下行で軽く表示 & 以降の main が同一ランで続行
                st.success(f"ようこそ {user['username']} さん！")
            else:
                st.error("ユーザー名またはパスワードが違います。")

    return st.session_state.me

def my_total_stake_this_gw(bets_df: pd.DataFrame, gw: str, username: str) -> int:
    if bets_df.empty:
        return 0
    part = bets_df[(bets_df["gw"] == gw) & (bets_df["user"] == username)]
    try:
        return int(part["stake"].astype("Int64").fillna(0).sum())
    except Exception:
        return int(part["stake"].fillna(0).sum())

def odds_row_for(match_id: str, odds_df: pd.DataFrame) -> Dict[str, Any]:
    if odds_df.empty:
        return {}
    row = odds_df.loc[odds_df["match_id"] == match_id]
    if row.empty:
        return {}
    s = row.iloc[0].to_dict()
    return {
        "home_win": float(s.get("home_win", 1.0) or 1.0),
        "draw": float(s.get("draw", 1.0) or 1.0),
        "away_win": float(s.get("away_win", 1.0) or 1.0),
        "locked": str(s.get("locked", "") or "").lower() in ("1", "true", "yes"),
        "updated_at": s.get("updated_at", ""),
    }

def pretty_money(x: float) -> str:
    return f"{x:,.0f}"

# ------------------------------------------------------------
# Pages
# ------------------------------------------------------------

def page_home(conf: Dict[str, str], me: Dict[str, str]):
    st.subheader("トップ")
    st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")

    role = me.get("role", "user") if me else "guest"
    st.write(f"ログイン中：**{me.get('username', 'guest')}** ({role})")

def page_matches_and_bets(conf: Dict[str, str], me: Dict[str, str]):
    # データ読み込み
    odds_df = read_sheet_as_df("odds")  # 空なら columns だけ
    bets_df = read_sheet_as_df("bets")

    # 次節（7日以内）の試合
    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    matches = [simplify_match_row(r, conf) for r in matches_raw]

    # ロック閾値（GW最初の試合の2時間前）
    lock_minutes = int(conf.get("lock_minutes_before_earliest", "120"))
    lock_threshold_utc = calc_gw_lock_threshold(matches_raw, lock_minutes)
    tzinfo = tz(conf)
    lock_threshold_local = lock_threshold_utc.astimezone(tzinfo) if lock_threshold_utc else None
    locked = (datetime.now(tzinfo).astimezone(timezone.utc) >= lock_threshold_utc) if lock_threshold_utc else False

    # 残り上限
    max_total = int(conf.get("max_total_stake_per_gw", "5000"))
    my_used = my_total_stake_this_gw(bets_df, gw, me.get("username", "guest"))
    remaining = max(0, max_total - my_used)

    st.subheader("試合とベット")
    with st.container(border=True):
        st.markdown(
            f"このGWのあなたの投票合計: **{pretty_money(my_used)}** / 上限 **{pretty_money(max_total)}** "
            f"(残り **{pretty_money(remaining)}**)"
        )
        if lock_threshold_local:
            st.caption(
                f"ロック基準時刻（最初の試合の {lock_minutes} 分前・UTC基準）: "
                f"{lock_threshold_utc.isoformat()}"
            )

    if not matches:
        st.info("7日以内に次節はありません。")
        return

    # リストレンダリング
    for r in matches:
        mid = r["id"]
        home = r["home"]
        away = r["away"]
        gw_name = r["gw"]
        kickoff_local = r["local_kickoff"]
        kickoff_str = kickoff_local.strftime("%m/%d %H:%M")

        with st.container(border=True):
            st.markdown(f"**{gw_name}** ・ {kickoff_str}")
            st.markdown(f"**{home}** vs {away}")

            # オッズ
            o = odds_row_for(mid, odds_df)
            if not o:
                st.info("オッズ未入力のため仮オッズ(=1.0)を表示中。管理者は『オッズ管理』で設定してください。")
                oh, od, oa = 1.0, 1.0, 1.0
                row_locked = False
            else:
                oh, od, oa = o["home_win"], o["draw"], o["away_win"]
                row_locked = bool(o["locked"])
            st.caption(f"Home: {oh:.2f} ・ Draw: {od:.2f} ・ Away: {oa:.2f}")

            # 注記 (GW基準でロック)…試合単位の locked フラグは補助的に表示のみ
            if locked:
                st.error("LOCKED (GWロック中)")
            else:
                st.success("OPEN")

            # その試合に対する現状ベット集計（全員分）
            if not bets_df.empty:
                bb = bets_df[bets_df["match_id"].astype(str) == str(mid)]
                home_sum = int(bb[bb["pick"] == "HOME"]["stake"].fillna(0).sum()) if not bb.empty else 0
                draw_sum = int(bb[bb["pick"] == "DRAW"]["stake"].fillna(0).sum()) if not bb.empty else 0
                away_sum = int(bb[bb["pick"] == "AWAY"]["stake"].fillna(0).sum()) if not bb.empty else 0
                st.caption(f"現在のベット状況：HOME {home_sum} / DRAW {draw_sum} / AWAY {away_sum}")

            # 入力 UI（GWロック時は非活性）
            c1, c2 = st.columns([3, 2])
            with c1:
                # 既存ベットがあればデフォルトを合わせる
                my_row = None
                if not bets_df.empty:
                    q = (bets_df["match_id"].astype(str) == str(mid)) & (bets_df["user"] == me["username"])
                    rows = bets_df[q]
                    if not rows.empty:
                        my_row = rows.iloc[0].to_dict()

                default_pick = (my_row or {}).get("pick", "HOME")
                default_stake = int((my_row or {}).get("stake", conf.get("stake_step", "100")))

                pick = st.radio(
                    "ピック",
                    options=["HOME", "DRAW", "AWAY"],
                    index=["HOME", "DRAW", "AWAY"].index(default_pick) if default_pick in ["HOME","DRAW","AWAY"] else 0,
                    key=f"pick-{mid}",
                    horizontal=True,
                    disabled=locked,
                )
            with c2:
                step = int(conf.get("stake_step", "100"))
                stake = st.number_input(
                    "ステーク",
                    min_value=step,
                    step=step,
                    value=max(step, default_stake),
                    key=f"stake-{mid}",
                    disabled=locked,
                )

            disabled = locked or (stake > remaining and (not my_row))
            if st.button("この内容でベット", key=f"bet-{mid}", disabled=disabled):
                # 上限チェック（既存ベットの上書きは差分のみ考慮）
                new_total = my_used - (int((my_row or {}).get("stake", 0)) if my_row else 0) + stake
                if new_total > max_total:
                    st.warning("このGWのベット上限を超えます。ステークを見直してください。")
                else:
                    # 保存
                    payload = {
                        "gw": gw_name,
                        "user": me["username"],
                        "match_id": str(mid),
                        "match": f"{home} vs {away}",
                        "pick": pick,
                        "stake": int(stake),
                        "odds": {"HOME": oh, "DRAW": od, "AWAY": oa}[pick],
                        "placed_at": datetime.utcnow().isoformat(timespec="seconds"),
                        "status": "OPEN",
                        "result": "",
                        "payout": "",
                        "net": "",
                        "settled_at": "",
                    }
                    upsert_bet_row(payload)
                    st.success("ベットを記録しました！")
                    # 残表示を即時反映
                    st.experimental_rerun()

def _safe_get(d: Dict[str, Any], k: str, default=""):
    v = d.get(k, default)
    return "" if pd.isna(v) else v

def page_history(conf: Dict[str, str], me: Dict[str, str]):
    st.subheader("履歴")
    bets_df = read_sheet_as_df("bets")
    if bets_df.empty:
        st.info("まだベット履歴がありません。")
        return

    # 必要列を安全に文字列化
    bets = bets_df.fillna("").to_dict(orient="records")

    # GW の候補（文字列化後、長さ→文字列順で安定ソート）
    gw_set = {str(b.get("gw", "")).strip() for b in bets if b.get("gw")}
    gw_list = sorted(list(gw_set), key=lambda x: (len(x), x))
    sel = st.selectbox("表示するGW", gw_list, index=max(0, len(gw_list)-1))

    view = [b for b in bets if str(b.get("gw","")).strip() == sel]

    def row_view(b: Dict[str, Any]):
        left = _safe_get(b, "match")
        pick = _safe_get(b, "pick")
        right = f"{pretty_money(int(str(_safe_get(b,'stake') or 0) or 0))} at {_safe_get(b, 'odds')}"
        user = _safe_get(b, "user")  # ← 列名は user 固定
        st.markdown(f"- **{user}**：{left} → {pick} / {right}")

    for b in view:
        row_view(b)

def page_realtime(conf: Dict[str, str], me: Dict[str, str]):
    st.subheader("リアルタイム")
    st.caption("更新ボタンで最新スコアを手動取得。自動更新は行いません。")
    if st.button("スコアを更新"):
        st.experimental_rerun()

    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("現在リアルタイム対象のGWはありません。")
        return

    tzinfo = tz(conf)
    earliest = min([pd.to_datetime(m["utcDate"]) for m in matches_raw])
    latest = max([pd.to_datetime(m["utcDate"]) + pd.Timedelta(minutes=110) for m in matches_raw])
    now = datetime.now(timezone.utc)

    if not (earliest <= now <= latest):
        st.warning("まだリアルタイム期間ではありません。")
        return

    odds_df = read_sheet_as_df("odds")
    bets_df = read_sheet_as_df("bets")

    # 仮: football-data の 進行状況/スコアは簡易表示（詳細APIに差し替え可）
    for m in matches_raw:
        simple = simplify_match_row(m, conf)
        mid = simple["id"]
        home, away = simple["home"], simple["away"]
        status = m.get("status", "SCHEDULED")
        score = m.get("score", {})
        ft = score.get("fullTime", {}) or {}
        hgoals = ft.get("home", "")
        agoals = ft.get("away", "")

        with st.container(border=True):
            st.markdown(f"**{home}** vs **{away}** 　`{status}`　 スコア: {hgoals}-{agoals}")
            # その試合の全員の時点収支（IN_PLAY は引き分け扱いなどの仮ルールでもOK）
            if bets_df.empty:
                st.caption("まだベットがありません。")
                continue

            bb = bets_df[bets_df["match_id"].astype(str) == str(mid)]
            if bb.empty:
                st.caption("この試合のベットはありません。")
                continue

            # 暫定判定（IN_PLAY/TIMED は常に 0、FINISHED は確定）
            def payout_row(row) -> Tuple[float, float]:
                stake = float(row.get("stake", 0) or 0)
                odds = float(row.get("odds", 1.0) or 1.0)
                pick = str(row.get("pick", "DRAW"))
                if status == "FINISHED":
                    # 勝敗確定
                    if hgoals > agoals and pick == "HOME":
                        return odds * stake, (odds * stake) - stake
                    if hgoals < agoals and pick == "AWAY":
                        return odds * stake, (odds * stake) - stake
                    if hgoals == agoals and pick == "DRAW":
                        return odds * stake, (odds * stake) - stake
                    return 0.0, -stake
                else:
                    # 進行中・未開始: 0（参考値）
                    return 0.0, 0.0

            recs = bb.fillna("").to_dict(orient="records")
            rows = []
            for r in recs:
                payout, net = payout_row(r)
                rows.append({
                    "user": r.get("user", ""),
                    "pick": r.get("pick", ""),
                    "stake": int(float(r.get("stake", 0) or 0)),
                    "odds": float(r.get("odds", 1.0) or 1.0),
                    "provisional_payout": int(payout),
                    "provisional_net": int(net),
                })
            df = pd.DataFrame(rows)
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)

def page_dashboard(conf: Dict[str, str], me: Dict[str, str]):
    st.subheader("ダッシュボード")
    bets_df = read_sheet_as_df("bets")
    if bets_df.empty:
        st.info("データがありません。")
        return

    # KPI: 総ベット額 / 勝ち払い総額 / 純利益（確定分のみ）
    settled = bets_df[bets_df["status"].str.upper().eq("SETTLED")] if "status" in bets_df.columns else pd.DataFrame()
    if settled.empty:
        st.caption("まだ確定済みのベットはありません（リアルタイム/履歴はオープンベットも表示します）。")
        total_bet = int(bets_df["stake"].fillna(0).sum())
        st.metric("総ベット額（全期間）", pretty_money(total_bet))
    else:
        total_bet = int(settled["stake"].fillna(0).sum())
        total_payout = int(pd.to_numeric(settled["payout"], errors="coerce").fillna(0).sum())
        net = int(pd.to_numeric(settled["net"], errors="coerce").fillna(0).sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("確定・総ベット額", pretty_money(total_bet))
        c2.metric("確定・払い戻し", pretty_money(total_payout))
        c3.metric("確定・純利益", pretty_money(net))

    # ユーザー別・チーム勝敗予想が最も当たっているランキング（確定分）
    if not settled.empty:
        # 勝ち = net > 0 の件数/金額をチーム/ユーザーで集計
        settled["win_flag"] = pd.to_numeric(settled["net"], errors="coerce").fillna(0) > 0
        agg = (
            settled.groupby(["user", "match"])  # match列は「Home vs Away」
            .agg(
                wins=("win_flag", "sum"),
                total=("win_flag", "count"),
                net_sum=("net", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
            )
            .reset_index()
        )
        # どの「チームの試合」で勝率・利益が高いかをユーザー毎にピック
        def team_name_from_match(m: str) -> str:
            # シンプルに Home 側チーム名を代表に
            return m.split(" vs ")[0] if " vs " in m else m

        agg["team"] = agg["match"].apply(team_name_from_match)
        rank = (
            agg.groupby(["user", "team"])
            .agg(wins=("wins", "sum"), total=("total", "sum"), net_sum=("net_sum", "sum"))
            .reset_index()
        )
        rank["win_rate"] = (rank["wins"] / rank["total"]).fillna(0.0)
        rank = rank.sort_values(["win_rate", "net_sum"], ascending=[False, False])
        st.markdown("#### ユーザー別・得意チームランキング（確定）")
        st.dataframe(rank.head(20), use_container_width=True, hide_index=True)

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="⚽", layout="wide")
    conf = get_conf()

    # 認証
    me = ensure_auth(conf)
    if not me:
        st.stop()

    # タブ
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱️ リアルタイム", "📊 ダッシュボード"])
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

if __name__ == "__main__":
    main()
