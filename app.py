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
    LOCKS_COLS,
    WORK_ORDERS_ALIASES,
    LOTS_ALIASES,
)
from services.gsheet import connect_gsheet, ensure_schema, read_all_as_df, build_row_map
from services.excel_parser import parse_excel
from services.status_service import compute_work_order_status, count_done_total
from services.kpi_service import compute_kpis
from services.lock_service import acquire_lock, release_lock

# =========================
# 기본 설정
# =========================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

OWNER = "streamlit_app"  # 락 owner 표시용(원하면 사용자명/PC명으로 바꿔도 됨)

# =========================
# Google Sheets 연결
# =========================
handles = connect_gsheet()
ws_work = handles.ws_work
ws_lots = handles.ws_lots
ws_locks = handles.ws_locks

# =========================
# 스키마 보정(앱 시작 시 1회)
# =========================
try:
    work_col_map = ensure_schema(ws_work, WORK_ORDERS_COLS, WORK_ORDERS_ALIASES)
    lots_col_map = ensure_schema(ws_lots, LOTS_COLS, LOTS_ALIASES)
    # locks도 헤더 보정
    _ = ensure_schema(ws_locks, LOCKS_COLS, {c: [] for c in LOCKS_COLS})
except Exception as e:
    st.error(f"구글시트 스키마 확인/보정 중 오류: {e}")
    st.stop()

# =========================
# 데이터 로드 (캐시)
# =========================
@st.cache_data(ttl=15)
def load_all():
    work_df, work_values = read_all_as_df(ws_work)
    lots_df, lots_values = read_all_as_df(ws_lots)

    # 표준 컬럼이 없더라도 ensure_schema가 만들어줬지만, 혹시 모를 상황 대비
    if work_df.empty:
        work_df = pd.DataFrame(columns=WORK_ORDERS_COLS)
        work_values = [WORK_ORDERS_COLS]
    if lots_df.empty:
        lots_df = pd.DataFrame(columns=LOTS_COLS)
        lots_values = [LOTS_COLS]

    # 누락 컬럼 생성(죽지 않게)
    for c in WORK_ORDERS_COLS:
        if c not in work_df.columns:
            work_df[c] = ""
    for c in LOTS_COLS:
        if c not in lots_df.columns:
            lots_df[c] = ""

    # 타입 정리
    work_df["id"] = work_df["id"].astype(str).str.strip()
    work_df["equipment"] = work_df["equipment"].astype(str).str.strip()
    work_df["status"] = work_df["status"].astype(str).str.strip()
    work_df["file_hash"] = work_df["file_hash"].astype(str).str.strip()

    lots_df["id"] = lots_df["id"].astype(str).str.strip()
    lots_df["work_order_id"] = lots_df["work_order_id"].astype(str).str.strip()
    lots_df["lot_key"] = lots_df["lot_key"].astype(str).str.strip()
    lots_df["move_card_no"] = lots_df["move_card_no"].astype(str).str.strip()
    lots_df["status"] = lots_df["status"].astype(str).str.strip()
    lots_df["qty"] = pd.to_numeric(lots_df["qty"], errors="coerce").fillna(0).astype(int)
    lots_df["done_at"] = lots_df["done_at"].astype(str)

    work_row_map = build_row_map(work_values, "id")
    lots_row_map = build_row_map(lots_values, "id")

    return work_df, lots_df, work_row_map, lots_row_map


def invalidate_cache():
    load_all.clear()


def next_id(df: pd.DataFrame) -> int:
    if df.empty:
        return 1
    nums = []
    for v in df["id"].astype(str).tolist():
        try:
            nums.append(int(float(v)))
        except Exception:
            pass
    return (max(nums) + 1) if nums else 1


# =========================
# 🔍 이동카드번호 통합 검색 (내부DB UI 동일)
# =========================
st.markdown("## 🔍 이동카드번호 통합 검색")

with st.form("move_search_form"):
    move_search = st.text_input("이동카드번호 입력 (예: C202602-36114)")
    search_submit = st.form_submit_button("검색")

if search_submit:
    key = move_search.strip()
    if key == "":
        st.warning("이동카드번호를 입력하세요.")
    else:
        work_df, lots_df, _, _ = load_all()
        # join
        merged = lots_df.merge(
            work_df[["id", "equipment", "file_name"]],
            left_on="work_order_id",
            right_on="id",
            how="left",
            suffixes=("", "_wo"),
        )
        result = merged[merged["move_card_no"].astype(str).str.strip() == key][
            ["equipment", "file_name", "lot_key", "qty", "status", "move_card_no"]
        ]

        if result.empty:
            st.error("검색 결과가 없습니다.")
        else:
            st.success(f"{len(result)}건 발견")
            st.dataframe(result, use_container_width=True)

