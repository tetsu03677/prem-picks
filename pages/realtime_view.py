import streamlit as st

def render():
    st.markdown("<div class='pp-header'>⏱ リアルタイム</div>", unsafe_allow_html=True)
    st.info("リアルタイム照合は次段で実装（ライブスコアAPI連携）。\n\n現時点では直近ベットの一覧と、試合結果取り込みのプレースホルダーを表示予定です。")
