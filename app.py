# =========================
# 재단공정 작업관리 시스템
# 완전 통합 안정화 최종 버전
# =========================

from __future__ import annotations

import os
import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st

from domain.constants import (
    EQUIP_TABS,
    LOT_STATUS_WAITING,
    LOT_STATUS_DONE,
    WO_STATUS_VOID,
)
from domain.schema import (
    WORK_ORDERS_COLS,
    LOTS_COLS,
    WORK_ORDERS_ALIASES,
    LOTS_ALIASES,
)
from services.gsheet import connect_gsheet, ensure_schema, read_all_as_df, build_row_map
from services.excel_parser import parse_excel
from services.status_service import compute_work_order_status, count_done_total
from services.kpi_service import compute_kpis

# -------------------------
# 기본 설정
# -------------------------
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# -------------------------
# Google Sheets 연결
# -------------------------
handles = connect_gsheet()
ws_work = handles.ws_work
ws_lots = handles.ws_lots

ensure_schema(ws_work, WORK_ORDERS_COLS, WORK_ORDERS_ALIASES)
ensure_schema(ws_lots, LOTS_COLS, LOTS_ALIASES)

# -------------------------
# 데이터 로드
# -------------------------
@st.cache_data(ttl=10)
def load_all():
    work_df, work_values = read_all_as_df(ws_work)
    lots_df, lots_values = read_all_as_df(ws_lots)

    for c in WORK_ORDERS_COLS:
        if c not in work_df.columns:
            work_df[c] = ""

    for c in LOTS_COLS:
        if c not in lots_df.columns:
            lots_df[c] = ""

    work_df["id"] = work_df["id"].astype(str)
    work_df["status"] = work_df["status"].astype(str)

    lots_df["id"] = lots_df["id"].astype(str)
    lots_df["work_order_id"] = lots_df["work_order_id"].astype(str)
    lots_df["status"] = lots_df["status"].astype(str)
    lots_df["qty"] = pd.to_numeric(lots_df["qty"], errors="coerce").fillna(0).astype(int)

    work_row_map = build_row_map(work_values, "id")
    lots_row_map = build_row_map(lots_values, "id")

    return work_df, lots_df, work_row_map, lots_row_map


def invalidate_cache():
    load_all.clear()


def next_id(df):
    if df.empty:
        return 1
    nums = []
    for v in df["id"]:
        try:
            nums.append(int(float(v)))
        except:
            pass
    return max(nums) + 1 if nums else 1


# =========================
# 📤 업로드 기능 (복구)
# =========================
st.sidebar.header("관리자")

with st.sidebar.form("upload_form", clear_on_submit=True):
    uploaded_file = st.file_uploader("ERP 엑셀 업로드", type=["xlsx"])
    upload_btn = st.form_submit_button("작업지시 등록")

if upload_btn and uploaded_file is not None:
    work_df, lots_df, _, _ = load_all()

    file_bytes = uploaded_file.getbuffer()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    if file_hash in work_df["file_hash"].astype(str).tolist():
        st.sidebar.error("동일 파일이 이미 등록되었습니다.")
        st.stop()

    safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)

    with open(save_path, "wb") as f:
        f.write(file_bytes)

    parsed = parse_excel(save_path)

    new_work_id = next_id(work_df)
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ws_work.append_row([
        new_work_id,
        uploaded_file.name,
        parsed.equipment,
        "WAITING",
        created,
        file_hash,
    ])

    new_lot_id = next_id(lots_df)

    rows = []
    for _, r in parsed.lots.iterrows():
        rows.append([
            new_lot_id,
            new_work_id,
            r["lot_key"],
            int(r["qty"]),
            r["move_card_no"],
            "WAITING",
            "",
        ])
        new_lot_id += 1

    ws_lots.append_rows(rows, value_input_option="USER_ENTERED")

    st.sidebar.success("업로드 완료")
    invalidate_cache()
    st.rerun()


# =========================
# 🔍 이동카드 검색
# =========================
st.markdown("## 🔍 이동카드번호 통합 검색")

with st.form("move_search_form"):
    move_search = st.text_input("이동카드번호 입력")
    search_submit = st.form_submit_button("검색")

