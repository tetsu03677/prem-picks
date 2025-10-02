from __future__ import annotations
import streamlit as st
from football_api import get_pl_fixtures_next_days
from google_sheets_client import read_config_dict

st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="centered")
st.title("Premier Picks")
st.subheader("直近のプレミア日程（API＋トークンはconfigシートから取得）")

# ── 診断：configから読めたキーを表示（本番で邪魔なら消せます）
with st.expander("🔧 接続トラブル時の診断（読めたconfigキー）"):
    cfg = read_config_dict()
    keys = ", ".join(sorted(cfg.keys())) if cfg else "(空)"
    st.caption(f"configシートから読めたキー: {keys}")
    st.caption("※ シート名は小文字の config、1行目は key / value 推奨")

days = st.slider("何日先まで表示するか", 3, 14, 10)

try:
    fixtures = get_pl_fixtures_next_days(days)
except Exception as e:
    st.error(f"試合データの取得に失敗しました。{e}")
    st.stop()

if not fixtures:
    st.info("指定期間内の試合が見つかりませんでした。")
else:
    for f in fixtures:
        st.markdown(
            f"### {f.get('home')} vs {f.get('away')}\n"
            f"🕒 {f.get('kickoff_jst')} JST | GW: {f.get('matchday')} | ID: {f.get('id')}"
        )
        st.divider()
