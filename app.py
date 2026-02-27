 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app.py b/app.py
index 839e1d02f95216f879e03d0da7222ab557ac3243..f326654ffa979f6ff11d1406c8fab65ec9c9c1a3 100644
--- a/app.py
+++ b/app.py
@@ -1,525 +1,448 @@
-import streamlit as st
-import pandas as pd
-from datetime import datetime
-import os
-from sheets_db import (
-    get_work_orders, get_lots_all,
-    insert_work_order, insert_lot,
-    update_lot_status, update_work_order_status,
-    update_pdf_path, append_ledger
-)
-
-# =========================
-# 기본 설정
-# =========================
-st.set_page_config(page_title="재단공정 작업관리", layout="wide")
-st.title("재단공정 작업관리 시스템")
-
-EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]
-
-EQUIPMENT_MAP = {
-    "판넬컷터 #1": "1호기",
-    "판넬컷터 #2": "2호기",
-    "네스팅 #1": "네스팅",
-    "판넬컷터 #6": "6호기",
-    "판넬컷터 #3(곡면)": "곡면",
-}
-
-UPLOAD_DIR = "uploads"
-os.makedirs(UPLOAD_DIR, exist_ok=True)
-
-# 카드 스타일 (Streamlit 기본 컴포넌트로는 테두리 제어가 제한적이라 HTML 사용)
-CARD_STYLE = """
-<div style="
-border:1px solid #e5e7eb;
-border-radius:14px;
-padding:14px 14px 12px 14px;
-margin:10px 0;
-background:#ffffff;">
-{body}
-</div>
-"""
-
-# =========================
-# 유틸
-# =========================
-def safe_int(x, default=None):
-    try:
-        return int(float(x))
-    except Exception:
-        return default
-
-def compute_work_order_status(current_wo_status: str, lots: list[dict]) -> tuple[int, int, str]:
-    # VOID는 유지
-    if current_wo_status == "VOID":
-        done = sum(1 for l in lots if l.get("status") == "DONE")
-        return done, len(lots), "VOID"
-
-    total = len(lots)
-    done = sum(1 for l in lots if l.get("status") == "DONE")
-
-    if total == 0 or done == 0:
-        return done, total, "WAITING"
-    if done < total:
-        return done, total, "IN_PROGRESS"
-    return done, total, "COMPLETED"
-
-def now_str():
-    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
-
-# =========================
-# 엑셀 자동 감지 (기존 로직 유지)
-# =========================
-def detect_equipment_column(df):
-    for col in df.columns:
-        sample = df[col].dropna().astype(str).head(40)
-        if sample.str.contains("판넬컷터|네스팅", regex=True).any():
-            return col
-    return None
-
-def detect_lot_column(df):
-    for col in reversed(df.columns):
-        sample = df[col].dropna().astype(str).head(80)
-        if sample.str.contains(r"\d+T-", regex=True).any():
-            return col
-    return None
-
-def detect_qty_column(df, lot_col):
-    cols = list(df.columns)
-    idx = cols.index(lot_col)
-    for col in cols[idx + 1:]:
-        s = df[col].dropna().head(50)
-        if len(s) == 0:
-            continue
-        try:
-            float(s.iloc[0])
-            return col
-        except Exception:
-            continue
-    return None
-
-def detect_move_card_column(df):
-    pattern = r"C\d{6}-\d+"
-    for col in df.columns:
-        sample = df[col].dropna().astype(str).head(100)
-        if sample.str.contains(pattern, regex=True).any():
-            return col
-    return None
-
-# =========================
-# 데이터 로드 (렌더링 1회)
-# =========================
-try:
-    ALL_WOS = get_work_orders()
-    ALL_LOTS = get_lots_all()
-except Exception:
-    st.error("Google Sheets 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
-    st.stop()
-
-wo_by_id = {str(w.get("id")): w for w in ALL_WOS}
-lots_by_wo = {}
-for l in ALL_LOTS:
-    wid = str(l.get("work_order_id"))
-    lots_by_wo.setdefault(wid, []).append(l)
-
-# =========================
-# Sidebar: 관리자 (검색 + 업로드)
-# =========================
-st.sidebar.header("관리자")
-
-with st.sidebar.expander("🔍 이동카드번호 통합 검색", expanded=False):
-    with st.form("move_search_form_sidebar"):
-        move_search = st.text_input("이동카드번호 입력", placeholder="예: C202602-36114")
-        search_submit = st.form_submit_button("검색")
-
-    if search_submit:
-        if move_search.strip() == "":
-            st.warning("이동카드번호를 입력하세요.")
-        else:
-            mc = move_search.strip()
-            rows = []
-            for l in ALL_LOTS:
-                if str(l.get("move_card_no", "")).strip() == mc:
-                    wo = wo_by_id.get(str(l.get("work_order_id")))
-                    if wo:
-                        rows.append({
-                            "설비": wo.get("equipment", ""),
-                            "파일명": wo.get("file_name", ""),
-                            "LOT": l.get("lot_key", ""),
-                            "수량": l.get("qty", ""),
-                            "상태": l.get("status", ""),
-                        })
-            if not rows:
-                st.error("검색 결과가 없습니다.")
-            else:
-                st.success(f"{len(rows)}건 발견")
-                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=240)
-
-st.sidebar.divider()
-
-with st.sidebar.expander("📤 작업지시 등록 (엑셀 + PDF 선택)", expanded=True):
-    uploaded_excel = st.file_uploader("ERP 엑셀 업로드(필수)", type=["xlsx"], key="excel_uploader")
-    uploaded_pdf = st.file_uploader("이동카드 PDF(선택)", type=["pdf"], key="pdf_uploader")
-
-    if uploaded_excel:
-        df = pd.read_excel(uploaded_excel)
-
-        equip_col = detect_equipment_column(df)
-        lot_col = detect_lot_column(df)
-        qty_col = detect_qty_column(df, lot_col) if lot_col else None
-        move_col = detect_move_card_column(df)
-
-        st.caption("자동 감지 결과")
-        st.write(f"- 설비 컬럼: **{equip_col}**")
-        st.write(f"- LOT 컬럼: **{lot_col}**")
-        st.write(f"- 수량 컬럼: **{qty_col}**")
-        st.write(f"- 이동카드 컬럼: **{move_col}**")
-
-        ok = True
-        if not equip_col:
-            st.error("설비 컬럼을 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
-            ok = False
-        if not lot_col or not qty_col:
-            st.error("LOT/수량 컬럼을 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
-            ok = False
-
-        if st.button("✅ 작업지시 등록", disabled=(not ok), use_container_width=True):
-            # 파일 저장
-            excel_safe = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_excel.name}"
-            excel_path = os.path.join(UPLOAD_DIR, excel_safe)
-            with open(excel_path, "wb") as f:
-                f.write(uploaded_excel.getbuffer())
-
-            pdf_path = ""
-            if uploaded_pdf is not None:
-                pdf_safe = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_pdf.name}"
-                pdf_path = os.path.join(UPLOAD_DIR, pdf_safe)
-                with open(pdf_path, "wb") as f:
-                    f.write(uploaded_pdf.getbuffer())
-
-            # 신규 work_order id 발급 (간단 버전)
-            existing_wos = get_work_orders()
-            new_wo_id = max([safe_int(w.get("id"), 0) for w in existing_wos], default=0) + 1
-
-            # lots id 시작
-            existing_lots = get_lots_all()
-            next_lot_id = max([safe_int(l.get("id"), 0) for l in existing_lots], default=0) + 1
-
-            created_at = now_str()
-            registered_cnt = 0
-
-            for equip_raw, sub in df.groupby(equip_col):
-                equip = EQUIPMENT_MAP.get(str(equip_raw).strip())
-                if not equip:
-                    continue
-
-                insert_work_order({
-                    "id": new_wo_id,
-                    "file_name": uploaded_excel.name,
-                    "equipment": equip,
-                    "status": "WAITING",
-                    "created_at": created_at,
-                    "file_hash": "",
-                    "excel_file_path": excel_path,
-                    "pdf_file_path": pdf_path,
-                })
-
-                for _, r in sub.iterrows():
-                    lot_key = r.get(lot_col)
-                    qty_val = r.get(qty_col)
-                    move_no = r.get(move_col) if move_col else ""
-
-                    if pd.isna(lot_key):
-                        continue
-
-                    qty = safe_int(qty_val, default=None)
-                    if qty is None:
-                        continue
-
-                    insert_lot({
-                        "id": next_lot_id,
-                        "work_order_id": new_wo_id,
-                        "lot_key": str(lot_key),
-                        "qty": qty,
-                        "move_card_no": str(move_no),
-                        "status": "WAITING",
-                        "done_at": "",
-                    })
-                    next_lot_id += 1
-
-                append_ledger("UPLOAD", "system", new_wo_id, "", f"excel={uploaded_excel.name}")
-                if pdf_path:
-                    append_ledger("PDF_UPLOAD", "system", new_wo_id, "", os.path.basename(pdf_path))
-
-                registered_cnt += 1
-                new_wo_id += 1
-
-            st.success(f"작업지시 등록 완료 ({registered_cnt}건)")
-            st.rerun()
-
-# =========================
-# 메인: 설비 탭
-# =========================
-tabs = st.tabs(EQUIP_TABS)
-
-for idx, equip in enumerate(EQUIP_TABS):
-    with tabs[idx]:
-
-        # 상단: 모드/필터
-        topA, topB, topC, topD = st.columns([1.2, 1, 1, 2.2])
-        with topA:
-            worker_mode = st.toggle("🧤 작업자 모드", value=True, key=f"worker_{equip}")
-        with topB:
-            show_completed = st.checkbox("완료 포함", value=False, key=f"comp_{equip}")
-        with topC:
-            show_void = st.checkbox("취소 포함", value=False, key=f"void_{equip}")
-        with topD:
-            if worker_mode:
-                st.caption("작업자 모드: 미완료 원장만 카드로 크게 표시됩니다.")
-            else:
-                st.caption("관리자 모드: 전체 원장/다운로드/취소 등 관리 기능이 표시됩니다.")
-
-        # 설비별 작업지시 필터
-        equip_wos = [w for w in ALL_WOS if w.get("equipment") == equip]
-
-        if not show_void:
-            equip_wos = [w for w in equip_wos if w.get("status") != "VOID"]
-        if not show_completed:
-            equip_wos = [w for w in equip_wos if w.get("status") != "COMPLETED"]
-
-        equip_wos = sorted(equip_wos, key=lambda x: str(x.get("created_at", "")), reverse=True)
-
-        if not equip_wos:
-            st.info("작업지시가 없습니다. 좌측 관리자에서 엑셀 업로드로 등록하세요.")
-            continue
-
-        # KPI (관리/작업자 둘 다 보이되, 작업자 모드에서는 간단히)
-        wo_ids = {str(w.get("id")) for w in equip_wos}
-        equip_lots = []
-        for wid in wo_ids:
-            equip_lots.extend(lots_by_wo.get(wid, []))
-
-        unfinished_qty = sum(safe_int(l.get("qty"), 0) for l in equip_lots if l.get("status") == "WAITING")
-        today = datetime.now().strftime("%Y-%m-%d")
-        today_done_qty = sum(
-            safe_int(l.get("qty"), 0)
-            for l in equip_lots
-            if l.get("status") == "DONE" and str(l.get("done_at", "")).startswith(today)
-        )
-        in_progress_cnt = sum(1 for w in equip_wos if w.get("status") == "IN_PROGRESS")
-
-        if not worker_mode:
-            k1, k2, k3, k4 = st.columns(4)
-            k1.metric("진행중 작업지시", in_progress_cnt)
-            k2.metric("미완료 원장(매수)", unfinished_qty)
-            k3.metric("오늘 완료(매수)", today_done_qty)
-            k4.metric("작업지시 수", len(equip_wos))
-            st.divider()
-        else:
-            k1, k2, k3 = st.columns(3)
-            k1.metric("진행중", in_progress_cnt)
-            k2.metric("미완료(매수)", unfinished_qty)
-            k3.metric("오늘 완료(매수)", today_done_qty)
-            st.divider()
-
-        left, right = st.columns([1.05, 2], gap="large")
-
-        # 좌측: 작업지시 선택
-        with left:
-            st.subheader("작업지시 선택")
-            options = []
-            for w in equip_wos:
-                wid = str(w.get("id"))
-                lots = lots_by_wo.get(wid, [])
-                done, total, disp_status = compute_work_order_status(w.get("status", ""), lots)
-                options.append((
-                    int(w.get("id")),
-                    f"[{disp_status}] {done}/{total}\n{w.get('created_at','')}  |  {w.get('file_name','')}"
-                ))
-
-            selected_id = st.radio(
-                "작업지시",
-                options,
-                format_func=lambda x: x[1],
-                key=f"radio_{equip}",
-            )[0]
-
-        # 우측: 상세 + 원장
-        with right:
-            wo = wo_by_id.get(str(selected_id))
-            if not wo:
-                st.error("선택된 작업지시를 찾지 못했습니다.")
-                continue
-
-            wo_status = wo.get("status", "")
-            all_lots_for_wo = lots_by_wo.get(str(selected_id), [])
-
-            # ========= 관리자 모드에서만: 상세/다운로드/VOID/PDF교체 =========
-            if not worker_mode:
-                st.subheader("작업지시 상세")
-
-                a, b, c = st.columns([1.2, 1.2, 1.6])
-                with a:
-                    st.write(f"**ID:** {wo.get('id')}")
-                    st.write(f"**상태:** `{wo_status}`")
-                with b:
-                    st.write(f"**등록:** {wo.get('created_at','')}")
-                    st.write(f"**파일:** {wo.get('file_name','')}")
-                with c:
-                    excel_path = wo.get("excel_file_path", "")
-                    pdf_path = wo.get("pdf_file_path", "")
-
-                    if excel_path and os.path.exists(excel_path):
-                        with open(excel_path, "rb") as f:
-                            st.download_button(
-                                "📥 원본 엑셀 다운로드",
-                                f,
-                                file_name=wo.get("file_name", "work.xlsx"),
-                                use_container_width=True,
-                                key=f"dl_excel_{equip}_{selected_id}",
-                            )
-                    else:
-                        st.caption("엑셀 파일이 서버에 없습니다(서버 재시작 시 삭제될 수 있음).")
-
-                    if pdf_path and os.path.exists(pdf_path):
-                        with open(pdf_path, "rb") as f:
-                            st.download_button(
-                                "📥 이동카드 PDF 다운로드",
-                                f,
-                                file_name=os.path.basename(pdf_path),
-                                use_container_width=True,
-                                key=f"dl_pdf_{equip}_{selected_id}",
-                            )
-                    else:
-                        st.caption("PDF 없음(업로드 단계에서 선택)")
-
-                # PDF 교체(선택)
-                with st.expander("📎 PDF 교체(선택)", expanded=False):
-                    new_pdf = st.file_uploader("새 PDF 업로드", type=["pdf"], key=f"pdf_replace_{equip}_{selected_id}")
-                    if new_pdf is not None:
-                        pdf_safe = f"{selected_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{new_pdf.name}"
-                        new_pdf_path = os.path.join(UPLOAD_DIR, pdf_safe)
-                        with open(new_pdf_path, "wb") as f:
-                            f.write(new_pdf.getbuffer())
-
-                        update_pdf_path(selected_id, new_pdf_path)
-                        append_ledger("PDF_REPLACE", "system", selected_id, "", os.path.basename(new_pdf_path))
-                        st.success("PDF 교체 완료")
-                        st.rerun()
-
-                st.divider()
-
-                # VOID 처리
-                if wo_status != "VOID":
-                    if st.button("⛔ 작업지시 취소(VOID)", use_container_width=True, key=f"void_{equip}_{selected_id}"):
-                        update_work_order_status(selected_id, "VOID")
-                        append_ledger("VOID", "system", selected_id, "", "")
-                        st.rerun()
-                else:
-                    st.warning("이 작업지시는 VOID 상태입니다. 원장 완료/완료취소 처리가 잠깁니다.")
-
-            # ========= 원장 표시: 작업자/관리자 공통 =========
-            if worker_mode:
-                # 작업자 모드: 미완료만 + 카드형 + 숫자 강조
-                lots = [l for l in all_lots_for_wo if l.get("status") == "WAITING"]
-
-                st.subheader("미완료 원장")
-
-                if not lots:
-                    st.success("🎉 모든 원장이 완료되었습니다.")
-                    continue
-
-                for lot in lots:
-                    lot_key = str(lot.get("lot_key", ""))
-                    qty = safe_int(lot.get("qty"), 0)
-                    move = str(lot.get("move_card_no", "")).strip()
-
-                    # 카드 본문: LOT은 작게, 수량/이동카드는 크게
-                    body = f"""
-                    <div style="display:flex; justify-content:space-between; gap:14px; flex-wrap:wrap;">
-                      <div style="min-width:200px;">
-                        <div style="font-size:14px; color:#6b7280;">원장(LOT)</div>
-                        <div style="font-size:18px; font-weight:700; margin-top:2px;">{lot_key}</div>
-                      </div>
-                      <div style="min-width:140px;">
-                        <div style="font-size:14px; color:#6b7280;">수량</div>
-                        <div style="font-size:26px; font-weight:800; margin-top:2px;">{qty}</div>
-                      </div>
-                      <div style="min-width:220px;">
-                        <div style="font-size:14px; color:#6b7280;">이동카드</div>
-                        <div style="font-size:20px; font-weight:800; margin-top:2px;">{move if move else "-"}</div>
-                      </div>
-                    </div>
-                    """
-
-                    st.markdown(CARD_STYLE.format(body=body), unsafe_allow_html=True)
-
-                    # 완료 버튼 (큰 버튼)
-                    if st.button(
-                        "✅ 완료 처리",
-                        key=f"done_{equip}_{selected_id}_{lot.get('id')}",
-                        use_container_width=True
-                    ):
-                        # 1) lot DONE
-                        update_lot_status(lot.get("id"), "DONE")
-
-                        # 2) 작업지시 상태 재계산 후 WRITE (클릭 시에만)
-                        new_lots_view = [
-                            dict(x, status=("DONE" if str(x.get("id")) == str(lot.get("id")) else x.get("status")))
-                            for x in all_lots_for_wo
-                        ]
-                        _, _, new_status = compute_work_order_status(wo_status, new_lots_view)
-                        update_work_order_status(selected_id, new_status)
-
-                        # 3) ledger
-                        append_ledger("DONE", "system", selected_id, lot.get("id"), "")
-
-                        st.success("완료 처리되었습니다.")
-                        st.rerun()
-
-            else:
-                # 관리자 모드: 전체 원장(기존 표형)
-                st.subheader("원장(전체)")
-                if not all_lots_for_wo:
-                    st.info("원장 데이터가 없습니다.")
-                    continue
-
-                for r in all_lots_for_wo:
-                    lot_id = r.get("id")
-                    lot_key = r.get("lot_key", "")
-                    qty = r.get("qty", "")
-                    status = r.get("status", "")
-                    move = r.get("move_card_no", "")
-
-                    c1, c2, c3, c4, c5 = st.columns([4.5, 1, 1.2, 2.2, 1.5])
-                    c1.write(f"**{lot_key}**")
-                    c2.write(qty)
-                    c3.write(f"`{status}`")
-                    c4.write(str(move))
-
-                    if wo_status == "VOID":
-                        c5.write("—")
-                        continue
-
-                    if status == "WAITING":
-                        if c5.button("완료", key=f"admin_done_{equip}_{selected_id}_{lot_id}"):
-                            update_lot_status(lot_id, "DONE")
-                            new_lots_view = [
-                                dict(x, status=("DONE" if str(x.get("id")) == str(lot_id) else x.get("status")))
-                                for x in all_lots_for_wo
-                            ]
-                            _, _, new_status = compute_work_order_status(wo_status, new_lots_view)
-                            update_work_order_status(selected_id, new_status)
-                            append_ledger("DONE", "system", selected_id, lot_id, "")
-                            st.rerun()
-                    else:
-                        if c5.button("완료취소", key=f"admin_undo_{equip}_{selected_id}_{lot_id}"):
-                            update_lot_status(lot_id, "WAITING")
-                            new_lots_view = [
-                                dict(x, status=("WAITING" if str(x.get("id")) == str(lot_id) else x.get("status")))
-                                for x in all_lots_for_wo
-                            ]
-                            _, _, new_status = compute_work_order_status(wo_status, new_lots_view)
-                            update_work_order_status(selected_id, new_status)
-                            append_ledger("UNDONE", "system", selected_id, lot_id, "")
-                            st.rerun()
+import os
+from datetime import datetime
+from html import escape
+from textwrap import dedent
+
+import pandas as pd
+import streamlit as st
+
+from sheets_db import (
+    append_ledger,
+    get_lots_all,
+    get_work_orders,
+    insert_lot,
+    insert_work_order,
+    update_lot_status,
+    update_pdf_path,
+    update_work_order_status,
+)
+
+
+st.set_page_config(page_title="재단공정 작업관리", layout="wide")
+st.title("재단공정 작업관리 시스템")
+
+EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]
+EQUIPMENT_MAP = {
+    "판넬컷터 #1": "1호기",
+    "판넬컷터 #2": "2호기",
+    "네스팅 #1": "네스팅",
+    "판넬컷터 #6": "6호기",
+    "판넬컷터 #3(곡면)": "곡면",
+}
+UPLOAD_DIR = "uploads"
+os.makedirs(UPLOAD_DIR, exist_ok=True)
+
+CARD_STYLE = """
+<div style="
+border:1px solid #d1d5db;
+border-radius:14px;
+padding:14px;
+margin:12px 0 6px 0;
+background:#ffffff;
+box-shadow: 0 1px 2px rgba(0,0,0,0.04);
+">
+{body}
+</div>
+"""
+
+
+def safe_int(v, default=None):
+    try:
+        return int(float(v))
+    except Exception:
+        return default
+
+
+def now_str():
+    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
+
+
+def compute_work_order_status(current_wo_status: str, lots: list[dict]) -> str:
+    if current_wo_status == "VOID":
+        return "VOID"
+    total = len(lots)
+    done = sum(1 for lot in lots if lot.get("status") == "DONE")
+    if total == 0 or done == 0:
+        return "WAITING"
+    if done < total:
+        return "IN_PROGRESS"
+    return "COMPLETED"
+
+
+def detect_equipment_column(df):
+    for col in df.columns:
+        sample = df[col].dropna().astype(str).head(40)
+        if sample.str.contains("판넬컷터|네스팅", regex=True).any():
+            return col
+    return None
+
+
+def detect_lot_column(df):
+    for col in reversed(df.columns):
+        sample = df[col].dropna().astype(str).head(80)
+        if sample.str.contains(r"\d+T-", regex=True).any():
+            return col
+    return None
+
+
+def detect_qty_column(df, lot_col):
+    cols = list(df.columns)
+    idx = cols.index(lot_col)
+    for col in cols[idx + 1 :]:
+        s = df[col].dropna().head(50)
+        if len(s) == 0:
+            continue
+        try:
+            float(s.iloc[0])
+            return col
+        except Exception:
+            continue
+    return None
+
+
+def detect_move_card_column(df):
+    pattern = r"C\d{6}-\d+"
+    for col in df.columns:
+        sample = df[col].dropna().astype(str).head(100)
+        if sample.str.contains(pattern, regex=True).any():
+            return col
+    return None
+
+
+def save_upload(uploaded_file, prefix=""):
+    filename = f"{prefix}{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
+    path = os.path.join(UPLOAD_DIR, filename)
+    with open(path, "wb") as fh:
+        fh.write(uploaded_file.getbuffer())
+    return path
+
+
+try:
+    ALL_WOS = get_work_orders()
+    ALL_LOTS = get_lots_all()
+except Exception:
+    st.error("Google Sheets 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
+    st.stop()
+
+wo_by_id = {str(w.get("id")): w for w in ALL_WOS}
+lots_by_wo = {}
+for lot in ALL_LOTS:
+    wid = str(lot.get("work_order_id"))
+    lots_by_wo.setdefault(wid, []).append(lot)
+
+st.sidebar.header("관리자")
+with st.sidebar.expander("🔍 이동카드번호 통합 검색", expanded=False):
+    with st.form("move_search_form_sidebar"):
+        move_search = st.text_input("이동카드번호 입력", placeholder="예: C202602-36114")
+        search_submit = st.form_submit_button("검색")
+
+    if search_submit:
+        keyword = move_search.strip()
+        if not keyword:
+            st.warning("이동카드번호를 입력하세요.")
+        else:
+            rows = []
+            for lot in ALL_LOTS:
+                if str(lot.get("move_card_no", "")).strip() != keyword:
+                    continue
+                wo = wo_by_id.get(str(lot.get("work_order_id")))
+                if not wo:
+                    continue
+                rows.append(
+                    {
+                        "설비": wo.get("equipment", ""),
+                        "파일명": wo.get("file_name", ""),
+                        "LOT": lot.get("lot_key", ""),
+                        "수량": lot.get("qty", ""),
+                        "상태": lot.get("status", ""),
+                    }
+                )
+            if not rows:
+                st.error("검색 결과가 없습니다.")
+            else:
+                st.success(f"{len(rows)}건 발견")
+                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=240)
+
+st.sidebar.divider()
+with st.sidebar.expander("📤 작업지시 등록 (엑셀 + PDF 선택)", expanded=True):
+    uploaded_excel = st.file_uploader("ERP 엑셀 업로드(필수)", type=["xlsx"], key="excel_uploader")
+    uploaded_pdf = st.file_uploader("이동카드 PDF(선택)", type=["pdf"], key="pdf_uploader")
+
+    if uploaded_excel:
+        df = pd.read_excel(uploaded_excel)
+        equip_col = detect_equipment_column(df)
+        lot_col = detect_lot_column(df)
+        qty_col = detect_qty_column(df, lot_col) if lot_col else None
+        move_col = detect_move_card_column(df)
+
+        st.caption("자동 감지 결과")
+        st.write(f"- 설비 컬럼: **{equip_col}**")
+        st.write(f"- LOT 컬럼: **{lot_col}**")
+        st.write(f"- 수량 컬럼: **{qty_col}**")
+        st.write(f"- 이동카드 컬럼: **{move_col}**")
+
+        ok = True
+        if not equip_col:
+            st.error("설비 컬럼을 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
+            ok = False
+        if not lot_col or not qty_col:
+            st.error("LOT/수량 컬럼을 찾지 못했습니다. 엑셀 내용을 확인해주세요.")
+            ok = False
+
+        if st.button("✅ 작업지시 등록", disabled=(not ok), use_container_width=True):
+            excel_path = save_upload(uploaded_excel)
+            pdf_path = save_upload(uploaded_pdf) if uploaded_pdf else ""
+
+            new_wo_id = max([safe_int(w.get("id"), 0) for w in ALL_WOS], default=0) + 1
+            next_lot_id = max([safe_int(l.get("id"), 0) for l in ALL_LOTS], default=0) + 1
+
+            created_at = now_str()
+            registered = 0
+            for equip_raw, sub in df.groupby(equip_col):
+                equip = EQUIPMENT_MAP.get(str(equip_raw).strip())
+                if not equip:
+                    continue
+
+                insert_work_order(
+                    {
+                        "id": new_wo_id,
+                        "file_name": uploaded_excel.name,
+                        "equipment": equip,
+                        "status": "WAITING",
+                        "created_at": created_at,
+                        "file_hash": "",
+                        "excel_file_path": excel_path,
+                        "pdf_file_path": pdf_path,
+                    }
+                )
+
+                for _, row in sub.iterrows():
+                    lot_key = row.get(lot_col)
+                    qty = safe_int(row.get(qty_col), None)
+                    if pd.isna(lot_key) or qty is None:
+                        continue
+                    move = row.get(move_col) if move_col else ""
+                    move_value = "" if pd.isna(move) else str(move)
+                    insert_lot(
+                        {
+                            "id": next_lot_id,
+                            "work_order_id": new_wo_id,
+                            "lot_key": str(lot_key),
+                            "qty": qty,
+                            "move_card_no": move_value,
+                            "status": "WAITING",
+                            "done_at": "",
+                        }
+                    )
+                    next_lot_id += 1
+
+                append_ledger("UPLOAD", "system", new_wo_id, "", f"excel={uploaded_excel.name}")
+                if pdf_path:
+                    append_ledger("PDF_UPLOAD", "system", new_wo_id, "", os.path.basename(pdf_path))
+                registered += 1
+                new_wo_id += 1
+
+            st.success(f"작업지시 등록 완료 ({registered}건)")
+            st.rerun()
+
+
+tabs = st.tabs(EQUIP_TABS)
+for idx, equip in enumerate(EQUIP_TABS):
+    with tabs[idx]:
+        c1, c2, c3, c4 = st.columns([1.3, 1, 1, 2])
+        with c1:
+            worker_mode = st.toggle("🧤 작업자 모드", value=True, key=f"worker_{equip}")
+        with c2:
+            show_completed = st.checkbox("완료 포함", value=False, key=f"comp_{equip}")
+        with c3:
+            show_void = st.checkbox("취소 포함", value=False, key=f"void_{equip}")
+        with c4:
+            st.caption("작업자 모드 ON + 미완료 기본 표시")
+
+        equip_wos = [w for w in ALL_WOS if w.get("equipment") == equip]
+        if not show_void:
+            equip_wos = [w for w in equip_wos if w.get("status") != "VOID"]
+
+        rendered_wos = []
+        for wo in equip_wos:
+            lots = lots_by_wo.get(str(wo.get("id")), [])
+            display_status = compute_work_order_status(wo.get("status", ""), lots)
+            if not show_completed and display_status == "COMPLETED":
+                continue
+            rendered_wos.append((wo, lots, display_status))
+
+        if not rendered_wos:
+            st.info("표시할 작업지시가 없습니다.")
+            continue
+
+        equip_lots = [lot for _, lots, _ in rendered_wos for lot in lots]
+        unfinished_qty = sum(safe_int(l.get("qty"), 0) for l in equip_lots if l.get("status") == "WAITING")
+        today = datetime.now().strftime("%Y-%m-%d")
+        today_done_qty = sum(
+            safe_int(l.get("qty"), 0)
+            for l in equip_lots
+            if l.get("status") == "DONE" and str(l.get("done_at", "")).startswith(today)
+        )
+        in_progress_cnt = sum(1 for _, _, s in rendered_wos if s == "IN_PROGRESS")
+
+        k1, k2, k3 = st.columns(3)
+        k1.metric("진행중", in_progress_cnt)
+        k2.metric("미완료(매수)", unfinished_qty)
+        k3.metric("오늘 완료(매수)", today_done_qty)
+        st.divider()
+
+        left, right = st.columns([1.05, 2], gap="large")
+        with left:
+            options = []
+            for wo, lots, status in rendered_wos:
+                done = sum(1 for x in lots if x.get("status") == "DONE")
+                total = len(lots)
+                options.append((int(wo.get("id")), f"[{status}] {done}/{total}\n{wo.get('created_at','')} | {wo.get('file_name','')}"))
+
+            selected_id = st.radio(
+                "작업지시",
+                options,
+                format_func=lambda x: x[1],
+                key=f"radio_{equip}",
+            )[0]
+
+        with right:
+            wo = wo_by_id.get(str(selected_id))
+            lots = lots_by_wo.get(str(selected_id), [])
+            wo_status = wo.get("status", "") if wo else ""
+            if not wo:
+                st.error("선택된 작업지시를 찾을 수 없습니다.")
+                continue
+
+            if not worker_mode:
+                st.subheader("작업지시 상세")
+                d1, d2, d3 = st.columns([1.2, 1.2, 1.8])
+                with d1:
+                    st.write(f"**ID:** {wo.get('id')}")
+                    st.write(f"**상태:** `{wo_status}`")
+                with d2:
+                    st.write(f"**등록:** {wo.get('created_at', '')}")
+                    st.write(f"**파일:** {wo.get('file_name', '')}")
+                with d3:
+                    excel_path = wo.get("excel_file_path", "")
+                    pdf_path = wo.get("pdf_file_path", "")
+                    if excel_path and os.path.exists(excel_path):
+                        with open(excel_path, "rb") as fh:
+                            st.download_button(
+                                "📥 원본 엑셀 다운로드",
+                                fh,
+                                file_name=wo.get("file_name", "work.xlsx"),
+                                use_container_width=True,
+                                key=f"dl_excel_{equip}_{selected_id}",
+                            )
+                    else:
+                        st.caption("엑셀 파일이 서버에 없습니다.")
+
+                    if pdf_path and os.path.exists(pdf_path):
+                        with open(pdf_path, "rb") as fh:
+                            st.download_button(
+                                "📥 이동카드 PDF 다운로드",
+                                fh,
+                                file_name=os.path.basename(pdf_path),
+                                use_container_width=True,
+                                key=f"dl_pdf_{equip}_{selected_id}",
+                            )
+                    else:
+                        st.caption("PDF 없음")
+
+                with st.expander("📎 PDF 교체(선택)", expanded=False):
+                    new_pdf = st.file_uploader("새 PDF 업로드", type=["pdf"], key=f"replace_pdf_{equip}_{selected_id}")
+                    if new_pdf and st.button("PDF 교체 저장", key=f"replace_btn_{equip}_{selected_id}", use_container_width=True):
+                        new_pdf_path = save_upload(new_pdf, prefix=f"{selected_id}_")
+                        update_pdf_path(selected_id, new_pdf_path)
+                        append_ledger("PDF_REPLACE", "system", selected_id, "", os.path.basename(new_pdf_path))
+                        st.success("PDF 교체 완료")
+                        st.rerun()
+
+                if wo_status != "VOID":
+                    if st.button("⛔ 작업지시 취소(VOID)", use_container_width=True, key=f"void_{equip}_{selected_id}"):
+                        update_work_order_status(selected_id, "VOID")
+                        append_ledger("VOID", "system", selected_id, "", "")
+                        st.rerun()
+                else:
+                    st.warning("VOID 상태입니다. 완료/완료취소 버튼이 잠깁니다.")
+                st.divider()
+
+            if worker_mode:
+                pending_lots = [l for l in lots if l.get("status") == "WAITING"]
+                st.subheader("미완료 원장")
+                if not pending_lots:
+                    st.success("🎉 모든 원장이 완료되었습니다.")
+                    continue
+
+                for lot in pending_lots:
+                    lot_key = str(lot.get("lot_key", ""))
+                    qty = safe_int(lot.get("qty"), 0)
+                    move = str(lot.get("move_card_no", "")).strip()
+                    body = dedent(f"""
+                    <div style='display:flex; gap:20px; justify-content:space-between; flex-wrap:wrap;'>
+                      <div style='min-width:180px;'>
+                        <div style='font-size:14px; color:#6b7280; border-bottom:1px solid #e5e7eb; padding-bottom:4px;'>원장(LOT)</div>
+                        <div style='font-size:20px; font-weight:700; margin-top:8px;'>{escape(lot_key)}</div>
+                      </div>
+                      <div style='min-width:130px;'>
+                        <div style='font-size:14px; color:#6b7280; border-bottom:1px solid #e5e7eb; padding-bottom:4px;'>수량</div>
+                        <div style='font-size:30px; font-weight:800; margin-top:8px;'>{qty}</div>
+                      </div>
+                      <div style='min-width:220px;'>
+                        <div style='font-size:14px; color:#6b7280; border-bottom:1px solid #e5e7eb; padding-bottom:4px;'>이동카드</div>
+                        <div style='font-size:24px; font-weight:800; margin-top:8px;'>{escape(move if move else '-')}</div>
+                      </div>
+                    </div>
+                    """).strip()
+                    st.markdown(CARD_STYLE.format(body=body), unsafe_allow_html=True)
+                    if st.button("✅ 완료 처리", key=f"done_{equip}_{selected_id}_{lot.get('id')}", use_container_width=True):
+                        update_lot_status(lot.get("id"), "DONE")
+                        lot_preview = [
+                            dict(x, status=("DONE" if str(x.get("id")) == str(lot.get("id")) else x.get("status")))
+                            for x in lots
+                        ]
+                        new_status = compute_work_order_status(wo_status, lot_preview)
+                        update_work_order_status(selected_id, new_status)
+                        append_ledger("DONE", "system", selected_id, lot.get("id"), "")
+                        st.rerun()
+            else:
+                st.subheader("원장(전체)")
+                if not lots:
+                    st.info("원장 데이터가 없습니다.")
+                    continue
+
+                for lot in lots:
+                    lot_id = lot.get("id")
+                    lc1, lc2, lc3, lc4, lc5 = st.columns([4.5, 1, 1.2, 2.2, 1.5])
+                    lc1.write(f"**{lot.get('lot_key', '')}**")
+                    lc2.write(lot.get("qty", ""))
+                    lc3.write(f"`{lot.get('status', '')}`")
+                    lc4.write(str(lot.get("move_card_no", "")))
+
+                    if wo_status == "VOID":
+                        lc5.write("—")
+                        continue
+
+                    if lot.get("status") == "WAITING":
+                        if lc5.button("완료", key=f"admin_done_{equip}_{selected_id}_{lot_id}"):
+                            update_lot_status(lot_id, "DONE")
+                            lot_preview = [
+                                dict(x, status=("DONE" if str(x.get("id")) == str(lot_id) else x.get("status")))
+                                for x in lots
+                            ]
+                            new_status = compute_work_order_status(wo_status, lot_preview)
+                            update_work_order_status(selected_id, new_status)
+                            append_ledger("DONE", "system", selected_id, lot_id, "")
+                            st.rerun()
+                    else:
+                        if lc5.button("완료취소", key=f"admin_undo_{equip}_{selected_id}_{lot_id}"):
+                            update_lot_status(lot_id, "WAITING")
+                            lot_preview = [
+                                dict(x, status=("WAITING" if str(x.get("id")) == str(lot_id) else x.get("status")))
+                                for x in lots
+                            ]
+                            new_status = compute_work_order_status(wo_status, lot_preview)
+                            update_work_order_status(selected_id, new_status)
+                            append_ledger("UNDONE", "system", selected_id, lot_id, "")
+                            st.rerun()
 
EOF
)
