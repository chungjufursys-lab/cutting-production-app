import os
import re
import hashlib
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

# =====================================================
# 기본 설정
# =====================================================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

SPREADSHEET_ID = "1c810UADSZThIRKuOqyKQzkt5BmVLljgKcevTqFQaN0g"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

# =====================================================
# 업로드 UI (항상 먼저 표시)
# =====================================================
st.sidebar.header("📤 작업지시 업로드")

excel_file = st.sidebar.file_uploader("ERP 엑셀 업로드 (필수)", type=["xlsx"])
pdf_file = st.sidebar.file_uploader("이동카드 PDF (선택)", type=["pdf"])
upload_clicked = st.sidebar.button("업로드 실행")

# =====================================================
# Google Sheets 연결 (실패해도 업로드는 보이도록 try 처리)
# =====================================================
try:
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    ws_work = spreadsheet.worksheet("work_orders")
    ws_lots = spreadsheet.worksheet("lots")
    sheet_connected = True
except Exception as e:
    sheet_connected = False
    st.error("📡 Google Sheets 연결 실패")
    st.warning("시트 연결이 안 되어도 업로드 UI는 표시됩니다.")
    st.write(str(e))

# =====================================================
# 업로드 실행
# =====================================================
if upload_clicked:

    if not sheet_connected:
        st.sidebar.error("시트 연결 실패 상태에서는 업로드할 수 없습니다.")
        st.stop()

    if excel_file is None:
        st.sidebar.error("엑셀은 필수입니다.")
        st.stop()

    try:
        work_data = ws_work.get_all_values()
        lots_data = ws_lots.get_all_values()
    except APIError:
        st.sidebar.error("Google API 호출 제한 초과. 잠시 후 다시 시도하세요.")
        st.stop()

    work_df = pd.DataFrame(work_data[1:], columns=work_data[0]) if len(work_data) > 1 else pd.DataFrame(columns=work_data[0])
    lots_df = pd.DataFrame(lots_data[1:], columns=lots_data[0]) if len(lots_data) > 1 else pd.DataFrame(columns=lots_data[0])

    new_work_id = 1 if work_df.empty else int(pd.to_numeric(work_df["id"]).max()) + 1

    file_hash = hashlib.md5(excel_file.getbuffer()).hexdigest()
    if not work_df.empty and file_hash in work_df["file_hash"].astype(str).tolist():
        st.sidebar.error("이미 등록된 파일입니다.")
        st.stop()

    # 파일 저장
    excel_path = os.path.join(UPLOAD_DIR, f"WO_{new_work_id}_{excel_file.name}")
    with open(excel_path, "wb") as f:
        f.write(excel_file.getbuffer())

    pdf_path = ""
    if pdf_file:
        pdf_path = os.path.join(UPLOAD_DIR, f"WO_{new_work_id}_move.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_file.getbuffer())

    ws_work.append_row([
        new_work_id,
        excel_file.name,
        "미분류",
        "WAITING",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        file_hash,
        excel_path,
        pdf_path
    ])

    st.sidebar.success("업로드 완료")
    st.rerun()

# =====================================================
# 탭 UI (시트 연결 성공 시에만 표시)
# =====================================================
if sheet_connected:

    work_df = pd.DataFrame(ws_work.get_all_values()[1:], columns=ws_work.get_all_values()[0])
    lots_df = pd.DataFrame(ws_lots.get_all_values()[1:], columns=ws_lots.get_all_values()[0])

    tabs = st.tabs(EQUIP_TABS)

    for i, equip in enumerate(EQUIP_TABS):
        with tabs[i]:

            if "equipment" not in work_df.columns:
                st.warning("work_orders 시트에 equipment 컬럼이 없습니다.")
                continue

            filtered = work_df[work_df["equipment"] == equip]

            if filtered.empty:
                st.info("작업지시 없음")
                continue

            selected = st.radio(
                "작업지시 선택",
                filtered["id"].tolist(),
                format_func=lambda x: f"{x} | {filtered[filtered['id']==x]['file_name'].iloc[0]}"
            )

            st.write("작업지시 상세 표시 영역")
