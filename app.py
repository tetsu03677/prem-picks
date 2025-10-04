# app.py
import json
from datetime import datetime, timedelta, timezone
import pytz
import streamlit as st

from google_sheets_client import read_rows_by_sheet, upsert_row, read_config, now_str
from football_api import fetch_matches_next_gw, fetch_matches_window
from ui_parts import pill, section_header, muted, kpi, tag

APP_TITLE = "Premier Picks"
st.set_page_config(page_title=APP_TITLE, page_icon="⚽", layout="wide")

# ---------- helpers ----------
def get_conf():
    rows = read_config()
    conf = {r["key"]: r["value"] for r in rows}
    # safety defaults
    conf.setdefault("timezone", "Asia/Tokyo")
    conf.setdefault("current_gw", "GW0")
    conf.setdefault("lock_minutes_before_earliest", "120")
    conf.setdefault("max_total_stake_per_gw", "5000")
    conf.setdefault("stake_step", "100")
    conf.setdefault("FOOTBALL_DATA_COMPETITION", "PL")
    conf.setdefault("API_FOOTBALL_SEASON", "2025")
    return conf

def get_users(conf):
    try:
        users = json.loads(conf.get("users_json","[]"))
        assert isinstance(users, list)
        return users
    except Exception:
        return [{"username":"guest","password":"", "role":"user","team":"-"}]

def tzaware(dt_utc, tzname):
    tz = pytz.timezone(tzname)
    return dt_utc.astimezone(tz)

def gw_lock_threshold(matches_utc, lock_minutes):
    # GW全体の最初の試合のキックオフの lock_minutes 前
    if not matches_utc:
        return None
    first_kick = min(m["utc_kickoff"] for m in matches_utc)
    return first_kick - timedelta(minutes=int(lock_minutes))

def total_stake_used(bets, gw, user):
    return sum(int(b["stake"]) for b in bets if b.get("gw")==gw and b.get("user")==user)

def ensure_auth(conf):
    st.markdown(f"### {APP_TITLE}")
    users = get_users(conf)

    # セッション保持
    if "me" not in st.session_state:
        st.session_state.me = None

    if st.session_state.me:
        return st.session_state.me  # 既ログイン

    if users and users[0].get("username") == "guest" and conf.get("users_json","").strip()=="":
        st.warning("config の users_json が空です。※一時的に guest のみ表示しています。", icon="⚠️")

    usernames = [u["username"] for u in users]
    col = st.container()
    with col:
        user = st.selectbox("ユーザー", usernames, index=0, key="login_user")
        pwd = st.text_input("パスワード", type="password")
        if st.button("ログイン", use_container_width=True):
            user_obj = next((u for u in users if u["username"]==user), None)
            if user_obj and user_obj.get("password","")==pwd:
                st.session_state.me = user_obj
                st.success("ログインしました。")
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います。")
    st.stop()

def odds_row_default(gw, match_id, home, away):
    return {
        "gw": gw, "match_id": str(match_id), "home": home, "away": away,
        "home_win": "", "draw": "", "away_win": "",
        "locked": "", "updated_at": now_str()
    }

def read_odds_map_by_match_id():
    odds = read_rows_by_sheet("odds")
    out = {}
    for r in odds:
        out[str(r.get("match_id"))] = r
    return out

def simplify_matches(raw, tzname):
    tz = pytz.timezone(tzname)
    out=[]
    for m in raw:
        out.append({
            "id": str(m["id"]),
            "gw": m["gw"],
            "home": m["home"],
            "away": m["away"],
            "status": m["status"],
            "utc_kickoff": m["utc_kickoff"],
            "local_kickoff": m["utc_kickoff"].astimezone(tz),
        })
    return out

