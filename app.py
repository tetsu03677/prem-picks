# prem-picks/app.py
import streamlit as st
from datetime import datetime
from football_api import get_pl_fixtures_next_days

st.set_page_config(page_title="Premier Picks", layout="centered")

st.title("Premier Picks")

# ==== 本物データ：直近のプレミア日程（7〜10日先まで） =========================
st.subheader("直近のプレミア日程（本物データ）", anchor=False)
col_l, col_r = st.columns([1,1])
with col_l:
    days = st.slider("何日先まで表示するか", 3, 14, 10)

fixtures = []
error_msg = None
try:
    fixtures = get_pl_fixtures_next_days(days)
except Exception as e:
    error_msg = f"試合データの取得に失敗しました: {e}"

if error_msg:
    st.error(error_msg)
elif not fixtures:
    st.info("表示できる試合がありません。")
else:
    for f in fixtures:
        with st.container(border=True):
            st.markdown(
                f"**GW {f.get('matchday','?')}** 　"
                f"{f['kickoff_jst']} 　"
                f"{f['homeTeam']}  vs  {f['awayTeam']}"
            )
# =============================================================================

st.caption("Googleスプレッドシート接続テスト（追記 & 上書き）")

st.write("①『追記テスト』で1行追加 → ②『上書きテスト』で同じキーを上書きします。")

try:
    from google_sheets_client import append_bet, upsert_bet
except Exception:
    st.error("google_sheets_client.py が見つかりません。先に追加/置き換えしてください。")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    if st.button("追記テスト（append）", type="primary", use_container_width=True):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            append_bet(
                gw="GW7",
                match="Arsenal vs West Ham",
                user="Tetsu",
                bet_team="Home",
                stake=100,
                odds=1.9,
                timestamp=ts
            )
            st.success("追記しました（bets に新しい行が追加）")
        except Exception as e:
            st.exception(e)

with col2:
    if st.button("上書きテスト（upsert）", use_container_width=True):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result = upsert_bet(
                gw="GW7",
                match="Arsenal vs West Ham",
                user="Tetsu",
                bet_team="Home",
                stake=500,  # ← ここが上書きされるか確認
                odds=1.9,
                timestamp=ts
            )
            st.success(f"アップサート完了（{result}）")
        except Exception as e:
            st.exception(e)
