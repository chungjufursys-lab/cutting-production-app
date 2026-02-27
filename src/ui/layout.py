import streamlit as st
from src.domain.exceptions import AppError


def render_app(cfg, repo, sync, workorders, kpis):
    st.title("재단공정 작업관리 시스템 (운영 안정화 v1.0)")

    # --- Top controls ---
    with st.expander("동기화 / 업로드", expanded=True):
        colA, colB, colC, colD = st.columns([1, 1, 2, 2])

        with colA:
            if st.button("Sheets → 앱(당겨오기)"):
                try:
                    r = sync.pull_from_sheets()
                    st.success(f"당겨오기 완료: 작업지시 {r['workorders']}건")
                except AppError as e:
                    st.error(e.user_message)

        with colB:
            if st.button("앱 → Sheets(전송)"):
                try:
                    r = sync.push_to_sheets()
                    st.success(f"전송 시도 완료: {r['pushed']}건")
                except AppError as e:
                    st.error(e.user_message)

        with colC:
            up = st.file_uploader("엑셀 업로드(LOT/수량/이동카드 자동 감지)", type=["xlsx", "xls"])
        with colD:
            if st.button("엑셀 파싱 실행"):
                if not up:
                    st.warning("엑셀 파일을 먼저 올려주세요.")
                else:
                    try:
                        out = workorders.upload_excel_and_parse(up)
                        st.success(f"저장: {out['saved_path']} / 파싱행수: {out['parsed']['count']}")
                        st.json(out["parsed"]["mapping"])
                    except AppError as e:
                        st.error(e.user_message)

    # --- Filters ---
    st.subheader("조회/필터")
    f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
    with f1:
        include_done = st.checkbox("완료 작업 포함", value=False)
    with f2:
        include_canceled = st.checkbox("작업취소 포함", value=False)
    with f3:
        search_move_card = st.text_input("이동카드 검색", value="")
    with f4:
        search_text = st.text_input("통합검색(지시/품목/LOT)", value="")

    # --- KPI ---
    k = kpis.compute()
    k1, k2, k3 = st.columns(3)
    k1.metric("오늘 완료", k["today_done"])
    k2.metric("오늘 취소", k["today_cancel"])
    k3.metric("오늘 완료취소", k["today_undone"])

    # --- Main layout: left = workorders, right = ledger ---
    left, right = st.columns([1.2, 1.8], gap="large")

    wos = repo.list_workorders(
        include_done=include_done,
        include_canceled=include_canceled,
        search_move_card=search_move_card,
        search_text=search_text
    )

    # 선택 상태 유지
    if "selected_wo_id" not in st.session_state:
        st.session_state.selected_wo_id = wos[0]["wo_id"] if wos else None

    with left:
        st.subheader("작업지시(좌측)")
        if not wos:
            st.info("조건에 맞는 작업지시가 없습니다. Sheets에서 당겨오기를 먼저 해보세요.")
        else:
            for wo in wos[:200]:
                is_sel = (wo["wo_id"] == st.session_state.selected_wo_id)
                box = st.container(border=True)
                with box:
                    cols = st.columns([3, 1])
                    with cols[0]:
                        st.markdown(f"**{wo['wo_id']}**  |  상태: `{wo['status']}`")
                        st.caption(f"품목: {wo['item']} / LOT: {wo['lot']} / 수량: {wo['qty']} / 이동카드: {wo['move_card']}")
                    with cols[1]:
                        if st.button("선택", key=f"sel_{wo['wo_id']}"):
                            st.session_state.selected_wo_id = wo["wo_id"]
                            st.rerun()

                    # 작업 버튼
                    note = st.text_input("메모(선택)", key=f"note_{wo['wo_id']}", label_visibility="collapsed", placeholder="메모를 입력할 수 있습니다")
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("완료", key=f"done_{wo['wo_id']}"):
                            try:
                                workorders.complete(wo["wo_id"], note=note)
                                st.success("완료 처리했습니다. (Sheets 전송은 배치로 진행)")
                                st.rerun()
                            except AppError as e:
                                st.error(e.user_message)
                    with b2:
                        if st.button("완료취소", key=f"undone_{wo['wo_id']}"):
                            try:
                                workorders.undo_complete(wo["wo_id"], note=note)
                                st.success("완료취소 처리했습니다.")
                                st.rerun()
                            except AppError as e:
                                st.error(e.user_message)
                    with b3:
                        if st.button("작업취소", key=f"cancel_{wo['wo_id']}"):
                            try:
                                workorders.cancel(wo["wo_id"], note=note)
                                st.success("작업취소 처리했습니다.")
                                st.rerun()
                            except AppError as e:
                                st.error(e.user_message)

                    if is_sel:
                        st.markdown("✅ **현재 선택됨**")

    with right:
        st.subheader("원장(우측)")
        sel = st.session_state.selected_wo_id
        if sel:
            st.caption(f"선택 작업지시: {sel}")
            led = repo.list_ledger(sel)
        else:
            st.caption("선택된 작업지시가 없어 전체 원장 일부를 표시합니다.")
            led = repo.list_ledger(None)

        st.dataframe(led, use_container_width=True, height=520)