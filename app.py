import streamlit as st
import pandas as pd
from datetime import datetime
import os
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
# 유틸: 작업지시 상태 재계산
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


def safe_int(x, default=0):
    try:
        return int(float(x))
    except Exception:
        return default


# =========================
# 엑셀 자동 감지(기존 로직 유지)
# =========================
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
    for col in cols[idx + 1:]:
        s = df[col].dropna().head(50)
        if len(s) == 0:
            continue
        try:
            float(s.iloc[0])
            return col
        except Exception:
            continue
    return None


def detect_move_card_column(df):
    pattern = r"C\d{6}-\d+"
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(100)
        if sample.str.contains(pattern, regex=True).any():
            return col
    return None


# =========================
# Sidebar: 관리자(업로드 + 이동카드 검색)
# =========================
st.sidebar.header("관리자")

with st.sidebar.expander("🔍 이동카드번호 통합 검색", expanded=False):
    with st.form("move_search_form_sidebar"):
        move_search = st.text_input("이동카드번호 입력", placeholder="예: C202602-36114")
        search_submit = st.form_submit_button("검색")

    if search_submit:
        if move_search.strip() == "":
            st.warning("이동카드번호를 입력하세요.")
        else:
            all_lots = get_lots()
            all_wos = get_work_orders()

            result = []
            for l in all_lots:
                if str(l.get("move_card_no", "")).strip() == move_search.strip():
                    wo = next((w for w in all_wos if str(w["id"]) == str(l["work_order_id"])), None)
                    if wo:
                        result.append({
                            "설비": wo.get("equipment", ""),
                            "파일명": wo.get("file_name", ""),
                            "LOT": l.get("lot_key", ""),
                            "수량": l.get("qty", ""),
                            "상태": l.get("status", ""),
                        })

            if len(result) == 0:
                st.error("검색 결과가 없습니다.")
            else:
                st.success(f"{len(result)}건 발견")
                st.dataframe(pd.DataFrame(result), use_container_width=True, height=220)

st.sidebar.divider()

with st.sidebar.expander("📤 작업지시 등록(엑셀 + PDF 옵션)", expanded=True):
    uploaded_excel = st.file_uploader("ERP 엑셀 업로드", type=["xlsx"], key="excel_uploader")
    uploaded_pdf = st.file_uploader("이동카드 PDF(선택)", type=["pdf"], key="pdf_uploader")

    if uploaded_excel:
        df = pd.read_excel(uploaded_excel)

        equip_col = detect_equipment_column(df)
        lot_col = detect_lot_column(df)
        qty_col = detect_qty_column(df, lot_col) if lot_col else None
        move_col = detect_move_card_column(df)

        st.caption("자동 감지 결과")
        st.write(f"- 설비 컬럼: **{equip_col}**")
        st.write(f"- LOT 컬럼: **{lot_col}**")
        st.write(f"- 수량 컬럼: **{qty_col}**")
        st.write(f"- 이동카드 컬럼: **{move_col}**")

        ok = True
        if not equip_col:
            st.error("설비 컬럼을 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
            ok = False
        if not lot_col or not qty_col:
            st.error("LOT/수량 컬럼을 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
            ok = False

        if st.button("✅ 작업지시 등록", disabled=(not ok), use_container_width=True):
            # 1) 파일 저장
            safe_excel_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_excel.name}"
            excel_path = os.path.join(UPLOAD_DIR, safe_excel_name)
            with open(excel_path, "wb") as f:
                f.write(uploaded_excel.getbuffer())

            pdf_path = ""
            if uploaded_pdf is not None:
                safe_pdf_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_pdf.name}"
                pdf_path = os.path.join(UPLOAD_DIR, safe_pdf_name)
                with open(pdf_path, "wb") as f:
                    f.write(uploaded_pdf.getbuffer())

            # 2) 신규 work_order id 발급
            work_orders = get_work_orders()
            new_wo_id = max([safe_int(w.get("id", 0)) for w in work_orders], default=0) + 1

            # 3) 설비별 그룹핑 등록
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            registered_cnt = 0
            for equip_raw, sub in df.groupby(equip_col):
                equip = EQUIPMENT_MAP.get(str(equip_raw).strip())
                if not equip:
                    continue

                insert_work_order({
                    "id": new_wo_id,
                    "file_name": uploaded_excel.name,
                    "equipment": equip,
                    "status": "WAITING",
                    "created_at": created_at,
                    "file_hash": "",
                    "excel_file_path": excel_path,
                    "pdf_file_path": pdf_path,
                })

                # lots id 발급
                all_lots = get_lots()
                next_lot_id = max([safe_int(l.get("id", 0)) for l in all_lots], default=0) + 1

                for _, r in sub.iterrows():
                    lot_key = r.get(lot_col)
                    qty_val = r.get(qty_col)
                    move_no = r.get(move_col) if move_col else ""

                    if pd.isna(lot_key):
                        continue

                    qty = safe_int(qty_val, default=None)
                    if qty is None:
                        continue

                    insert_lot({
                        "id": next_lot_id,
                        "work_order_id": new_wo_id,
                        "lot_key": str(lot_key),
                        "qty": qty,
                        "move_card_no": str(move_no),
                        "status": "WAITING",
                        "done_at": "",
                    })
                    next_lot_id += 1

                # 업로드/옵션 PDF 로그
                append_ledger("UPLOAD", "system", new_wo_id, "", f"excel={uploaded_excel.name}")
                if pdf_path:
                    append_ledger("PDF_UPLOAD", "system", new_wo_id, "", os.path.basename(pdf_path))

                registered_cnt += 1
                new_wo_id += 1

            st.success(f"작업지시 등록 완료 ({registered_cnt}건)")
            st.rerun()


