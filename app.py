import json
from datetime import datetime, timedelta, timezone
import pytz
import streamlit as st

import streamlit as st

# ← ここで最初にページ設定を一度だけ
st.set_page_config(
    page_title="Premier Picks",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

from google_sheets_client import read_config, upsert_bet_row, read_bets
from football_api import get_next_fixtures

# ====== Global style (simple & clean) ======
STYLES = """
<style>
/* base */
:root { --accent:#e24c4c; }
section.main { padding-top: 1.2rem; }
.block-container { padding-top: 1.2rem; max-width: 980px; }
h1, h2, h3 { letter-spacing: .02em; }
hr { border: none; border-top: 1px solid #2a2d33; margin: 1.25rem 0; }

/* cards */
.card {
  background: #1e2229;
  border: 1px solid #323843;
  border-radius: 14px;
  padding: 14px 16px;
  box-shadow: 0 4px 18px rgba(0,0,0,.25);
}
.badge {
  display:inline-block; padding:2px 8px; border-radius:999px;
  background:#2a3038; border:1px solid #3a404a; font-size:.75rem;
}

/* nice buttons */
.stButton>button {
  border-radius: 10px !important;
  border: 1px solid #3a404a !important;
  padding: .6rem 1.1rem !important;
  font-weight: 600 !important;
}
.stButton>button[kind="primary"] {
  background: linear-gradient(180deg, var(--accent), #c83b3b) !important;
  color: #fff !important;
  border: none !important;
}

/* sidebar white base */
[data-testid="stSidebar"] {
  background: #f7f8fb !important;
  border-right: 1px solid #e6e8ef;
}
[data-testid="stSidebar"] h2 { color: #182026 !important; }
[data-testid="stSidebar"] .stSelectbox>div>div { background: #fff; }

/* table */
tbody tr:hover td { background: rgba(226,76,76,.06) !important; }
</style>
"""
st.markdown(STYLES, unsafe_allow_html=True)

# ====== Helpers ======
def tz_now(conf):
    tz = pytz.timezone(conf.get("timezone", "Asia/Tokyo"))
    return datetime.now(tz)

def parse_users(conf):
    """config.users_json を [{username,password,role,team}] へ"""
    raw = conf.get("users_json", "").strip()
    if not raw:
        return []
    try:
        users = json.loads(raw)
        assert isinstance(users, list)
        return users
    except Exception as e:
        st.error(f"ユーザー設定の読み込みに失敗しました: {e}")
        return []

def get_usernames(conf):
    return [u["username"] for u in parse_users(conf)]

def get_user(conf, username):
    for u in parse_users(conf):
        if u["username"] == username:
            return u
    return None

# ====== Auth ======
def show_login():
    st.markdown("### Premier Picks")
    st.caption("ログインしてください。")
    conf = read_config()

    users = parse_users(conf)
    usernames = [u["username"] for u in users] or ["guest"]

    c1, c2 = st.columns(2)
    with c1:
        username = st.selectbox("ユーザー", usernames, index=0, key="login_user")
    with c2:
        password = st.text_input("パスワード", type="password", key="login_pw")

    colA, colB = st.columns([1,1])
    with colA:
        if st.button("ログイン", type="primary", use_container_width=True):
            u = get_user(conf, username)
            if u and (password == u.get("password", "")):
                st.session_state["is_authenticated"] = True
                st.session_state["username"] = username
                st.session_state["role"] = u.get("role", "user")
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います。")

    with colB:
        st.button("キャンセル", use_container_width=True)

def logout_box():
    u = st.session_state.get("username", "guest")
    r = st.session_state.get("role", "user")
    st.markdown(
        f'<div class="card"><b>{u}</b> <span class="badge">{r}</span> '
        f'<span class="badge">{read_config().get("current_gw","GW?")}</span> '
        '</div>', unsafe_allow_html=True
    )
    if st.button("ログアウト", key="logout_btn"):
        st.session_state.clear()
        st.rerun()

# ====== Navbar (radio) ======
PAGES = {
    "トップ": "home",
    "試合とベット": "bet",
    "履歴": "history",
    "リアルタイム": "realtime",
    "ルール": "rules",
    "設定(管理者)": "settings",
}
def navbar():
    st.sidebar.markdown("## メニュー")
    page_key = st.sidebar.radio(
        label="ページ",
        options=list(PAGES.keys()),
        label_visibility="collapsed",
        index=0 if st.session_state.get("active_page") is None else list(PAGES.values()).index(st.session_state["active_page"]),
    )
    st.session_state["active_page"] = PAGES[page_key]

# ====== Pages ======
def page_home():
    conf = read_config()
    st.markdown("## ダッシュボード")
    st.caption("直近のスケジュールと利用上限のサマリー")

    # Fixtures
    st.markdown("#### 直近の試合")
    days = st.slider("何日先まで表示するか", 3, 14, 7)
    ok, fixtures_or_msg = get_next_fixtures(days, conf)
    if not ok:
        st.warning(fixtures_or_msg)
    else:
        fixt = fixtures_or_msg
        if not fixt:
            st.info("対象期間の試合がありません。")
        else:
            for f in fixt:
                st.markdown(
                    f'<div class="card">'
                    f'<b>{f["home"]}</b> vs <b>{f["away"]}</b>　'
                    f'<span class="badge">{f["kickoff_local"]}</span> '
                    f'<span class="badge">GW {f.get("matchday","?")}</span>'
                    f'</div>', unsafe_allow_html=True
                )

    # KPI
    st.markdown("#### 残高と利用上限（仮）")
    bets = read_bets()
    user = st.session_state.get("username","guest")
    my = [b for b in bets if b.get("user")==user]
    total_stake = sum(int(b.get("stake",0) or 0) for b in my)
    st.write(f"今節のベット合計: **{total_stake}** 円 / 上限 **{conf.get('max_total_stake_per_gw','?')}** 円")
    st.progress(min(1.0, total_stake/max(1,int(conf.get('max_total_stake_per_gw',5000)))))

def page_bet():
    conf = read_config()
    st.markdown("## 試合とベット")
    logout_box()

    username = st.session_state.get("username", "guest")
    bookmaker = conf.get("bookmaker_username","")
    if username == bookmaker:
        st.info(f"今節は **{bookmaker}** がブックメーカー役のため、ベッティングできません。")
        return

    # Fixtures
    lock_min = int(conf.get("lock_minutes_before_earliest", 120))
    ok, fixtures_or_msg = get_next_fixtures(7, conf)
    if not ok:
        st.warning(fixtures_or_msg)
        return
    fixtures = fixtures_or_msg

    if not fixtures:
        st.info("対象期間の試合がありません。")
        return

    # 最も早いKOの lock 時刻
    earliest = min([f["kickoff_dt"] for f in fixtures])
    lock_at = earliest - timedelta(minutes=lock_min)
    now = tz_now(conf)
    locked = now >= lock_at
    st.caption(f"ロック時刻: {lock_at.strftime('%Y-%m-%d %H:%M')}　（現在: {now.strftime('%H:%M')}）")
    if locked:
        st.warning("現在ロック中のため、ベットはできません。")
        return

    # 入力UI
    picks = []
    for i, f in enumerate(fixtures):
        with st.expander(f'{f["kickoff_local"]} ｜ GW{f.get("matchday","?")} ｜ {f["home"]} vs {f["away"]}', expanded=False):
            col1, col2, col3 = st.columns([1.2,1,1])
            with col1:
                bet_team = st.selectbox("賭け先", [f["home"], "Draw", f["away"]],
                                        key=f"bt_{i}")
            with col2:
                odds = st.number_input("オッズ", value=float(f.get("odds", 1.9)), step=0.01,
                                       key=f"od_{i}")
            with col3:
                step = int(conf.get("stake_step", 100))
                stake = st.number_input("掛金(円)", value=step, step=step, min_value=0,
                                        key=f"st_{i}")
            picks.append({"match": f'{f["home"]} vs {f["away"]}',
                          "bet_team": bet_team, "odds": odds, "stake": stake})

    # 送信
    if st.button("保存（各試合を1行で記録）", type="primary", use_container_width=True):
        for p in picks:
            if p["stake"] and p["stake"]>0:
                upsert_bet_row(
                    gw=conf.get("current_gw","GW?"),
                    match=p["match"],
                    user=username,
                    bet_team=p["bet_team"],
                    stake=int(p["stake"]),
                    odds=float(p["odds"]),
                    ts=tz_now(conf).strftime("%Y-%m-%d %H:%M:%S"),
                )
        st.success("保存しました。")
        st.rerun()

def page_history():
    st.markdown("## 履歴")
    logout_box()
    bets = read_bets()
    if not bets:
        st.info("まだ記録がありません。")
        return
    # 並べ替え
    bets = sorted(bets, key=lambda x: x.get("timestamp",""))
    st.dataframe(bets, use_container_width=True, hide_index=True)

def page_realtime():
    st.markdown("## リアルタイム")
    logout_box()
    st.info("（デモ）ここに速報スコア×ベット金額のリアルタイム損益を出します。")

def page_rules():
    st.markdown("## ルール")
    st.markdown("""
- 1GWあたりの上限は **config.max_total_stake_per_gw** 円  
- 最も早いキックオフの **config.lock_minutes_before_earliest** 分前にロック  
- ブックメーカー役（**config.bookmaker_username**）はベット不可
""")

def page_settings():
    st.markdown("## 設定（管理者）")
    logout_box()
    if st.session_state.get("role") != "admin":
        st.warning("管理者のみアクセスできます。")
        return
    conf = read_config()
    st.json(conf)

# ====== Router ======
def router():
    page = st.session_state.get("active_page", "home")
    if page == "home": page_home()
    elif page == "bet": page_bet()
    elif page == "history": page_history()
    elif page == "realtime": page_realtime()
    elif page == "rules": page_rules()
    elif page == "settings": page_settings()

# ====== App entry ======
def main():
    navbar()
    if st.session_state.get("is_authenticated"):
        router()
    else:
        show_login()

if __name__ == "__main__":
    main()
