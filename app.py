import streamlit as st
import pandas as pd
from datetime import datetime
import os
import re
from sheets_db import *

# =========================
# 기본 설정
# =========================

st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

EQUIPMENT_MAP = {
    "판넬컷터 #1": "1호기",
    "판넬컷터 #2": "2호기",
    "네스팅 #1": "네스팅",
    "판넬컷터 #6": "6호기",
    "판넬컷터 #3(곡면)": "곡면",
}

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =========================
# 상태 재계산
# =========================

def recalc_work_order_status(work_order_id):
    work_orders = get_work_orders()
    lots = get_lots(work_order_id)

    wo = next((w for w in work_orders if str(w["id"]) == str(work_order_id)), None)
    if not wo:
        return 0, 0, "UNKNOWN"

    if wo["status"] == "VOID":
        total = len(lots)
        done = sum(1 for l in lots if l["status"] == "DONE")
        return done, total, "VOID"

    total = len(lots)
    done = sum(1 for l in lots if l["status"] == "DONE")

    if total == 0 or done == 0:
        new_status = "WAITING"
    elif done < total:
        new_status = "IN_PROGRESS"
    else:
        new_status = "COMPLETED"

    update_work_order_status(work_order_id, new_status)
    return done, total, new_status

# =========================
# 🔍 이동카드 검색
# =========================

st.markdown("## 🔍 이동카드번호 통합 검색")

with st.form("move_search_form"):
    move_search = st.text_input("이동카드번호 입력")
    search_submit = st.form_submit_button("검색")

if search_submit:
    all_lots = get_lots()
    all_wos = get_work_orders()

    result = []
    for l in all_lots:
        if str(l["move_card_no"]) == move_search.strip():
            wo = next((w for w in all_wos if str(w["id"]) == str(l["work_order_id"])), None)
            if wo:
                result.append({
                    "equipment": wo["equipment"],
                    "file_name": wo["file_name"],
                    "lot_key": l["lot_key"],
                    "qty": l["qty"],
                    "status": l["status"]
                })

    if len(result) == 0:
        st.error("검색 결과가 없습니다.")
    else:
        st.success(f"{len(result)}건 발견")
        st.dataframe(result, use_container_width=True)

st.divider()

# =========================
# 업로드
# =========================

st.sidebar.header("관리자")
uploaded = st.sidebar.file_uploader("ERP 엑셀 업로드", type=["xlsx"])

def detect_equipment_column(df):
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(40)
        if sample.str.contains("판넬컷터|네스팅", regex=True).any():
            return col
    return None

def detect_lot_column(df):
    for col in reversed(df.columns):
        sample = df[col].dropna().astype(str).head(80)
        if sample.str.contains(r"\d+T-", regex=True).any():
            return col
    return None

def detect_qty_column(df, lot_col):
    cols = list(df.columns)
    idx = cols.index(lot_col)
    for col in cols[idx+1:]:
        s = df[col].dropna().head(50)
        try:
            float(s.iloc[0])
            return col
        except:
            continue
    return None

def detect_move_card_column(df):
    pattern = r"C\d{6}-\d+"
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(100)
        if sample.str.contains(pattern, regex=True).any():
            return col
    return None

if uploaded:
    df = pd.read_excel(uploaded)

    equip_col = detect_equipment_column(df)
    lot_col = detect_lot_column(df)
    qty_col = detect_qty_column(df, lot_col) if lot_col else None
    move_col = detect_move_card_column(df)

    st.sidebar.write("자동 감지 결과")
    st.sidebar.write(f"설비: {equip_col}")
    st.sidebar.write(f"로트: {lot_col}")
    st.sidebar.write(f"수량: {qty_col}")
    st.sidebar.write(f"이동카드: {move_col}")

    if st.sidebar.button("작업지시 등록"):
        safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded.name}"
        saved_path = os.path.join(UPLOAD_DIR, safe_name)

        with open(saved_path, "wb") as f:
            f.write(uploaded.getbuffer())

        work_orders = get_work_orders()
        new_id = max([int(w["id"]) for w in work_orders], default=0) + 1

        for equip_raw, sub in df.groupby(equip_col):
            equip = EQUIPMENT_MAP.get(str(equip_raw).strip())
            if not equip:
                continue

            insert_work_order({
                "id": new_id,
                "file_name": uploaded.name,
                "equipment": equip,
                "status": "WAITING",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file_hash": "",
                "excel_file_path": saved_path,
                "pdf_file_path": ""
            })

            all_lots = get_lots()
            lot_id = max([int(l["id"]) for l in all_lots], default=0) + 1

            for _, r in sub.iterrows():
                lot_key = r.get(lot_col)
                qty_val = r.get(qty_col)
                move_no = r.get(move_col)

                if pd.isna(lot_key):
                    continue

                try:
                    qty = int(float(qty_val))
                except:
                    continue

                insert_lot({
                    "id": lot_id,
                    "work_order_id": new_id,
                    "lot_key": str(lot_key),
                    "qty": qty,
                    "move_card_no": str(move_no),
                    "status": "WAITING",
                    "done_at": ""
                })

                lot_id += 1

            new_id += 1

        st.sidebar.success("작업지시 등록 완료")
        st.rerun()

