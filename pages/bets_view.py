import streamlit as st
from datetime import datetime, timedelta
import pytz
from google_sheets_client import read_config, ws

def _tz():
    import pytz
    tz = read_config().get("timezone", "Asia/Tokyo")
    try:
        return pytz.timezone(tz)
    except Exception:
        return pytz.timezone("Asia/Tokyo")

def _now():
    return datetime.now(tz=_tz())

def _is_locked():
    """最も早い試合の2時間前 相当。今回はデモとして毎日 23:59 を最初キックオフ扱いに。"""
    conf = read_config()
    minutes = int(conf.get("lock_minutes_before_earliest", 120))
    # デモ：今日 23:59 をキックオフに見立て
    ko = _now().replace(hour=23, minute=59, second=0, microsecond=0)
    return _now() > (ko - timedelta(minutes=minutes))

def render():
    st.markdown("<div class='pp-header'>🎯 試合とベット</div>", unsafe_allow_html=True)
    user = st.session_state.get("user", {})
    conf = read_config()
    gw = conf.get("current_gw", "-")
    bookmaker = conf.get("bookmaker_username", "")
    step = int(conf.get("stake_step", 100))
    max_total = int(conf.get("max_total_stake_per_gw", 5000))

    # 役割・ロック判定
    if user.get("username") == bookmaker:
        st.info(f"**{user.get('username')}** さんは今節のブックメーカーです。このページではベットできません。")
        return

    if _is_locked():
        st.warning("今節はロックされています（キックオフ2時間前ルール）。次節が表示されるまでお待ちください。")
        return

    st.caption(f"GW: **{gw}** 　（※ デモ：試合カードは手入力／API接続前提で置き換え予定）")

    # 入力UI（デモ用の手動入力。API接続したら差し替え）
    with st.form("bet_form", border=True):
        match = st.text_input("対戦カード", placeholder="Arsenal vs Spurs")
        bet_team = st.selectbox("ベットする側", ["Home", "Draw", "Away"])
        stake = st.number_input("掛金", min_value=0, step=step, value=step)
        odds = st.number_input("オッズ（少数）", min_value=1.01, step=0.01, value=1.90, format="%.2f")
        submitted = st.form_submit_button("保存（ベット）")

    if submitted:
        if not match:
            st.error("対戦カードを入力してください。")
            return

        # 本人の今節合計をチェック（上限）
        sh = ws("bets")
        rows = sh.get_all_records()
        total_this_gw = sum(int(r.get("stake", 0)) for r in rows if r.get("gw")==gw and r.get("user")==user.get("username"))
        if total_this_gw + int(stake) > max_total:
            st.error(f"今節の上限 {max_total:,} 円を超えます。現在 {total_this_gw:,} 円。")
            return

        # 追記
        ts = _now().strftime("%Y-%m-%d %H:%M:%S")
        sh.append_row([gw, match, user.get("username"), bet_team, int(stake), float(odds), ts])
        st.success("ベットを保存しました！")
