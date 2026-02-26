# =========================
# 재단공정 작업관리 시스템
# 완료작업 숨김 기능 포함 최종버전
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

st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

handles = connect_gsheet()
ws_work = handles.ws_work
ws_lots = handles.ws_lots

ensure_schema(ws_work, WORK_ORDERS_COLS, WORK_ORDERS_ALIASES)
ensure_schema(ws_lots, LOTS_COLS, LOTS_ALIASES)

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
# 설비 탭
# =========================
tabs = st.tabs(EQUIP_TABS)

for equip in EQUIP_TABS:
    with tabs[EQUIP_TABS.index(equip)]:

        work_df, lots_df, work_row_map, lots_row_map = load_all()

        show_completed = st.checkbox("완료 작업지시 포함", key=f"comp_{equip}")
        show_void = st.checkbox("취소 작업지시 포함", key=f"void_{equip}")

        # ---- 상태 동적 계산 ----
        filtered_list = []

        for _, r in work_df[work_df["equipment"] == equip].iterrows():
            wid = r["id"]
            original_status = r["status"]

            if original_status == WO_STATUS_VOID:
                computed_status = WO_STATUS_VOID
            else:
                computed_status = compute_work_order_status(lots_df, wid, original_status)

            # 필터 조건 적용
            if not show_completed and computed_status == "COMPLETED":
                continue

            if not show_void and computed_status == WO_STATUS_VOID:
                continue

            filtered_list.append((wid, computed_status, r["file_name"]))

        if not filtered_list:
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
            for wid, status, fname in filtered_list:
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
            wo_row = next(x for x in filtered_list if x[0] == selected_id)
            st.subheader(wo_row[2])

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