# =========================
# 메인: 설비 탭 운영 화면
# =========================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:
        # 상단 필터/도움말
        cA, cB, cC = st.columns([1, 1, 2])
        with cA:
            show_completed = st.checkbox("완료 포함", key=f"comp_{equip}")
        with cB:
            show_void = st.checkbox("취소 포함", key=f"void_{equip}")
        with cC:
            st.caption("작업 흐름: 엑셀(필수) + PDF(선택) 업로드 → LOT 완료/완료취소 → 작업지시 상태 자동 계산")

        all_work_orders = get_work_orders()
        equip_work_orders = [w for w in all_work_orders if w.get("equipment") == equip]

        if not show_completed:
            equip_work_orders = [w for w in equip_work_orders if w.get("status") != "COMPLETED"]
        if not show_void:
            equip_work_orders = [w for w in equip_work_orders if w.get("status") != "VOID"]

        equip_work_orders = sorted(equip_work_orders, key=lambda x: str(x.get("created_at", "")), reverse=True)

        if len(equip_work_orders) == 0:
            st.info("작업지시가 없습니다. 좌측 관리자에서 엑셀을 업로드해 등록하세요.")
            continue

        # KPI (기존과 동일 의미)
        all_lots = get_lots()

        wo_ids_in_equip = {str(w["id"]) for w in equip_work_orders}
        equip_lots = [l for l in all_lots if str(l.get("work_order_id")) in wo_ids_in_equip]

        unfinished_qty = sum(safe_int(l.get("qty", 0)) for l in equip_lots if l.get("status") == "WAITING")

        today = datetime.now().strftime("%Y-%m-%d")
        today_done_qty = sum(
            safe_int(l.get("qty", 0))
            for l in equip_lots
            if l.get("status") == "DONE" and str(l.get("done_at", "")).startswith(today)
        )

        in_progress_cnt = sum(1 for w in equip_work_orders if w.get("status") == "IN_PROGRESS")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("진행중 작업지시", in_progress_cnt)
        k2.metric("미완료 원장(매수)", unfinished_qty)
        k3.metric("오늘 완료(매수)", today_done_qty)
        k4.metric("작업지시 수", len(equip_work_orders))

        st.divider()

        left, right = st.columns([1.05, 2], gap="large")

        # 좌측: 작업지시 리스트(라디오)
        with left:
            st.subheader("작업지시 선택")

            # 선택 유지(설비별)
            sel_key = f"selected_wo_{equip}"
            if sel_key not in st.session_state:
                st.session_state[sel_key] = int(equip_work_orders[0]["id"])

            options = []
            for w in equip_work_orders:
                done, total, status = recalc_work_order_status(w["id"])
                created = str(w.get("created_at", ""))
                filename = str(w.get("file_name", ""))
                options.append((
                    int(w["id"]),
                    f"[{status}] {done}/{total}  |  {created}\n{filename}"
                ))

            selected_id = st.radio(
                "작업지시",
                options,
                index=0,
                key=f"radio_{equip}",
                format_func=lambda x: x[1],
            )[0]

            st.session_state[sel_key] = selected_id

        # 우측: 상세 + 원장
        with right:
            wo = next(w for w in equip_work_orders if int(w["id"]) == int(selected_id))
            wo_status = wo.get("status", "")

            st.subheader("작업지시 상세")

            top1, top2, top3 = st.columns([1.2, 1.2, 1.6])
            with top1:
                st.write(f"**ID:** {wo.get('id')}")
                st.write(f"**상태:** `{wo_status}`")
            with top2:
                st.write(f"**등록:** {wo.get('created_at', '')}")
                st.write(f"**파일:** {wo.get('file_name', '')}")
            with top3:
                # 다운로드 영역
                excel_path = wo.get("excel_file_path", "")
                pdf_path = wo.get("pdf_file_path", "")

                if excel_path and os.path.exists(excel_path):
                    with open(excel_path, "rb") as f:
                        st.download_button(
                            "📥 원본 엑셀 다운로드",
                            f,
                            file_name=wo.get("file_name", "work.xlsx"),
                            use_container_width=True,
                            key=f"down_excel_{equip}_{selected_id}",
                        )
                else:
                    st.caption("엑셀 파일이 서버에 없습니다(재시작/정리로 삭제되었을 수 있음).")

                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "📥 이동카드 PDF 다운로드",
                            f,
                            file_name=os.path.basename(pdf_path),
                            use_container_width=True,
                            key=f"down_pdf_{equip}_{selected_id}",
                        )
                else:
                    st.caption("PDF 없음(선택 업로드)")

            # 작업지시 취소
            st.divider()
            cancel_col, info_col = st.columns([1, 3])
            with cancel_col:
                if wo_status != "VOID":
                    if st.button("⛔ 작업지시 취소(VOID)", use_container_width=True, key=f"void_{equip}_{selected_id}"):
                        update_work_order_status(selected_id, "VOID")
                        append_ledger("VOID", "system", selected_id, "", "")
                        st.rerun()
                else:
                    st.button("이미 취소됨", disabled=True, use_container_width=True, key=f"void_disabled_{equip}_{selected_id}")
            with info_col:
                if wo_status == "VOID":
                    st.warning("이 작업지시는 취소(VOID) 상태입니다. 원장 완료/취소 처리가 잠깁니다.")
                else:
                    st.caption("원장(LOT) 단위로 완료/완료취소를 처리하면 상태가 자동으로 계산됩니다.")

            # LOT 원장
            st.subheader("원장(LOT)")
            lots_df = get_lots(selected_id)

            if len(lots_df) == 0:
                st.info("원장 데이터가 없습니다.")
                continue

            # 원장 표 형태 + 버튼
            for r in lots_df:
                lot_id = r.get("id")
                lot_key = r.get("lot_key", "")
                qty = r.get("qty", "")
                status = r.get("status", "")

                c1, c2, c3, c4, c5 = st.columns([4.5, 1, 1.2, 2, 1.5])
                c1.write(f"**{lot_key}**")
                c2.write(qty)
                c3.write(f"`{status}`")
                c4.write(str(r.get("move_card_no", "")))

                # VOID면 잠금
                if wo_status == "VOID":
                    c5.write("—")
                    continue

                if status == "WAITING":
                    if c5.button("완료", key=f"done_{equip}_{selected_id}_{lot_id}"):
                        update_lot_status(lot_id, "DONE")
                        recalc_work_order_status(selected_id)
                        append_ledger("DONE", "system", selected_id, lot_id)
                        st.rerun()
                else:
                    if c5.button("완료취소", key=f"undo_{equip}_{selected_id}_{lot_id}"):
                        update_lot_status(lot_id, "WAITING")
                        recalc_work_order_status(selected_id)
                        append_ledger("UNDONE", "system", selected_id, lot_id)
                        st.rerun()
