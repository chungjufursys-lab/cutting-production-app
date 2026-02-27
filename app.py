import streamlit as st
import pandas as pd
from datetime import datetime
import os
from sheets_db import (
    get_work_orders, get_lots_all,
    insert_work_order, insert_lot,
    update_lot_status, update_work_order_status,
    append_ledger
)

# =========================
# 기본 설정
# =========================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =========================
# 유틸
# =========================
def safe_int(x, default=0):
    try:
        return int(float(x))
    except:
        return default


def compute_status(wo_status, lots):
    if wo_status == "VOID":
        return "VOID"
    total = len(lots)
    done = sum(1 for l in lots if l["status"] == "DONE")
    if total == 0 or done == 0:
        return "WAITING"
    if done < total:
        return "IN_PROGRESS"
    return "COMPLETED"


# =========================
# 데이터 1회 로드
# =========================
try:
    ALL_WOS = get_work_orders()
    ALL_LOTS = get_lots_all()
except:
    st.error("Google Sheets 연결 오류. 잠시 후 다시 시도하세요.")
    st.stop()

wo_by_id = {str(w["id"]): w for w in ALL_WOS}
lots_by_wo = {}
for l in ALL_LOTS:
    lots_by_wo.setdefault(str(l["work_order_id"]), []).append(l)


# =========================
# 설비 탭
# =========================
tabs = st.tabs(EQUIP_TABS)

for equip_index, equip in enumerate(EQUIP_TABS):

    with tabs[equip_index]:

        # 작업자 모드 기본 ON
        worker_mode = st.toggle("🧤 작업자 모드", value=True, key=f"worker_{equip}")

        equip_wos = [w for w in ALL_WOS if w["equipment"] == equip and w["status"] != "VOID"]

        if not equip_wos:
            st.info("작업지시가 없습니다.")
            continue

        # 작업지시 선택
        options = []
        for w in equip_wos:
            lots = lots_by_wo.get(str(w["id"]), [])
            status = compute_status(w["status"], lots)
            done = sum(1 for l in lots if l["status"] == "DONE")
            total = len(lots)
            options.append((int(w["id"]), f"[{status}] {done}/{total} | {w['file_name']}"))

        selected_id = st.radio(
            "작업지시 선택",
            options,
            format_func=lambda x: x[1],
            key=f"radio_{equip}"
        )[0]

        selected_wo = wo_by_id[str(selected_id)]
        wo_status = selected_wo["status"]
        lots = lots_by_wo.get(str(selected_id), [])

        st.divider()

        # =========================
        # 작업자 모드 UI
        # =========================
        if worker_mode:

            # 미완료만
            lots = [l for l in lots if l["status"] == "WAITING"]

            if not lots:
                st.success("🎉 모든 원장이 완료되었습니다.")
                continue

            st.subheader("미완료 원장")

            for lot in lots:

                with st.container():
                    st.markdown("### 📄 LOT")
                    st.write(f"**LOT:** {lot['lot_key']}")
                    st.write(f"수량: {lot['qty']}")
                    st.write(f"이동카드: {lot.get('move_card_no','')}")

                    if st.button(
                        "✅ 완료 처리",
                        key=f"done_{equip}_{selected_id}_{lot['id']}",
                        use_container_width=True
                    ):
                        update_lot_status(lot["id"], "DONE")

                        # 상태 재계산
                        new_status = compute_status(
                            wo_status,
                            [dict(x, status=("DONE" if x["id"] == lot["id"] else x["status"])) for x in lots_by_wo[str(selected_id)]]
                        )
                        update_work_order_status(selected_id, new_status)

                        append_ledger("DONE", "system", selected_id, lot["id"])
                        st.success("완료 처리되었습니다.")
                        st.rerun()

                    st.markdown("---")

        # =========================
        # 관리자 모드 UI
        # =========================
        else:

            st.subheader("전체 원장")

            for lot in lots:

                c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
                c1.write(lot["lot_key"])
                c2.write(lot["qty"])
                c3.write(lot["status"])

                if lot["status"] == "WAITING":
                    if c4.button("완료", key=f"admin_done_{equip}_{lot['id']}"):
                        update_lot_status(lot["id"], "DONE")
                        append_ledger("DONE", "system", selected_id, lot["id"])
                        st.rerun()
                else:
                    if c4.button("취소", key=f"admin_undo_{equip}_{lot['id']}"):
                        update_lot_status(lot["id"], "WAITING")
                        append_ledger("UNDONE", "system", selected_id, lot["id"])
                        st.rerun()
