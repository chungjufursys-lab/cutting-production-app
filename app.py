# =========================
# 재단공정 작업관리 시스템
# DuplicateElementId 해결 버전
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
    WO_STATUS_COMPLETED,
)
from domain.schema import (
    WORK_ORDERS_COLS,
    LOTS_COLS,
    WORK_ORDERS_ALIASES,
    LOTS_ALIASES,
)
from services.gsheet import connect_gsheet, ensure_schema, read_all_as_df, build_row_map
from services.excel_parser import parse_excel
from services.status_service import count_done_total
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

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df, lots_df, work_row_map, lots_row_map = load_all()

        show_completed = st.checkbox("완료 작업지시 포함", key=f"comp_{equip}")
        show_void = st.checkbox("취소 작업지시 포함", key=f"void_{equip}")

        w = work_df[work_df["equipment"] == equip].copy()

        if not show_completed:
            w = w[w["status"] != WO_STATUS_COMPLETED]

        if not show_void:
            w = w[w["status"] != WO_STATUS_VOID]

        if w.empty:
            st.info("작업지시 없음")
            continue

        k = compute_kpis(work_df, lots_df, equip)

        c1, c2, c3 = st.columns(3)
        c1.metric("진행중 작업지시", k["in_progress_cnt"])
        c2.metric("미완료 원장 (매수)", k["unfinished_qty"])
        c3.metric("오늘 완료 원장 (매수)", k["today_done_qty"])

        st.divider()

        left, right = st.columns([1, 2])

        with left:
            options = []
            for _, r in w.iterrows():
                wid = r["id"]
                done, total = count_done_total(lots_df, wid)
                label = f"{r['status']} | {done}/{total}\n{r['file_name']}"
                options.append((wid, label))

            selected = st.radio(
                "작업지시 선택",
                options,
                format_func=lambda x: x[1],
                key=f"radio_{equip}",
            )

            selected_id = selected[0]

        with right:
            wo = w[w["id"] == selected_id].iloc[0]
            st.subheader(wo["file_name"])

            # 원본 다운로드
            possible_files = [f for f in os.listdir(UPLOAD_DIR) if f.endswith(wo["file_name"])]
            if possible_files:
                file_path = os.path.join(UPLOAD_DIR, possible_files[-1])
                with open(file_path, "rb") as f:
                    st.download_button(
                        "📥 원본 엑셀 다운로드",
                        f,
                        file_name=wo["file_name"],
                        key=f"download_{equip}_{selected_id}",
                    )

            # 작업취소 버튼 (key 추가)
            if wo["status"] != WO_STATUS_VOID:
                if st.button(
                    "⛔ 작업지시 취소",
                    key=f"void_{equip}_{selected_id}",
                ):
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
