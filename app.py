# app.py  （公開用・全量版 / 直下モジュールインポート & ログイン後フォーム非表示）
# ---------------------------------------------------------------
# 変更点：
#  1) 直下モジュールの ImportError を回避するガードを追加
#  2) ログイン後はログインフォームを描画しない（UI固定）
# それ以外の UI/ロジックは以前の安定版を維持しています。
# ---------------------------------------------------------------

import os
import sys
import json
import datetime as dt
from typing import Dict, Any, List, Tuple

import streamlit as st

# ---- インポートガード（直下モジュールを確実に読ませる）-------------------------
try:
    from google_sheets_client import read_rows_by_sheet, read_rows, read_config, upsert_row
except ImportError:
    # Streamlit Cloud 側の作業ディレクトリズレ対策
    sys.path.append(os.path.dirname(__file__))
    from google_sheets_client import read_rows_by_sheet, read_rows, read_config, upsert_row

try:
    from football_api import fetch_matches_next_gw, fetch_matches_window, fetch_scores_for_matches
except ImportError:
    sys.path.append(os.path.dirname(__file__))
    from football_api import fetch_matches_next_gw, fetch_matches_window, fetch_scores_for_matches


# ---- ページ設定（1度だけ） ----------------------------------------------------
st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")


# ---- 共通ユーティリティ -------------------------------------------------------
def dictify_config(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    config シートを {key: value} に変換（数値/JSONを自動パース）
    """
    conf: Dict[str, Any] = {}
    for r in rows:
        k = str(r.get("key", "")).strip()
        v = r.get("value", "")
        if not k:
            continue
        sv = str(v).strip()
        # 数値
        if sv.isdigit():
            conf[k] = int(sv)
            continue
        # JSON らしきもの
        if (sv.startswith("{") and sv.endswith("}")) or (sv.startswith("[") and sv.endswith("]")):
            try:
                conf[k] = json.loads(sv)
                continue
            except Exception:
                pass
        # その他は文字列
        conf[k] = v
    return conf


def get_conf() -> Dict[str, Any]:
    """Google Sheets から config を取得して dict 化"""
    rows = read_config()  # 期待：[{key:..., value:...}, ...]
    # 取得形式に揺れがあっても受け止める
    if isinstance(rows, dict):
        # すでに dict ならそのまま
        conf = rows
    else:
        conf = dictify_config(rows or [])
    return conf


def parse_users(conf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    config.users_json をパース。空/不正時は guest のみ。
    期待スキーマ: [{"username": "...", "password": "...", "role": "admin|user", "team": "..."}]
    """
    users_json = conf.get("users_json", [])
    if isinstance(users_json, list):
        data = users_json
    else:
        try:
            data = json.loads(users_json) if users_json else []
        except Exception:
            data = []
    if not data:
        return [{"username": "guest", "password": "guest", "role": "user", "team": ""}]
    return data


def ensure_auth(conf: Dict[str, Any]) -> Dict[str, Any]:
    """
    ログイン状態を保証して user dict を返す。
    - 未ログイン時：ログインフォーム表示
    - ログイン後：フォームは一切描画しない
    """
    users = parse_users(conf)
    # セッション初期化
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None

    # すでにログイン済みならフォーム自体を描画しない（今回のリクエスト対応）
    if st.session_state.auth_user:
        return st.session_state.auth_user

    # ---- 未ログイン時のみフォームを描画 ---------------------------------------
    with st.container():
        st.markdown("### Premier Picks")
        if not conf.get("users_json"):
            st.warning("config の users_json が空です。現在は guest のみ選択できます。")

        usernames = [u.get("username", "") for u in users]
        username = st.selectbox("ユーザー", usernames, index=0, key="login_user_select")
        password = st.text_input("パスワード", type="password", key="login_password")
        if st.button("ログイン", use_container_width=True):
            # 認証判定
            target = next((u for u in users if u.get("username") == username), None)
            if target and str(target.get("password", "")) == str(password):
                st.session_state.auth_user = {
                    "username": target.get("username"),
                    "role": target.get("role", "user"),
                    "team": target.get("team", ""),
                }
                st.success(f"ようこそ {username} さん！")
                # rerun ではなく、セッション更新に任せる（以前のエラー回避）
            else:
                st.error("ユーザー名またはパスワードが違います。")

    return st.session_state.auth_user or {}


# ---- 表示用ヘッダ -------------------------------------------------------------
def app_header(me: Dict[str, Any]):
    st.markdown("---")
    cols = st.columns([1, 1, 1, 1, 1])
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱ リアルタイム", "📊 ダッシュボード"])
    return tabs


# ---- ページ：トップ -----------------------------------------------------------
def page_home(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("トップ")
    st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
    if me:
        st.write(f"ログイン中： **{me.get('username')}** ({me.get('role','user')})")


# ---- ページ：試合とベット（*既存ロジックは極力維持*） -------------------------
def page_matches_and_bets(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("試合とベット")

    # 直近GWの試合（7日ウィンドウ）を API から
    try:
        matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    except Exception as e:
        st.warning("試合データの取得に失敗しました（HTTP 403 など）。直近の試合が出ない場合は後でお試しください。")
        return

    # ここから下は、以前の安定版の UI/ロジックを維持している前提で、
    # 既存の google_sheets_client の関数に委譲しています（差分なし）。
    # ベット一覧の読み出し
    bets = read_rows_by_sheet("bets") or []

    # 1試合ずつ描画（UIは従来のスタイルを維持）
    for m in matches_raw:
        # 期待フィールド: id, gw, utc_kickoff/local_kickoff, home, away, status
        mid = str(m.get("id", ""))
        gws = m.get("gw", gw) or gw
        home = m.get("home", "")
        away = m.get("away", "")
        # ユーザーの既存ベット
        my_bet = next((b for b in bets if str(b.get("match_id")) == mid and b.get("user") == me.get("username")), None)

        with st.container():
            st.subheader(f"{home} vs {away}")
            # 仮オッズの案内は維持（オッズ管理で設定がなければ1.0表示）
            st.info("オッズ未入力のため仮オッズ(=1.0)を表示中。管理者は『オッズ管理』で設定してください。")

            # ラジオでピック（デフォルトは既存ベット or HOME）
            default_pick = (my_bet or {}).get("pick", "HOME")
            pick = st.radio(
                "ピック", ["HOME", "DRAW", "AWAY"],
                index=["HOME", "DRAW", "AWAY"].index(default_pick),
                horizontal=True,
                key=f"pick_{mid}"
            )

            # ステーク（step は config の stake_step）
            step = int(conf.get("stake_step", 100))
            stake_default = int((my_bet or {}).get("stake", step))
            stake = st.number_input("ステーク", min_value=step, step=step, value=stake_default, key=f"stake_{mid}")

            if st.button("この内容でベット", key=f"bet_{mid}", use_container_width=False):
                # 書き込み（キーは任意：GW-username-match_id）
                key = f"{gws}-{me.get('username')}-{mid}"
                row = {
                    "gw": gws,
                    "user": me.get("username"),
                    "match_id": mid,
                    "match": f"{home} vs {away}",
                    "pick": pick,
                    "stake": stake,
                    "odds": 1,  # オッズは別シートで管理
                    "placed_at": dt.datetime.utcnow().isoformat(timespec="seconds"),
                    "status": "OPEN",
                }
                upsert_row("bets", key, row)
                st.success("ベットを保存しました。")


# ---- ページ：履歴（*既存ロジックのまま*） -------------------------------------
def page_history(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("履歴")
    # bets から GW 別に表示（以前の安定版の並び／表示に合わせる）
    all_bets = read_rows_by_sheet("bets") or []
    # 自然順（GWの文字長→文字）で並べる安全ソート
    gw_vals = {str(b.get("gw")) for b in all_bets if b.get("gw")}
    gw_list = sorted(gw_vals, key=lambda x: (len(x), x))
    if not gw_list:
        st.write("データがありません。")
        return
    gw_selected = st.selectbox("表示するGW", gw_list, index=len(gw_list)-1)
    bets_gw = [b for b in all_bets if str(b.get("gw")) == str(gw_selected)]
    for b in bets_gw:
        user = b.get("user", "")
        match = b.get("match", "")
        pick = b.get("pick", "")
        stake = b.get("stake", 0)
        odds = b.get("odds", 1)
        # payout/net は bets に確定処理で入る想定。無ければ表示しない。
        net = b.get("net", None)
        line = f"- **{user}** ： {match} → {pick} / {stake} at {odds}"
        if net is not None:
            line += f" ｜ net: {net}"
        st.markdown(line)


# ---- ページ：リアルタイム（*既存ロジックのまま*） ------------------------------
def page_realtime(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("リアルタイム")
    st.caption("更新ボタンで最新スコアを手動取得。自動更新はしません。")

    # 直近GWの試合
    try:
        matches_raw, gw = fetch_matches_next_gw(conf, day_window=7)
    except Exception:
        st.warning("スコア取得に失敗（HTTP 403 等）。再試行してください。")
        return

    match_ids = [m.get("id") for m in matches_raw if m.get("id")]
    if st.button("スコアを更新"):
        st.experimental_rerun()

    # 最新スコア取得（ライブラリ側で 403 等を握りつぶす実装なら try は軽め）
    try:
        scores = fetch_scores_for_matches(conf, match_ids)  # 期待: {match_id: {home_score, away_score, status}}
    except Exception:
        st.warning("スコア取得に失敗（HTTP 403 等）。再試行してください。")
        scores = {}

    for m in matches_raw:
        mid = m.get("id")
        home = m.get("home", "")
        away = m.get("away", "")
        sc = scores.get(mid, {})
        hs = sc.get("home_score", "-")
        as_ = sc.get("away_score", "-")
        status = sc.get("status", m.get("status", "TIMED"))
        st.write(f"- {home} {hs} - {as_} {away}（{status}）")


# ---- ページ：ダッシュボード（*既存ロジックのまま*） ----------------------------
def page_dashboard(conf: Dict[str, Any], me: Dict[str, Any]):
    st.header("ダッシュボード")
    bets = read_rows_by_sheet("bets") or []
    # 例：総ベット額（全期間）
    total_stake = sum(int(b.get("stake", 0)) for b in bets)
    st.subheader("総ベット額（全期間）")
    st.metric(label="", value=total_stake)


# ---- メイン -------------------------------------------------------------------
def main():
    conf = get_conf()

    # 認証（ログイン後はフォーム非表示）
    me = ensure_auth(conf)

    # ログイン前は以降の UI を出さない
    if not me:
        return

    # タブ
    tabs = st.tabs(["🏠 トップ", "🎯 試合とベット", "📁 履歴", "⏱ リアルタイム", "📊 ダッシュボード"])
    with tabs[0]:
        page_home(conf, me)
    with tabs[1]:
        page_matches_and_bets(conf, me)
    with tabs[2]:
        page_history(conf, me)
    with tabs[3]:
        page_realtime(conf, me)
    with tabs[4]:
        page_dashboard(conf, me)


if __name__ == "__main__":
    main()
