import streamlit as st
import pandas as pd
from datetime import datetime
import os
from sheets_db import (
    get_work_orders, get_lots_all,
    insert_work_order, insert_lot,
    update_lot_status, update_work_order_status,
    update_pdf_path, append_ledger
)

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
# 유틸
# =========================
def safe_int(x, default=None):
    try:
        return int(float(x))
    except Exception:
        return default


def compute_work_order_status(wo_status: str, lots: list[dict]):
    # VOID는 무조건 유지
    if wo_status == "VOID":
        done = sum(1 for l in lots if l.get("status") == "DONE")
        return done, len(lots), "VOID"

    total = len(lots)
    done = sum(1 for l in lots if l.get("status") == "DONE")

    if total == 0 or done == 0:
        return done, total, "WAITING"
    if done < total:
        return done, total, "IN_PROGRESS"
    return done, total, "COMPLETED"


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
# 1) Sidebar: 관리자 영역 (검색 + 업로드)
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
            # 렌더링에서 1회 로드
            all_wos = get_work_orders()
            all_lots = get_lots_all()
            wo_by_id = {str(w["id"]): w for w in all_wos}

            rows = []
            for l in all_lots:
                if str(l.get("move_card_no", "")).strip() == move_search.strip():
                    wo = wo_by_id.get(str(l.get("work_order_id")))
                    if wo:
                        rows.append({
                            "설비": wo.get("equipment", ""),
                            "파일명": wo.get("file_name", ""),
                            "LOT": l.get("lot_key", ""),
                            "수량": l.get("qty", ""),
                            "상태": l.get("status", ""),
                        })

            if not rows:
                st.error("검색 결과가 없습니다.")
            else:
                st.success(f"{len(rows)}건 발견")
                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=240)

st.sidebar.divider()

with st.sidebar.expander("📤 작업지시 등록 (엑셀 + PDF 선택)", expanded=True):
    uploaded_excel = st.file_uploader("ERP 엑셀 업로드(필수)", type=["xlsx"], key="excel_uploader")
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
            # 파일 저장
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

            # 신규 id 발급 (간단 버전: 1주 운영 목표)
            existing_wos = get_work_orders()
            new_wo_id = max([safe_int(w.get("id", 0), 0) for w in existing_wos], default=0) + 1

            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # lots id 시작
            existing_lots = get_lots_all()
            next_lot_id = max([safe_int(l.get("id", 0), 0) for l in existing_lots], default=0) + 1

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

                append_ledger("UPLOAD", "system", new_wo_id, "", f"excel={uploaded_excel.name}")
                if pdf_path:
                    append_ledger("PDF_UPLOAD", "system", new_wo_id, "", os.path.basename(pdf_path))

                registered_cnt += 1
                new_wo_id += 1

            st.success(f"작업지시 등록 완료 ({registered_cnt}건)")
            st.rerun()


# =========================
# 2) 메인: 설비 탭 운영
# =========================
try:
    # ✅ 렌더링에서 딱 1번씩만 읽기
    ALL_WOS = get_work_orders()
    ALL_LOTS = get_lots_all()
