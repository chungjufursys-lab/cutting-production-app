from typing import List, Dict, Any
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


class SheetsGateway:
    def __init__(self, sheet_cfg, logger):
        self.sheet_cfg = sheet_cfg
        self.logger = logger
        self._client = None

    def _get_client(self):
        if self._client:
            return self._client

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        sa_info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        self._client = gspread.authorize(creds)
        return self._client

    def _open(self):
        client = self._get_client()
        return client.open_by_key(self.sheet_cfg.spreadsheet_id)

    def fetch_workorders(self) -> List[Dict[str, Any]]:
        sh = self._open()
        ws = sh.worksheet(self.sheet_cfg.workorders_sheet)
        rows = ws.get_all_records()
        return rows

    def fetch_ledger(self) -> List[Dict[str, Any]]:
        sh = self._open()
        ws = sh.worksheet(self.sheet_cfg.ledger_sheet)
        rows = ws.get_all_records()
        return rows

    def batch_update_workorder_status(self, updates: List[Dict[str, Any]], wo_id_col_name: str, status_col_name: str, updated_at_col_name: str):
        """
        updates: [{"wo_id": "...", "status": "DONE", "updated_at": "..."}]
        구현 단순화를 위해:
        - 시트에서 wo_id 컬럼 위치 찾고
        - 해당 row를 찾아 status/updated_at 셀을 update
        """
        if not updates:
            return

        sh = self._open()
        ws = sh.worksheet(self.sheet_cfg.workorders_sheet)

        header = ws.row_values(1)
        col_idx = {name: i + 1 for i, name in enumerate(header)}

        if wo_id_col_name not in col_idx or status_col_name not in col_idx or updated_at_col_name not in col_idx:
            raise ValueError("WORK_ORDERS 시트 헤더(컬럼명)가 config와 다릅니다. config.py ColumnMap을 확인하세요.")

        wo_col = col_idx[wo_id_col_name]
        status_col = col_idx[status_col_name]
        upd_col = col_idx[updated_at_col_name]

        # wo_id -> row number mapping (한 번에 구축)
        all_wo_ids = ws.col_values(wo_col)[1:]  # exclude header
        row_map = {}
        for i, val in enumerate(all_wo_ids, start=2):
            if val:
                row_map[str(val).strip()] = i

        # 셀 업데이트 모으기
        cell_updates = []
        for u in updates:
            wo_id = str(u["wo_id"]).strip()
            r = row_map.get(wo_id)
            if not r:
                continue
            cell_updates.append(gspread.Cell(r, status_col, str(u["status"])))
            cell_updates.append(gspread.Cell(r, upd_col, str(u["updated_at"])))

        if cell_updates:
            ws.update_cells(cell_updates)

    def append_ledger_rows(self, rows: List[Dict[str, Any]]):
        if not rows:
            return
        sh = self._open()
        ws = sh.worksheet(self.sheet_cfg.ledger_sheet)

        header = ws.row_values(1)
        values = []
        for r in rows:
            values.append([r.get(h, "") for h in header])

        ws.append_rows(values, value_input_option="USER_ENTERED")