if search_submit:
    work_df, lots_df, _, _ = load_all()

    merged = lots_df.merge(
        work_df[["id", "equipment", "file_name"]],
        left_on="work_order_id",
        right_on="id",
        how="left",
    )

    result = merged[merged["move_card_no"] == move_search][
        ["equipment", "file_name", "lot_key", "qty", "status"]
    ]

    if result.empty:
        st.error("검색 결과 없음")
    else:
        st.success(f"{len(result)}건 발견")
        st.dataframe(result, use_container_width=True)

st.divider()


# =========================
# 설비 탭
# =========================
tabs = st.tabs(EQUIP_TABS)

for equip in EQUIP_TABS:
    with tabs[EQUIP_TABS.index(equip)]:

        work_df, lots_df, work_row_map, lots_row_map = load_all()

        show_completed = st.checkbox("완료 작업지시 포함", key=f"comp_{equip}")
        show_void = st.checkbox("취소 작업지시 포함", key=f"void_{equip}")

        filtered = []

        for _, r in work_df[work_df["equipment"] == equip].iterrows():
            wid = r["id"]
            original_status = r["status"]

            if original_status == WO_STATUS_VOID:
                computed_status = WO_STATUS_VOID
            else:
                computed_status = compute_work_order_status(lots_df, wid, original_status)

            if not show_completed and computed_status == "COMPLETED":
                continue

            if not show_void and computed_status == WO_STATUS_VOID:
                continue

            filtered.append((wid, computed_status, r["file_name"]))

        if not filtered:
            st.info("작업지시 없음")
            continue

        # KPI
        k = compute_kpis(work_df, lots_df, equip)
        c1, c2, c3 = st.columns(3)
        c1.metric("진행중 작업지시", k["in_progress_cnt"])
        c2.metric("미완료 원장 (매수)", k["unfinished_qty"])
        c3.metric("오늘 완료 원장 (매수)", k["today_done_qty"])

        st.divider()

        left, right = st.columns([1, 2])

        with left:
            options = []
            for wid, status, fname in filtered:
                done, total = count_done_total(lots_df, wid)
                label = f"{status} | {done}/{total}\n{fname}"
                options.append((wid, label))

            selected = st.radio(
                "작업지시 선택",
                options,
                format_func=lambda x: x[1],
                key=f"radio_{equip}",
            )

            selected_id = selected[0]

        with right:
            wo_status = next(x[1] for x in filtered if x[0] == selected_id)
            file_name = next(x[2] for x in filtered if x[0] == selected_id)

            st.subheader(file_name)

            # 원본 다운로드
            possible_files = [f for f in os.listdir(UPLOAD_DIR) if f.endswith(file_name)]
            if possible_files:
                file_path = os.path.join(UPLOAD_DIR, possible_files[-1])
                with open(file_path, "rb") as f:
                    st.download_button(
                        "📥 원본 엑셀 다운로드",
                        f,
                        file_name=file_name,
                        key=f"download_{equip}_{selected_id}",
                    )

            # 작업취소 버튼
            if wo_status != WO_STATUS_VOID:
                if st.button("⛔ 작업지시 취소", key=f"void_{equip}_{selected_id}"):
                    row_no = work_row_map.get(selected_id)
                    ws_work.update(f"D{row_no}", [[WO_STATUS_VOID]])
                    invalidate_cache()
                    st.rerun()

            st.divider()

            wlots = lots_df[lots_df["work_order_id"] == selected_id]

            for _, lr in wlots.iterrows():
                lot_id = lr["id"]
                row_no = lots_row_map.get(str(lot_id))

                c1, c2, c3 = st.columns([5, 1, 1])
                c1.write(lr["lot_key"])
                c2.write(lr["qty"])

                if lr["status"] == LOT_STATUS_WAITING:
                    if c3.button("완료", key=f"d_{equip}_{lot_id}"):
                        ws_lots.update(f"F{row_no}", [[LOT_STATUS_DONE]])
                        ws_lots.update(
                            f"G{row_no}",
                            [[datetime.now().strftime("%Y-%m-%d %H:%M:%S")]]
                        )
                        invalidate_cache()
                        st.rerun()
                else:
                    if c3.button("완료취소", key=f"u_{equip}_{lot_id}"):
                        ws_lots.update(f"F{row_no}", [[LOT_STATUS_WAITING]])
                        ws_lots.update(f"G{row_no}", [[""]])
                        invalidate_cache()
                        st.rerun()