# =========================
# 설비 탭
# =========================

tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        show_completed = st.checkbox("완료 작업지시 포함", key=f"comp_{equip}")
        show_void = st.checkbox("취소 작업지시 포함", key=f"void_{equip}")

        all_work_orders = get_work_orders()
        work_orders = [w for w in all_work_orders if w["equipment"] == equip]

        if not show_completed:
            work_orders = [w for w in work_orders if w["status"] != "COMPLETED"]

        if not show_void:
            work_orders = [w for w in work_orders if w["status"] != "VOID"]

        work_orders = sorted(work_orders, key=lambda x: x["created_at"], reverse=True)

        # KPI 계산
        all_lots = get_lots()
        equip_lots = [
            l for l in all_lots
            if any(str(w["id"]) == str(l["work_order_id"]) and w["equipment"] == equip and w["status"] != "VOID"
                   for w in all_work_orders)
        ]

        unfinished_qty = sum(int(l["qty"]) for l in equip_lots if l["status"] == "WAITING")

        today = datetime.now().strftime("%Y-%m-%d")
        today_done_qty = sum(
            int(l["qty"]) for l in equip_lots
            if l["status"] == "DONE" and str(l["done_at"]).startswith(today)
        )

        in_progress_cnt = sum(1 for w in work_orders if w["status"] == "IN_PROGRESS")

        c1, c2, c3 = st.columns(3)
        c1.metric("진행중 작업지시", in_progress_cnt)
        c2.metric("미완료 원장 (매수)", unfinished_qty)
        c3.metric("오늘 완료 원장 (매수)", today_done_qty)

        st.divider()

        if len(work_orders) == 0:
            st.info("작업지시 없음")
            continue

        left, right = st.columns([1, 2])

        with left:
            options = []
            for w in work_orders:
                done, total, status = recalc_work_order_status(w["id"])
                options.append((w["id"], f"{status} | {done}/{total}\n{w['file_name']}"))

            selected = st.radio("작업지시 선택", options, format_func=lambda x: x[1])
            selected_id = selected[0]

        with right:
            wo = next(w for w in work_orders if w["id"] == selected_id)
            wo_status = wo["status"]

            if wo_status != "VOID":
                if st.button("⛔ 작업지시 취소", key=f"void_{equip}_{selected_id}"):
                    update_work_order_status(selected_id, "VOID")
                    append_ledger("VOID", "system", selected_id, "", "")
                    st.rerun()

            if wo.get("excel_file_path") and os.path.exists(wo["excel_file_path"]):
                with open(wo["excel_file_path"], "rb") as f:
                    st.download_button(
                        "📥 원본 엑셀 다운로드",
                        f,
                        file_name=wo["file_name"],
                        key=f"down_{equip}_{selected_id}"
                    )

            st.divider()

            lots_df = get_lots(selected_id)

            for r in lots_df:
                c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
                c1.write(r["lot_key"])
                c2.write(r["qty"])
                c3.write(r["status"])

                if wo_status == "VOID":
                    c4.write("-")
                    continue

                if r["status"] == "WAITING":
                    if c4.button("완료", key=f"done_{r['id']}"):
                        update_lot_status(r["id"], "DONE")
                        recalc_work_order_status(selected_id)
                        append_ledger("DONE", "system", selected_id, r["id"])
                        st.rerun()
                else:
                    if c4.button("완료취소", key=f"undo_{r['id']}"):
                        update_lot_status(r["id"], "WAITING")
                        recalc_work_order_status(selected_id)
                        append_ledger("UNDONE", "system", selected_id, r["id"])
                        st.rerun()
