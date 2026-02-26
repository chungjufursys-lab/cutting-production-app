import streamlit as st
import pandas as pd
import os
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===============================
# Google Sheets 연결
# ===============================
@st.cache_resource
def connect_gsheet():
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

    return (
        spreadsheet.worksheet("work_orders"),
        spreadsheet.worksheet("lots")
    )

ws_work, ws_lots = connect_gsheet()

def load_work_orders():
    df = pd.DataFrame(ws_work.get_all_records())
    if not df.empty:
        df.columns = df.columns.str.strip()
    return df

def load_lots():
    df = pd.DataFrame(ws_lots.get_all_records())
    if not df.empty:
        df.columns = df.columns.str.strip()
    return df

# ===============================
# 파일 업로드
# ===============================
st.subheader("📤 작업지시 업로드")

uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx"])

if uploaded_file:
    save_path = os.path.join(UPLOAD_DIR, uploaded_file.name)

    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    df = pd.read_excel(save_path)

    # -------------------------
    # 설비 (A열)
    # -------------------------
    equipment = str(df.iloc[0, 0]).strip()

    # -------------------------
    # 원장열 자동 감지
    # -------------------------
    candidate_pairs = [(13,14), (14,15)]  # N,O 또는 O,P

    lot_col = None
    qty_col = None

    for c1, c2 in candidate_pairs:
        if c2 < len(df.columns):
            sample = df.iloc[:, c1:c2+1].dropna()
            if not sample.empty:
                lot_col = c1
                qty_col = c2
                break

    if lot_col is None:
        st.error("원장 열을 찾을 수 없습니다.")
        st.stop()

    lot_df = df.iloc[:, [lot_col, qty_col]].dropna()
    lot_df.columns = ["lot_key", "qty"]

    # SUBTOTAL 제거
    lot_df = lot_df[~lot_df["lot_key"].astype(str).str.contains("SUBTOTAL", na=False)]

    if lot_df.empty:
        st.error("원장 데이터가 없습니다.")
        st.stop()

    # -------------------------
    # work_orders 저장
    # -------------------------
    work_df = load_work_orders()
    new_id = 1 if work_df.empty else int(work_df["id"].max()) + 1

    ws_work.append_row([
        int(new_id),
        uploaded_file.name,
        equipment,
        "WAITING",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ])

    # -------------------------
    # lots 저장
    # -------------------------
    lots_sheet = load_lots()
    next_lot_id = 1 if lots_sheet.empty else int(lots_sheet["id"].max()) + 1

    for _, row in lot_df.iterrows():

        qty_value = row["qty"]

        if pd.isna(qty_value):
            continue

        qty_value = int(float(qty_value))

        ws_lots.append_row([
            int(next_lot_id),
            int(new_id),
            str(row["lot_key"]).strip(),
            qty_value,
            "",
            "WAITING",
            ""
        ])

        next_lot_id += 1

    st.success("업로드 완료")
    st.rerun()

st.divider()

# ===============================
# 설비 탭
# ===============================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df = load_work_orders()
        lots_df = load_lots()

        if work_df.empty:
            st.info("작업지시 없음")
            continue

        work_df = work_df[work_df["equipment"] == equip]

        if work_df.empty:
            st.info("해당 설비 작업 없음")
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
