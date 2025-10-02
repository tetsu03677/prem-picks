# app.py  --- 直近のプレミア日程表示 + Googleシート接続テスト
from __future__ import annotations
import streamlit as st
from football_api import get_pl_fixtures_next_days
from google_sheets_client import append_bet, upsert_bet
from datetime import datetime

st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="centered")

st.title("Premier Picks")
st.subheader("直近のプレミア日程（本物データ）")

days = st.slider("何日先まで表示するか", 3, 14, 10)

# ===== 試合表示 =====
try:
    fixtures = get_pl_fixtures_next_days(days)
    if not fixtures:
        st.info("期間内に予定された試合が見つかりませんでした。")
    else:
        for f in fixtures:
            # ここは f は必ず辞書。キー欠損も考慮して安全に表示
            md = f.get("matchday", "?")
            ko = f.get("kickoff_jst", "?")
            home = f.get("home", "?")
            away = f.get("away", "?")
            st.markdown(f"**GW {md}**　{ko}（JST）　{home} vs {away}")
except Exception as e:
    st.error(
        "試合データの取得に失敗しました。Secretsの設定をご確認ください。\n\n"
        f"詳細: {e}"
    )

st.divider()

# ===== Googleスプレッドシート接続テスト（既存のまま） =====
st.caption("Googleスプレッドシート接続テスト（追記＆上書き）")

colA, colB = st.columns(2)
with colA:
    if st.button("追記テスト（append）", type="primary"):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            append_bet(
                gw="GW7",
                match="Arsenal vs West",
                user="Tetsu",
                bet_team="Home",
                stake=100,
                odds=1.90,
                timestamp=ts,
            )
            st.success("Googleシートに追記しました！Driveで確認してください。")
        except Exception as e:
            st.error(f"追記に失敗: {e}")

with colB:
    if st.button("上書きテスト（upsert）"):
        try:
            upsert_bet(
                key_cols={"gw": "GW7", "user": "Tetsu"},
                update_cols={
                    "match": "Arsenal vs West",
                    "bet_team": "Home",
                    "stake": 200,
                    "odds": 1.95,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            st.success("同じキーの行を上書きしました！")
        except Exception as e:
            st.error(f"上書きに失敗: {e}")
