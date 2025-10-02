# prem-picks/app.py
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Premier Picks", layout="centered")
st.title("Premier Picks")
st.caption("Googleスプレッドシート接続テスト")

st.write("下のボタンを押すと、bets シートに1行追記します（成功したらメッセージが出ます）")

try:
    from google_sheets_client import append_bet
except Exception:
    st.error("google_sheets_client.py が見つかりません。先にリポジトリへ追加してください。")
    st.stop()

if st.button("書き込みテスト（betsに1行追加）", type="primary"):
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
        st.success("Googleシートに追記しました！Driveで確認してください。")
    except Exception as e:
        st.exception(e)
