import json
from datetime import datetime
from typing import Dict, Any, List

import streamlit as st
import pytz

from google_sheets_client import read_config
from football_api import get_fixtures_for_round, get_odds_for_fixture

# ---------- ページ基本 ----------
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")


# ---------- ユーティリティ ----------
def _tz() -> pytz.timezone:
    conf = read_config()
    return pytz.timezone(conf.get("timezone", "Asia/Tokyo"))


def _conf_gw_to_round(conf: Dict[str, str]) -> int:
    gw_text = conf.get("current_gw", "GW7")
    try:
        return int(gw_text.replace("GW", "").strip())
    except Exception:
        return 7


def _load_users() -> List[Dict[str, Any]]:
    conf = read_config()
    raw = conf.get("users_json", "").strip()
    if not raw:
        return [{"username": "guest", "password": "guest", "role": "user", "team": "-"}]
    try:
        return json.loads(raw)
    except Exception:
        return [{"username": "guest", "password": "guest", "role": "user", "team": "-"}]


def _match_user(username: str, password: str) -> Dict[str, Any] | None:
    for u in _load_users():
        if u.get("username") == username and u.get("password") == password:
            return u
    return None


# ---------- ログイン ----------
def show_login():
    st.markdown(
        """
        <div style="text-align:center; margin-top:8vh;">
          <div style="font-size:28px; font-weight:800; margin-bottom:8px;">Premier Picks</div>
          <div style="opacity:.8; margin-bottom:24px;">ログインしてください</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            username = st.text_input("ユーザー名", value="")
        with c2:
            password = st.text_input("パスワード", value="", type="password")
        ok = st.form_submit_button("ログイン", use_container_width=True)
        if ok:
            user = _match_user(username, password)
            if user:
                st.session_state["is_authenticated"] = True
                st.session_state["user"] = user
                st.success(f"ログイン成功：{user['username']}")
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが正しくありません。")


# ---------- 画面：ダッシュボード ----------
def page_home():
    conf = read_config()
    tz = _tz()
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    st.markdown(
        f"""
<div style="background:#161a1d;border:1px solid #2a2f35;border-radius:12px;padding:14px;margin-bottom:12px;">
  <div style="font-size:18px;font-weight:700;">ダッシュボード</div>
  <div style="opacity:.8;font-size:13px;">{now}（{conf.get('timezone','Asia/Tokyo')}）</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric("現在のGW", conf.get("current_gw", "GW?"))
    with k2:
        st.metric("リーグ/シーズン", f"{conf.get('API_FOOTBALL_LEAGUE_ID','39')} / {conf.get('API_FOOTBALL_SEASON','2025')}")
    with k3:
        st.metric("ブックメーカー", conf.get("bookmaker_username", "-"))

    st.caption("※ この段階ではKPIはダミー。ベット機能実装後に集計反映します。")


# ---------- 画面：試合とオッズ（閲覧のみ） ----------
def page_bets_view_only():
    conf = read_config()
    gw_num = _conf_gw_to_round(conf)

    st.subheader(f"今節の試合とオッズ（{conf.get('current_gw','GW?')}）", divider="gray")

    with st.spinner("API から今節のカードを取得中…"):
        fixtures = get_fixtures_for_round(gw_num)

    if not fixtures:
        st.warning("今節の試合が見つかりませんでした。config の current_gw をご確認ください。")
        return

    tz = _tz()
    for fx in fixtures:
        f = fx.get("fixture", {})
        t = fx.get("teams", {})
        home = t.get("home", {}).get("name", "Home")
        away = t.get("away", {}).get("name", "Away")
        fid = f.get("id")

        # Kickoff -> ローカル表示
        ko_iso = f.get("date")
        try:
            ko_local = datetime.fromisoformat(ko_iso.replace("Z", "+00:00")).astimezone(tz)
            kickoff = ko_local.strftime("%m/%d %a %H:%M")
        except Exception:
            kickoff = "-"

        # 1X2 オッズ
        odds = get_odds_for_fixture(fid) if fid else {}
        o1 = odds.get("1", "-")
        ox = odds.get("X", "-")
        o2 = odds.get("2", "-")

        st.markdown(
            f"""
<div style="background:#161a1d;border:1px solid #2a2f35;border-radius:12px;padding:14px;margin-bottom:12px;">
  <div style="font-size:14px;opacity:.8;">{kickoff}</div>
  <div style="font-size:18px;font-weight:700;margin:6px 0 10px 0;">{home}  vs  {away}</div>
  <div style="display:flex;gap:8px;">
    <div style="flex:1;text-align:center;border:1px solid #2f3540;border-radius:10px;padding:8px;">
      <div style="font-size:12px;opacity:.8;">Home</div>
      <div style="font-size:18px;font-weight:800;">{o1}</div>
    </div>
    <div style="flex:1;text-align:center;border:1px solid #2f3540;border-radius:10px;padding:8px;">
      <div style="font-size:12px;opacity:.8;">Draw</div>
      <div style="font-size:18px;font-weight:800;">{ox}</div>
    </div>
    <div style="flex:1;text-align:center;border:1px solid #2f3540;border-radius:10px;padding:8px;">
      <div style="font-size:12px;opacity:.8;">Away</div>
      <div style="font-size:18px;font-weight:800;">{o2}</div>
    </div>
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.caption("※ まずは閲覧のみ。次ステップで“ベット入力→betsシート書き込み”を組み込みます。")


# ---------- 画面：履歴 / リアルタイム / ルール（プレースホルダ） ----------
def page_history_placeholder():
    st.subheader("履歴（準備中）", divider="gray")
    st.info("次のステップで bets シートから読み出してタイムライン表示します。")

def page_realtime_placeholder():
    st.subheader("リアルタイム（準備中）", divider="gray")
    st.info("ライブスコアとの突合・手動更新ボタンを次のステップで追加します。")

def page_rules_placeholder():
    st.subheader("ルール", divider="gray")
    st.markdown(
        """
- 1試合あたり 1x2（Home/Draw/Away）のみ  
- ステーク刻み：config `stake_step`  
- GWロック：最も早いKOの **lock_minutes_before_earliest** 分前  
- 収支は今後履歴/リアルタイムで表示
        """
    )


# ---------- メイン ----------
def main():
    if not st.session_state.get("is_authenticated"):
        show_login()
        return

    user = st.session_state.get("user", {"username": "?"})

    # サイドバー：メニュー＋ログアウト
    with st.sidebar:
        st.markdown("### メニュー")
        page = st.radio(
            " ",
            options=["トップ", "試合とベット", "履歴", "リアルタイム", "ルール"],
            index=0,
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"ログイン中：**{user.get('username','?')}**")
        if st.button("ログアウト", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    # メイン切り替え
    if page == "トップ":
        page_home()
    elif page == "試合とベット":
        page_bets_view_only()
    elif page == "履歴":
        page_history_placeholder()
    elif page == "リアルタイム":
        page_realtime_placeholder()
    else:
        page_rules_placeholder()


if __name__ == "__main__":
    main()
