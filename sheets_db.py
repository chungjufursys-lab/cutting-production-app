import time
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime


# -------------------------
# Client / Spreadsheet
# -------------------------
@st.cache_resource
def get_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes,
    )
    return gspread.authorize(creds)


def get_spreadsheet():
    client = get_client()
    return client.open_by_key(st.secrets["sheets"]["spreadsheet_id"])


def get_ws(name: str):
    return get_spreadsheet().worksheet(name)


# -------------------------
# Retry helpers
# -------------------------
def _retry(call, *, tries=4, base_sleep=0.8):
    last = None
    for attempt in range(tries):
        try:
            return call()
        except gspread.exceptions.APIError as e:
            last = e
            # 지수 백오프
            time.sleep(base_sleep * (2 ** attempt))
    raise last


# -------------------------
# Cached reads (짧은 TTL)
# -------------------------
@st.cache_data(ttl=6, show_spinner=False)
def _cached_records(sheet_name: str):
    ws = get_ws(sheet_name)
    return _retry(lambda: ws.get_all_records())


def invalidate_cache():
    # 전체 cache_data 초기화(간단/확실)
    st.cache_data.clear()


# =========================
# work_orders
# =========================
def get_work_orders():
    return _cached_records(st.secrets["sheets"]["workorders_sheet"])


def insert_work_order(data: dict):
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    _retry(lambda: ws.append_row(list(data.values()), value_input_option="USER_ENTERED"))
    invalidate_cache()


def update_work_order_status(work_order_id, new_status):
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    header = _retry(lambda: ws.row_values(1))
    status_col = header.index("status") + 1

    rows = _retry(lambda: ws.get_all_records())
    for i, row in enumerate(rows, start=2):
        if str(row["id"]) == str(work_order_id):
            _retry(lambda: ws.update_cell(i, status_col, new_status))
            break

    invalidate_cache()


def update_pdf_path(work_order_id, pdf_path):
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    header = _retry(lambda: ws.row_values(1))
    pdf_col = header.index("pdf_file_path") + 1

    rows = _retry(lambda: ws.get_all_records())
    for i, row in enumerate(rows, start=2):
        if str(row["id"]) == str(work_order_id):
            _retry(lambda: ws.update_cell(i, pdf_col, pdf_path))
            break

    invalidate_cache()


# =========================
# lots
# =========================
def get_lots_all():
    return _cached_records(st.secrets["sheets"]["lots_sheet"])


def insert_lot(data: dict):
    ws = get_ws(st.secrets["sheets"]["lots_sheet"])
    _retry(lambda: ws.append_row(list(data.values()), value_input_option="USER_ENTERED"))
    invalidate_cache()


def update_lot_status(lot_id, new_status):
    ws = get_ws(st.secrets["sheets"]["lots_sheet"])
    header = _retry(lambda: ws.row_values(1))

    status_col = header.index("status") + 1
    done_col = header.index("done_at") + 1

    rows = _retry(lambda: ws.get_all_records())
    for i, row in enumerate(rows, start=2):
        if str(row["id"]) == str(lot_id):
            _retry(lambda: ws.update_cell(i, status_col, new_status))
            if new_status == "DONE":
                _retry(lambda: ws.update_cell(i, done_col, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            else:
                _retry(lambda: ws.update_cell(i, done_col, ""))
            break

    invalidate_cache()


# =========================
# LEDGER
# =========================
def append_ledger(action, user, work_order_id="", lot_id="", note=""):
    ws = get_ws(st.secrets["sheets"]["ledger_sheet"])
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        action,
        user,
        work_order_id,
        lot_id,
        note,
    ]
    _retry(lambda: ws.append_row(row, value_input_option="USER_ENTERED"))
    # ledger는 캐시 안 써도 되지만, 통일성 위해 초기화
    invalidate_cache()
