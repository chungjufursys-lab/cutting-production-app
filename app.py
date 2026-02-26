import os
import re
import time
import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# =====================================================
# 기본 설정
# =====================================================
st.set_page_config(page_title="재단공정 작업관리", layout="wide")
st.title("재단공정 작업관리 시스템")

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

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# =====================================================
# Google Sheets 연결
# =====================================================
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

# =====================================================
# 안전한 데이터 로드 (KeyError 차단)
# =====================================================
def safe_load(ws, required_cols=None):
    try:
        df = pd.DataFrame(ws.get_all_records())
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    df.columns = df.columns.astype(str).str.strip()

    if required_cols:
        for col in required_cols:
            if col not in df.columns:
                return pd.DataFrame()

    return df

def load_work():
    return safe_load(ws_work, ["id", "file_name", "equipment", "status"])

def load_lots():
    return safe_load(ws_lots, ["id", "work_order_id", "lot_key", "qty", "status"])

def next_id(df):
    if df.empty:
        return 1
    nums = []
    for v in df["id"]:
        try:
            nums.append(int(float(v)))
        except:
            pass
    return max(nums) + 1 if nums else 1

def normalize_equipment(val):
    return EQUIPMENT_MAP.get(str(val).strip())

# =====================================================
# 엑셀 감지
# =====================================================
LOT_PATTERN = re.compile(r"\d+(\.\d+)?T-[A-Za-z]+")

def detect_lot_qty(df):
    lot_col = None
    qty_col = None

    for col in df.columns:
        if df[col].astype(str).str.contains(LOT_PATTERN).any():
            lot_col = col
            break

    if lot_col is None:
        raise ValueError("원장 열을 찾을 수 없습니다.")

    idx = list(df.columns).index(lot_col)
    for j in range(idx+1, min(idx+5, len(df.columns))):
        if pd.to_numeric(df[df.columns[j]], errors="coerce").notna().any():
            qty_col = df.columns[j]
            break

    if qty_col is None:
        raise ValueError("수량 열을 찾을 수 없습니다.")

    result = df[[lot_col, qty_col]].copy()
    result.columns = ["lot_key", "qty"]
    result["lot_key"] = result["lot_key"].astype(str).str.strip()
    result = result[result["lot_key"].str.contains(LOT_PATTERN)]
    result["qty"] = pd.to_numeric(result["qty"], errors="coerce").fillna(0).astype(int)
    return result

# =====================================================
# 업로드 (중복 방지 포함)
# =====================================================
st.subheader("📤 작업지시 업로드")

if "upload_lock" not in st.session_state:
    st.session_state.upload_lock = False

with st.form("upload_form", clear_on_submit=True):
    up = st.file_uploader("엑셀 파일 업로드", type=["xlsx"])
    submit = st.form_submit_button("업로드 실행")

if submit and up is not None:

    if st.session_state.upload_lock:
        st.warning("이미 처리된 업로드입니다.")
        st.stop()

    st.session_state.upload_lock = True

    file_bytes = up.getbuffer()
    fhash = hashlib.md5(file_bytes).hexdigest()

    work_df = load_work()
    if "file_hash" in work_df.columns:
        if fhash in work_df["file_hash"].astype(str).tolist():
            st.error("동일한 파일이 이미 등록되었습니다.")
            st.stop()

    save_path = os.path.join(UPLOAD_DIR, up.name)
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    df = pd.read_excel(save_path)

    raw_eq = str(df.iloc[0,0]).strip()
    equipment = normalize_equipment(raw_eq)
    if equipment is None:
        st.error(f"설비 매핑 실패: {raw_eq}")
        st.stop()

    lots = detect_lot_qty(df)

    new_work_id = next_id(work_df)
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ws_work.append_row([
        new_work_id,
        up.name,
        equipment,
        "WAITING",
        created,
        fhash
    ])

    lot_df = load_lots()
    lid = next_id(lot_df)

    for _, r in lots.iterrows():
        ws_lots.append_row([
            lid,
            new_work_id,
            r["lot_key"],
            int(r["qty"]),
            "",
            "WAITING",
            ""
        ])
        lid += 1

    st.success("업로드 완료")
    st.rerun()

st.divider()

# =====================================================
# 설비 탭
# =====================================================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df = load_work()
        lots_df = load_lots()

        if work_df.empty:
            st.info("작업지시 없음")
            continue

        if "equipment" not in work_df.columns:
            st.warning("시트 구조 오류: equipment 컬럼 없음")
            continue

        work_df["equipment"] = work_df["equipment"].astype(str).str.strip()
        filtered = work_df[work_df["equipment"] == equip]

        if filtered.empty:
            st.info("해당설비 작업없음")
            continue

        for _, w in filtered.iterrows():
            wid = w["id"]
            fname = w["file_name"]

            st.subheader(fname)

            if lots_df.empty:
                st.warning("원장 데이터 없음")
                continue

            wlots = lots_df[lots_df["work_order_id"] == wid]

            total = int(wlots["qty"].sum()) if not wlots.empty else 0
            done = int(wlots[wlots["status"] == "DONE"]["qty"].sum()) if not wlots.empty else 0

            pct = 0 if total == 0 else int(done * 100 / total)
            st.progress(pct)
            st.write(f"{done}/{total} 매")

            for _, r in wlots.iterrows():
                c1, c2, c3 = st.columns([3,1,1])
                c1.write(r["lot_key"])
                c2.write(f"{r['qty']}매")

                if r["status"] == "WAITING":
                    if c3.button("완료", key=f"d_{wid}_{r['id']}"):
                        cell = ws_lots.find(str(r["id"]))
                        ws_lots.update_cell(cell.row, 6, "DONE")
                        ws_lots.update_cell(cell.row, 7, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        st.rerun()
                else:
                    if c3.button("취소", key=f"u_{wid}_{r['id']}"):
                        cell = ws_lots.find(str(r["id"]))
                        ws_lots.update_cell(cell.row, 6, "WAITING")
                        ws_lots.update_cell(cell.row, 7, "")
                        st.rerun()
