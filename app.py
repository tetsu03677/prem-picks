import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

import pytz
import streamlit as st

from google_sheets_client import (
    read_config_map,
    read_rows_by_sheet,
    upsert_row,
)
from football_api import (
    fetch_matches_next_gw,
    fetch_scores_for_match_ids,
    # ★ 追加
    fetch_matches_by_gw,
)

# ------------------------------------------------------------
# スタイル（アイコンは使わない・落ち着いた最小限）
# ------------------------------------------------------------
CSS = """
<style>
/* ← タブ上部が切れないように上マージンを増量 */
.block-container {padding-top:3.2rem; padding-bottom:3rem;}

.app-card{border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:18px; background:rgba(255,255,255,.02);}
.subtle{color:rgba(255,255,255,.6); font-size:.9rem}
.kpi-row{display:flex; gap:12px; flex-wrap:wrap}
.kpi{flex:1 1 140px; border:1px solid rgba(120,120,120,.25); border-radius:10px; padding:10px 14px}
.kpi .h{font-size:.8rem; color:rgba(255,255,255,.55)}
.kpi .v{font-size:1.3rem; font-weight:700; margin-top:2px}
.section{margin:16px 0 10px}
table {width:100%}
.login-hidden {display:none}

/* トップの3分割カード（BM=赤、その他=グレー） */
.role-cards{display:flex; gap:12px; flex-wrap:wrap}
.role-card{flex:1 1 0; min-width:120px; border:1px solid rgba(120,120,120,.25); border-radius:12px; padding:12px 14px; background:rgba(255,255,255,.02)}
.role-card.bm{border-color:rgba(255,0,0,.35); background:rgba(255,255,255,.08)}
.role-card .name{font-weight:700; font-size:1.05rem}
.role-card .role{font-size:.9rem; color:rgba(255,255,255,.7)}
.badges{display:flex; gap:8px; flex-wrap:wrap; margin-top:6px}
.badge{display:inline-block; padding:3px 8px; border-radius:999px; font-size:.85rem;
       border:1px solid rgba(120,120,120,.25); background:rgba(255,255,255,.06)}

/* ログイン見出し（枠なし・少し大きめ。安全策） */
.login-title{font-size:1.5rem; font-weight:700; margin:0 0 8px 2px;}
.login-area{padding:2px 0 0;} /* 余白のみ。枠は出さない */

/* 右上のユーティリティバー（目立ちすぎない） */
.util-bar{display:flex; justify-content:flex-end; gap:8px; margin:-10px 2px 6px 0;}
.util-btn{border:1px solid rgba(120,120,120,.25); border-radius:8px; padding:2px 8px; background:rgba(255,255,255,.03); font-size:.9rem;}
</style>
"""
st.set_page_config(page_title="Premier Picks", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

# ------------------------------------------------------------
# ユーティリティ
# ------------------------------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def parse_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def parse_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def _gw_sort_key(x):
    """GWの並び替え用：GW7 / 7 / None / '' が混在しても安全にソート"""
    s = "" if x is None else str(x).strip()
    n = 999999
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        elif num:
            break
    if num:
        try:
            n = int(num)
        except Exception:
            n = 999999
    return (n, s)

# ---- 追加：ID正規化（数字だけを抜き出して文字列化） ----
def norm_id(x) -> str:
    s = "".join(ch for ch in str(x or "").strip() if ch.isdigit())
    return s or str(x or "").strip()

# ★ 追加：GW番号の安全抽出（"GW7"/"7"→7、失敗時はNone）
def _parse_gw_number(gw_name: str):
    try:
        digits = "".join(ch for ch in str(gw_name or "") if ch.isdigit())
        return int(digits) if digits else None
    except Exception:
        return None

# ------------------------------------------------------------
# キャッシュ・スナップショット戦略
#  - ログイン時のスナップショットを既定として使用
#  - 「データ更新」クリックでのみ世代(rev)を進めて再取得
# ------------------------------------------------------------
def _data_rev() -> int:
    return int(st.session_state.get("_data_rev", 0))

@st.cache_data(show_spinner=False)
def _cached_sheet_rows(sheet: str, rev: int):
    return read_rows_by_sheet(sheet) or []

@st.cache_data(show_spinner=False)
def _cached_fetch_matches_by_gw(conf: Dict[str, str], gw_label: str, rev: int):
    ms, gw = fetch_matches_by_gw(conf, gw_label)
    return ms or [], gw

@st.cache_data(show_spinner=False)
def _cached_fetch_scores(conf: Dict[str, str], ids_tuple: tuple, rev: int):
    ids = list(ids_tuple)
    return fetch_scores_for_match_ids(conf, ids) or {}

def rows(sheet: str):
    return _cached_sheet_rows(sheet, _data_rev())

def api_matches_by_gw(conf: Dict[str, str], gw_label: str):
    ms, _ = _cached_fetch_matches_by_gw(conf, gw_label, _data_rev())
    return ms

def api_scores(conf: Dict[str, str], ids: List[str]):
    return _cached_fetch_scores(conf, tuple(ids), _data_rev())

# ★ 追加：与えたGW表記（"GW7"や"7"）でマッチ取得（両表記を順番に試す／キャッシュ利用）
def _fetch_matches_by_gw_any(conf: Dict[str, str], gw_label: str) -> List[Dict]:
    variants = []
    n = _parse_gw_number(gw_label)
    if gw_label:
        variants.append(str(gw_label))
    if n is not None:
        variants.extend([f"GW{n}", str(n)])
    seen = []
    for v in variants:
        if v in seen:
            continue
        seen.append(v)
        try:
            ms = api_matches_by_gw(conf, v)
            if ms:
                return ms
        except Exception:
            pass
    return []

# ------------------------------------------------------------
# 設定読込
# ------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def get_conf() -> Dict[str, str]:
    return read_config_map()

def get_users(conf: Dict[str, str]) -> List[Dict]:
    users_json = conf.get("users_json", "").strip()
    if not users_json:
        return [{"username": "guest", "password": "guest", "role": "user", "team": ""}]
    try:
        return json.loads(users_json)
    except Exception:
        return [{"username": "guest", "password": "guest", "role": "user", "team": ""}]

# ------------------------------------------------------------
# 右上：データ更新ボタン（景観控えめ）
#   ※ 重複キー回避のため page_id を必須に
# ------------------------------------------------------------
def render_refresh_bar(page_id: str):
    st.markdown('<div class="util-bar"></div>', unsafe_allow_html=True)
    cols = st.columns([1, 0.17])
    with cols[-1]:
        if st.button("データ更新", key=f"btn_data_refresh_{page_id}", use_container_width=True):
            # 世代を進めてキャッシュ全クリア → 同じタブのまま再実行
            st.session_state["_data_rev"] = _data_rev() + 1
            st.cache_data.clear()
            st.toast("最新データを取得しました。", icon="✅")
            st.rerun()

# ------------------------------------------------------------
# 認証（ログイン後はUIを描画しない） ★枠ナシ見出し（既存維持）
# ------------------------------------------------------------
def login_ui(conf: Dict[str, str]) -> Dict:
    if st.session_state.get("signed_in") and st.session_state.get("me"):
        return st.session_state.get("me")

    with st.container():
        st.markdown('<div class="login-area">', unsafe_allow_html=True)
        st.markdown('<div class="login-title">Premier Picks</div>', unsafe_allow_html=True)

        users = get_users(conf)
        usernames = [u["username"] for u in users]
        default_idx = 0

        c1, c2 = st.columns([1, 1])
        with c1:
            user_sel = st.selectbox("ユーザー", usernames, index=default_idx, key="login_user_sel")
        with c2:
            pwd = st.text_input("パスワード", type="password", key="login_pwd")

        if st.button("ログイン", use_container_width=True, key="btn_login"):
            selected = next((u for u in users if u["username"] == user_sel), None)
            if selected and pwd == selected.get("password", ""):
                st.session_state["signed_in"] = True
                st.session_state["me"] = selected
                # ★ ログイン直後はスナップショット世代を0に初期化
                st.session_state["_data_rev"] = 0
                st.success(f"ようこそ {selected['username']} さん！")
                # ログイン成功時に一度だけ同期フラグを落とす
                st.session_state.pop("_synced_once", None)
                st.rerun()
            else:
                st.warning("ユーザー名またはパスワードが違います。」")

        st.markdown("</div>", unsafe_allow_html=True)

    return st.session_state.get("me")

# ------------------------------------------------------------
# 共通: GW の判定（参考用）
# ------------------------------------------------------------
def gw_and_lock_state(conf: Dict[str, str], matches: List[Dict]) -> Tuple[str, bool, datetime]:
    if not matches:
        return conf.get("current_gw", ""), False, None
    earliest = min(m["utc_kickoff"] for m in matches if m.get("utc_kickoff"))
    minutes_before = parse_int(conf.get("lock_minutes_before_earliest", conf.get("odds_freeze_minutes_before_first", 120)), 120)
    lock_at_utc = earliest - timedelta(minutes=minutes_before)
    locked = now_utc() >= lock_at_utc
    gw_name = matches[0].get("gw") or conf.get("current_gw", "")
    return gw_name, locked, lock_at_utc

# ------------------------------------------------------------
# トップ専用：BMカウントと次回担当
# ------------------------------------------------------------
def _get_bm_counts(users: List[str]) -> Dict[str, int]:
    counts = {u: 0 for u in users}
    try:
        rows_ = rows("bm_log")
        for r in rows_:
            u = str(r.get("bookmaker") or r.get("user") or "").strip()
            if u in counts:
                counts[u] += 1
    except Exception:
        pass
    return counts

def _pick_next_bm(users: List[str], counts: Dict[str, int]) -> str:
    order = {u: i for i, u in enumerate(users)}
    return sorted(users, key=lambda u: (counts.get(u, 0), order[u]))[0] if users else ""

# ========== 追加：このGWのブックメーカーを取得 ==========
def get_bookmaker_for_gw(gw_name: str) -> str:
    rows_ = rows("bm_log")
    targets = {str(gw_name).strip(), str(gw_name).replace("GW", "").strip()}
    for r in rows_:
        gw_cell = str(r.get("gw", "")).strip()
        gw_num = str(r.get("gw_number", "")).strip()
        if gw_cell in targets or gw_num in targets:
            return str(r.get("bookmaker") or r.get("user") or "").strip()
    return ""

# ★ 追加：bm_log の最新GW番号を返す（なければ None）
def _get_latest_gw_number_in_bm_log() -> int:
    try:
        rows_ = rows("bm_log")
        cand = []
        for r in rows_:
            n = None
            if r.get("gw_number"):
                try:
                    n = int(str(r["gw_number"]).strip())
                except Exception:
                    n = None
            if n is None and r.get("gw"):
                n = _parse_gw_number(r["gw"])
            if n is not None:
                cand.append(n)
        return max(cand) if cand else None
    except Exception:
        return None

# ★ 追加：前節が全試合確定かを判定
def _is_gw_finished(conf: Dict[str, str], gw_label: str) -> bool:
    try:
        matches = _fetch_matches_by_gw_any(conf, gw_label)
        if not matches:
            return False
        ids = [norm_id(m.get("id")) for m in matches if m.get("id")]
        if not ids:
            return False
        scores = api_scores(conf, ids)
        def _done(s):
            stt = (s.get("status") or "").upper()
            return stt in ("FINISHED", "AWARDED")
        for mid in ids:
            sc = scores.get(mid) or {}
            if not _done(sc):
                return False
        return True
    except Exception:
        return False

def get_active_gw_label(conf: Dict[str, str]) -> str:
    """
    bm_log を起点に「現在アクティブなGW（表示や権限制御で使うGW）」を返す。
    - 最新GWが全試合終了していれば → GW{最新+1}
    - 終了していなければ → GW{最新}
    - bm_logが空 or 異常時は conf.current_gw をフォールバック
    """
    try:
        gw_max = parse_int(conf.get("gw_max", 38), 38)
        latest_n = _get_latest_gw_number_in_bm_log()
        if latest_n is None:
            return conf.get("current_gw", "").strip()

        prev_label = f"GW{latest_n}"
        next_label = f"GW{latest_n + 1}"

        if latest_n >= gw_max:
            return prev_label
        if _is_gw_finished(conf, prev_label):
            return next_label
        return prev_label
    except Exception:
        return conf.get("current_gw", "").strip()

# ★ 変更：bm_log の「最新GW+1」を“次節”として自動確定して追記（より厳密）
def auto_assign_bm_if_needed(conf: Dict[str, str]):
    try:
        gw_max = parse_int(conf.get("gw_max", 38), 38)
        latest_n = _get_latest_gw_number_in_bm_log()
        if latest_n is None:
            return

        prev_label = f"GW{latest_n}"
        next_n = latest_n + 1
        next_label = f"GW{next_n}"

        if get_bookmaker_for_gw(next_label):
            return
        if next_n > gw_max:
            return
        if not _is_gw_finished(conf, prev_label):
            return

        users_conf = get_users(conf)
        users = [u["username"] for u in users_conf]
        counts = _get_bm_counts(users)
        next_bm = _pick_next_bm(users, counts)
        if not next_bm:
            return

        row = {
            "gw": next_label,
            "gw_number": str(next_n),
            "bookmaker": next_bm,
            "decided_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        upsert_row("bm_log", row, key_cols=["gw", "gw_number"])
        return

    except Exception:
        pass

# ★ 追加：次節BMのトースト通知（セッション内で初回だけ）
def _toast_next_bm_once(conf: Dict[str, str], me: Dict):
    try:
        if st.session_state.get("_bm_toast_done"):
            return
        latest_n = _get_latest_gw_number_in_bm_log()
        if latest_n is None:
            return
        next_label = f"GW{latest_n+1}"
        bm = get_bookmaker_for_gw(next_label)
        if not bm:
            return
        if me and me.get("username") == bm:
            st.toast(f"次節 {next_label} のBMはあなた（{bm}）です。オッズを確定してください。", icon="✅")
        else:
            st.toast(f"次節 {next_label} のBMは {bm} です。BM以外のメンバーは『試合とベット』からベッティングしてください。", icon="ℹ️")
        st.session_state["_bm_toast_done"] = True
    except Exception:
        pass

# ------------------------------------------------------------
# ★★★ 追加：結果同期＋自動精算（result & bets を更新）＋ fd_match_id 自動補完 ★★★
#   ※ 同期処理は“書き込み”なのでキャッシュを使わず生I/Oで実施
# ------------------------------------------------------------
def sync_results_and_settle(conf: Dict[str, str]):
    try:
        odds_rows = read_rows_by_sheet("odds") or []
        bets_rows = read_rows_by_sheet("bets") or []

        def _norm_name(s: str) -> str:
            s = (s or "").lower().strip()
            for t in [" fc", ".", ",", "-", "  "]:
                s = s.replace(t, " ")
            return " ".join(s.split())

        need_fix = [r for r in odds_rows if not str(r.get("fd_match_id") or "").strip()
                    and str(r.get("gw") or "").strip() and str(r.get("home") or "").strip() and str(r.get("away") or "").strip()]
        gw_set = sorted({str(r.get("gw")).strip() for r in need_fix})
        fd_lookup_by_gw = {}
        for gw in gw_set:
            try:
                api_matches, _ = fetch_matches_by_gw(conf, gw)
                lut = {}
                for m in api_matches:
                    key = (_norm_name(m["home"]), _norm_name(m["away"]))
                    lut[key] = norm_id(m["id"])
                fd_lookup_by_gw[gw] = lut
            except Exception:
                fd_lookup_by_gw[gw] = {}

        fixed_any = False
        for r in need_fix:
            gw = str(r.get("gw")).strip()
            key = (_norm_name(r.get("home")), _norm_name(r.get("away")))
            fd_id = fd_lookup_by_gw.get(gw, {}).get(key)
            if fd_id:
                newrow = dict(r)
                newrow["fd_match_id"] = fd_id
                newrow["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
                upsert_row("odds", newrow, key_cols=["match_id", "gw"])
                fixed_any = True

        if fixed_any:
            odds_rows = read_rows_by_sheet("odds") or []

        in2fd = {}
        meta_by_fd = {}
        for r in odds_rows:
            in_id = norm_id(r.get("match_id"))
            fd_id = norm_id(r.get("fd_match_id"))
            if fd_id:
                in2fd[in_id] = fd_id
                meta_by_fd[fd_id] = {
                    "gw": r.get("gw", ""),
                    "home": r.get("home", ""),
                    "away": r.get("away", ""),
                }

        candidate_fd_ids = sorted({v for v in in2fd.values() if v})
        if not candidate_fd_ids:
            return

        result_rows = read_rows_by_sheet("result") or []
        result_by_fd = {norm_id(r.get("match_id")): r for r in result_rows if r.get("match_id")}

        scores = fetch_scores_for_match_ids(conf, candidate_fd_ids) or {}

        for fd in candidate_fd_ids:
            sc = scores.get(fd) or {}
            status = (sc.get("status") or "").upper()
            if status not in ("FINISHED", "AWARDED"):
                continue
            home_score = parse_int(sc.get("home_score"), 0)
            away_score = parse_int(sc.get("away_score"), 0)
            winner = "DRAW" if home_score == away_score else ("HOME" if home_score > away_score else "AWAY")
            exist = result_by_fd.get(fd) or {}
            meta = meta_by_fd.get(fd, {})
            if (parse_int(exist.get("home_score"), -999) != home_score) or \
               (parse_int(exist.get("away_score"), -999) != away_score) or \
               ((exist.get("status") or "").upper() != status):
                row = {
                    "match_id": fd,
                    "gw": exist.get("gw") or meta.get("gw", ""),
                    "home": exist.get("home") or meta.get("home", ""),
                    "away": exist.get("away") or meta.get("away", ""),
                    "status": status,
                    "home_score": str(home_score),
                    "away_score": str(away_score),
                    "winner": winner,
                    "finalized_at": datetime.utcnow().isoformat(timespec="seconds"),
                    "source": "football-data",
                    "raw_json": "",
                    "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
                }
                upsert_row("result", row, key_col="match_id")
                result_by_fd[fd] = row

        if result_by_fd:
            for b in bets_rows:
                if (b.get("status") or "").upper() != "OPEN":
                    continue
                internal_mid = norm_id(b.get("match_id"))
                fd_id = in2fd.get(internal_mid)
                if not fd_id:
                    continue
                res = result_by_fd.get(fd_id)
                if not res:
                    continue
                stake = parse_int(b.get("stake"), 0)
                odds = parse_float(b.get("odds"), 1.0) or 1.0
                pick = (b.get("pick") or "").upper()
                winner = (res.get("winner") or "").upper()
                win_flag = (pick == winner)
                payout = float(stake) * float(odds) if win_flag else 0.0
                net = payout - float(stake)
                row = dict(b)
                row.update({
                    "status": "SETTLED",
                    "result": "WIN" if win_flag else "LOSE",
                    "payout": f"{payout:.2f}",
                    "net": f"{net:.2f}",
                    "settled_at": datetime.utcnow().isoformat(timespec="seconds"),
                })
                upsert_row("bets", row, key_col="key")
    except Exception:
        pass

# ------------------------------------------------------------
# UI: トップ（BM表示＋カウンタ）
# ------------------------------------------------------------
def page_home(conf: Dict[str, str], me: Dict):
    render_refresh_bar("home")
    st.markdown("## トップ")
    st.info("ここでは簡単なガイドだけを表示。実際の操作は上部タブから。")
    if me:
        st.caption(f"ログイン中： {me['username']} ({me.get('role','')})")

    users_conf = get_users(conf)
    users = [u["username"] for u in users_conf]

    latest_n = _get_latest_gw_number_in_bm_log()
    current_bm = ""
    current_gw_label = ""
    if latest_n is not None:
        current_gw_label = f"GW{latest_n}"
        current_bm = get_bookmaker_for_gw(current_gw_label)

    st.markdown('<div class="section">今節のメンバー（bm_log基準）</div>', unsafe_allow_html=True)
    st.markdown('<div class="role-cards">', unsafe_allow_html=True)
    for u in users:
        is_bm = (u == current_bm)
        role_txt = "Bookmaker" if is_bm else "Player"
        card_class = "role-card bm" if is_bm else "role-card"
        html = (
            f'<div class="{card_class}">'
            f'<div class="name">{u}</div>'
            f'<div class="role">{role_txt}</div>'
            f'</div>'
        )
        st.markdown(html, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if current_gw_label:
        st.caption(f"今節: {current_gw_label}／Bookmaker: {current_bm or '-'}（bm_logの最新行を参照）")

    counts = _get_bm_counts(users)
    st.markdown('<div class="section">ブックメーカー担当回数（これまで）</div>', unsafe_allow_html=True)
    badges = " ".join([f'<span class="badge">{u}: {counts.get(u,0)}</span>' for u in users])
    st.markdown(f'<div class="badges">{badges}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------
# UI: 試合とベット（GW基準＝get_active_gw_label）
# ------------------------------------------------------------
def page_matches_and_bets(conf: Dict[str, str], me: Dict):
    render_refresh_bar("bets")
    st.markdown("## 試合とベット")

    gw_name = get_active_gw_label(conf)
    current_bm = get_bookmaker_for_gw(gw_name)
    matches_raw = _fetch_matches_by_gw_any(conf, gw_name)

    if current_bm and me.get("username") == current_bm:
        st.warning(f"このGW（{gw_name}）はあなたがブックメーカーです。ベッティングは禁止です。")
        return

    bets_all = rows("bets")
    my_gw_bets = [b for b in bets_all if (b.get("user") == me["username"] and (b.get("gw") == gw_name or b.get("gw") == gw_name.replace("GW","")))]
    my_total = sum(parse_int(b.get("stake", 0)) for b in my_gw_bets)
    max_total = parse_int(conf.get("max_total_stake_per_gw", 5000), 5000)
    st.markdown(f'<div class="kpi-row"><div class="kpi"><div class="h">このGWのあなたの投票合計</div><div class="v">{my_total:,} / 上限 {max_total:,}</div></div></div>', unsafe_allow_html=True)

    if not matches_raw:
        st.info("このGWに表示できる試合がありません。")
        return

    odds_rows = rows("odds")
    odds_by_match = {str(r.get("match_id")): r for r in odds_rows if r.get("match_id")}

    step = parse_int(conf.get("stake_step", 100), 100)
    lock_minutes = parse_int(conf.get("odds_freeze_minutes_before_first", 120), 120)

    def latest_my_bet_for_match(match_id: str):
        rows_ = [b for b in my_gw_bets if str(b.get("match_id")) == match_id]
        if not rows_:
            return None
        def _row_ts(b):
            ts = b.get("placed_at") or ""
            try:
                return datetime.fromisoformat(ts)
            except Exception:
                k = str(b.get("key",""))
                if ":" in k:
                    tail = k.split(":")[-1]
                    try:
                        return datetime.fromisoformat(tail)
                    except Exception:
                        return datetime.min.replace(tzinfo=None)
                return datetime.min.replace(tzinfo=None)
        rows_.sort(key=_row_ts, reverse=True)
        return rows_[0]

    picks, stakes = {}, {}
    defaults, odds_map, meta_home = {}, {}, {}
    locked_map, ready_map = {}, {}

    with st.form("bets_bulk_form", clear_on_submit=False):
        for m in matches_raw:
            match_id = str(m["id"])
            teams_line = f"{m['home']} vs {m['away']}"
            lock_at = m["utc_kickoff"] - timedelta(minutes=lock_minutes) if m.get("utc_kickoff") else None
            locked_this = (now_utc() >= lock_at) if lock_at else False

            od = odds_by_match.get(match_id, {})
            home_odds = parse_float(od.get("home_win"), 1.0)
            draw_odds = parse_float(od.get("draw"), 1.0)
            away_odds = parse_float(od.get("away_win"), 1.0)

            is_odds_ready = (
                str(od.get("locked", "")).upper() == "YES"
                and (home_odds is not None and draw_odds is not None and away_odds is not None)
                and (home_odds > 1.0 and draw_odds > 1.0 and away_odds > 1.0)
            )

            last = latest_my_bet_for_match(match_id)
            default_pick = (last.get("pick") if last else "HOME")
            default_stake = parse_int(last.get("stake"), 0) if last else 0

            with st.container(border=True):
                st.markdown(f"**{gw_name}**　・　{m['local_kickoff'].strftime('%m/%d %H:%M')}")
                st.markdown(f"### {teams_line}")
                st.caption("（この試合はキックオフ2時間前に個別ロック）")

                if od:
                    st.caption(f"Home: {home_odds:.2f} / Draw: {draw_odds:.2f} / Away: {away_odds:.2f}")
                else:
                    st.info("オッズ未入力のため仮オッズ (=1.0) を表示中。管理者は『オッズ管理』で設定してください。")
                    st.caption(f"Home: {home_odds:.2f} / Draw: {draw_odds:.2f} / Away: {away_odds:.2f}")

                if not is_odds_ready:
                    st.warning("オッズ未確定のためベッティング不可。ブックメーカーが確定してください。")

                mine = [b for b in my_gw_bets if str(b.get("match_id")) == match_id]
                summary = {"HOME":0,"DRAW":0,"AWAY":0}
                for b in mine:
                    summary[b.get("pick","")] = summary.get(b.get("pick",""),0) + parse_int(b.get("stake",0))
                st.caption(f"現在のベット状況（あなた）: HOME {summary['HOME']} / DRAW {summary['DRAW']} / AWAY {summary['AWAY']}")

                c1, c2 = st.columns([2,1])
                disabled_flag = (locked_this or (not is_odds_ready))
                with c1:
                    pick = st.radio(
                        "ピック",
                        ["HOME","DRAW","AWAY"],
                        index=["HOME","DRAW","AWAY"].index(default_pick) if default_pick in ["HOME","DRAW","AWAY"] else 0,
                        key=f"pick_{match_id}",
                        horizontal=True,
                        disabled=disabled_flag
                    )
                with c2:
                    stake = st.number_input(
                        "ステーク",
                        min_value=0,
                        step=step,
                        value=default_stake,
                        key=f"stake_{match_id}",
                        disabled=disabled_flag
                    )

            picks[match_id] = pick
            stakes[match_id] = int(stake)
            defaults[match_id] = int(default_stake)
            odds_map[match_id] = {"HOME": home_odds, "DRAW": draw_odds, "AWAY": away_odds}
            meta_home[match_id] = m["home"]
            locked_map[match_id] = locked_this
            ready_map[match_id] = is_odds_ready

        submitted_bulk = st.form_submit_button("このGWのベットを一括保存", use_container_width=True)

    # ★ デバウンス：多重保存を抑止
    if submitted_bulk:
        if st.session_state.get("_bets_saving"):
            st.info("保存処理中です…（二重送信は無視されます）")
            return
        st.session_state["_bets_saving"] = True
        try:
            proposed_total = my_total
            for mid in stakes.keys():
                if locked_map.get(mid) or not ready_map.get(mid):
                    continue
                proposed_total += int(stakes[mid]) - int(defaults[mid])

            if proposed_total > max_total:
                st.warning(f"このGWの投票上限（{max_total:,}）を超えます。現在 {my_total:,} → 変更後 {proposed_total:,}")
                return

            saved, skipped = 0, []
            for mid in stakes.keys():
                if locked_map.get(mid):
                    skipped.append((mid, "ロック済のためスキップ"))
                    continue
                if not ready_map.get(mid):
                    skipped.append((mid, "オッズ未確定のためスキップ"))
                    continue

                new_pick = picks[mid]
                new_stake = int(stakes[mid])
                old_stake = int(defaults[mid])

                last = next((b for b in my_gw_bets if str(b.get("match_id")) == mid), None)
                old_pick = (last.get("pick") if last else "HOME")
                if (new_pick == old_pick) and (new_stake == old_stake):
                    continue

                use_odds = odds_map[mid][new_pick]
                fixed_key = f"{gw_name}:{me['username']}:{mid}"
                row = {
                    "key": fixed_key,
                    "gw": gw_name,
                    "user": me["username"],
                    "match_id": mid,
                    "match": meta_home[mid],
                    "pick": new_pick,
                    "stake": str(int(new_stake)),
                    "odds": str(use_odds),
                    "placed_at": datetime.utcnow().isoformat(timespec="seconds"),
                    "status": "OPEN",
                    "result": "", "payout": "", "net": "", "settled_at": "",
                }
                upsert_row("bets", row, key_col="key")
                saved += 1

            if saved > 0:
                st.success(f"ベットを一括保存しました（更新 {saved} 件）。")
            if skipped:
                msg = " / ".join([f"{k}: {reason}" for k, reason in skipped])
                st.info(f"スキップ：{msg}")
        finally:
            st.session_state["_bets_saving"] = False

# ------------------------------------------------------------
# UI: 履歴（ユーザー切替あり）
# ------------------------------------------------------------
def page_history(conf: Dict[str, str], me: Dict):
    render_refresh_bar("history")
    st.markdown("## 履歴")

    bets = rows("bets")
    if not bets:
        st.info("履歴はまだありません。")
        return

    gw_vals = {(b.get("gw") if b.get("gw") not in (None, "") else "") for b in bets}
    gw_set = sorted(gw_vals, key=_gw_sort_key)
    sel_gw = st.selectbox("表示するGW", gw_set, index=0 if gw_set else None, key="hist_gw")

    all_users = sorted({b.get("user") for b in bets if b.get("user")})
    my_name = me.get("username")
    admin_only = str(conf.get("admin_only_view_others", "false")).lower() == "true"
    can_view_others = (me.get("role") == "admin") or (not admin_only)

    opts = [my_name] + [u for u in all_users if u != my_name and can_view_others]
    label_map = {u: (f"{u}（自分）" if u == my_name else u) for u in opts}
    sel_label = st.selectbox(
        "ユーザー",
        [label_map[u] for u in opts],
        index=0,
        key="hist_user",
        help="既定は自分。他ユーザーはプレビュー表示（編集はできません）。"
    )
    inv_label = {v: k for k, v in label_map.items()}
    sel_user = inv_label.get(sel_label, my_name)

    target = [b for b in bets if (b.get("gw") == sel_gw and b.get("user") == sel_user)]
    if not target:
        st.info("対象のデータがありません。")
        return

    total_stake = sum(parse_int(b.get("stake", 0)) for b in target)
    total_payout = sum(parse_float(b.get("payout"), 0.0) or 0.0 for b in target if (b.get("result") in ["WIN","LOSE"]))
    total_net = total_payout - total_stake
    badge = "（閲覧）" if sel_user != my_name else ""
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="h">合計ステーク（{sel_user}{badge}）</div><div class="v">{total_stake:,}</div></div>
      <div class="kpi"><div class="h">合計ペイアウト（{sel_user}{badge}）</div><div class="v">{total_payout:,.2f}</div></div>
      <div class="kpi"><div class="h">合計収支（{sel_user}{badge}）</div><div class="v">{total_net:,.2f}</div></div>
    </div>
    """
    st.markdown(kpi_html, unsafe_allow_html=True)

    odds_rows = rows("odds") or []
    away_lut = {}
    for r in odds_rows:
        gw = str(r.get("gw") or "")
        mid = str(r.get("match_id") or "")
        away_lut[(gw, mid)] = r.get("away", "")

    def row_view(b):
        stake = parse_int(b.get("stake", 0))
        odds = parse_float(b.get("odds"), 1.0) or 1.0
        result = (b.get("result") or "").upper()

        pick = (b.get("pick") or "").upper()
        if pick == "HOME":
            pred_team = b.get("match", "")
        elif pick == "AWAY":
            pred_team = away_lut.get((b.get("gw"), str(b.get("match_id"))), "AWAY")
        else:
            pred_team = "Draw"

        if result in ["WIN", "LOSE"]:
            payout = parse_float(b.get("payout"), stake * odds if result == "WIN" else 0.0) or 0.0
            net = payout - stake
            res_tag = "Hit!!" if result == "WIN" else "Miss"
            st.markdown(f"・{b.get('user','')}｜[Pred] {pred_team}｜[Res] {res_tag}｜{stake} at {odds:.2f}→{payout:.2f}（net {net:.2f}）")
        else:
            st.markdown(f"・{b.get('user','')}｜[Pred] {pred_team}｜[Res] -｜{stake} at {odds:.2f}→-（net -）")

    for b in target:
        row_view(b)

# ------------------------------------------------------------
# UI: リアルタイム（GW基準＝get_active_gw_label）
# ------------------------------------------------------------
def page_realtime(conf: Dict[str, str], me: Dict):
    render_refresh_bar("realtime")
    st.markdown("## リアルタイム")
    st.caption("更新ボタンで最新スコアを手動取得。自動更新はしません。")

    gw = get_active_gw_label(conf)
    matches_raw = _fetch_matches_by_gw_any(conf, gw)

    api_ids = [norm_id(m["id"]) for m in matches_raw]
    api_meta = {norm_id(m["id"]): {"home": m["home"], "away": m["away"], "utc_kickoff": m.get("utc_kickoff")} for m in matches_raw}

    odds_rows = rows("odds")
    bets_rows = rows("bets")

    gw_odds = [r for r in odds_rows if str(r.get("gw", "")) == str(gw)]
    gw_bets = [r for r in bets_rows if str(r.get("gw", "")) == str(gw)]

    in2fd = {}
    for r in gw_odds:
        in_id = norm_id(r.get("match_id"))
        fd_id = norm_id(r.get("fd_match_id"))
        if fd_id:
            in2fd[in_id] = fd_id

    def has_teams(r):
        return bool(str(r.get("home","")).strip() and str(r.get("away","")).strip())

    odds_ids = [norm_id(r.get("fd_match_id")) for r in gw_odds if r.get("fd_match_id") and has_teams(r)]
    bet_ids = []
    for r in gw_bets:
        internal_mid = norm_id(r.get("match_id"))
        fd = in2fd.get(internal_mid)
        if fd:
            bet_ids.append(fd)

    for r in gw_odds:
        fd = norm_id(r.get("fd_match_id"))
        if fd and fd not in api_meta and has_teams(r):
            api_meta[fd] = {"home": r.get("home"), "away": r.get("away"), "utc_kickoff": None}

    candidate_ids = sorted(list({*api_ids, *odds_ids, *bet_ids}))

    scores = api_scores(conf, candidate_ids)

    def is_active(fd):
        s = scores.get(fd, {})
        status = (s.get("status") or "").upper()
        return status not in ("FINISHED", "AWARDED")

    active_ids = [fd for fd in candidate_ids if is_active(fd)]

    odds_by_fd = {}
    for r in gw_odds:
        fd = norm_id(r.get("fd_match_id"))
        if fd:
            odds_by_fd[fd] = r

    def current_payout(b):
        internal_mid = norm_id(b.get("match_id"))
        fd = in2fd.get(internal_mid)
        if not fd:
            return 0.0
        stake = parse_int(b.get("stake", 0))
        pick = b.get("pick", "")
        odds = parse_float(b.get("odds"), None)
        if odds is None:
            odrow = odds_by_fd.get(fd, {})
            odds_key = {"HOME":"home_win","DRAW":"draw","AWAY":"away_win"}.get(pick)
            odds = parse_float(odrow.get(odds_key), 1.0)
        sc = scores.get(fd)
        if not sc:
            return 0.0
        status = sc.get("status")
        hs, as_ = sc.get("home_score", 0), sc.get("away_score", 0)
        if status in ("SCHEDULED", "TIMED", "POSTPONED"):
            return 0.0
        if status in ("FINISHED", "AWARDED"):
            winner = "DRAW" if hs == as_ else ("HOME" if hs > as_ else "AWAY")
            return stake * odds if pick == winner else 0.0
        if hs == as_:
            return stake * odds if pick == "DRAW" else 0.0
        winner_now = "HOME" if hs > as_ else "AWAY"
        return stake * odds if pick == winner_now else 0.0

    this_gw_bets = [b for b in bets_rows if (b.get("gw") == gw)]
    total_stake = sum(parse_int(b.get("stake", 0)) for b in this_gw_bets)
    total_curr = sum(current_payout(b) for b in this_gw_bets)
    total_net = total_curr - total_stake

    st.markdown(
        f"""
        <div class="kpi-row">
          <div class="kpi"><div class="h">このGW ステーク合計</div><div class="v">{total_stake:,}</div></div>
          <div class="kpi"><div class="h">想定ペイアウト</div><div class="v">{total_curr:,.2f}</div></div>
          <div class="kpi"><div class="h">この時点の想定収支</div><div class="v">{total_net:,.2f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    users = sorted(list({b.get("user") for b in this_gw_bets if b.get("user")}))
    current_bm = get_bookmaker_for_gw(gw)
    if users:
        st.markdown('<div class="section">ユーザー別の時点収支</div>', unsafe_allow_html=True)
        user_net = {}
        for u in users:
            ub = [b for b in this_gw_bets if b.get("user") == u]
            ustake = sum(parse_int(b.get("stake", 0)) for b in ub)
            upayout = sum(current_payout(b) for b in ub)
            user_net[u] = upayout - ustake

        if current_bm:
            others_net_sum = sum(v for k, v in user_net.items() if k != current_bm)
            user_net[current_bm] = -others_net_sum

        disp_users = list(users)
        cols = st.columns(max(2, min(4, len(disp_users))))
        for i, u in enumerate(disp_users):
            ub = [b for b in this_gw_bets if b.get("user") == u]
            ustake = sum(parse_int(b.get("stake", 0)) for b in ub)
            upayout = sum(current_payout(b) for b in ub)
            unat = user_net.get(u, upayout - ustake)
            with cols[i % len(cols)]:
                st.markdown(f'<div class="kpi"><div class="h">{u}{"（BM）" if u==current_bm else ""}</div><div class="v">{unat:,.2f}</div><div class="h">stake {ustake:,} / payout {upayout:,.2f}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="section">試合別（現在スコアに基づく暫定：未開始＋進行中）</div>', unsafe_allow_html=True)

    def kickoff_key(fd):
        info = api_meta.get(fd, {})
        ko = info.get("utc_kickoff")
        return (0, ko) if ko else (1, None)

    def bet_fd(b):
        return in2fd.get(norm_id(b.get("match_id")))

    for fd in sorted(active_ids, key=kickoff_key):
        info = api_meta.get(fd)
        if not info:
            continue
        s = scores.get(fd, {})
        hs, as_ = s.get("home_score", 0), s.get("away_score", 0)
        st.markdown(f"**{info['home']} vs {info['away']}**　（{s.get('status','-')}　{hs}-{as_}）")
        rows_ = [b for b in this_gw_bets if bet_fd(b) == fd]
        if not rows_:
            st.caption("（ベットなし）")
            continue
        for b in rows_:
            cp = current_payout(b)
            st.caption(f"- {b.get('user')}：{b.get('pick')} / {b.get('stake')} at {b.get('odds')} → 時点 {cp:,.2f}")

    st.button("スコアを更新", use_container_width=True)

# ------------------------------------------------------------
# UI: ダッシュボード
# ------------------------------------------------------------
def page_dashboard(conf: Dict[str, str], me: Dict):
    render_refresh_bar("dashboard")
    st.markdown("## ダッシュボード")

    bets = rows("bets")
    if not bets:
        st.info("データがありません。")
        return

    my_name = me.get("username")
    my_bets = [b for b in bets if b.get("user") == my_name]

    total_stake = sum(parse_int(b.get("stake", 0)) for b in my_bets)
    total_payout = sum((parse_float(b.get("payout"), 0.0) or 0.0)
                       for b in my_bets if (b.get("result") in ["WIN", "LOSE"]))
    total_net = total_payout - total_stake

    st.markdown(
        f"""
        <div class="kpi-row">
          <div class="kpi"><div class="h">トータル収支（{my_name}）</div><div class="v">{total_net:,.2f}</div></div>
          <div class="kpi"><div class="h">総支出額（stake）</div><div class="v">{total_stake:,}</div></div>
          <div class="kpi"><div class="h">トータル収入額（payout）</div><div class="v">{total_payout:,.2f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    users = sorted(list({b.get("user") for b in bets if b.get("user")}))
    others = [u for u in users if u != my_name]
    if others:
        st.markdown('<div class="section">他ユーザー（参考）</div>', unsafe_allow_html=True)
        cols = st.columns(max(2, min(4, len(others))))
        for i, u in enumerate(others):
            ub = [b for b in bets if b.get("user") == u]
            ustake = sum(parse_int(b.get("stake", 0)) for b in ub)
            upayout = sum((parse_float(b.get("payout"), 0.0) or 0.0)
                          for b in ub if (b.get("result") in ["WIN", "LOSE"]))
            unat = upayout - ustake
            with cols[i % len(cols)]:
                st.markdown(
                    f'<div class="kpi"><div class="h">{u}</div>'
                    f'<div class="v">{unat:,.2f}</div>'
                    f'<div class="h">stake {ustake:,} / payout {upayout:,.2f}</div></div>',
                    unsafe_allow_html=True
                )

    st.markdown('<div class="section">ユーザー別：的中率が高いチーム TOP3（最低3ベット）</div>', unsafe_allow_html=True)

    by_team = {}
    for b in my_bets:
        if (b.get("result") or "").upper() not in ["WIN", "LOSE"]:
            continue
        pick = b.get("pick")
        team = ""
        if pick == "HOME":
            team = b.get("match", "")
        elif pick == "AWAY":
            team = "AWAY"
        else:
            continue

        by_team.setdefault(team, {"n": 0, "win": 0, "net": 0.0})
        by_team[team]["n"] += 1
        if (b.get("result") or "").upper() == "WIN":
            by_team[team]["win"] += 1
            by_team[team]["net"] += (parse_float(b.get("payout"), 0.0) or 0.0) - parse_int(b.get("stake", 0))
        else:
            by_team[team]["net"] -= parse_int(b.get("stake", 0))

    stats = []
    for t, v in by_team.items():
        if v["n"] >= 3:
            acc = v["win"] / v["n"]
            stats.append((t, acc, v["n"], v["net"]))
    if not stats:
        st.caption("　対象データ不足（3ベット未満）")
    else:
        stats.sort(key=lambda x: (-x[1], -x[3]))
        for t, acc, n, net in stats[:3]:
            st.caption(f"　- {t}: 的中率 {acc*100:.1f}%（{n}件）／ 累計net {net:,.2f}")

# ------------------------------------------------------------
# UI: オッズ管理（GW基準＝get_active_gw_label）
# ------------------------------------------------------------
def page_odds_admin(conf: Dict[str, str], me: Dict):
    render_refresh_bar("odds")
    st.markdown("## オッズ管理")
    is_admin = (me.get("role") == "admin")
    if not is_admin:
        st.info("閲覧のみ（管理者のみ編集可能）")

    gw = get_active_gw_label(conf)
    matches_raw = _fetch_matches_by_gw_any(conf, gw)
    if not matches_raw:
        st.info(f"{gw} の試合がAPIから取得できません。必要に応じて odds シートに試合を追加してください。")
        return

    odds_rows = rows("odds")
    odds_by_match = {str(r.get("match_id")): r for r in odds_rows if r.get("match_id")}

    for m in matches_raw:
        mid = str(m["id"])
        od = odds_by_match.get(mid, {})
        with st.container(border=True):
            st.markdown(f"**{m['home']} vs {m['away']}**　（{gw}）")

            with st.form(f"odds_form_{mid}", clear_on_submit=False):
                c1, c2, c3, c4, c5 = st.columns([1,1,1,0.9,1.2])
                with c1:
                    home = st.number_input("Home", min_value=1.01, step=0.1,
                                           value=parse_float(od.get("home_win"), 1.01),
                                           key=f"od_h_{mid}", disabled=not is_admin)
                with c2:
                    draw = st.number_input("Draw", min_value=1.01, step=0.1,
                                           value=parse_float(od.get("draw"), 1.01),
                                           key=f"od_d_{mid}", disabled=not is_admin)
                with c3:
                    away = st.number_input("Away", min_value=1.01, step=0.1,
                                           value=parse_float(od.get("away_win"), 1.01),
                                           key=f"od_a_{mid}", disabled=not is_admin)
                with c4:
                    confirm = st.checkbox("オッズを確定（公開）", value=(str(od.get("locked","")).upper()=="YES"),
                                          key=f"od_locked_{mid}", disabled=not is_admin)
                with c5:
                    submitted = st.form_submit_button("保存", disabled=not is_admin, use_container_width=True)

                if submitted and is_admin:
                    if home <= 1.0 or draw <= 1.0 or away <= 1.0:
                        st.warning("3つのオッズはすべて 1.01 以上で入力してください。")
                    else:
                        row = {
                            "gw": gw,
                            "match_id": mid,
                            "home": m["home"],
                            "away": m["away"],
                            "home_win": str(home),
                            "draw": str(draw),
                            "away_win": str(away),
                            "locked": "YES" if confirm else "",
                            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
                        }
                        upsert_row("odds", row, key_cols=["match_id", "gw"])
                        st.success("保存しました。")

# ------------------------------------------------------------
# メイン
# ------------------------------------------------------------
def main():
    conf = get_conf()

    me = login_ui(conf)
    if not me:
        st.stop()

    # ★ ログイン後に一度だけ同期（result更新＆bets精算）
    if not st.session_state.get("_synced_once"):
        sync_results_and_settle(conf)
        auto_assign_bm_if_needed(conf)
        _toast_next_bm_once(conf, me)
        st.session_state["_synced_once"] = True

    tabs = st.tabs(["トップ", "試合とベット", "履歴", "リアルタイム", "ダッシュボード", "オッズ管理"])

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
    with tabs[5]:
        page_odds_admin(conf, me)

if __name__ == "__main__":
    main()
