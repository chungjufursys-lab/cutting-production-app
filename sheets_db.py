import time
from datetime import datetime

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials


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
def _retry(call, *, tries=5, base_sleep=0.7):
    last_err = None
    for attempt in range(tries):
        try:
            return call()
        except gspread.exceptions.APIError as err:
            last_err = err
            time.sleep(base_sleep * (2**attempt))
    raise last_err


# -------------------------
# Cached reads
# -------------------------
@st.cache_data(ttl=6, show_spinner=False)
def _cached_records(sheet_name: str):
    ws = get_ws(sheet_name)
    return _retry(lambda: ws.get_all_records())


def invalidate_cache():
    st.cache_data.clear()


def _header_map(ws):
    headers = _retry(lambda: ws.row_values(1))
    return {name: idx + 1 for idx, name in enumerate(headers)}


def _find_row_by_id(ws, row_id, *, id_col="id"):
    cells = _retry(lambda: ws.get_all_values())
    if not cells:
        return None, None

    headers = cells[0]
    try:
        id_idx = headers.index(id_col)
    except ValueError:
        return None, None

    for row_no, row in enumerate(cells[1:], start=2):
        if id_idx < len(row) and str(row[id_idx]) == str(row_id):
            return row_no, headers
    return None, headers


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
    row_no, headers = _find_row_by_id(ws, work_order_id, id_col="id")
    if row_no is None:
        return False

    status_idx = headers.index("status") + 1
    _retry(lambda: ws.update_cell(row_no, status_idx, new_status))
    invalidate_cache()
    return True


def update_pdf_path(work_order_id, pdf_path):
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    row_no, headers = _find_row_by_id(ws, work_order_id, id_col="id")
    if row_no is None:
        return False

    pdf_idx = headers.index("pdf_file_path") + 1
    _retry(lambda: ws.update_cell(row_no, pdf_idx, pdf_path))
    invalidate_cache()
    return True


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
    row_no, headers = _find_row_by_id(ws, lot_id, id_col="id")
    if row_no is None:
        return False

    status_idx = headers.index("status") + 1
    done_idx = headers.index("done_at") + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if new_status == "DONE" else ""

    _retry(lambda: ws.batch_update([
        {"range": gspread.utils.rowcol_to_a1(row_no, status_idx), "values": [[new_status]]},
        {"range": gspread.utils.rowcol_to_a1(row_no, done_idx), "values": [[now]]},
    ]))
    invalidate_cache()
    return True


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
    invalidate_cache()