# ---------- pages ----------
def page_home(me):
    section_header("トップ")
    muted("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
    st.write(f"ログイン中： **{me['username']} ({me.get('role','user')})**")

def page_matches_and_bets(conf, me):
    section_header("試合とベット")
    # 次節取得（7日以内 / なければ「7日以内に次節はありません」）
    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("**7日以内に次節はありません。**")
        return

    tzname = conf.get("timezone","Asia/Tokyo")
    matches = simplify_matches(matches_raw, tzname)

    # GWロック：最初の試合の2時間前固定（configのlock_minutes_before_earliest）
    lock_thr = gw_lock_threshold([m for m in matches], conf.get("lock_minutes_before_earliest","120"))
    locked = datetime.utcnow().replace(tzinfo=timezone.utc) >= lock_thr if lock_thr else False
    st.write(tag("OPEN" if not locked else "LOCKED", "success" if not locked else "danger"),
             muted(f" このGWのあなたの投票合計: {total_stake_used(read_rows_by_sheet('bets'), gw, me['username'])} / 上限 {conf.get('max_total_stake_per_gw','5000')}"))

    odds_map = read_odds_map_by_match_id()
    bets = read_rows_by_sheet("bets")

    for m in matches:
        with st.container(border=True):
            st.markdown(f"**{m['gw']}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')}")
            st.markdown(f"**{m['home']}** vs {m['away']}")
            # オッズ
            o = odds_map.get(m["id"]) or odds_row_default(gw, m["id"], m["home"], m["away"])
            if not (o["home_win"] and o["draw"] and o["away_win"]):
                st.info("オッズ未入力のため **仮オッズ (=1.0)** を表示中。管理者は『オッズ管理』で設定してください。")

            home_odds = float(o["home_win"] or 1.0)
            draw_odds = float(o["draw"] or 1.0)
            away_odds = float(o["away_win"] or 1.0)
            st.write(muted(f"Home: {home_odds:.2f} ・ Draw: {draw_odds:.2f} ・ Away: {away_odds:.2f}"))

            # 既存ベット
            my_existing = next((b for b in bets if b.get("gw")==gw and b.get("user")==me["username"] and b.get("match_id")==m["id"]), None)
            cur_pick = (my_existing or {}).get("pick", "AWAY")
            cur_stake = int((my_existing or {}).get("stake", conf.get("stake_step","100")))
            st.write(muted(f"現在のベット状況：HOME {0} / DRAW {0} / AWAY {0}"))

            # 入力（ユニークキーで DuplicateWidgetID を回避）
            pick = st.radio("ピック", options=["HOME","DRAW","AWAY"],
                            index=["HOME","DRAW","AWAY"].index(cur_pick),
                            horizontal=True, key=f"pick_{m['id']}")
            step = int(conf.get("stake_step","100"))
            stake = st.number_input("ステーク", min_value=step, max_value=int(conf.get("max_total_stake_per_gw","5000")),
                                    value=cur_stake, step=step, key=f"stake_{m['id']}", label_visibility="visible")

            col_b1, col_b2 = st.columns([1,1])
            if col_b1.button("この内容でベット", key=f"bet_{m['id']}", disabled=locked):
                # 上限チェック
                used = total_stake_used(bets, gw, me["username"]) - (int(my_existing["stake"]) if my_existing else 0)
                if used + stake > int(conf.get("max_total_stake_per_gw","5000")):
                    st.error("このGWの上限を超えます。")
                else:
                    odds_used = {"HOME":home_odds,"DRAW":draw_odds,"AWAY":away_odds}[pick]
                    row = {
                        "key": f"{gw}-{me['username']}-{m['id']}",
                        "gw": gw,
                        "user": me["username"],
                        "match_id": m["id"],
                        "match": f"{m['home']} vs {m['away']}",
                        "pick": pick,
                        "stake": str(stake),
                        "odds": f"{odds_used:.2f}",
                        "placed_at": now_str(),
                        "status": "OPEN",
                        "result": "",
                        "payout": "",
                        "net": "",
                        "settled_at": ""
                    }
                    upsert_row("bets", "key", row)
                    st.success("ベットを記録しました。")
                    st.rerun()

            if col_b2.button("ベットを取り消す", key=f"del_{m['id']}", disabled=(locked or my_existing is None)):
                upsert_row("bets", "key", {"key": f"{gw}-{me['username']}-{m['id']}", "_delete": True})
                st.success("ベットを取り消しました。")
                st.rerun()

def page_history(me):
    section_header("履歴")
    bets = read_rows_by_sheet("bets")
    my = [b for b in bets if b.get("user")==me["username"]]
    if not my:
        st.info("まだ履歴がありません。")
        return
    # 表示用
    cols = st.columns([2,2,1,1,1,1,1,1])
    headers = ["GW","試合","ピック","Stake","Odds","Result","Payout","Net"]
    for c,h in zip(cols,headers): c.write(f"**{h}**")
    for b in sorted(my, key=lambda x: (x.get("gw",""), x.get("match",""))):
        c = st.columns([2,2,1,1,1,1,1,1])
        c[0].write(b.get("gw",""))
        c[1].write(b.get("match",""))
        c[2].write(b.get("pick",""))
        c[3].write(b.get("stake",""))
        c[4].write(b.get("odds",""))
        c[5].write(b.get("result",""))
        c[6].write(b.get("payout",""))
        c[7].write(b.get("net",""))

def page_realtime(conf):
    section_header("リアルタイム")
    st.caption("※自動更新は行いません。必要なときに『最新化』を押してください。")
    if st.button("最新化", type="primary"):
        st.rerun()

    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7, accept_today=True, include_live=True)
    if not matches_raw:
        st.info("対象期間に試合はありません。")
        return

    tzname = conf.get("timezone","Asia/Tokyo")
    matches = simplify_matches(matches_raw, tzname)
    odds_map = read_rows_by_sheet("odds")
    odds_by_id = {str(o["match_id"]):o for o in odds_map}
    bets = read_rows_by_sheet("bets")

    # 試合ごとの時点収支（読み取り計算）
    for m in matches:
        with st.container(border=True):
            st.markdown(f"**{m['gw']}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')} ・ 状態：{m['status']}")
            st.markdown(f"**{m['home']}** vs {m['away']}")
            o = odds_by_id.get(m["id"], {})
            home_odds = float(o.get("home_win") or 1.0)
            draw_odds = float(o.get("draw") or 1.0)
            away_odds = float(o.get("away_win") or 1.0)
            st.write(muted(f"Home {home_odds:.2f} / Draw {draw_odds:.2f} / Away {away_odds:.2f}"))

            # ここでは実スコアをAPIから持ってきて判定…（簡易：LIVE/TIMEDは未確定, FINISHEDは確定）
            tbl = []
            for b in [x for x in bets if x.get("match_id")==m["id"]]:
                stake = int(b.get("stake","0") or 0)
                pick = b.get("pick")
                odds_used = {"HOME":home_odds,"DRAW":draw_odds,"AWAY":away_odds}[pick]
                payout_est = stake * odds_used if m["status"] in ("FINISHED","IN_PLAY","PAUSED") and pick else 0.0
                tbl.append((b["user"], pick, stake, odds_used, payout_est))
            if tbl:
                col = st.columns([2,1,1,1,1])
                for w,h in zip(col,["User","Pick","Stake","Odds","Est.Payout"]): w.write(f"**{h}**")
                for r in tbl:
                    c = st.columns([2,1,1,1,1])
                    for i,v in enumerate(r): c[i].write(v)
            else:
                st.write(muted("ベットはまだありません。"))