except Exception:
    st.error("Google Sheets 연결/쿼터 문제로 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
    st.stop()

wo_by_id = {str(w["id"]): w for w in ALL_WOS}
lots_by_wo = {}
for l in ALL_LOTS:
    wid = str(l.get("work_order_id"))
    lots_by_wo.setdefault(wid, []).append(l)

tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            show_completed = st.checkbox("완료 포함", key=f"comp_{equip}")
        with c2:
            show_void = st.checkbox("취소 포함", key=f"void_{equip}")
        with c3:
            st.caption("※ 1주 운영 안정화를 위해, 화면 표시 중에는 시트 WRITE를 하지 않도록 최적화됨")

        equip_wos = [w for w in ALL_WOS if w.get("equipment") == equip]

        if not show_completed:
            equip_wos = [w for w in equip_wos if w.get("status") != "COMPLETED"]
        if not show_void:
            equip_wos = [w for w in equip_wos if w.get("status") != "VOID"]

        equip_wos = sorted(equip_wos, key=lambda x: str(x.get("created_at", "")), reverse=True)

        if not equip_wos:
            st.info("작업지시가 없습니다. 좌측 관리자에서 엑셀을 업로드해 등록하세요.")
            continue

        # KPI (표시용)
        wo_ids = {str(w["id"]) for w in equip_wos}
        equip_lots = []
        for wid in wo_ids:
            equip_lots.extend(lots_by_wo.get(wid, []))

        unfinished_qty = sum(safe_int(l.get("qty", 0), 0) for l in equip_lots if l.get("status") == "WAITING")
        today = datetime.now().strftime("%Y-%m-%d")
        today_done_qty = sum(
            safe_int(l.get("qty", 0), 0)
            for l in equip_lots
            if l.get("status") == "DONE" and str(l.get("done_at", "")).startswith(today)
        )
        in_progress_cnt = sum(1 for w in equip_wos if w.get("status") == "IN_PROGRESS")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("진행중 작업지시", in_progress_cnt)
        k2.metric("미완료(매수)", unfinished_qty)
        k3.metric("오늘 완료(매수)", today_done_qty)
        k4.metric("작업지시 수", len(equip_wos))

        st.divider()

        left, right = st.columns([1.1, 2], gap="large")

        with left:
            st.subheader("작업지시 선택")

            options = []
            for w in equip_wos:
                wid = str(w["id"])
                done, total, disp_status = compute_work_order_status(w.get("status", ""), lots_by_wo.get(wid, []))
                options.append((int(w["id"]), f"[{disp_status}] {done}/{total} | {w.get('created_at','')}\n{w.get('file_name','')}"))

            selected_id = st.radio(
                "작업지시",
                options,
                format_func=lambda x: x[1],
                key=f"radio_{equip}",
            )[0]

        with right:
            selected_wo = wo_by_id.get(str(selected_id))
            if not selected_wo:
                st.error("선택된 작업지시를 찾지 못했습니다.")
                continue

            wo_status = selected_wo.get("status", "")
            st.subheader("작업지시 상세")

            a, b, c = st.columns([1.2, 1.2, 1.6])
            with a:
                st.write(f"**ID:** {selected_wo.get('id')}")
                st.write(f"**상태:** `{wo_status}`")
            with b:
                st.write(f"**등록:** {selected_wo.get('created_at','')}")
                st.write(f"**파일:** {selected_wo.get('file_name','')}")
            with c:
                excel_path = selected_wo.get("excel_file_path", "")
                pdf_path = selected_wo.get("pdf_file_path", "")

                if excel_path and os.path.exists(excel_path):
                    with open(excel_path, "rb") as f:
                        st.download_button("📥 원본 엑셀", f, file_name=selected_wo.get("file_name","work.xlsx"),
                                           use_container_width=True, key=f"dl_excel_{equip}_{selected_id}")
                else:
                    st.caption("엑셀 파일이 서버에 없습니다(재시작 시 삭제될 수 있음).")

                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        st.download_button("📥 이동카드 PDF", f, file_name=os.path.basename(pdf_path),
                                           use_container_width=True, key=f"dl_pdf_{equip}_{selected_id}")
                else:
                    st.caption("PDF 없음(업로드 단계에서 선택)")

            st.divider()

            # 작업지시 취소
            if wo_status != "VOID":
                if st.button("⛔ 작업지시 취소(VOID)", use_container_width=True, key=f"void_{equip}_{selected_id}"):
                    update_work_order_status(selected_id, "VOID")
                    append_ledger("VOID", "system", selected_id, "", "")
                    st.rerun()
            else:
                st.warning("이 작업지시는 VOID 상태입니다. LOT 완료/완료취소가 잠깁니다.")

            st.subheader("원장(LOT)")

            lots = lots_by_wo.get(str(selected_id), [])
            if not lots:
                st.info("원장 데이터가 없습니다.")
                continue

            for r in lots:
                lot_id = r.get("id")
                lot_key = r.get("lot_key", "")
                qty = r.get("qty", "")
                status = r.get("status", "")
                move = r.get("move_card_no", "")

                x1, x2, x3, x4, x5 = st.columns([4.5, 1, 1.2, 2.2, 1.5])
                x1.write(f"**{lot_key}**")
                x2.write(qty)
                x3.write(f"`{status}`")
                x4.write(str(move))

                if wo_status == "VOID":
                    x5.write("—")
                    continue

                if status == "WAITING":
                    if x5.button("완료", key=f"done_{equip}_{selected_id}_{lot_id}"):
                        update_lot_status(lot_id, "DONE")

                        # ✅ 클릭 이벤트에서만 작업지시 상태 WRITE
                        new_done, new_total, new_status = compute_work_order_status(
                            wo_status,
                            [dict(rr, status=("DONE" if rr.get("id") == lot_id else rr.get("status"))) for rr in lots]
                        )
                        update_work_order_status(selected_id, new_status)

                        append_ledger("DONE", "system", selected_id, lot_id, "")
                        st.rerun()
                else:
                    if x5.button("완료취소", key=f"undo_{equip}_{selected_id}_{lot_id}"):
                        update_lot_status(lot_id, "WAITING")

                        new_done, new_total, new_status = compute_work_order_status(
                            wo_status,
                            [dict(rr, status=("WAITING" if rr.get("id") == lot_id else rr.get("status"))) for rr in lots]
                        )
                        update_work_order_status(selected_id, new_status)

                        append_ledger("UNDONE", "system", selected_id, lot_id, "")
                        st.rerun()
