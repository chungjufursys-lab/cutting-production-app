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
# 안전한 Google Sheets 연결
# =====================================================
@st.cache_resource
def connect_gsheet():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=scope,
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        return spreadsheet
    except KeyError:
        st.error("🔐 서비스계정 키(secrets) 설정이 올바르지 않습니다.")
        st.stop()
    except APIError:
        st.error("📡 Google Sheets 접근 실패.\n시트 공유 또는 API 활성화를 확인하세요.")
        st.stop()
    except Exception as e:
        st.error(f"❗ Google 연결 오류: {e}")
        st.stop()

spreadsheet = connect_gsheet()

try:
    ws_work = spreadsheet.worksheet("work_orders")
    ws_lots = spreadsheet.worksheet("lots")
except Exception:
    st.error("📄 work_orders 또는 lots 시트를 찾을 수 없습니다.")
    st.stop()

# =====================================================
# 파일 자동 정리
# =====================================================
def cleanup_files(days=10):
    try:
        now = datetime.now()
        for file in os.listdir(UPLOAD_DIR):
            path = os.path.join(UPLOAD_DIR, file)
            if os.path.isfile(path):
                created = datetime.fromtimestamp(os.path.getctime(path))
                if now - created > timedelta(days=days):
                    os.remove(path)
    except Exception:
        pass

cleanup_files(10)

# =====================================================
# 안전 로딩
# =====================================================
def load_ws(ws):
    try:
        data = ws.get_all_values()
    except APIError:
        st.error("📡 Google Sheets 호출 제한 초과 또는 네트워크 오류입니다.\n잠시 후 다시 시도하세요.")
        st.stop()
    except Exception as e:
        st.error(f"❗ 시트 로딩 중 오류: {e}")
        st.stop()

    if not data:
        return pd.DataFrame()

    header = data[0]
    if len(data) == 1:
        return pd.DataFrame(columns=header)

    df = pd.DataFrame(data[1:], columns=header)

    try:
        if "id" in df.columns:
            df["id"] = pd.to_numeric(df["id"], errors="coerce")
        if "work_order_id" in df.columns:
            df["work_order_id"] = pd.to_numeric(df["work_order_id"], errors="coerce")
    except Exception:
        st.error("📊 시트 데이터 형식 오류 (숫자 변환 실패)")
        st.stop()

    return df

work_df = load_ws(ws_work)
lots_df = load_ws(ws_lots)

# =====================================================
# 설비 탭 UI
# =====================================================
tabs = st.tabs(EQUIP_TABS)

for i, equip in enumerate(EQUIP_TABS):
    with tabs[i]:

        try:
            filtered = work_df[work_df["equipment"] == equip]
        except KeyError:
            st.error("📄 work_orders 시트에 'equipment' 컬럼이 없습니다.")
            continue

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

            with c1:
                path = wo.get("excel_file_path", "")
                if path and os.path.exists(path):
                    with open(path, "rb") as f:
                        st.download_button(
                            "📥 원본 엑셀 다운로드",
                            f,
                            file_name=wo["file_name"],
                            use_container_width=True
                        )
                else:
                    st.warning("엑셀 파일이 서버에 존재하지 않습니다.\n(10일 경과 삭제 가능)")

            with c2:
                path = wo.get("pdf_file_path", "")
                if path and os.path.exists(path):
                    with open(path, "rb") as f:
                        st.download_button(
                            "📎 이동카드 다운로드",
                            f,
                            file_name="move_card.pdf",
                            use_container_width=True
                        )
                else:
                    st.info("이동카드가 등록되지 않았습니다.")

            st.divider()

            wlots = lots_df[lots_df["work_order_id"] == selected]

            for _, r in wlots.iterrows():
                c1, c2 = st.columns([4,1])
                c1.write(r.get("lot_key", ""))
                c2.write(r.get("status", ""))