st.divider()

# =========================
# 📤 업로드 (내부DB UI 감각 + 락 + 중복방지)
# =========================
st.sidebar.header("관리자")

with st.sidebar.form("upload_form", clear_on_submit=True):
    up = st.file_uploader("ERP 엑셀 업로드", type=["xlsx"])
    do_upload = st.form_submit_button("작업지시 등록")

if do_upload and up is not None:
    # 분산락(멀티 사용자 업로드 경합 방지)
    if not acquire_lock(ws_locks, lock_key="upload", owner=OWNER, ttl_seconds=120):
        st.sidebar.warning("다른 사용자가 업로드 중입니다. 잠시 후 다시 시도하세요.")
        st.stop()

    try:
        work_df, lots_df, _, _ = load_all()

        file_bytes = up.getbuffer()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        if file_hash in work_df["file_hash"].astype(str).tolist():
            st.sidebar.error("동일한 파일이 이미 등록되었습니다. (file_hash 중복)")
            st.stop()

        # 파일 저장(주의: Streamlit Cloud는 장기 저장 보장 안 됨)
        safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{up.name}"
        save_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(save_path, "wb") as f:
            f.write(file_bytes)

        # 엑셀 파싱
        parsed = parse_excel(save_path)

        new_work_id = next_id(work_df)
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # work_orders append
        ws_work.append_row([
            new_work_id,
            up.name,
            parsed.equipment,
            "WAITING",
            created,
            file_hash,
        ])

        # lots append
        lot_df = lots_df
        new_lot_id = next_id(lot_df)

        rows_to_append = []
        for _, r in parsed.lots.iterrows():
            rows_to_append.append([
                new_lot_id,
                new_work_id,
                str(r["lot_key"]).strip(),
                int(r["qty"]),
                str(r.get("move_card_no", "")).strip(),
                "WAITING",
                "",
            ])
            new_lot_id += 1

        # 한 번에 여러 줄 append(호출 횟수 감소)
        # gspread는 append_rows 지원(버전에 따라 다름). 없으면 fallback.
        if hasattr(ws_lots, "append_rows"):
            ws_lots.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        else:
            for row in rows_to_append:
                ws_lots.append_row(row)

        st.sidebar.success(f"작업지시 등록 완료: {parsed.equipment} / lots {len(rows_to_append)}개")
        invalidate_cache()
        st.rerun()

    except Exception as e:
        st.sidebar.error(f"업로드 실패: {e}")
        st.stop()
    finally:
        release_lock(ws_locks, lock_key="upload", owner=OWNER)

st.divider()

