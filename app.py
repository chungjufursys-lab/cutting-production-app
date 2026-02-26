import os
import re
import time
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError


# ===============================
# 기본 설정
# ===============================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

# 엑셀 A열(설비명) -> 탭 설비명 매핑
EQUIPMENT_MAP = {
    "판넬컷터 #1": "1호기",
    "판넬컷터 #2": "2호기",
    "네스팅 #1": "네스팅",
    "판넬컷터 #6": "6호기",
    "판넬컷터 #3(곡면)": "곡면",
    # 혹시 이미 탭명으로 들어오는 경우도 허용
    "1호기": "1호기",
    "2호기": "2호기",
    "네스팅": "네스팅",
    "6호기": "6호기",
    "곡면": "곡면",
}

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ===============================
# uploads 폴더 청소 (2일 유지)
# ===============================
def cleanup_old_uploads(folder: str = UPLOAD_DIR, days: int = 2) -> None:
    now = time.time()
    cutoff = now - (days * 86400)
    try:
        for fn in os.listdir(folder):
            fp = os.path.join(folder, fn)
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                os.remove(fp)
    except Exception:
        # 운영 중 청소 실패는 치명적이 아니므로 무시
        pass


cleanup_old_uploads()


# ===============================
# Google Sheets 연결
# ===============================
@st.cache_resource
def connect_gsheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open("cutting-production-db")

    ws_work = spreadsheet.worksheet("work_orders")
    ws_lots = spreadsheet.worksheet("lots")
    return ws_work, ws_lots


ws_work, ws_lots = connect_gsheet()