def page_odds_admin(conf, me):
    if me.get("role")!="admin":
        st.info("管理者のみアクセスできます。")
        return
    section_header("オッズ管理")
    matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    if not matches_raw:
        st.info("7日以内に次節はありません。")
        return
    tzname = conf.get("timezone","Asia/Tokyo")
    matches = simplify_matches(matches_raw, tzname)
    odds_map = read_odds_map_by_match_id()

    for m in matches:
        with st.container(border=True):
            st.markdown(f"**{m['gw']}** ・ {m['local_kickoff'].strftime('%m/%d %H:%M')}")
            st.markdown(f"**{m['home']}** vs {m['away']}")
            o = odds_map.get(m["id"]) or odds_row_default(m["gw"], m["id"], m["home"], m["away"])
            col1, col2, col3 = st.columns(3)
            hv = col1.number_input("Home", value=float(o["home_win"] or 1.0), step=0.01, key=f"h_{m['id']}")
            dv = col2.number_input("Draw", value=float(o["draw"] or 1.0), step=0.01, key=f"d_{m['id']}")
            av = col3.number_input("Away", value=float(o["away_win"] or 1.0), step=0.01, key=f"a_{m['id']}")
            if st.button("保存", key=f"save_{m['id']}"):
                row = {
                    "gw": m["gw"], "match_id": m["id"], "home": m["home"], "away": m["away"],
                    "home_win": f"{hv:.2f}", "draw": f"{dv:.2f}", "away_win": f"{av:.2f}",
                    "locked": "", "updated_at": now_str()
                }
                upsert_row("odds","match_id",row)
                st.success("保存しました。")
                st.rerun()

