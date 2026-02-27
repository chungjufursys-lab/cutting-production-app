import os
import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from services.drive_service import (
    upload_pdf_to_drive,
    generate_drive_link
)

# =========================
# 기본 설정
# =========================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

# =========================
# Google Sheets 연결
# =========================
@st.cache_resource
def connect_gsheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open("cutting-production-db")
    return spreadsheet.worksheet("work_orders"), spreadsheet.worksheet("lots")

ws_work, ws_lots = connect_gsheet()

# =========================
# 공통 함수
# =========================
def load_ws(ws):
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df.columns = df.columns.astype(str).str.strip()
    return df

def next_id(df):
    if df.empty:
        return 1
    return int(max(df["id"])) + 1

# =========================
# 좌측 업로드 영역
# =========================
st.sidebar.header("📤 작업지시 업로드")

excel_file = st.sidebar.file_uploader("ERP 엑셀 업로드 (필수)", type=["xlsx"])
pdf_file = st.sidebar.file_uploader("이동카드 PDF (선택)", type=["pdf"])

if st.sidebar.button("업로드 실행"):

    if excel_file is None:
        st.sidebar.error("엑셀은 필수입니다.")
        st.stop()

    work_df = load_ws(ws_work)
    new_work_id = next_id(work_df)

    # PDF 처리 (선택)
    file_id = ""
    if pdf_file is not None:
        pdf_bytes = pdf_file.getbuffer()
        drive_filename = f"WO_{new_work_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        file_id = upload_pdf_to_drive(pdf_bytes, drive_filename)

    # 엑셀 처리
    df = pd.read_excel(excel_file)

    equipment = str(df.iloc[0, 0]).strip()

    ws_work.append_row([
        new_work_id,
        excel_file.name,
        equipment,
        "WAITING",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
        file_id
    ])

    lot_df = load_ws(ws_lots)
    lot_id = next_id(lot_df)

    for _, r in df.iterrows():
        lot_key = r.iloc[0]
        if pd.isna(lot_key):
            continue

        ws_lots.append_row([
            lot_id,
            new_work_id,
            str(lot_key),
            1,
            "",
            "WAITING",
            ""
        ])
        lot_id += 1

    st.success("작업지시 등록 완료")
    st.rerun()

# =========================
# 설비 탭
# =========================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df = load_ws(ws_work)
        lots_df = load_ws(ws_lots)

        if work_df.empty:
            st.info("작업지시 없음")
            continue

        filtered = work_df[
            (work_df["equipment"] == equip) &
            (work_df["status"] != "COMPLETED") &
            (work_df["status"] != "VOID")
        ]

        if filtered.empty:
            st.info("해당 설비 작업 없음")
            continue

        left, right = st.columns([1,2])

        with left:
            selected = st.radio(
                "작업지시 선택",
                filtered["id"].tolist(),
                format_func=lambda x: f"WO {x}"
            )

        with right:
            wo = work_df[work_df["id"] == selected].iloc[0]
            pdf_id = wo.get("pdf_drive_file_id", "")

            st.subheader("📎 이동카드")

            # PDF 없을 경우 → 추가 가능
            if not pdf_id:
                new_pdf = st.file_uploader("PDF 추가 업로드", type=["pdf"], key=f"addpdf_{selected}")
                if new_pdf:
                    new_file_id = upload_pdf_to_drive(
                        new_pdf.getbuffer(),
                        f"WO_{selected}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    )
                    cell = ws_work.find(str(selected))
                    ws_work.update_cell(cell.row, work_df.columns.get_loc("pdf_drive_file_id")+1, new_file_id)
                    st.success("PDF 등록 완료")
                    st.rerun()
            else:
                link = generate_drive_link(pdf_id)
                st.link_button("📎 이동카드 열기", link)

                replace_pdf = st.file_uploader("PDF 교체", type=["pdf"], key=f"reppdf_{selected}")
                if replace_pdf:
                    new_file_id = upload_pdf_to_drive(
                        replace_pdf.getbuffer(),
                        f"WO_{selected}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    )
                    cell = ws_work.find(str(selected))
                    ws_work.update_cell(cell.row, work_df.columns.get_loc("pdf_drive_file_id")+1, new_file_id)
                    st.success("PDF 교체 완료")
                    st.rerun()

            st.divider()

            st.subheader("원장 목록")
            wlots = lots_df[lots_df["work_order_id"] == selected]

            for _, r in wlots.iterrows():
                c1, c2 = st.columns([3,1])
                c1.write(r["lot_key"])
                c2.write(r["status"])

# =========================
# 이동카드 검색 (좌측 하단)
# =========================
st.sidebar.divider()
st.sidebar.header("🔍 이동카드 검색")

search_key = st.sidebar.text_input("이동카드번호 입력")

if st.sidebar.button("검색"):
    if search_key.strip() == "":
        st.sidebar.warning("번호 입력 필요")
    else:
        lots_df = load_ws(ws_lots)
        work_df = load_ws(ws_work)

        result = lots_df[lots_df["move_card_no"] == search_key.strip()]

        if result.empty:
            st.error("검색 결과 없음")
        else:
            merged = result.merge(
                work_df,
                left_on="work_order_id",
                right_on="id",
                how="left"
            )
            st.dataframe(
                merged[["equipment", "file_name", "lot_key", "status"]],
                use_container_width=True
            )
