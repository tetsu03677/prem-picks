# /pages/02_Bets.py
from __future__ import annotations
import streamlit as st
from typing import List, Dict, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google_sheets_client import (
    get_config_value, set_config_value, list_bets, upsert_bet_record, now_jst_str
)
from football_api import fetch_upcoming_pl_matches, pick_matchday_block

JST = ZoneInfo("Asia/Tokyo")
st.set_page_config(page_title="試合とベット", page_icon="🎯", layout="centered")

# ------- guard & nav -------
if "user" not in st.session_state:
    st.switch_page("app.py")
user = st.session_state["user"]
username = user["username"]
role = user.get("role","user")

# 簡易ナビ
cols = st.columns([1,1,1,1,1,1])
with cols[0]: st.page_link("app.py", label="🏠 トップ", use_container_width=True)
with cols[1]: st.page_link("pages/02_Bets.py", label="🎯 試合とベット", use_container_width=True)
with cols[2]: st.page_link("pages/03_History.py", label="📜 履歴", use_container_width=True)
with cols[3]: st.page_link("pages/04_Realtime.py", label="⏱ リアルタイム", use_container_width=True)
with cols[4]: st.page_link("pages/05_Rules.py", label="📘 ルール", use_container_width=True)
with cols[5]:
    if role=="admin":
        st.page_link("pages/01_Settings.py", label="🛠 設定", use_container_width=True)
    else:
        st.write("")

# ------- config -------
current_gw = get_config_value("current_gw","GW7")
bookmaker = get_config_value("bookmaker_username","Tetsu")
lock_minutes = int(get_config_value("lock_minutes_before_earliest","120") or "120")
max_total = int(get_config_value("max_total_stake_per_gw","5000") or "5000")
step = int(get_config_value("stake_step","100") or "100")

st.markdown(f"### {current_gw} ベット入力")
st.caption(f"ブックメーカー：{bookmaker} / 一括ロック：最初のKOの {lock_minutes} 分前 / 上限：1節合計 {max_total} / 刻み：{step}")

if username == bookmaker:
    st.error(f"{current_gw} はあなたがブックメーカー役のため、ベットできません。")
    st.stop()

# ------- fixtures from API (no persist) -------
try:
    matches = fetch_upcoming_pl_matches(days_ahead=21)
except Exception as e:
    st.error(f"試合データ取得に失敗：{e}")
    st.stop()

# target block pick（current_gw, fallback to next）
block = pick_matchday_block(current_gw, matches)

# 一括ロック判定（ブロック内の最初のKO基準）
def parse_jst(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    except Exception:
        return None

lock_time = None
if block:
    first_ko = min(parse_jst(m["kickoff_jst"]) for m in block if m.get("kickoff_jst"))
    if first_ko:
        lock_time = first_ko - timedelta(minutes=lock_minutes)

gw_locked = False
if lock_time:
    gw_locked = datetime.now(JST) >= lock_time

# ロック済みの場合は、次のマッチデーブロックを自動選択（表示だけ切替）
display_block = block
display_gw = current_gw
if gw_locked:
    st.warning("このGWはロック済みのため、次のゲームウィークに切り替えています。", icon="🔒")
    # 次のMD探し
    try:
        curr_num = int(current_gw.replace("GW","").strip())
    except Exception:
        curr_num = None
    if curr_num is not None:
        # 次のMDブロックを取得
        next_block = pick_matchday_block(f"GW{curr_num+1}", matches)
        if next_block:
            display_block = next_block
            display_gw = f"GW{curr_num+1}"
        else:
            display_block = []  # 表示できる次GWが無い
    else:
        display_block = []

if not display_block:
    st.info("表示できる試合が見つかりません。少し時間を置いてお試しください。")
    st.stop()

# 既存の自分のベット合計（display_gwで集計）
my_bets = [b for b in list_bets(user=username, gw=display_gw)]
already_total = sum(int(b.get("stake") or 0) for b in my_bets)
st.info(f"あなたの {display_gw} 合計ステーク：{already_total} / 残り：{max(0, max_total - already_total)}")
if lock_time and not gw_locked:
    st.caption(f"{current_gw} の一括ロック：{lock_time.strftime('%Y-%m-%d %H:%M')} JST")

# 画面
for m in display_block:
    mid = str(m.get("id"))
    home = m.get("home")
    away = m.get("away")
    ko_txt = m.get("kickoff_jst")

    st.markdown(f"#### {home}  vs  {away}")
    st.caption(f"🕒 {ko_txt} JST | Match ID: {mid} | GW: {display_gw}")

    pick_key = f"pick-{display_gw}-{username}-{mid}"
    stake_key = f"stake-{display_gw}-{username}-{mid}"

    # 既存ベットの復元
    prev = next((b for b in my_bets if b.get("match_id")==mid), None)
    pick_default = {"Home":0,"Draw":1,"Away":2}.get((prev or {}).get("pick","Home"), 0)
    cols = st.columns([2,1,1,1])
    pick = cols[0].radio("予想", ["Home","Draw","Away"], index=pick_default, key=pick_key, horizontal=True, disabled=False)
    stake_val = int((prev or {}).get("stake") or 0)
    stake = cols[1].number_input("掛金", min_value=0, max_value=max_total, step=step, value=stake_val, key=stake_key)

    # オッズは外部API依存にせず、入力/編集式（確定保存）
    odds_val = float((prev or {}).get("odds") or 0.0)
    odds = cols[2].number_input("オッズ", min_value=0.0, step=0.01, value=odds_val, key=f"odds-{display_gw}-{username}-{mid}")
    cols[3].metric("参考", odds if odds>0 else 0.0)

    st.divider()

# 保存処理
if st.button("保存（このGWのベットを記録）", type="primary", use_container_width=True):
    # 上限チェック（差分追加のみ加算）
    new_total = already_total
    to_save: List[Dict[str, Any]] = []
    for m in display_block:
        mid = str(m.get("id"))
        home = m.get("home"); away = m.get("away")
        pick = st.session_state.get(f"pick-{display_gw}-{username}-{mid}")
        stake = int(st.session_state.get(f"stake-{display_gw}-{username}-{mid}") or 0)
        odds  = float(st.session_state.get(f"odds-{display_gw}-{username}-{mid}") or 0.0)
        if stake <= 0 or odds <= 0:
            continue
        prev = next((b for b in my_bets if b.get("match_id")==mid), None)
        prev_stake = int((prev or {}).get("stake") or 0)
        add = max(0, stake - prev_stake)
        if new_total + add > max_total:
            st.error(f"上限超過：{home} vs {away} の入力で {max_total} を超えます。")
            to_save = []
            break
        rec = {
            "key": f"{display_gw}|{username}|{mid}",
            "gw": display_gw,
            "user": username,
            "match_id": mid,
            "match": f"{home} vs {away}",
            "pick": pick,
            "stake": stake,
            "odds": odds,
            "placed_at": now_jst_str(),
            "status": "OPEN",
            "result": "",
            "payout": "",
            "net": "",
            "settled_at": "",
        }
        to_save.append(rec)
        new_total += add

    if to_save:
        for r in to_save:
            upsert_bet_record(r)
        st.success(f"{len(to_save)} 件保存しました。")
        st.rerun()
