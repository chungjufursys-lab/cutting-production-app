import streamlit as st
import pandas as pd
import os
import time
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ===================================
# 기본 설정
# ===================================
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

# ===================================
# 오래된 파일 자동 삭제 (2일)
# ===================================
def cleanup_old_uploads(folder="uploads", days=2):
    now = time.time()
    cutoff = now - (days * 86400)
    for filename in os.listdir(folder):
        filepath = os.path.join(folder, filename)
        if os.path.isfile(filepath):
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)

cleanup_old_uploads()

# ===================================
# Google Sheets 연결
# ===================================
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=scope
)

client = gspread.authorize(creds)
spreadsheet = client.open("cutting-production-db")
ws_work = spreadsheet.worksheet("work_orders")
ws_lots = spreadsheet.worksheet("lots")

# ===================================
# 데이터 로드
# ===================================
def load_work_orders():
    data = ws_work.get_all_records()
    return pd.DataFrame(data)

def load_lots():
    data = ws_lots.get_all_records()
    return pd.DataFrame(data)

# ===================================
# 이동카드 검색
# ===================================
st.markdown("## 🔍 이동카드번호 통합 검색")

with st.form("search_form"):
    move_no = st.text_input("이동카드번호 입력")
    search_btn = st.form_submit_button("검색")

if search_btn:
    lots_df = load_lots()
    work_df = load_work_orders()

    result = lots_df[lots_df["move_card_no"] == move_no]

    if result.empty:
        st.warning("검색 결과 없음")
    else:
        merged = result.merge(work_df, left_on="work_order_id", right_on="id")
        st.dataframe(
            merged[["equipment", "file_name", "lot_key", "qty", "status"]],
            use_container_width=True
        )

st.divider()

# ===================================
# 업로드
# ===================================
st.sidebar.header("관리자")
uploaded = st.sidebar.file_uploader("ERP 엑셀 업로드", type=["xlsx"])

def detect_equipment_column(df):
    for col in df.columns:
        if df[col].astype(str).str.contains("판넬컷터|네스팅", regex=True).any():
            return col
    return None

def detect_lot_column(df):
    for col in df.columns[::-1]:
        if df[col].astype(str).str.contains(r"\d+T-", regex=True).any():
            return col
    return None

def detect_qty_column(df, lot_col):
    cols = list(df.columns)
    idx = cols.index(lot_col)
    for col in cols[idx+1:]:
        try:
            float(df[col].dropna().iloc[0])
            return col
        except:
            continue
    return None

def detect_move_card_column(df):
    for col in df.columns:
        if df[col].astype(str).str.contains(r"C\d{6}-\d+", regex=True).any():
            return col
    return None

if uploaded:
    df = pd.read_excel(uploaded)

    equip_col = detect_equipment_column(df)
    lot_col = detect_lot_column(df)
    qty_col = detect_qty_column(df, lot_col)
    move_col = detect_move_card_column(df)

    if st.sidebar.button("작업지시 등록"):

        work_df = load_work_orders()
        new_id = len(work_df) + 1

        equipment_value = EQUIPMENT_MAP.get(
            str(df[equip_col].iloc[0]).strip(),
            str(df[equip_col].iloc[0]).strip()
        )

        ws_work.append_row([
            new_id,
            equipment_value,
            uploaded.name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "WAITING"
        ])

        # 파일 임시 저장
        safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded.name}"
        path = os.path.join(UPLOAD_DIR, safe_name)
        with open(path, "wb") as f:
            f.write(uploaded.getbuffer())

        lots_df = load_lots()
        next_lot_id = len(lots_df) + 1

        for _, row in df.iterrows():
            try:
                lot_key = row[lot_col]
                qty = int(float(row[qty_col]))
                move_no = row.get(move_col, "")
            except:
                continue

            ws_lots.append_row([
                next_lot_id,
                new_id,
                str(lot_key),
                qty,
                str(move_no),
                "WAITING",
                ""
            ])

            next_lot_id += 1

        st.success("등록 완료")
        st.rerun()

# ===================================
# 설비 탭
# ===================================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df = load_work_orders()
        lots_df = load_lots()

        work_df = work_df[work_df["equipment"] == equip]

        if work_df.empty:
            st.info("작업지시 없음")
            continue

        merged = lots_df.merge(work_df, left_on="work_order_id", right_on="id")

        unfinished_qty = merged[merged["status_x"] == "WAITING"]["qty"].sum()

        today = datetime.now().strftime("%Y-%m-%d")
        today_done = merged[
            (merged["status_x"] == "DONE") &
            (merged["done_at"].astype(str).str.startswith(today))
        ]["qty"].sum()

        c1, c2 = st.columns(2)
        c1.metric("미완료 원장(매수)", unfinished_qty)
        c2.metric("오늘 완료 원장(매수)", today_done)

        selected_id = st.selectbox(
            "작업지시 선택",
            work_df["id"],
            format_func=lambda x: work_df[work_df["id"] == x]["file_name"].values[0]
        )

        selected_lots = lots_df[lots_df["work_order_id"] == selected_id]

        for _, r in selected_lots.iterrows():

            col1, col2, col3, col4 = st.columns([4,1,1,1])
            col1.write(r["lot_key"])
            col2.write(r["qty"])
            col3.write(r["status"])

            if r["status"] == "WAITING":
                if col4.button("완료", key=f"done_{r['id']}"):
                    cell = ws_lots.find(str(r["id"]))
                    ws_lots.update_cell(cell.row, 6, "DONE")
                    ws_lots.update_cell(cell.row, 7, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    st.rerun()
            else:
                if col4.button("완료취소", key=f"undo_{r['id']}"):
                    cell = ws_lots.find(str(r["id"]))
                    ws_lots.update_cell(cell.row, 6, "WAITING")
                    ws_lots.update_cell(cell.row, 7, "")
                    st.rerun()