# ===============================
# Sheet 로드/유틸
# ===============================
def safe_get_all_records(ws) -> pd.DataFrame:
    try:
        df = pd.DataFrame(ws.get_all_records())
    except APIError as e:
        st.error("Google Sheets API 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
        st.stop()
    except Exception as e:
        st.error("Google Sheets 데이터를 읽는 중 오류가 발생했습니다.")
        st.stop()

    if df.empty:
        return df

    # 헤더 공백/숨은문자 방지
    df.columns = df.columns.astype(str).str.strip()

    # id가 비어있는 줄 제거(가끔 빈 행이 records로 들어오는 케이스)
    if "id" in df.columns:
        df = df[df["id"].astype(str).str.strip() != ""]
    return df


def load_work_orders() -> pd.DataFrame:
    return safe_get_all_records(ws_work)


def load_lots() -> pd.DataFrame:
    return safe_get_all_records(ws_lots)


def normalize_equipment(raw: Any) -> Optional[str]:
    s = str(raw).strip()
    return EQUIPMENT_MAP.get(s)


def to_int_safe(x: Any, default: int = 0) -> int:
    try:
        if pd.isna(x):
            return default
        return int(float(str(x).strip()))
    except Exception:
        return default


def next_int_id(df: pd.DataFrame, col: str) -> int:
    """
    기존에 int id를 쓰던 구조를 유지하기 위한 함수.
    숫자로 변환 가능한 값만 뽑아 max+1. 없으면 1.
    """
    if df is None or df.empty or col not in df.columns:
        return 1
    nums = []
    for v in df[col].tolist():
        try:
            vv = str(v).strip()
            if vv == "":
                continue
            nums.append(int(float(vv)))
        except Exception:
            continue
    return (max(nums) + 1) if nums else 1


# ===============================
# 엑셀 자동 감지 엔진
# ===============================
LOT_PATTERN = re.compile(r"\b\d+(\.\d+)?T-[A-Za-z]{1,}\b")  # 15T-WW, 0.5T-WW 등
MOVE_PATTERN = re.compile(r"^C\d{6}-\d+", re.IGNORECASE)    # C202602-36114

SUBTOTAL_PATTERN = re.compile(r"subtotal|합계|총계", re.IGNORECASE)


def detect_move_card_col(df: pd.DataFrame) -> Optional[Any]:
    best_col = None
    best_score = 0
    for col in df.columns:
        s = df[col].dropna().astype(str)
        score = s.str.match(MOVE_PATTERN).sum()
        if score > best_score:
            best_score = score
            best_col = col
    return best_col if best_score > 0 else None


def detect_lot_col(df: pd.DataFrame) -> Optional[Any]:
    best_col = None
    best_score = 0
    for col in df.columns:
        s = df[col].dropna().astype(str)
        score = s.apply(lambda v: bool(LOT_PATTERN.search(v))).sum()
        if score > best_score:
            best_score = score
            best_col = col
    return best_col if best_score > 0 else None


def detect_qty_col_near(df: pd.DataFrame, lot_col: Any) -> Optional[Any]:
    """
    lot_col 오른쪽 가까운 열부터 탐색(+1~+5), 숫자성 데이터가 가장 많은 열을 qty로 선택.
    """
    idx = list(df.columns).index(lot_col)
    candidates = []
    for j in range(idx + 1, min(idx + 6, len(df.columns))):
        col = df.columns[j]
        s = pd.to_numeric(df[col], errors="coerce")
        score = s.notna().sum()
        candidates.append((score, col))
    candidates.sort(reverse=True, key=lambda x: x[0])
    if candidates and candidates[0][0] > 0:
        return candidates[0][1]
    return None


def extract_lots(df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[Any]]:
    """
    다양한 엑셀 구조에서도 lot_key / qty / move_card_no를 최대한 자동으로 뽑아냄.
    반환: (lots_df, move_col)
    """
    move_col = detect_move_card_col(df)
    lot_col = detect_lot_col(df)
    if lot_col is None:
        raise ValueError("원장(로트) 열을 감지하지 못했습니다. (예: 15T-WW 형태가 있는 열)")

    qty_col = detect_qty_col_near(df, lot_col)
    if qty_col is None:
        # 근처에 없으면 전체에서 숫자열 가장 강한 걸 찾되, lot와 행 매칭이 깨질 수 있어 보수적으로 실패 처리
        raise ValueError("수량 열을 감지하지 못했습니다. (원장 열 오른쪽에 수량이 있어야 합니다)")

    # 원장/수량 추출
    base = df[[lot_col, qty_col]].copy()
    base.columns = ["lot_key", "qty"]

    # 값 정리
    base["lot_key"] = base["lot_key"].astype(str).str.strip()
    base = base[base["lot_key"] != ""]
    base = base[~base["lot_key"].str.contains(SUBTOTAL_PATTERN, na=False)]

    # lot_key 안에 실제 lot 패턴이 있는 행만 유지(잡음 제거)
    base = base[base["lot_key"].apply(lambda v: bool(LOT_PATTERN.search(str(v))))]

    # qty 정수화(엉뚱한 값 제거)
    base["qty"] = base["qty"].apply(lambda x: to_int_safe(x, default=-1))
    base = base[base["qty"] >= 0]

    if base.empty:
        raise ValueError("원장 데이터가 비어있습니다. (SUBTOTAL 제외 후 데이터 없음)")

    # 이동카드번호 매칭(같은 행 기준)
    if move_col is not None:
        mc = df[move_col].astype(str).str.strip()
        base["move_card_no"] = base.index.map(lambda i: mc.loc[i] if i in mc.index else "")
        base["move_card_no"] = base["move_card_no"].where(base["move_card_no"].str.match(MOVE_PATTERN, na=False), "")
    else:
        base["move_card_no"] = ""

    return base[["lot_key", "qty", "move_card_no"]], move_col


# ===============================
# work_order 상태 자동 계산/동기화
# ===============================
def compute_work_status(lots_for_work: pd.DataFrame, is_canceled: bool) -> str:
    if is_canceled:
        return "CANCELED"
    if lots_for_work.empty:
        return "WAITING"
    done_cnt = (lots_for_work["status"].astype(str) == "DONE").sum()
    total_cnt = len(lots_for_work)
    if done_cnt == 0:
        return "WAITING"
    if done_cnt == total_cnt:
        return "DONE"
    return "IN_PROGRESS"


def update_work_order_status_in_sheet(work_id: int, new_status: str) -> None:
    """
    work_orders 시트에서 해당 id 행 찾아 status 업데이트.
    """
    try:
        cell = ws_work.find(str(work_id))
        # status는 4번째 컬럼(헤더 기준: id(1), file_name(2), equipment(3), status(4))
        ws_work.update_cell(cell.row, 4, new_status)
    except Exception:
        # 운영 중 상태 동기화 실패해도 화면은 계산 기반으로 유지 가능
        pass


def ensure_sheet_has_canceled_at_column():
    """
    work_orders 헤더에 canceled_at 없으면 추가 권장.
    자동으로 넣을 수도 있지만 시트 편집 충돌을 피하려고 안내만.
    """
    try:
        headers = ws_work.row_values(1)
        headers = [h.strip() for h in headers]
        if "canceled_at" not in headers:
            st.warning("work_orders 시트에 'canceled_at' 컬럼이 없습니다. 1행 헤더에 추가하면 취소시간 기록이 깔끔해집니다.")
    except Exception:
        pass


ensure_sheet_has_canceled_at_column()


# ===============================
# UI: 업로드
# ===============================
st.subheader("📤 작업지시 업로드")

uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx"])

if uploaded_file is not None:
    # 저장(다운로드 기능용)
    save_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    # 읽기
    df = pd.read_excel(save_path)

    # 설비는 A열(0열) 첫 값
    raw_equipment = str(df.iloc[0, 0]).strip()
    equipment = normalize_equipment(raw_equipment)
    if equipment is None:
        st.error(f"설비 매핑 실패: '{raw_equipment}'  (EQUIPMENT_MAP에 등록 필요)")
        st.stop()

    # 원장/수량/이동카드 자동 추출
    try:
        lots_extracted, _ = extract_lots(df)
    except Exception as e:
        st.error(str(e))
        st.stop()

    # work_orders 저장
    work_df = load_work_orders()
    new_work_id = next_int_id(work_df, "id")

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # work_orders append (canceled_at 없는 시트도 고려: 5~6열)
    try:
        headers = [h.strip() for h in ws_work.row_values(1)]
        row = [new_work_id, uploaded_file.name, equipment, "WAITING", created_at]
        if "canceled_at" in headers:
            # canceled_at 컬럼까지 맞춰 길이 보정
            if len(headers) >= 6:
                row.append("")
        ws_work.append_row(row)
    except Exception:
        st.error("work_orders 시트에 작업지시 저장 중 오류가 발생했습니다.")
        st.stop()

    # lots 저장
    lots_df = load_lots()
    next_lot_id = next_int_id(lots_df, "id")

    try:
        for _, r in lots_extracted.iterrows():
            ws_lots.append_row([
                next_lot_id,
                new_work_id,
                str(r["lot_key"]).strip(),
                int(r["qty"]),
                str(r.get("move_card_no", "")).strip(),
                "WAITING",
                ""
            ])
            next_lot_id += 1
    except Exception:
        st.error("lots 시트에 원장 저장 중 오류가 발생했습니다.")
        st.stop()

    st.success(f"업로드 완료: {uploaded_file.name}  ({equipment})")
    st.rerun()

st.divider()


# ===============================
# UI: 이동카드 통합 검색 (Enter 지원)
# ===============================
st.subheader("🔎 이동카드번호 통합 검색")

with st.form("search_form", clear_on_submit=False):
    move_no = st.text_input("이동카드번호 입력 (예: C202602-36114)")
    submitted = st.form_submit_button("검색")

if submitted and move_no:
    lots_df = load_lots()
    work_df = load_work_orders()

    # 공백/대소문자 정리
    q = move_no.strip()

    hits = lots_df[lots_df["move_card_no"].astype(str).str.strip() == q]
    if hits.empty:
        st.warning("검색 결과 없음")
    else:
        merged = hits.merge(work_df, left_on="work_order_id", right_on="id", how="left", suffixes=("_lot", "_work"))
        show_cols = ["equipment", "file_name", "lot_key", "qty", "status_lot"]
        existing = [c for c in show_cols if c in merged.columns]
        st.dataframe(merged[existing], use_container_width=True)

st.divider()


# ===============================
# UI 옵션
# ===============================
copt1, copt2 = st.columns([1, 2])
with copt1:
    show_done_orders = st.checkbox("완료 작업지시 포함", value=False)
with copt2:
    show_canceled_orders = st.checkbox("취소 작업지시 포함", value=False)


# ===============================
# UI: 설비 탭
# ===============================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:
        work_df = load_work_orders()
        lots_df = load_lots()

        if work_df.empty:
            st.info("작업지시 없음")
            continue

        # 설비 필터
        work_df["equipment"] = work_df["equipment"].astype(str).str.strip()
        equip_work = work_df[work_df["equipment"] == equip].copy()

        if equip_work.empty:
            st.info("해당설비 작업없음")
            continue

        # canceled_at 있으면 취소 여부 판단
        if "canceled_at" in equip_work.columns:
            equip_work["is_canceled"] = equip_work["canceled_at"].astype(str).str.strip() != ""
        else:
            equip_work["is_canceled"] = (equip_work["status"].astype(str) == "CANCELED")

        # lots join해서 상태 계산
        # lots_df의 status 컬럼 정리
        if not lots_df.empty and "status" in lots_df.columns:
            lots_df["status"] = lots_df["status"].astype(str).str.strip()

        # work_id 별 lots 묶음
        # 상태 자동 계산 + 시트 status 동기화(가벼운 수준)
        computed_status = []
        total_qty = []
        done_qty = []
        for _, w in equip_work.iterrows():
            wid = w["id"]
            wlots = lots_df[lots_df["work_order_id"] == wid] if not lots_df.empty else pd.DataFrame()
            is_canceled = bool(w["is_canceled"])
            status = compute_work_status(wlots, is_canceled)
            computed_status.append(status)

            # 진행률(원장 개수 기준이 아니라 "매수" 기준 KPI도 같이 낼 수 있게 qty 합산)
            tq = int(wlots["qty"].sum()) if not wlots.empty and "qty" in wlots.columns else 0
            dq = int(wlots[wlots["status"] == "DONE"]["qty"].sum()) if not wlots.empty and "qty" in wlots.columns else 0
            total_qty.append(tq)
            done_qty.append(dq)

            # 시트에 status 동기화(취소는 덮어쓰지 않음)
            # (너무 자주 업데이트되는 걸 피하려고, 달라질 때만 업데이트)
            try:
                cur = str(w.get("status", "")).strip()
                if cur != status:
                    update_work_order_status_in_sheet(int(wid), status)
            except Exception:
                pass

        equip_work["status_calc"] = computed_status
        equip_work["total_qty"] = total_qty
        equip_work["done_qty"] = done_qty

        # 보기 옵션 적용
        view = equip_work.copy()
        if not show_done_orders:
            view = view[view["status_calc"] != "DONE"]
        if not show_canceled_orders:
            view = view[view["status_calc"] != "CANCELED"]

        # KPI (매수 합계 기준)
        # 미완료 = WAITING + IN_PROGRESS의 남은 qty
        # 오늘 완료 = DONE 처리된 lot의 qty 합
        merged = pd.DataFrame()
        if not lots_df.empty:
            merged = lots_df.merge(work_df[["id", "equipment"]], left_on="work_order_id", right_on="id", how="left", suffixes=("_lot", "_work"))
            merged = merged[merged["equipment"].astype(str).str.strip() == equip].copy()

        unfinished_qty = 0
        today_done_qty = 0
        in_progress_orders = 0

        if not merged.empty:
            # 작업지시 취소된 건은 KPI에서 제외(원하면 포함으로 바꿀 수 있음)
            canceled_ids = set(equip_work[equip_work["status_calc"] == "CANCELED"]["id"].tolist())
            merged_kpi = merged[~merged["work_order_id"].isin(canceled_ids)].copy()

            unfinished_qty = int(merged_kpi[merged_kpi["status"] != "DONE"]["qty"].sum())

            today = datetime.now().strftime("%Y-%m-%d")
            today_done_qty = int(
                merged_kpi[
                    (merged_kpi["status"] == "DONE") &
                    (merged_kpi["done_at"].astype(str).str.startswith(today))
                ]["qty"].sum()
            )

        in_progress_orders = int((equip_work["status_calc"] == "IN_PROGRESS").sum())

        k1, k2, k3 = st.columns(3)
        k1.metric("진행중 작업지시(건)", in_progress_orders)
        k2.metric("미완료 원장(매수)", unfinished_qty)
        k3.metric("오늘 완료 원장(매수)", today_done_qty)

        st.divider()

        # 좌우 레이아웃: 왼쪽 작업지시 / 오른쪽 원장
        left, right = st.columns([1.15, 1.85], gap="large")

        # 세션 선택값 유지
        sel_key = f"selected_work_{equip}"
        if sel_key not in st.session_state:
            st.session_state[sel_key] = None

        with left:
            st.subheader("📄 작업지시 목록")

            if view.empty:
                st.info("표시할 작업지시가 없습니다.")
            else:
                # 최신 업로드가 위로
                if "created_at" in view.columns:
                    view = view.sort_values("created_at", ascending=False)

                for _, w in view.iterrows():
                    wid = int(w["id"])
                    fname = str(w["file_name"])
                    status = str(w["status_calc"])

                    tq = int(w["total_qty"])
                    dq = int(w["done_qty"])
                    pct = 0 if tq == 0 else int(round(dq * 100 / tq))

                    box = st.container(border=True)
                    with box:
                        top1, top2 = st.columns([1, 1])
                        with top1:
                            if st.button(f"📌 {fname}", key=f"pick_{equip}_{wid}"):
                                st.session_state[sel_key] = wid
                        with top2:
                            st.write(f"상태: **{status}**")

                        st.write(f"진행률: {dq}/{tq} 매 ({pct}%)")
                        st.progress(min(max(pct, 0), 100))

                        # 원본 다운로드(uploads에 남아있을 때만)
                        dl_path = os.path.join(UPLOAD_DIR, fname)
                        dl1, dl2 = st.columns([1, 1])
                        with dl1:
                            if os.path.exists(dl_path):
                                with open(dl_path, "rb") as f:
                                    st.download_button(
                                        "⬇️ 원본다운로드",
                                        data=f.read(),
                                        file_name=fname,
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        key=f"dl_{equip}_{wid}",
                                    )
                            else:
                                st.caption("원본 파일 없음(서버 재시작/만료 가능)")

                        # 작업지시 취소(취소 상태면 버튼 비활성 대신 안내)
                        with dl2:
                            if status != "CANCELED":
                                if st.button("🚫 작업지시 취소", key=f"cancel_{equip}_{wid}"):
                                    # work_orders: status=CANCELED + canceled_at 기록
                                    try:
                                        cell = ws_work.find(str(wid))
                                        ws_work.update_cell(cell.row, 4, "CANCELED")
                                        headers = [h.strip() for h in ws_work.row_values(1)]
                                        if "canceled_at" in headers:
                                            cidx = headers.index("canceled_at") + 1
                                            ws_work.update_cell(cell.row, cidx, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                    except Exception:
                                        st.error("작업지시 취소 처리 중 오류가 발생했습니다.")
                                        st.stop()
                                    st.rerun()
                            else:
                                st.caption("취소됨")

        with right:
            st.subheader("📦 원장 목록")

            selected_work_id = st.session_state.get(sel_key, None)
            if selected_work_id is None:
                st.info("왼쪽에서 작업지시를 선택하세요.")
            else:
                wlots = lots_df[lots_df["work_order_id"] == selected_work_id].copy()
                if wlots.empty:
                    st.warning("원장 데이터가 없습니다.")
                else:
                    # lot_key 정리
                    wlots["lot_key"] = wlots["lot_key"].astype(str).str.strip()
                    wlots["status"] = wlots["status"].astype(str).str.strip()

                    # 완료/대기만 운영(원장단위는 WAITING/DONE)
                    for _, r in wlots.iterrows():
                        lid = int(r["id"])
                        lot_key = str(r["lot_key"])
                        qty = to_int_safe(r["qty"], 0)
                        status = str(r["status"])

                        row = st.container(border=True)
                        with row:
                            c1, c2, c3, c4 = st.columns([3.2, 1, 1, 1])

                            c1.write(f"**{lot_key}**")
                            c2.write(f"{qty}매")
                            c3.write("✅ 완료" if status == "DONE" else "⏳ 대기")

                            if status == "WAITING":
                                if c4.button("완료", key=f"done_{equip}_{selected_work_id}_{lid}"):
                                    try:
                                        cell = ws_lots.find(str(lid))
                                        # lots: status(6열), done_at(7열)
                                        ws_lots.update_cell(cell.row, 6, "DONE")
                                        ws_lots.update_cell(cell.row, 7, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                    except Exception:
                                        st.error("완료 처리 중 오류가 발생했습니다.")
                                        st.stop()
                                    st.rerun()
                            else:
                                if c4.button("완료취소", key=f"undo_{equip}_{selected_work_id}_{lid}"):
                                    try:
                                        cell = ws_lots.find(str(lid))
                                        ws_lots.update_cell(cell.row, 6, "WAITING")
                                        ws_lots.update_cell(cell.row, 7, "")
                                    except Exception:
                                        st.error("완료취소 처리 중 오류가 발생했습니다.")
                                        st.stop()
                                    st.rerun()
