import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from services.drive_service import upload_file, generate_link, cleanup_old_files

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

def update_status(work_df, lots_df):
    for idx, row in work_df.iterrows():
        wid = row["id"]
        wlots = lots_df[lots_df["work_order_id"] == wid]

        if row["status"] == "VOID":
            continue

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

# =========================
# 10일 자동 정리
# =========================
cleanup_old_files(10)

# =========================
# 업로드 영역
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

    file_hash = hashlib.md5(excel_file.getbuffer()).hexdigest()

    if "file_hash" in work_df.columns:
        if file_hash in work_df["file_hash"].astype(str).tolist():
            st.sidebar.error("이미 등록된 파일입니다.")
            st.stop()

    # 엑셀 Drive 업로드
    excel_id = upload_file(
        excel_file.getbuffer(),
        f"WO_{new_work_id}_{excel_file.name}",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    pdf_id = ""
    if pdf_file:
        pdf_id = upload_file(
            pdf_file.getbuffer(),
            f"WO_{new_work_id}_move.pdf",
            "application/pdf"
        )

    df = pd.read_excel(excel_file)
    equipment = str(df.iloc[0, 0]).strip()

    ws_work.append_row([
        new_work_id,
        excel_file.name,
        equipment,
        "WAITING",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        file_hash,
        excel_id,
        pdf_id
    ])

    lots_df = load_ws(ws_lots)
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

# =========================
# 설비 탭 UI 복원
# =========================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        work_df = load_ws(ws_work)
        lots_df = load_ws(ws_lots)

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

        # KPI
        equip_lots = lots_df[lots_df["work_order_id"].isin(filtered["id"])]
        unfinished = len(equip_lots[equip_lots["status"] == "WAITING"])
        today_done = len(equip_lots[equip_lots["status"] == "DONE"])

        c1, c2 = st.columns(2)
        c1.metric("미완료 원장", unfinished)
        c2.metric("완료 원장", today_done)

        left, right = st.columns([1,2])

        with left:
            selected = st.radio(
                "작업지시 선택",
                filtered["id"].tolist(),
                format_func=lambda x: f"{x} | {filtered[filtered['id']==x]['status'].iloc[0]}"
            )

        with right:
            wo = work_df[work_df["id"] == selected].iloc[0]

            st.link_button("📥 원본 엑셀 다운로드",
                           generate_link(wo["excel_drive_file_id"]))

            if wo["pdf_drive_file_id"]:
                st.link_button("📎 이동카드 열기",
                               generate_link(wo["pdf_drive_file_id"]))

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

# =========================
# 이동카드 검색
# =========================
st.sidebar.divider()
st.sidebar.header("🔍 이동카드 검색")

search_key = st.sidebar.text_input("이동카드번호 입력")

if st.sidebar.button("검색"):
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
