# =========================
# 재단공정 작업관리 시스템
# (락 제거 안정화 버전)
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

# =========================
# 기본 설정
# =========================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =========================
# Google Sheets 연결
# =========================
handles = connect_gsheet()
ws_work = handles.ws_work
ws_lots = handles.ws_lots

# =========================
# 스키마 보정
# =========================
ensure_schema(ws_work, WORK_ORDERS_COLS, WORK_ORDERS_ALIASES)
ensure_schema(ws_lots, LOTS_COLS, LOTS_ALIASES)

# =========================
# 데이터 로드
# =========================
@st.cache_data(ttl=15)
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
# 업로드 (락 제거)
# =========================
st.sidebar.header("관리자")

with st.sidebar.form("upload_form", clear_on_submit=True):
    up = st.file_uploader("ERP 엑셀 업로드", type=["xlsx"])
    do_upload = st.form_submit_button("작업지시 등록")

if do_upload and up is not None:
    work_df, lots_df, _, _ = load_all()

    file_bytes = up.getbuffer()
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    if file_hash in work_df["file_hash"].astype(str).tolist():
        st.sidebar.error("동일한 파일이 이미 등록되었습니다.")
        st.stop()

    safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{up.name}"
    save_path = os.path.join(UPLOAD_DIR, safe_name)

    with open(save_path, "wb") as f:
        f.write(file_bytes)

    parsed = parse_excel(save_path)

    new_work_id = next_id(work_df)
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ws_work.append_row([
        new_work_id,
        up.name,
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

    if hasattr(ws_lots, "append_rows"):
        ws_lots.append_rows(rows, value_input_option="USER_ENTERED")
    else:
        for row in rows:
            ws_lots.append_row(row)

    st.sidebar.success("업로드 완료")
    invalidate_cache()
    st.rerun()

st.divider()

# =========================
# 설비 탭 UI
# =========================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df, lots_df, work_row_map, lots_row_map = load_all()

        w = work_df[work_df["equipment"] == equip]

        if w.empty:
            st.info("작업지시 없음")
            continue

        k = compute_kpis(work_df, lots_df, equip)

        c1, c2, c3 = st.columns(3)
        c1.metric("진행중 작업지시", k["in_progress_cnt"])
        c2.metric("미완료 원장 (매수)", k["unfinished_qty"])
        c3.metric("오늘 완료 원장 (매수)", k["today_done_qty"])

        st.divider()

        for _, r in w.iterrows():
            wid = r["id"]
            fname = r["file_name"]

            st.subheader(fname)

            wlots = lots_df[lots_df["work_order_id"] == wid]

            total = len(wlots)
            done = (wlots["status"] == LOT_STATUS_DONE).sum()

            st.progress(0 if total == 0 else int(done * 100 / total))
            st.write(f"{done}/{total}")

            for _, lr in wlots.iterrows():
                lot_id = lr["id"]
                row_no = lots_row_map.get(str(lot_id))

                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(lr["lot_key"])
                c2.write(lr["qty"])

                if lr["status"] == LOT_STATUS_WAITING:
                    if c3.button("완료", key=f"d_{lot_id}"):
                        ws_lots.update(f"F{row_no}", LOT_STATUS_DONE)
                        ws_lots.update(f"G{row_no}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        invalidate_cache()
                        st.rerun()
                else:
                    if c3.button("취소", key=f"u_{lot_id}"):
                        ws_lots.update(f"F{row_no}", LOT_STATUS_WAITING)
                        ws_lots.update(f"G{row_no}", "")
                        invalidate_cache()
                        st.rerun()
