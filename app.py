# app.py  — Premier Picks (Cloud デモ版)
from __future__ import annotations

import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

# ===== ページ設定 =====
st.set_page_config(page_title="Premier Picks", layout="centered")

st.title("Premier Picks")
st.subheader("直近のプレミア日程（本物データ）")

# ====== 一時トークンのオーバーライド（接続トラブル時の保険）======
with st.expander("🔧 接続トラブル時の一時トークン入力（必要な時だけ開く）", expanded=False):
    tok = st.text_input("football-data.org の API トークンを貼り付け", type="password")
    if tok:
        st.session_state["DEV_TOKEN_OVERRIDE"] = tok.strip()
        st.success("このセッション中は、シート/Secretsよりもこの値を優先して使います。")

# ====== API 呼び出し（fixtures）======
from football_api import get_pl_fixtures_next_days  # noqa: E402

days = st.slider("何日先まで表示するか", 3, 14, 10)
try:
    fixtures = get_pl_fixtures_next_days(days)
    if not fixtures:
        st.info("表示できる試合がありません。日数を広げるか、少し時間をおいて再度お試しください。")
    else:
        df = pd.DataFrame(fixtures)[
            ["kickoff_jst", "matchday", "home", "away", "stage"]
        ].rename(
            columns={
                "kickoff_jst": "Kickoff (JST)",
                "matchday": "GW",
                "home": "Home",
                "away": "Away",
                "stage": "Stage",
            }
        )
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )
except Exception as e:
    # football_api 側は詳細を raise しているので、ここではユーザ向けの優しい文面に
    msg = str(e)
    if "APIトークン" in msg:
        st.error("試合データの取得に失敗しました。Secrets または Googleシートの `config` に API トークンを設定してください。")
    else:
        st.error(f"試合データの取得に失敗しました。\n\n詳細: {msg}")

st.markdown("---")
st.subheader("Googleスプレッドシート接続テスト（追記＆上書き）")

# ====== シート操作ユーティリティ ======
def _now_jst_str() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")

@st.cache_resource(show_spinner=False)
def _gs_client_and_ws(sheet_name: str):
    """
    Secrets 内のサービスアカウント情報で gspread を初期化し、
    st.secrets['sheets']['sheet_id'] のワークシートを返す。
    """
    import gspread
    from google.oauth2.service_account import Credentials

    # サービスアカウント情報（前段のスプレッドシート連携で既に保存済みの前提）
    sa_keys = [
        "type","project_id","private_key_id","private_key","client_email",
        "client_id","auth_uri","token_uri","auth_provider_x509_cert_url","client_x509_cert_url"
    ]
    sa_info = {k: st.secrets[k] for k in sa_keys if k in st.secrets}
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    gc = gspread.authorize(creds)

    sheet_id = st.secrets["sheets"]["sheet_id"]
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(sheet_name)
    except Exception:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=26)
        # 必要ならヘッダ行を入れる
        if sheet_name == "bets":
            ws.update("A1:G1", [["gw","match","user","bet_team","stake","odds","timestamp"]])
    return gc, ws

def append_bet_row(row_dict: dict):
    _, ws = _gs_client_and_ws("bets")
    header = [c.strip().lower() for c in ws.row_values(1)]
    row = [row_dict.get(h, "") for h in header]
    ws.append_row(row, value_input_option="RAW")

def upsert_bet_row(key_cols: list[str], row_dict: dict):
    """
    key_cols に一致する行があれば更新、なければ追加。
    """
    _, ws = _gs_client_and_ws("bets")
    values = ws.get_all_values()
    if not values:
        ws.update("A1:G1", [["gw","match","user","bet_team","stake","odds","timestamp"]])
        values = ws.get_all_values()
    header = [c.strip().lower() for c in values[0]]
    rows = [dict(zip(header, r)) for r in values[1:]]
    # 既存検索
    target_idx = None
    for idx, r in enumerate(rows, start=2):  # 2 = 2行目（ヘッダの次）
        if all((r.get(k, "") == str(row_dict.get(k, ""))) for k in key_cols):
            target_idx = idx
            break
    # 更新 or 追加
    ordered = [row_dict.get(h, "") for h in header]
    if target_idx:
        ws.update(f"A{target_idx}:G{target_idx}", [ordered])
    else:
        ws.append_row(ordered, value_input_option="RAW")

# ====== ボタン：追記 / 上書き（簡易動作テスト）======
col1, col2 = st.columns(2)
with col1:
    if st.button("追記テスト（append）", type="primary"):
        try:
            append_bet_row(
                dict(
                    gw="GW7",
                    match="Arsenal vs West",
                    user="Tetsu",
                    bet_team="Home",
                    stake="100",
                    odds="1.9",
                    timestamp=_now_jst_str(),
                )
            )
            st.success("Googleシートに追記しました！")
        except Exception as e:
            st.error(f"シートへの追記に失敗しました: {e}")

with col2:
    if st.button("上書きテスト（upsert）"):
        try:
            # 同じキー（gw+match+user）を上書き
            upsert_bet_row(
                ["gw","match","user"],
                dict(
                    gw="GW7",
                    match="Arsenal vs West",
                    user="Tetsu",
                    bet_team="Home",
                    stake="300",  # 変更点：ステークを 300 に
                    odds="1.9",
                    timestamp=_now_jst_str(),
                )
            )
            st.success("同じキーの行を上書き（なければ追加）しました！")
        except Exception as e:
            st.error(f"シートの上書きに失敗しました: {e}")

st.caption("※ ここは接続確認用の簡易UIです。本番の“試合とベット”画面は別ファイルで実装します。")
