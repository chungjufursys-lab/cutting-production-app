import os
import re
from datetime import datetime
from html import escape
from textwrap import dedent

import pandas as pd
import streamlit as st

from sheets_db import (
    append_ledger,
    get_lots_all,
    get_work_orders,
    insert_lot,
    insert_work_order,
    update_lot_status,
    update_pdf_path,
    update_work_order_status,
)


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

CARD_STYLE = """
<div style="
border:1px solid #d1d5db;
border-radius:14px;
padding:14px;
margin:12px 0 6px 0;
background:#ffffff;
box-shadow: 0 1px 2px rgba(0,0,0,0.04);
">
{body}
</div>
"""


def safe_int(v, default=None):
    try:
        return int(float(v))
    except Exception:
        return default


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_move_cards(raw_value) -> list[str]:
    text = "" if pd.isna(raw_value) else str(raw_value).strip()
    if not text:
        return []

    chunks = [part.strip() for part in text.replace("\n", ",").replace(";", ",").split(",")]
    return [part for part in chunks if part]


def format_move_cards_for_display(raw_value, *, sep="\n") -> str:
    cards = parse_move_cards(raw_value)
    return sep.join(cards) if cards else "-"


def merge_move_cards(values: list[str]) -> str:
    uniq = []
    seen = set()
    for value in values:
        card = str(value).strip()
        if not card or card in seen:
            continue
        seen.add(card)
        uniq.append(card)
    return ", ".join(uniq)


def compute_work_order_status(current_wo_status: str, lots: list[dict]) -> str:
    if current_wo_status == "VOID":
        return "VOID"
    total = len(lots)
    done = sum(1 for lot in lots if lot.get("status") == "DONE")
    if total == 0 or done == 0:
        return "WAITING"
    if done < total:
        return "IN_PROGRESS"
    return "COMPLETED"


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


def _qty_column_score(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric) < 5:
        return float("-inf")

    int_ratio = (numeric % 1 == 0).mean()
    positive_ratio = (numeric > 0).mean()
    small_ratio = (numeric <= 1000).mean()
    median = float(numeric.median())

    score = (int_ratio * 2.0) + (positive_ratio * 1.5) + (small_ratio * 1.5)
    if median > 2000:
        score -= 2.5
    elif median > 1000:
        score -= 1.2
    return score


def _qty_header_score(col_name) -> float:
    name = str(col_name).lower().replace(" ", "")
    positive_keywords = ["qty", "수량", "계획량", "매수", "ea", "pcs"]
    negative_keywords = ["규격", "폭", "길이", "두께", "중량", "면적"]

    score = 0.0
    if any(k in name for k in positive_keywords):
        score += 1.5
    if any(k in name for k in negative_keywords):
        score -= 2.0
    return score


def detect_qty_column(df, lot_col):
    cols = list(df.columns)
    idx = cols.index(lot_col)

    candidates: list[tuple[float, int, str]] = []
    for offset, col in enumerate(cols[idx + 1 :], start=1):
        sample = df[col].dropna().head(120)
        score = _qty_column_score(sample)
        if score == float("-inf"):
            continue

        header_bonus = _qty_header_score(col)
        # LOT과 멀어질수록 감점, 가까운 우측 컬럼 우대
        distance_penalty = offset * 0.12
        final_score = score + header_bonus - distance_penalty
        candidates.append((final_score, offset, col))

    if not candidates:
        return None

    # 근접 후보(LOT 기준 우측 8칸 이내)가 있으면 우선 선택
    nearby = [c for c in candidates if c[1] <= 8]
    target = nearby if nearby else candidates
    target.sort(key=lambda x: x[0], reverse=True)
    return target[0][2]


def detect_move_card_column(df):
    pattern = r"C\d{6}-\d+"
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(100)
        if sample.str.contains(pattern, regex=True).any():
            return col
    return None


def detect_lot_columns(df) -> list[str]:
    cols = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(80)
        if sample.str.contains(r"\d+T-", regex=True).any():
            cols.append(col)
    return cols


def detect_move_card_columns(df) -> list[str]:
    pattern = r"C\d{6}-\d+"
    cols = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(100)
        if sample.str.contains(pattern, regex=True).any():
            cols.append(col)
    return cols


def normalize_header_name(col_name) -> str:
    base = re.sub(r"\.\d+$", "", str(col_name))
    return re.sub(r"\s+", "", base).lower()


