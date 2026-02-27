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
scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=scope,
)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key(SPREADSHEET_ID)
ws_work = spreadsheet.worksheet("work_orders")
ws_lots = spreadsheet.worksheet("lots")

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
    df["id"] = pd.to_numeric(df["id"], errors="coerce")
    if "work_order_id" in df.columns:
        df["work_order_id"] = pd.to_numeric(df["work_order_id"], errors="coerce")
    return df

def next_id(df):
    if df.empty:
        return 1
    return int(df["id"].max()) + 1

# =====================================================
# 작업지시 상태 재계산
# =====================================================
def update_work_status(work_id):
    lots_df = load_ws(ws_lots)
    wlots = lots_df[lots_df["work_order_id"] == work_id]

    if wlots.empty:
        return

    total = len(wlots)
    done = len(wlots[wlots["status"] == "DONE"])

    if done == 0:
        new_status = "WAITING"
    elif done < total:
        new_status = "IN_PROGRESS"
    else:
        new_status = "COMPLETED"

    cell = ws_work.find(str(work_id))
    ws_work.update_cell(cell.row, 4, new_status)

# =====================================================
# 메인 데이터 로드
# =====================================================
work_df = load_ws(ws_work)
lots_df = load_ws(ws_lots)

# =====================================================
# 설비 탭 UI
# =====================================================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        filtered = work_df[work_df["equipment"] == equip]

        if filtered.empty:
            st.info("작업지시 없음")
            continue

        left, right = st.columns([1, 2])

        with left:
            selected = st.radio(
                "작업지시 선택",
                filtered["id"].tolist(),
                format_func=lambda x: f"{x} | {filtered[filtered['id']==x]['file_name'].iloc[0]}"
            )

        with right:
            wo = work_df[work_df["id"] == selected].iloc[0]

            st.markdown("### 📁 파일 관리")
            c1, c2 = st.columns(2)

            if os.path.exists(wo["excel_file_path"]):
                with open(wo["excel_file_path"], "rb") as f:
                    c1.download_button("📥 원본 엑셀 다운로드", f, wo["file_name"], use_container_width=True)

            if wo["pdf_file_path"] and os.path.exists(wo["pdf_file_path"]):
                with open(wo["pdf_file_path"], "rb") as f:
                    c2.download_button("📎 이동카드 다운로드", f, "move_card.pdf", use_container_width=True)

            st.divider()

            wlots = lots_df[lots_df["work_order_id"] == selected]

            for _, r in wlots.iterrows():
                c1, c2, c3 = st.columns([4,1,1])
                c1.write(r["lot_key"])
                c2.write(r["status"])

                if r["status"] == "WAITING":
                    if c3.button("완료", key=f"done_{r['id']}"):
                        cell = ws_lots.find(str(r["id"]))
                        ws_lots.update_cell(cell.row, 6, "DONE")
                        ws_lots.update_cell(cell.row, 7, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        update_work_status(selected)
                        st.rerun()
                else:
                    if c3.button("완료취소", key=f"undo_{r['id']}"):
                        cell = ws_lots.find(str(r["id"]))
                        ws_lots.update_cell(cell.row, 6, "WAITING")
                        ws_lots.update_cell(cell.row, 7, "")
                        update_work_status(selected)
                        st.rerun()
