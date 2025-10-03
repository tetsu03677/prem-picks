# pages/99_API_Check.py
import datetime as dt
import requests
import streamlit as st

from google_sheets_client import read_config

PAGE_TITLE = "🧪 API 接続チェック（football-data.org）"

def require_login():
    # 未ログインならトップへ
    if not st.session_state.get("user"):
        st.info("ログインしてください。")
        st.page_link("app.py", label="トップへ戻る ⤴")
        st.stop()

def get_fd_headers(token: str) -> dict:
    return {"X-Auth-Token": token}

def fetch_matches_fd(
    token: str,
    comp: str,      # 例: "PL" もしくは "2021"
    date_from: str, # "YYYY-MM-DD"
    date_to: str    # "YYYY-MM-DD"
):
    # competition はコード(PL)でもID(2021)でもOK
    url = "https://api.football-data.org/v4/matches"
    params = {"dateFrom": date_from, "dateTo": date_to, "competitions": comp}
    resp = requests.get(url, headers=get_fd_headers(token), params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()

def main():
    require_login()

    st.set_page_config(page_title=PAGE_TITLE, layout="centered")
    st.title(PAGE_TITLE)

    conf = read_config()
    token = conf.get("FOOTBALL_DATA_API_TOKEN", "").strip()
    comp  = conf.get("FOOTBALL_DATA_COMPETITION", "PL").strip()  # ★ ここ

    # 画面
    st.caption(f"League/Competition: {comp}  /  Season: {conf.get('API_FOOTBALL_SEASON', '—')}")
    days = st.slider("何日先までチェックするか", 3, 21, 14, help="dateFrom/dateTo で照会します（UTC）。")
    if st.button("▶ 接続テストを実行", use_container_width=True):
        if not token:
            st.error("FOOTBALL_DATA_API_TOKEN が空です。config シートを確認してください。")
            return
        try:
            today = dt.datetime.utcnow().date()
            date_from = today.isoformat()
            date_to   = (today + dt.timedelta(days=days)).isoformat()

            with st.expander("✓ Fixtures を取得中…", expanded=True):
                st.write(f"`{date_from}` 〜 `{date_to}` / competitions=`{comp}`")
                data = fetch_matches_fd(token, comp, date_from, date_to)
                count = len(data.get("matches", []))
                st.success(f"OK: {count} 試合ヒット")
                if count:
                    for m in data["matches"][:10]:  # 先頭10件だけプレビュー
                        k = m.get("utcDate", "—").replace("T", " ")[:16]
                        h = m["homeTeam"]["name"]
                        a = m["awayTeam"]["name"]
                        st.write(f"{k}  —  {h} vs {a}")

        except requests.HTTPError as e:
            st.error(f"HTTPError: {e}")
        except Exception as e:
            st.error(f"Error: {e}")

if __name__ == "__main__":
    main()
