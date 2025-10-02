# /pages/03_History.py
from __future__ import annotations
import streamlit as st
import pandas as pd
from google_sheets_client import list_bets, list_results

st.set_page_config(page_title="履歴", page_icon="📜", layout="centered")

if "user" not in st.session_state:
    st.switch_page("app.py")

user = st.session_state["user"]
username = user["username"]

st.markdown("### 履歴")
bets = list_bets(user=username)
if not bets:
    st.info("まだベット履歴がありません。")
    st.stop()

results = list_results()  # {(gw, match_id): result}
rows = []
total_stake = 0
total_return = 0
for b in bets:
    gw = b.get("gw")
    mid = b.get("match_id")
    pick = (b.get("pick") or "").upper()
    stake = float(b.get("stake") or 0)
    odds = float(b.get("odds") or 0)
    total_stake += stake

    res = results.get((gw, mid))
    status = "未確定"
    ret = 0.0
    if res:
        if res[0:1].upper() == pick[0:1]:
            ret = stake * odds
            status = "的中"
        else:
            ret = 0.0
            status = "ハズレ"
        total_return += ret

    rows.append({
        "GW": gw,
        "試合": b.get("match"),
        "選択": b.get("pick"),
        "ステーク": int(stake),
        "オッズ": odds,
        "結果": res if res else "-",
        "払戻": int(ret) if ret else 0,
        "確定": status,
        "日時": b.get("timestamp"),
    })

st.metric("総ステーク", f"{int(total_stake)}")
st.metric("総払戻", f"{int(total_return)}")
st.metric("損益", f"{int(total_return - total_stake)}")

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)
