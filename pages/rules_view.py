import streamlit as st

RULES_MD = """
### ルール（要点）
- 各GWでブックメーカー役の1名はベット不可  
- 最も早い試合の **キックオフ2時間前** で当GWのベットはロック  
- 掛金は **100円刻み（設定で変更可）**、節あたり上限あり  
- オッズはロック時点で確定

### 注意
- 実ベットではありません。ゲーム用途の非公式アプリです。
"""

def render():
    st.markdown("<div class='pp-header'>📘 ルール</div>", unsafe_allow_html=True)
    st.markdown(RULES_MD)
