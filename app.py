import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

import streamlit as st

from google_sheets_client import read_config, ws, read_sheet, write_sheet
from football_api import fetch_matches_window, simplify_matches

# ─────────────────────────────────────
# ユーティリティ（UTCのaware datetimeで統一）
# ─────────────────────────────────────
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def parse_utc(dt_str: str) -> datetime:
    if not dt_str:
        return now_utc()
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# ─────────────────────────────────────
# ログイン
# ─────────────────────────────────────
def ensure_auth(conf: Dict[str, str]) -> None:
    if "user" in st.session_state and st.session_state["user"]:
        return
    st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")
    st.markdown("<h2 style='margin-top:0'>Premier Picks</h2>", unsafe_allow_html=True)

    users = json.loads(conf.get("users_json", "[]"))
    usernames = [u["username"] for u in users]
    col = st.container()
    with col:
        st.markdown("#### ログイン")
        u = st.selectbox("ユーザー", usernames, index=0)
        p = st.text_input("パスワード", type="password")
        if st.button("ログイン"):
            user = next((x for x in users if x["username"] == u), None)
            if user and p == user.get("password"):
                st.session_state["user"] = {"name": u, "role": user.get("role", "user")}
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います。")
    st.stop()

# ─────────────────────────────────────
# bets / odds ヘルパ
# ─────────────────────────────────────
def load_bets() -> List[Dict]:
    data = read_sheet("bets")
    if not data:
        return []
    header = data[0]
    rows = data[1:]
    out = []
    for r in rows:
        if len(r) < len(header):
            r += [""] * (len(header) - len(r))
        out.append({header[i]: r[i] for i in range(len(header))})
    return out

def save_bets(bets: List[Dict]) -> None:
    if not bets:
        write_sheet("bets", [["key","gw","user","match_id","match","pick","stake","odds","placed_at","status","result","payout","net","settled_at"]])
        return
    header = ["key","gw","user","match_id","match","pick","stake","odds","placed_at","status","result","payout","net","settled_at"]
    values = [header]
    for b in bets:
        values.append([b.get(h,"") for h in header])
    write_sheet("bets", values)

def load_odds_map() -> Dict[str, Dict]:
    data = read_sheet("odds")
    if not data:
        return {}
    header = data[0]
    rows = data[1:]
    out = {}
    for r in rows:
        if not r:
            continue
        if len(r) < len(header):
            r += [""] * (len(header) - len(r))
        rec = {header[i]: r[i] for i in range(len(header))}
        mid = str(rec.get("match_id","")).strip()
        if mid:
            out[mid] = rec
    return out

def upsert_bet(existing: Optional[Dict], new_bet: Dict) -> None:
    bets = load_bets()
    if existing:
        # 上書き
        for i, b in enumerate(bets):
            if b["key"] == existing["key"]:
                bets[i] = new_bet
                break
    else:
        bets.append(new_bet)
    save_bets(bets)

def find_user_bet_for_match(bets: List[Dict], user: str, match_id: str, gw: str) -> Optional[Dict]:
    for b in bets:
        if b.get("user")==user and str(b.get("match_id"))==str(match_id) and b.get("gw")==gw:
            return b
    return None

def sum_user_stake_in_gw(bets: List[Dict], user: str, gw: str) -> int:
    s = 0
    for b in bets:
        if b.get("user")==user and b.get("gw")==gw and b.get("status","open")=="open":
            try:
                s += int(b.get("stake",0))
            except:
                pass
    return s

def render_top(conf: Dict[str,str]):
    st.markdown("### トップ")
    st.write(f"ようこそ **{st.session_state['user']['name']}** さん！")

def render_history():
    st.markdown("### 履歴")
    st.info("履歴ページは今は簡易版です。")

def render_realtime():
    st.markdown("### リアルタイム")
    st.info("手動更新ボタンで最新化できます。")
    if st.button("更新"):
        st.success("更新しました。")

