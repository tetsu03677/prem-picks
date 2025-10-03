# app.py の先頭（他の import より先）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


import json
from datetime import datetime, timezone
import pytz
import streamlit as st
from streamlit_option_menu import option_menu

# 既存のシート接続ヘルパー（前に置いたもの）を利用
from google_sheets_client import read_config, ws

# -----------------------------
# ページ基本設定 & カスタムCSS
# -----------------------------
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")

_UI_CSS = """
<style>
/* 全体のベース */
:root{
  --pp-red:#E53935;
  --pp-red-weak:#fdeaea;
  --pp-ink:#111;
  --pp-muted:#6b7280;
  --pp-card:#ffffff0f; /* darkでもほんのり面 */
}

/* ヘッダー風タイトル */
.pp-header{
  font-weight:800;
  letter-spacing:.2px;
  font-size:clamp(22px,3.2vw,30px);
  margin: 4px 0 12px 0;
}

/* カード */
.pp-card{
  border-radius:14px;
  border:1px solid #ffffff1a;
  background: var(--pp-card);
  padding:16px 18px;
  box-shadow:0 6px 24px #00000014, 0 2px 8px #00000010;
}

/* プライマリボタン */
.stButton>button{
  background: var(--pp-red) !important;
  border: 0 !important;
  color: white !important;
  font-weight: 700;
  border-radius: 12px;
}
.stButton>button:hover{ filter:brightness(.95); }

/* 任意のバッジ */
.pp-badge{
  display:inline-block;
  padding:4px 10px;
  border-radius:999px;
  font-size:12px; font-weight:700;
  background:var(--pp-red-weak);
  color:var(--pp-ink);
  border:1px solid #e5e7eb33;
}

/* option-menu の行間を少し詰める */
div[role="tablist"] .nav-link{
  padding:8px 14px !important;
  border-radius:10px !important;
}
</style>
"""
st.markdown(_UI_CSS, unsafe_allow_html=True)

# -----------------------------
# 共通ユーティリティ
# -----------------------------
@st.cache_data(ttl=30, show_spinner=False)
def get_conf():
    """config シート（key / value）を dict で取得"""
    return read_config()

def app_tz():
    tzname = get_conf().get("timezone", "Asia/Tokyo")
    try:
        return pytz.timezone(tzname)
    except Exception:
        return pytz.timezone("Asia/Tokyo")

def now_ts():
    return datetime.now(tz=app_tz()).strftime("%Y-%m-%d %H:%M:%S")

def parse_users():
    raw = get_conf().get("users_json", "").strip()
    if not raw:
        # フォールバック（ゲストのみ）
        return [{"username":"guest", "password":"guest", "role":"guest", "team":"Neutral"}]
    try:
        users = json.loads(raw)
        return users
    except Exception:
        return [{"username":"guest", "password":"guest", "role":"guest", "team":"Neutral"}]

def login_box():
    st.write("### サインイン")
    users = parse_users()
    usernames = [u["username"] for u in users]
    u = st.selectbox("ユーザーを選択", usernames, index=0)
    p = st.text_input("パスワード", type="password")
    col1, col2 = st.columns([1,1])
    login_clicked = col1.button("ログイン")
    if login_clicked:
        user = next((x for x in users if x["username"] == u and x.get("password") == p), None)
        if user:
            st.session_state["user"] = user
            st.success("ログインしました。")
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが正しくありません。")

def user_badge():
    u = st.session_state.get("user")
    if not u: return
    st.markdown(
        f"**{u['username']}**　"
        f"<span class='pp-badge'>{u.get('role','guest')}</span> 　"
        f"<span class='pp-badge'>Team: {u.get('team','-')}</span>",
        unsafe_allow_html=True
    )
    if st.button("ログアウト", use_container_width=True):
        for k in ["user"]:
            st.session_state.pop(k, None)
        st.rerun()

# -----------------------------
# ページ描画（各ビュー）
# -----------------------------
def view_home():
    st.markdown("<div class='pp-header'>🏠 トップ</div>", unsafe_allow_html=True)
    conf = get_conf()
    gw = conf.get("current_gw", "-")
    st.info(f"現在のゲームウィーク: **{gw}**")
    with st.container():
        col1, col2 = st.columns([1,1])
        with col1:
            st.markdown("#### 今週のルール要点")
            st.markdown("- ブックメーカー役はベット不可\n- キックオフ2時間前でロック\n- 100円刻みでベット可能")
        with col2:
            st.markdown("#### あなたのステータス")
            u = st.session_state.get("user", {})
            st.write(f"- ユーザー: **{u.get('username','-')}**")
            st.write(f"- ロール: **{u.get('role','-')}**")
            st.write(f"- 推し: **{u.get('team','-')}**")

def view_bets():
    from pages.bets_view import render as render_bets
    render_bets()

def view_history():
    from pages.history_view import render as render_history
    render_history()

def view_realtime():
    from pages.realtime_view import render as render_realtime
    render_realtime()

def view_rules():
    from pages.rules_view import render as render_rules
    render_rules()

def view_settings():
    from pages.settings_view import render as render_settings
    render_settings()

# -----------------------------
# サイドバー：ログイン専用
# -----------------------------
with st.sidebar:
    st.markdown("### アカウント")
    if "user" not in st.session_state:
        login_box()
    else:
        user_badge()

# -----------------------------
# ナビゲーション（option-menu）
# -----------------------------
user = st.session_state.get("user", {"role": "guest"})
is_admin = user.get("role") == "admin"

labels = ["トップ", "試合とベット", "履歴", "リアルタイム", "ルール"]
icons  = ["house", "bullseye", "clock-history", "stopwatch", "book"]
if is_admin:
    labels.append("設定")
    icons.append("gear")

choice = option_menu(
    None,
    labels,
    icons=icons,
    default_index=0,
    orientation="horizontal",
    styles={
        "container": {"padding": "6px 0px 0px 0px"},
        "icon": {"color": "#E53935", "font-size": "18px"},
        "nav-link": {"--hover-color": "#fdeaea"},
        "nav-link-selected": {"background-color": "#fdeaea", "color": "#111"}
    }
)

# -----------------------------
# ルーティング
# -----------------------------
if choice == "トップ":
    view_home()
elif choice == "試合とベット":
    view_bets()
elif choice == "履歴":
    view_history()
elif choice == "リアルタイム":
    view_realtime()
elif choice == "ルール":
    view_rules()
elif choice == "設定" and is_admin:
    view_settings()
