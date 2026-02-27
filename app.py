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

# =====================================================
# Google Sheets 연결 (open_by_key 사용)
# =====================================================
@st.cache_resource
def connect_gsheet():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    return spreadsheet.worksheet("work_orders"), spreadsheet.worksheet("lots")

ws_work, ws_lots = connect_gsheet()

# =====================================================
# 10일 파일 자동 삭제
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
# 안전 로딩 함수
# =====================================================
def load_ws(ws, required_cols):
    try:
        data = ws.get_all_values()
    except Exception as e:
        st.error(f"시트 로딩 실패: {e}")
        st.stop()

    if not data:
        return pd.DataFrame(columns=required_cols)

    header = [h.strip() for h in data[0]]

    for col in required_cols:
        if col not in header:
            st.error(f"시트 구조 오류: '{col}' 컬럼이 없습니다.")
            st.stop()

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
# 상태 자동 계산
# =====================================================
def update_status(work_df, lots_df):
    for _, row in work_df.iterrows():
        wid = row["id"]

        if row["status"] == "VOID":
            continue

        wlots = lots_df[lots_df["work_order_id"] == wid]
        if wlots.empty:
            continue

        total = len(wlots)
        done = len(wlots[wlots["status"] == "DONE"])

        if done == 0:
            new_status = "WAITING"
        elif done < total:
            new_status = "IN_PROGRESS"
        else:
            new_status = "COMPLETED"

        if new_status != row["status"]:
            cell = ws_work.find(str(wid))
            ws_work.update_cell(cell.row, 4, new_status)

# =====================================================
# 업로드 영역
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

    # 엑셀 저장
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
    equipment = str(df.iloc[0, 0]).strip()

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
# 설비 탭 UI
# =====================================================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df = load_ws(ws_work, [
            "id","file_name","equipment","status",
            "created_at","file_hash",
            "excel_file_path","pdf_file_path"
        ])

        lots_df = load_ws(ws_lots, [
            "id","work_order_id","lot_key",
            "qty","move_card_no","status","done_at"
        ])

        update_status(work_df, lots_df)

        show_completed = st.checkbox("완료 포함", key=f"comp_{equip}")
        show_void = st.checkbox("취소 포함", key=f"void_{equip}")

        filtered = work_df[work_df["equipment"] == equip]

        if not show_completed:
            filtered = filtered[filtered["status"] != "COMPLETED"]

        if not show_void:
            filtered = filtered[filtered["status"] != "VOID"]

        if filtered.empty:
            st.info("작업지시 없음")
            continue

        left, right = st.columns([1,2])

        with left:
            selected = st.radio(
                "작업지시 선택",
                filtered["id"].tolist(),
                format_func=lambda x: f"{x} | {filtered[filtered['id']==x]['status'].iloc[0]}"
            )

        with right:
            wo = work_df[work_df["id"] == selected].iloc[0]

            if wo["excel_file_path"] and os.path.exists(wo["excel_file_path"]):
                with open(wo["excel_file_path"], "rb") as f:
                    st.download_button("📥 원본 엑셀 다운로드", f, file_name=wo["file_name"])

            if wo["pdf_file_path"] and os.path.exists(wo["pdf_file_path"]):
                with open(wo["pdf_file_path"], "rb") as f:
                    st.download_button("📎 이동카드 다운로드", f, file_name="move.pdf")

            st.divider()

            wlots = lots_df[lots_df["work_order_id"] == selected]

            for _, r in wlots.iterrows():
                c1, c2, c3 = st.columns([3,1,1])
                c1.write(r["lot_key"])
                c2.write(r["status"])

                if r["status"] == "WAITING":
                    if c3.button("완료", key=f"d_{r['id']}"):
                        cell = ws_lots.find(str(r["id"]))
                        ws_lots.update_cell(cell.row, 6, "DONE")
                        st.rerun()

# =====================================================
# 이동카드 검색
# =====================================================
st.sidebar.divider()
st.sidebar.header("🔍 이동카드 검색")

search_key = st.sidebar.text_input("이동카드번호 입력")

if st.sidebar.button("검색"):
    lots_df = load_ws(ws_lots, [
        "id","work_order_id","lot_key",
        "qty","move_card_no","status","done_at"
    ])
    work_df = load_ws(ws_work, [
        "id","file_name","equipment","status",
        "created_at","file_hash",
        "excel_file_path","pdf_file_path"
    ])

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