def build_lot_qty_move_groups(df) -> list[dict]:
    cols = list(df.columns)
    col_index = {col: i for i, col in enumerate(cols)}
    lot_cols = detect_lot_columns(df)
    move_cols = detect_move_card_columns(df)

    groups = []
    move_cols_by_name: dict[str, list[str]] = {}
    for col in move_cols:
        move_cols_by_name.setdefault(normalize_header_name(col), []).append(col)

    for lot_col in lot_cols:
        qty_col = detect_qty_column(df, lot_col)
        if not qty_col:
            continue

        lot_idx = col_index[lot_col]
        lot_base = normalize_header_name(lot_col)

        # 1순위: LOT 컬럼과 헤더 이름이 같은 이동카드 컬럼
        # (헤더가 비어있어도 '' 이름으로 비교 가능)
        same_name_moves = move_cols_by_name.get(lot_base, [])
        move_col = None
        if same_name_moves:
            move_col = min(same_name_moves, key=lambda m: abs(col_index[m] - lot_idx))

        # 2순위: 위치 기반 가장 가까운 이동카드 컬럼
        if not move_col and move_cols:
            move_col = min(move_cols, key=lambda m: abs(col_index[m] - lot_idx))

        groups.append({"lot_col": lot_col, "qty_col": qty_col, "move_col": move_col})

    return groups


