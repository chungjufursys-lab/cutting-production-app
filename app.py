import os
import hashlib
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# =====================================================
# 기본 설정
# =====================================================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

SPREADSHEET_ID = "1c810UADSZThIRKuOqyKQzkt5BmVLljgKcevTqFQaN0g"

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

EQUIPMENT_MAP = {
    "판넬컷터 #1": "1호기",
    "판넬컷터 #2": "2호기",
    "네스팅 #1": "네스팅",
    "판넬컷터 #6": "6호기",
    "판넬컷터 #3(곡면)": "곡면",
    "1호기": "1호기",
    "2호기": "2호기",
    "네스팅": "네스팅",
    "6호기": "6호기",
    "곡면": "곡면",
}

# =====================================================
# Google Sheets 연결
# =====================================================
@st.cache_resource
def connect_gsheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet("work_orders"), spreadsheet.worksheet("lots")

ws_work, ws_lots = connect_gsheet()

# =====================================================
# 파일 정리
# =====================================================
def cleanup_files(days=10):
    now = datetime.now()
    for file in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, file)
        if os.path.isfile(path):
            created = datetime.fromtimestamp(os.path.getctime(path))
            if now - created > timedelta(days=days):
                os.remove(path)

cleanup_files(10)

# =====================================================
# 안전 로딩
# =====================================================
def load_ws(ws, required_cols):
    data = ws.get_all_values()

    if not data:
        return pd.DataFrame(columns=required_cols)

    header = [h.strip() for h in data[0]]

    if len(data) == 1:
        return pd.DataFrame(columns=header)

    df = pd.DataFrame(data[1:], columns=header)

    if "id" in df.columns:
        df["id"] = pd.to_numeric(df["id"], errors="coerce")

    if "work_order_id" in df.columns:
        df["work_order_id"] = pd.to_numeric(df["work_order_id"], errors="coerce")

    return df

def next_id(df):
    if df.empty:
        return 1
    return int(df["id"].max()) + 1

# =====================================================
# 업로드
# =====================================================
st.sidebar.header("📤 작업지시 업로드")

excel_file = st.sidebar.file_uploader("ERP 엑셀 업로드 (필수)", type=["xlsx"])
pdf_file = st.sidebar.file_uploader("이동카드 PDF (선택)", type=["pdf"])

if st.sidebar.button("업로드 실행"):

    if excel_file is None:
        st.sidebar.error("엑셀은 필수입니다.")
        st.stop()

    work_df = load_ws(ws_work, [
        "id","file_name","equipment","status",
        "created_at","file_hash",
        "excel_file_path","pdf_file_path"
    ])

    new_work_id = next_id(work_df)

    file_hash = hashlib.md5(excel_file.getbuffer()).hexdigest()

    if not work_df.empty and file_hash in work_df["file_hash"].astype(str).tolist():
        st.sidebar.error("이미 등록된 파일입니다.")
        st.stop()

    excel_filename = f"WO_{new_work_id}_{excel_file.name}"
    excel_path = os.path.join(UPLOAD_DIR, excel_filename)

    with open(excel_path, "wb") as f:
        f.write(excel_file.getbuffer())

    pdf_path = ""
    if pdf_file:
        pdf_filename = f"WO_{new_work_id}_move.pdf"
        pdf_path = os.path.join(UPLOAD_DIR, pdf_filename)
        with open(pdf_path, "wb") as f:
            f.write(pdf_file.getbuffer())

    df = pd.read_excel(excel_file)
    raw_equipment = str(df.iloc[0, 0]).strip()

    equipment = EQUIPMENT_MAP.get(raw_equipment)

    if equipment is None:
        st.sidebar.error(f"설비 매핑 실패: {raw_equipment}")
        st.stop()

    ws_work.append_row([
        new_work_id,
        excel_file.name,
        equipment,
        "WAITING",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        file_hash,
        excel_path,
        pdf_path
    ])

    lots_df = load_ws(ws_lots, [
        "id","work_order_id","lot_key",
        "qty","move_card_no","status","done_at"
    ])

    lot_id = next_id(lots_df)

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

# =====================================================
# 설비 탭
# =====================================================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df = load_ws(ws_work, [
            "id","file_name","equipment","status",
            "created_at","file_hash",
            "excel_file_path","pdf_file_path"
        ])

        filtered = work_df[work_df["equipment"] == equip]

        if filtered.empty:
            st.info("작업지시 없음")
            continue

        st.write(filtered)