def page_dashboard(conf):
    section_header("ダッシュボード")
    bets = read_rows_by_sheet("bets")
    if not bets:
        st.info("データがまだありません。")
        return

    # KPI（読み取り計算）
    total_stake = sum(int(b.get("stake","0") or 0) for b in bets)
    total_payout = sum(float(b.get("payout") or 0) for b in bets if b.get("payout"))
    total_net = sum(float(b.get("net") or 0) for b in bets if b.get("net"))

    c1,c2,c3,c4 = st.columns(4)
    kpi(c1, "総投票額", f"{int(total_stake):,}")
    kpi(c2, "総払戻", f"{total_payout:,.0f}")
    kpi(c3, "総損益", f"{total_net:,.0f}")
    kpi(c4, "ブックメーカー役", conf.get("bookmaker_username","-"))

    st.markdown("#### ユーザー別損益（当GW・暫定）")
    gw = conf.get("current_gw","")
    gw_bets = [b for b in bets if b.get("gw")==gw]
    if gw_bets:
        users = {}
        for b in gw_bets:
            u = b["user"]
            stake = int(b.get("stake","0") or 0)
            net = float(b.get("net") or 0)
            users.setdefault(u, {"stake":0,"net":0})
            users[u]["stake"] += stake
            users[u]["net"] += net
        cc = st.columns([2,1,1])
        for w,h in zip(cc,["User","Stake","Net"]): w.write(f"**{h}**")
        for u,rec in sorted(users.items(), key=lambda x: x[1]["net"], reverse=True):
            c = st.columns([2,1,1]); c[0].write(u); c[1].write(rec["stake"]); c[2].write(f"{rec['net']:.0f}")
    else:
        st.write(muted("当GWのデータなし。"))

    st.markdown("#### ユーザーごとの『得意チーム』ランキング（通算）")
    # pick=HOME/DRAW/AWAY のとき、「予想チーム」は HOMEならhomeチーム、AWAYならawayチーム、DRAWは除外
    best = {}  # user -> list of (team, played, win_rate, net)
    for b in bets:
        if b.get("result") not in ("WIN","LOSE"):
            continue
        if b.get("pick")=="DRAW":
            continue
        team = (b["match"].split(" vs ")[0] if b["pick"]=="HOME" else b["match"].split(" vs ")[1])
        user = b["user"]
        won = 1 if b["result"]=="WIN" else 0
        net = float(b.get("net") or 0)
        best.setdefault(user, {})
        rec = best[user].setdefault(team, {"played":0,"win":0,"net":0.0})
        rec["played"] += 1
        rec["win"] += won
        rec["net"] += net

    cols = st.columns([2,3])
    for user, teams in best.items():
        rows=[]
        for t, r in teams.items():
            win_rate = r["win"]/r["played"] if r["played"] else 0
            rows.append((t, r["played"], f"{win_rate:.0%}", f"{r['net']:.0f}"))
        rows.sort(key=lambda x: (float(x[2].strip('%')), float(x[3])), reverse=True)
        with st.expander(f"{user} の得意チーム TOP5"):
            c = st.columns([2,1,1,1])
            for w,h in zip(c,["Team","試行","勝率","損益"]): w.write(f"**{h}**")
            for r in rows[:5]:
                cc = st.columns([2,1,1,1])
                for i,v in enumerate(r): cc[i].write(v)

# ---------- main ----------
def main():
    conf = get_conf()
    me = ensure_auth(conf)

    tabs = st.tabs(["🏠 トップ","🎯 試合とベット","📁 履歴","⏱️ リアルタイム","📊 ダッシュボード","🛠 オッズ管理"])
    with tabs[0]: page_home(me)
    with tabs[1]: page_matches_and_bets(conf, me)
    with tabs[2]: page_history(me)
    with tabs[3]: page_realtime(conf)
    with tabs[4]: page_dashboard(conf)
    with tabs[5]: page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
