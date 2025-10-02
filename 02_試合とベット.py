# /pages/02_試合とベット.py
from __future__ import annotations
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google_sheets_client import (
    read_config, list_fixtures, list_bets, upsert_bet
)

JST = ZoneInfo("Asia/Tokyo")
st.set_page_config(page_title="試合とベット", page_icon="🎯", layout="centered")

# ログイン必須
if "user" not in st.session_state:
    st.switch_page("app.py")
user = st.session_state["user"]
username = user["username"]

cfg = read_config()
gw = cfg.get("current_gw","GW7")
bm = cfg.get("bookmaker_username","Tetsu")
lock_minutes = int(cfg.get("lock_minutes_before_earliest","120"))
max_total = int(cfg.get("max_total_stake_per_gw","5000"))
step = int(cfg.get("stake_step","100"))

st.markdown(f"### {gw}  ベット入力")
st.caption(f"ブックメーカー：{bm} / ロック：最初のキックオフの {lock_minutes} 分前 / 上限：1節合計 {max_total} / 刻み：{step}")

# ブックメーカーはベット不可
if username == bm:
    st.error(f"{gw} はあなたがブックメーカー役のため、ベットできません。")
    st.stop()

fixtures = list_fixtures(gw)
if not fixtures:
    st.info("fixtures シートに対戦カードがありません。ヘッダ: gw, match_id, kickoff_jst, home_team, away_team, odds_home, odds_draw, odds_away")
    st.stop()

# 節の最初のKOを探す → 全体ロック時刻
def parse_dt(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    except Exception:
        return None

earliest = None
for f in fixtures:
    ko = parse_dt(str(f.get("kickoff_jst","")))
    if ko and (earliest is None or ko < earliest):
        earliest = ko
gw_locked = False
lock_time = None
if earliest:
    lock_time = earliest - timedelta(minutes=lock_minutes)
    gw_locked = datetime.now(JST) >= lock_time

# 既存の自分のベットを取得
my_bets = [b for b in list_bets(user=username) if b.get("gw")==gw]
my_by_mid = { (b.get("match_id") or ""): b for b in my_bets }
already_total = sum(int(b.get("stake") or 0) for b in my_bets)

# 入力
st.info(f"あなたの {gw} 現在の合計ステーク：{already_total} / 残り：{max(0, max_total - already_total)}")
if lock_time:
    st.caption(f"ベット締切（全体）：{lock_time.strftime('%Y-%m-%d %H:%M')} JST")

saved_records = []

for f in sorted(fixtures, key=lambda r: str(r.get("kickoff_jst",""))):
    mid = str(f.get("match_id","")).strip()
    ko_txt = str(f.get("kickoff_jst","")).strip()
    home = str(f.get("home_team","")).strip()
    away = str(f.get("away_team","")).strip()
    oh = float(f.get("odds_home") or 0.0)
    od = float(f.get("odds_draw") or 0.0)
    oa = float(f.get("odds_away") or 0.0)

    # 一括ロック（節全体）
    disabled_all = gw_locked

    st.markdown(f"#### {home}  vs  {away}")
    st.caption(f"🕒 {ko_txt} JST  |  Match ID: {mid}")
    cols = st.columns([2,1,1,1])
    pick_key = f"pick-{gw}-{username}-{mid}"
    stake_key= f"stake-{gw}-{username}-{mid}"

    prev = my_by_mid.get(mid, {})
    pick_default = {"Home":0,"Draw":1,"Away":2}.get(prev.get("pick","Home"), 0)

    pick = cols[0].radio("予想", ["Home","Draw","Away"], index=pick_default, key=pick_key, horizontal=True, disabled=disabled_all)
    stake_val = int(prev.get("stake") or 0)
    stake = cols[1].number_input("掛金", min_value=0, max_value=max_total, step=step, value=stake_val, key=stake_key, disabled=disabled_all)

    cols[2].metric("Home", oh)
    cols[3].metric("Draw/Away", max(od, oa))

    st.divider()

if st.button("保存（このGWのベットを記録）", type="primary", use_container_width=True, disabled=gw_locked):
    # 合計制限チェック
    new_total = already_total
    records_to_save = []
    for f in fixtures:
        mid = str(f.get("match_id","")).strip()
        home = str(f.get("home_team","")).strip()
        away = str(f.get("away_team","")).strip()
        oh = float(f.get("odds_home") or 0.0)
        od = float(f.get("odds_draw") or 0.0)
        oa = float(f.get("odds_away") or 0.0)

        pick = st.session_state.get(f"pick-{gw}-{username}-{mid}")
        stake = int(st.session_state.get(f"stake-{gw}-{username}-{mid}") or 0)
        if stake <= 0:
            continue

        # 既存の同試合分を除いた追加分だけ合算チェック
        prev = my_by_mid.get(mid, {})
        prev_stake = int(prev.get("stake") or 0)
        add = max(0, stake - prev_stake)
        if new_total + add > max_total:
            st.error(f"上限超過：{home} vs {away} の入力で {max_total} を超えます。")
            records_to_save = []
            break

        odds = {"Home": oh, "Draw": od, "Away": oa}.get(pick, 0.0)
        record = {
            "key": f"{gw}|{username}|{mid}",
            "gw": gw,
            "match_id": mid,
            "match": f"{home} vs {away}",
            "user": username,
            "pick": pick,
            "stake": int(stake),
            "odds": float(odds),
            "timestamp": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
        }
        records_to_save.append(record)
        new_total += add

    if records_to_save:
        for r in records_to_save:
            upsert_bet(r)
        st.success(f"{len(records_to_save)} 件保存しました。")
        st.experimental_rerun()