# =========================
# 설비 탭 (내부DB UI 형태로 복원)
# =========================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:
        work_df, lots_df, work_row_map, lots_row_map = load_all()

        show_completed = st.checkbox("완료 작업지시 포함", key=f"comp_{equip}")
        show_void = st.checkbox("취소 작업지시 포함", key=f"void_{equip}")

        # 설비 필터
        w = work_df[work_df["equipment"] == equip].copy()
        if not show_void:
            w = w[w["status"] != WO_STATUS_VOID]
        if not show_completed:
            w = w[w["status"] != "COMPLETED"]

        # 최신순
        # created_at이 비어도 죽지 않게 string 기준 정렬
        w["created_at_sort"] = w["created_at"].astype(str)
        w = w.sort_values("created_at_sort", ascending=False)

        # KPI
        k = compute_kpis(work_df, lots_df, equip)
        c1, c2, c3 = st.columns(3)
        c1.metric("진행중 작업지시", k["in_progress_cnt"])
        c2.metric("미완료 원장 (매수)", k["unfinished_qty"])
        c3.metric("오늘 완료 원장 (매수)", k["today_done_qty"])

        st.divider()

        if w.empty:
            st.info("작업지시 없음")
            continue

        left, right = st.columns([1, 2])

        with left:
            options = []
            for _, r in w.iterrows():
                wid = str(r["id"]).strip()
                cur_status = str(r["status"]).strip()
                derived = compute_work_order_status(lots_df, wid, cur_status)
                done_cnt, total_cnt = count_done_total(lots_df, wid)

                label = f"{derived} | {done_cnt}/{total_cnt}\n{r['file_name']}"
                options.append((wid, label))

            selected = st.radio("작업지시 선택", options, format_func=lambda x: x[1])
            selected_id = selected[0]

        with right:
            wo = work_df[work_df["id"] == str(selected_id)].copy()
            if wo.empty:
                st.warning("선택한 작업지시를 찾을 수 없습니다.")
                continue

            wo_row = wo.iloc[0]
            wo_status = str(wo_row["status"]).strip()
            file_name = str(wo_row["file_name"]).strip()

            # 작업지시 상태(파생 포함 표시)
            derived_status = compute_work_order_status(lots_df, selected_id, wo_status)
            st.subheader(f"{file_name}")
            st.caption(f"상태: {wo_status} (표시용 계산상태: {derived_status})")

            # 취소 버튼(VOID)
            if wo_status != WO_STATUS_VOID:
                if st.button("⛔ 작업지시 취소", key=f"void_btn_{equip}_{selected_id}"):
                    # work_orders status 업데이트
                    row_no = work_row_map.get(str(selected_id))
                    if row_no is None:
                        st.error("work_orders에서 해당 id 행을 찾지 못했습니다.")
                    else:
                        # status는 4번째 컬럼(D)
                        ws_work.update(f"D{row_no}", WO_STATUS_VOID)
                        invalidate_cache()
                        st.rerun()

            # 원본 엑셀 다운로드(현재는 업로드 폴더에서만 가능: Cloud 재시작 시 유실 가능)
            st.info("원본 다운로드는 현재 서버 저장(uploads) 기반입니다. Streamlit Cloud 재배포/재시작 시 파일이 유실될 수 있습니다. "
                    "장기 보관이 필요하면 Google Drive 저장 방식으로 확장하는 것을 권장합니다.")

            st.divider()

            # lots 표시
            wlots = lots_df[lots_df["work_order_id"] == str(selected_id)].copy()
            if wlots.empty:
                st.warning("원장 데이터 없음")
                continue

            for _, lr in wlots.iterrows():
                lot_id = str(lr["id"]).strip()
                lot_key = str(lr["lot_key"]).strip()
                qty = int(lr["qty"])
                lstatus = str(lr["status"]).strip()

                c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
                c1.write(lot_key)
                c2.write(qty)
                c3.write(lstatus)

                # VOID면 버튼 비활성
                if wo_status == WO_STATUS_VOID:
                    c4.write("-")
                    continue

                row_no = lots_row_map.get(lot_id)
                if row_no is None:
                    c4.write("행없음")
                    continue

                if lstatus == LOT_STATUS_WAITING:
                    if c4.button("완료", key=f"done_{equip}_{selected_id}_{lot_id}"):
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        # lots: status(F), done_at(G)
                        ws_lots.update(f"F{row_no}", LOT_STATUS_DONE)
                        ws_lots.update(f"G{row_no}", now)

                        # work_orders status도 즉시 반영(내부DB용 UX 동일)
                        # (캐시 갱신 후 계산)
                        invalidate_cache()
                        work_df2, lots_df2, work_row_map2, _ = load_all()
                        wo2 = work_df2[work_df2["id"] == str(selected_id)]
                        if not wo2.empty:
                            cur = str(wo2.iloc[0]["status"]).strip()
                            new_status = compute_work_order_status(lots_df2, selected_id, cur)
                            wrow = work_row_map2.get(str(selected_id))
                            if wrow is not None:
                                ws_work.update(f"D{wrow}", new_status)

                        invalidate_cache()
                        st.rerun()
                else:
                    if c4.button("완료취소", key=f"undo_{equip}_{selected_id}_{lot_id}"):
                        ws_lots.update(f"F{row_no}", LOT_STATUS_WAITING)
                        ws_lots.update(f"G{row_no}", "")

                        invalidate_cache()
                        work_df2, lots_df2, work_row_map2, _ = load_all()
                        wo2 = work_df2[work_df2["id"] == str(selected_id)]
                        if not wo2.empty:
                            cur = str(wo2.iloc[0]["status"]).strip()
                            new_status = compute_work_order_status(lots_df2, selected_id, cur)
                            wrow = work_row_map2.get(str(selected_id))
                            if wrow is not None:
                                ws_work.update(f"D{wrow}", new_status)

                        invalidate_cache()
                        st.rerun()