def render_odds_admin(conf: Dict[str,str]):
    st.markdown("### オッズ管理（管理者）")
    if st.session_state["user"].get("role") != "admin":
        st.warning("権限がありません。")
        return

    # 直近7日以内の試合だけ取得
    matches_raw = fetch_matches_window(
        days=7,
        league_id_or_code=conf.get("API_FOOTBALL_LEAGUE_ID","39"),
        season=conf.get("API_FOOTBALL_SEASON","2025"),
        token=conf.get("FOOTBALL_DATA_API_TOKEN","")
    )
    matches = simplify_matches(matches_raw)
    odds_map = load_odds_map()

    if not matches:
        st.info("7日以内に試合はありません。")
        return

    st.caption("未入力の試合は青い注意ボックスが出ます。")
    for m in matches:
        with st.container():
            st.markdown(
                f"""
                <div style='padding:.6rem 1rem;border:1px solid #eee;border-radius:.6rem;margin:.6rem 0'>
                  <div style='font-size:.9rem;color:#666'>GW {conf.get("current_gw","")}</div>
                  <div style='font-size:1.08rem'><b>{m["home"]}</b> vs {m["away"]}</div>
                  <div style='font-size:.85rem;color:#666'>{m["kickoff_local"]}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            rec = odds_map.get(str(m["id"]), {})
            c1, c2, c3 = st.columns(3)
            home_odds = c1.number_input("Home Win", min_value=1.0, step=0.01,
                                        value=float(rec.get("home_win") or 1.0), key=f"o_h_{m['id']}")
            draw_odds = c2.number_input("Draw", min_value=1.0, step=0.01,
                                        value=float(rec.get("draw") or 1.0), key=f"o_d_{m['id']}")
            away_odds = c3.number_input("Away Win", min_value=1.0, step=0.01,
                                        value=float(rec.get("away_win") or 1.0), key=f"o_a_{m['id']}")
            locked = st.checkbox("ロック", value=bool(rec.get("locked")), key=f"lock_{m['id']}")

            if st.button("保存", key=f"save_{m['id']}"):
                # odds sheet は「ヘッダー行固定で上書き方式」
                data = read_sheet("odds")
                header = data[0] if data else ["gw","match_id","home","away","home_win","draw","away_win","locked","updated_at"]
                rows = data[1:] if len(data)>1 else []

                # 既存行検索
                idx = None
                for i, r in enumerate(rows):
                    if str(r[1]) == str(m["id"]):
                        idx = i
                        break
                new_row = [
                    conf.get("current_gw",""),
                    str(m["id"]),
                    m["home"],
                    m["away"],
                    f"{home_odds:.2f}",
                    f"{draw_odds:.2f}",
                    f"{away_odds:.2f}",
                    "TRUE" if locked else "",
                    now_utc().isoformat()
                ]
                if idx is None:
                    rows.append(new_row)
                else:
                    rows[idx] = new_row
                write_sheet("odds", [header] + rows)
                st.success("保存しました。")
                st.rerun()

def render_matches_and_bets(conf: Dict[str,str]):
    st.markdown("### 試合とベット")

    user = st.session_state["user"]["name"]
    gw = conf.get("current_gw","")
    freeze_minutes = int(conf.get("lock_minutes_before_earliest", conf.get("odds_freeze_minutes_before_first","120")))

    # 7日固定で取得
    matches_raw = fetch_matches_window(
        days=7,
        league_id_or_code=conf.get("API_FOOTBALL_LEAGUE_ID","39"),
        season=conf.get("API_FOOTBALL_SEASON","2025"),
        token=conf.get("FOOTBALL_DATA_API_TOKEN","")
    )
    matches = simplify_matches(matches_raw)
    if not matches:
        st.info("7日以内に次節はありません。")
        return

    # ベット上限・合計
    bets = load_bets()
    total_stake = sum_user_stake_in_gw(bets, user, gw)
    st.caption(f"このGWのあなたの投票合計: {total_stake} / 上限 {conf.get('max_total_stake_per_gw','5000')} "
               f"(残り {int(conf.get('max_total_stake_per_gw','5000')) - total_stake})")

    # オッズ
    odds_map = load_odds_map()

    for m in matches:
        kickoff_utc = parse_utc(m["utcDate"])
        lock_threshold = kickoff_utc - timedelta(minutes=freeze_minutes)
        locked = now_utc() >= lock_threshold

        with st.container():
            st.markdown(
                f"""
                <div style='padding:.8rem 1rem;border:1px solid #eee;border-radius:.7rem;margin:1rem 0;background:#f9fafb'>
                  <div style='display:flex;gap:.5rem;align-items:center'>
                    <span style='font-size:.85rem;color:#666;'>GW {gw}</span>
                    <span style='font-size:.85rem;color:#666;'>{m["kickoff_local"]}</span>
                  </div>
                  <div style='font-size:1.1rem;margin-top:.2rem;'>
                    <b>{m["home"]}</b> vs {m["away"]}
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            # オッズ
            rec = odds_map.get(str(m["id"]), {})
            home_odds = float(rec.get("home_win") or 1.0)
            draw_odds = float(rec.get("draw") or 1.0)
            away_odds = float(rec.get("away_win") or 1.0)
            if not rec:
                st.info("オッズが未入力のため仮オッズ(=1.0)を表示中。管理者は『オッズ管理』で設定してください。")

            # 他ユーザーの現時点ベット簡易表示
            others = [b for b in bets if b.get("match_id")==str(m["id"]) and b.get("gw")==gw]
            if others:
                chips = []
                for b in others:
                    chips.append(f"{b['user']}:{b['pick']}/{b['stake']}")
                st.caption("現在のベッティング: " + " ｜ ".join(chips))

            # 自分のベット
            my_bet = find_user_bet_for_match(bets, user, str(m["id"]), gw)

            st.write("ピック")
            c1,c2,c3 = st.columns(3)
            pick = st.radio(
                label="",
                options=["Home Win","Draw","Away Win"],
                index= {"H":0,"D":1,"A":2}.get(my_bet["pick"], 0) if my_bet else 0,
                horizontal=False,
                key=f"pick_{m['id']}"
            )
            stake = st.number_input(
                "ステーク",
                min_value=0, step=int(conf.get("stake_step","100")),
                value=int(my_bet["stake"]) if my_bet else int(conf.get("stake_step","100")),
                key=f"stake_{m['id']}"
            )

            # ボタン
            disabled = locked
            if locked:
                st.error("LOCKED（締切）")
            if st.button("この内容でベット", key=f"bet_{m['id']}", disabled=disabled):
                # 上限チェック
                new_total = total_stake - (int(my_bet["stake"]) if my_bet else 0) + stake
                limit = int(conf.get("max_total_stake_per_gw","5000"))
                if new_total > limit:
                    st.error(f"このベットで上限 {limit} を超えます。現在 {total_stake}。")
                else:
                    pick_code = {"Home Win":"H","Draw":"D","Away Win":"A"}[pick]
                    used_odds = {"H":home_odds,"D":draw_odds,"A":away_odds}[pick_code]
                    row = {
                        "key": my_bet["key"] if my_bet else str(uuid.uuid4()),
                        "gw": gw,
                        "user": user,
                        "match_id": str(m["id"]),
                        "match": f"{m['home']} vs {m['away']}",
                        "pick": pick_code,
                        "stake": str(stake),
                        "odds": f"{used_odds:.2f}",
                        "placed_at": now_utc().isoformat(),
                        "status": "open",
                        "result": "",
                        "payout": "",
                        "net": "",
                        "settled_at": ""
                    }
                    upsert_bet(my_bet, row)
                    st.success("ベットを記録しました！")
                    st.rerun()

# ─────────────────────────────────────
# メイン
# ─────────────────────────────────────
def main():
    st.set_page_config(page_title="Premier Picks", page_icon="⚽", layout="wide")
    conf = read_config()
    ensure_auth(conf)

    # ヘッダー
    left, right = st.columns([1,1])
    with left:
        if st.button("ログアウト"):
            for k in list(st.session_state.keys()):
                st.session_state.pop(k, None)
            st.rerun()
    with right:
        st.write(f"ログイン中：**{st.session_state['user']['name']}**  ({st.session_state['user'].get('role','user')})")

    tabs = st.tabs(["🏠 トップ","🎯 試合とベット","📁 履歴","⏱️ リアルタイム","🛠️ オッズ管理"])
    with tabs[0]:
        render_top(conf)
    with tabs[1]:
        page_matches_and_bets(conf)
    with tabs[2]:
        render_history()
    with tabs[3]:
        render_realtime()
    with tabs[4]:
        render_odds_admin(conf)

if __name__ == "__main__":
    main()