def collect_lot_entries(df: pd.DataFrame, lot_groups: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for _, row in df.iterrows():
        row_seen: set[tuple[str, int, tuple[str, ...]]] = set()
        for group in lot_groups:
            lot_col = group["lot_col"]
            qty_col = group["qty_col"]
            move_col = group.get("move_col")

            lot_key = row.get(lot_col)
            qty = safe_int(row.get(qty_col), None)
            if pd.isna(lot_key) or qty is None:
                continue

            lot_key_value = str(lot_key).strip()
            if not lot_key_value:
                continue

            move_raw = row.get(move_col) if move_col else ""
            move_cards = parse_move_cards(move_raw)
            dedup_key = (lot_key_value, qty, tuple(move_cards))
            if dedup_key in row_seen:
                continue
            row_seen.add(dedup_key)

            entries.append(
                {
                    "lot_key": lot_key_value,
                    "qty": qty,
                    "move_cards": move_cards,
                }
            )
    return entries


def save_upload(uploaded_file, prefix=""):
    filename = f"{prefix}{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as fh:
        fh.write(uploaded_file.getbuffer())
    return path


try:
    ALL_WOS = get_work_orders()
    ALL_LOTS = get_lots_all()
except Exception:
    st.error("Google Sheets 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
    st.stop()

wo_by_id = {str(w.get("id")): w for w in ALL_WOS}
lots_by_wo = {}
for lot in ALL_LOTS:
    wid = str(lot.get("work_order_id"))
    lots_by_wo.setdefault(wid, []).append(lot)

st.sidebar.header("관리자")
with st.sidebar.expander("🔍 이동카드번호 통합 검색", expanded=False):
    with st.form("move_search_form_sidebar"):
        move_search = st.text_input("이동카드번호 입력", placeholder="예: C202602-36114")
        search_mode = st.radio("검색 방식", ["정확히 일치", "포함"], horizontal=True)
        search_submit = st.form_submit_button("검색")

    if search_submit:
        keyword = move_search.strip()
        if not keyword:
            st.warning("이동카드번호를 입력하세요.")
        else:
            rows = []
            keyword_lower = keyword.lower()
            for lot in ALL_LOTS:
                move_cards = parse_move_cards(lot.get("move_card_no", ""))
                if search_mode == "정확히 일치":
                    matched_cards = [card for card in move_cards if card == keyword]
                else:
                    matched_cards = [card for card in move_cards if keyword_lower in card.lower()]

                if not matched_cards:
                    continue

                wo = wo_by_id.get(str(lot.get("work_order_id")))
                if not wo:
                    continue
                rows.append(
                    {
                        "설비": wo.get("equipment", ""),
                        "파일명": wo.get("file_name", ""),
                        "LOT": lot.get("lot_key", ""),
                        "수량": lot.get("qty", ""),
                        "상태": lot.get("status", ""),
                        "일치 이동카드": ", ".join(matched_cards),
                        "전체 이동카드": merge_move_cards(move_cards),
                    }
                )
            if not rows:
                st.error("검색 결과가 없습니다.")
            else:
                st.success(f"{len(rows)}건 발견")
                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=280)

st.sidebar.divider()
with st.sidebar.expander("📤 작업지시 등록 (엑셀 + PDF 선택)", expanded=True):
    uploaded_excel = st.file_uploader("ERP 엑셀 업로드(필수)", type=["xlsx"], key="excel_uploader")
    uploaded_pdf = st.file_uploader("이동카드 PDF(선택)", type=["pdf"], key="pdf_uploader")

    if uploaded_excel:
        df = pd.read_excel(uploaded_excel)
        equip_col = detect_equipment_column(df)
        lot_groups = build_lot_qty_move_groups(df)

        st.caption("자동 감지 결과")
        st.write(f"- 설비 컬럼: **{equip_col}**")
        if lot_groups:
            st.write(f"- LOT/수량/이동카드 페어 수: **{len(lot_groups)}**")
            for i, group in enumerate(lot_groups, start=1):
                st.write(
                    f"  · 페어{i}: LOT=`{group['lot_col']}`, 수량=`{group['qty_col']}`, 이동카드=`{group['move_col'] or '-'}`"
                )
        else:
            st.write("- LOT/수량/이동카드 페어: **감지 실패**")

        ok = True
        if not equip_col:
            st.error("설비 컬럼을 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
            ok = False
        if not lot_groups:
            st.error("LOT/수량 컬럼 페어를 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
            ok = False

        if ok:
            preview_entries = collect_lot_entries(df, lot_groups)
            total_rows = len(preview_entries)
            unique_lots = len({e["lot_key"] for e in preview_entries})
            duplicated_rows = max(total_rows - unique_lots, 0)
            st.caption(f"업로드 미리보기: 유효 행 {total_rows}건 / 고유 LOT {unique_lots}건 / LOT 중복 행 {duplicated_rows}건")
            st.info("같은 LOT가 여러 행에 있으면 수량은 합산되고 이동카드는 중복 제거 후 함께 저장됩니다.")

        if st.button("✅ 작업지시 등록", disabled=(not ok), use_container_width=True):
            excel_path = save_upload(uploaded_excel)
            pdf_path = save_upload(uploaded_pdf) if uploaded_pdf else ""

            new_wo_id = max([safe_int(w.get("id"), 0) for w in ALL_WOS], default=0) + 1
            next_lot_id = max([safe_int(l.get("id"), 0) for l in ALL_LOTS], default=0) + 1

            created_at = now_str()
            registered = 0
            total_registered_lots = 0
            for equip_raw, sub in df.groupby(equip_col):
                equip = EQUIPMENT_MAP.get(str(equip_raw).strip())
                if not equip:
                    continue

                insert_work_order(
                    {
                        "id": new_wo_id,
                        "file_name": uploaded_excel.name,
                        "equipment": equip,
                        "status": "WAITING",
                        "created_at": created_at,
                        "file_hash": "",
                        "excel_file_path": excel_path,
                        "pdf_file_path": pdf_path,
                    }
                )

                lot_map: dict[str, dict] = {}
                move_card_owner: dict[str, str] = {}

                for entry in collect_lot_entries(sub, lot_groups):
                    lot_key_value = entry["lot_key"]
                    lot_data = lot_map.setdefault(
                        lot_key_value,
                        {
                            "qty": 0,
                            "move_cards": [],
                        },
                    )
                    lot_data["qty"] += entry["qty"]

                    for card in entry["move_cards"]:
                        owner = move_card_owner.get(card)
                        if owner and owner != lot_key_value:
                            # 이동카드 1개는 하나의 LOT에만 매핑
                            continue
                        move_card_owner[card] = lot_key_value
                        lot_data["move_cards"].append(card)

                for lot_key_value, lot_data in lot_map.items():
                    insert_lot(
                        {
                            "id": next_lot_id,
                            "work_order_id": new_wo_id,
                            "lot_key": lot_key_value,
                            "qty": lot_data["qty"],
                            "move_card_no": merge_move_cards(lot_data["move_cards"]),
                            "status": "WAITING",
                            "done_at": "",
                        }
                    )
                    total_registered_lots += 1
                    next_lot_id += 1

                append_ledger("UPLOAD", "system", new_wo_id, "", f"excel={uploaded_excel.name}")
                if pdf_path:
                    append_ledger("PDF_UPLOAD", "system", new_wo_id, "", os.path.basename(pdf_path))
                registered += 1
                new_wo_id += 1

            st.success(f"작업지시 등록 완료 (작업지시 {registered}건 / 원장 {total_registered_lots}건)")
            st.rerun()


tabs = st.tabs(EQUIP_TABS)
for idx, equip in enumerate(EQUIP_TABS):
    with tabs[idx]:
        c1, c2, c3, c4 = st.columns([1.3, 1, 1, 2])
        with c1:
            worker_mode = st.toggle("🧤 작업자 모드", value=True, key=f"worker_{equip}")
        with c2:
            show_completed = st.checkbox("완료 포함", value=False, key=f"comp_{equip}")
        with c3:
            show_void = st.checkbox("취소 포함", value=False, key=f"void_{equip}")
        with c4:
            st.caption("작업자 모드 ON + 미완료 기본 표시")

        equip_wos = [w for w in ALL_WOS if w.get("equipment") == equip]
        if not show_void:
            equip_wos = [w for w in equip_wos if w.get("status") != "VOID"]

        rendered_wos = []
        for wo in equip_wos:
            lots = lots_by_wo.get(str(wo.get("id")), [])
            display_status = compute_work_order_status(wo.get("status", ""), lots)
            if not show_completed and display_status == "COMPLETED":
                continue
            rendered_wos.append((wo, lots, display_status))

        if not rendered_wos:
            st.info("표시할 작업지시가 없습니다.")
            continue

        equip_lots = [lot for _, lots, _ in rendered_wos for lot in lots]
        unfinished_qty = sum(safe_int(l.get("qty"), 0) for l in equip_lots if l.get("status") == "WAITING")
        today = datetime.now().strftime("%Y-%m-%d")
        today_done_qty = sum(
            safe_int(l.get("qty"), 0)
            for l in equip_lots
            if l.get("status") == "DONE" and str(l.get("done_at", "")).startswith(today)
        )
        in_progress_cnt = sum(1 for _, _, s in rendered_wos if s == "IN_PROGRESS")

        k1, k2, k3 = st.columns(3)
        k1.metric("진행중", in_progress_cnt)
        k2.metric("미완료(매수)", unfinished_qty)
        k3.metric("오늘 완료(매수)", today_done_qty)
        st.divider()

        left, right = st.columns([1.05, 2], gap="large")
        with left:
            options = []
            for wo, lots, status in rendered_wos:
                done = sum(1 for x in lots if x.get("status") == "DONE")
                total = len(lots)
                options.append((int(wo.get("id")), f"[{status}] {done}/{total}\n{wo.get('created_at','')} | {wo.get('file_name','')}"))

            selected_id = st.radio(
                "작업지시",
                options,
                format_func=lambda x: x[1],
                key=f"radio_{equip}",
            )[0]

        with right:
            wo = wo_by_id.get(str(selected_id))
            lots = lots_by_wo.get(str(selected_id), [])
            wo_status = wo.get("status", "") if wo else ""
            if not wo:
                st.error("선택된 작업지시를 찾을 수 없습니다.")
                continue

            if not worker_mode:
                st.subheader("작업지시 상세")
                d1, d2, d3 = st.columns([1.2, 1.2, 1.8])
                with d1:
                    st.write(f"**ID:** {wo.get('id')}")
                    st.write(f"**상태:** `{wo_status}`")
                with d2:
                    st.write(f"**등록:** {wo.get('created_at', '')}")
                    st.write(f"**파일:** {wo.get('file_name', '')}")
                with d3:
                    excel_path = wo.get("excel_file_path", "")
                    pdf_path = wo.get("pdf_file_path", "")
                    if excel_path and os.path.exists(excel_path):
                        with open(excel_path, "rb") as fh:
                            st.download_button(
                                "📥 원본 엑셀 다운로드",
                                fh,
                                file_name=wo.get("file_name", "work.xlsx"),
                                use_container_width=True,
                                key=f"dl_excel_{equip}_{selected_id}",
                            )
                    else:
                        st.caption("엑셀 파일이 서버에 없습니다.")

                    if pdf_path and os.path.exists(pdf_path):
                        with open(pdf_path, "rb") as fh:
                            st.download_button(
                                "📥 이동카드 PDF 다운로드",
                                fh,
                                file_name=os.path.basename(pdf_path),
                                use_container_width=True,
                                key=f"dl_pdf_{equip}_{selected_id}",
                            )
                    else:
                        st.caption("PDF 없음")

                with st.expander("📎 PDF 교체(선택)", expanded=False):
                    new_pdf = st.file_uploader("새 PDF 업로드", type=["pdf"], key=f"replace_pdf_{equip}_{selected_id}")
                    if new_pdf and st.button("PDF 교체 저장", key=f"replace_btn_{equip}_{selected_id}", use_container_width=True):
                        new_pdf_path = save_upload(new_pdf, prefix=f"{selected_id}_")
                        update_pdf_path(selected_id, new_pdf_path)
                        append_ledger("PDF_REPLACE", "system", selected_id, "", os.path.basename(new_pdf_path))
                        st.success("PDF 교체 완료")
                        st.rerun()

                if wo_status != "VOID":
                    if st.button("⛔ 작업지시 취소(VOID)", use_container_width=True, key=f"void_{equip}_{selected_id}"):
                        update_work_order_status(selected_id, "VOID")
                        append_ledger("VOID", "system", selected_id, "", "")
                        st.rerun()
                else:
                    st.warning("VOID 상태입니다. 완료/완료취소 버튼이 잠깁니다.")
                st.divider()

            if worker_mode:
                pending_lots = [l for l in lots if l.get("status") == "WAITING"]
                st.subheader("미완료 원장")
                if not pending_lots:
                    st.success("🎉 모든 원장이 완료되었습니다.")
                    continue

                for lot in pending_lots:
                    lot_key = str(lot.get("lot_key", ""))
                    qty = safe_int(lot.get("qty"), 0)
                    body = dedent(f"""
                    <div style='display:flex; gap:20px; justify-content:space-between; flex-wrap:wrap;'>
                      <div style='min-width:180px;'>
                        <div style='font-size:14px; color:#6b7280; border-bottom:1px solid #e5e7eb; padding-bottom:4px;'>원장(LOT)</div>
                        <div style='font-size:20px; font-weight:700; margin-top:8px;'>{escape(lot_key)}</div>
                      </div>
                      <div style='min-width:130px;'>
                        <div style='font-size:14px; color:#6b7280; border-bottom:1px solid #e5e7eb; padding-bottom:4px;'>수량</div>
                        <div style='font-size:30px; font-weight:800; margin-top:8px;'>{qty}</div>
                      </div>
                      <div style='min-width:220px;'>
                        <div style='font-size:14px; color:#6b7280; border-bottom:1px solid #e5e7eb; padding-bottom:4px;'>작업상태</div>
                        <div style='font-size:24px; font-weight:800; margin-top:8px; white-space:pre-line;'>대기중</div>
                      </div>
                    </div>
                    """).strip()
                    st.markdown(CARD_STYLE.format(body=body), unsafe_allow_html=True)
                    if st.button("✅ 완료 처리", key=f"done_{equip}_{selected_id}_{lot.get('id')}", use_container_width=True):
                        update_lot_status(lot.get("id"), "DONE")
                        lot_preview = [
                            dict(x, status=("DONE" if str(x.get("id")) == str(lot.get("id")) else x.get("status")))
                            for x in lots
                        ]
                        new_status = compute_work_order_status(wo_status, lot_preview)
                        update_work_order_status(selected_id, new_status)
                        append_ledger("DONE", "system", selected_id, lot.get("id"), "")
                        st.rerun()
            else:
                st.subheader("원장(전체)")
                if not lots:
                    st.info("원장 데이터가 없습니다.")
                    continue

                for lot in lots:
                    lot_id = lot.get("id")
                    lc1, lc2, lc3, lc4, lc5 = st.columns([4.5, 1, 1.2, 2.2, 1.5])
                    lc1.write(f"**{lot.get('lot_key', '')}**")
                    lc2.write(lot.get("qty", ""))
                    lc3.write(f"`{lot.get('status', '')}`")
                    lc4.write(format_move_cards_for_display(lot.get("move_card_no", "")))

                    if wo_status == "VOID":
                        lc5.write("—")
                        continue

                    if lot.get("status") == "WAITING":
                        if lc5.button("완료", key=f"admin_done_{equip}_{selected_id}_{lot_id}"):
                            update_lot_status(lot_id, "DONE")
                            lot_preview = [
                                dict(x, status=("DONE" if str(x.get("id")) == str(lot_id) else x.get("status")))
                                for x in lots
                            ]
                            new_status = compute_work_order_status(wo_status, lot_preview)
                            update_work_order_status(selected_id, new_status)
                            append_ledger("DONE", "system", selected_id, lot_id, "")
                            st.rerun()
                    else:
                        if lc5.button("완료취소", key=f"admin_undo_{equip}_{selected_id}_{lot_id}"):
                            update_lot_status(lot_id, "WAITING")
                            lot_preview = [
                                dict(x, status=("WAITING" if str(x.get("id")) == str(lot_id) else x.get("status")))
                                for x in lots
                            ]
                            new_status = compute_work_order_status(wo_status, lot_preview)
                            update_work_order_status(selected_id, new_status)
                            append_ledger("UNDONE", "system", selected_id, lot_id, "")
                            st.rerun()
