import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

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


def get_ws(name):
    return get_spreadsheet().worksheet(name)


# =========================
# work_orders
# =========================

def get_work_orders():
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    return ws.get_all_records()


def insert_work_order(data: dict):
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    ws.append_row(list(data.values()), value_input_option="USER_ENTERED")


def update_work_order_status(work_order_id, new_status):
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    rows = ws.get_all_records()
    header = ws.row_values(1)

    id_col = header.index("id") + 1
    status_col = header.index("status") + 1

    for i, row in enumerate(rows, start=2):
        if str(row["id"]) == str(work_order_id):
            ws.update_cell(i, status_col, new_status)
            break


def update_pdf_path(work_order_id, pdf_path):
    ws = get_ws(st.secrets["sheets"]["workorders_sheet"])
    rows = ws.get_all_records()
    header = ws.row_values(1)

    id_col = header.index("id") + 1
    pdf_col = header.index("pdf_file_path") + 1

    for i, row in enumerate(rows, start=2):
        if str(row["id"]) == str(work_order_id):
            ws.update_cell(i, pdf_col, pdf_path)
            break


# =========================
# lots
# =========================

def get_lots(work_order_id=None):
    ws = get_ws(st.secrets["sheets"]["lots_sheet"])
    rows = ws.get_all_records()
    if work_order_id is None:
        return rows
    return [r for r in rows if str(r["work_order_id"]) == str(work_order_id)]


def insert_lot(data: dict):
    ws = get_ws(st.secrets["sheets"]["lots_sheet"])
    ws.append_row(list(data.values()), value_input_option="USER_ENTERED")


def update_lot_status(lot_id, new_status):
    ws = get_ws(st.secrets["sheets"]["lots_sheet"])
    rows = ws.get_all_records()
    header = ws.row_values(1)

    id_col = header.index("id") + 1
    status_col = header.index("status") + 1
    done_col = header.index("done_at") + 1

    for i, row in enumerate(rows, start=2):
        if str(row["id"]) == str(lot_id):
            ws.update_cell(i, status_col, new_status)
            if new_status == "DONE":
                ws.update_cell(i, done_col, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            else:
                ws.update_cell(i, done_col, "")
            break


# =========================
# LEDGER
# =========================

def append_ledger(action, user, work_order_id="", lot_id="", note=""):
    ws = get_ws(st.secrets["sheets"]["ledger_sheet"])
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        action,
        user,
        work_order_id,
        lot_id,
        note
    ])
