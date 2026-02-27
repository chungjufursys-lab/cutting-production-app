import os
import re
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
# 엑셀 자동 감지 (DB버전 복원)
# =====================================================
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
    for col in cols[idx+1:]:
        s = df[col].dropna().head(50)
        if len(s) == 0:
            continue
        try:
            float(s.iloc[0])
            return col
        except:
            continue
    return None

def detect_move_card_column(df):
    pattern = r"C\d{6}-\d+"
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(100)
        if sample.str.contains(pattern, regex=True).any():
            return col
    return None

# =====================================================
# 데이터 로딩
# =====================================================
def load_ws(ws):
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    header = data[0]
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

    work_df = load_ws(ws_work)
    new_work_id = next_id(work_df)

    file_hash = hashlib.md5(excel_file.getbuffer()).hexdigest()
    if not work_df.empty and file_hash in work_df["file_hash"].astype(str).tolist():
        st.sidebar.error("이미 등록된 파일입니다.")
        st.stop()

    df = pd.read_excel(excel_file)

    equip_col = detect_equipment_column(df)
    lot_col = detect_lot_column(df)
    qty_col = detect_qty_column(df, lot_col)
    move_col = detect_move_card_column(df)

    if not equip_col or not lot_col or not qty_col:
        st.sidebar.error("엑셀 구조 감지 실패")
        st.stop()

    raw_equipment = str(df[equip_col].dropna().iloc[0]).strip()
    equipment = EQUIPMENT_MAP.get(raw_equipment)

    if equipment is None:
        st.sidebar.error(f"설비 매핑 실패: {raw_equipment}")
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
        equipment,
        "WAITING",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        file_hash,
        excel_path,
        pdf_path
    ])

    lots_df = load_ws(ws_lots)
    lot_id = next_id(lots_df)

    for _, r in df.iterrows():
        lot_key = r.get(lot_col)
        qty_val = r.get(qty_col)
        move_no = r.get(move_col) if move_col else ""

        if pd.isna(lot_key):
            continue
        if "SUBTOTAL" in str(lot_key):
            continue

        try:
            qty = int(float(qty_val))
        except:
            continue

        ws_lots.append_row([
            lot_id,
            new_work_id,
            str(lot_key),
            qty,
            str(move_no),
            "WAITING",
            ""
        ])
        lot_id += 1

    st.success("작업지시 등록 완료")
    st.rerun()
