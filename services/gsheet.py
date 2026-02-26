from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


@dataclass
class SheetHandle:
    ws_work: gspread.Worksheet
    ws_lots: gspread.Worksheet
    ws_locks: gspread.Worksheet


@st.cache_resource
def connect_gsheet() -> SheetHandle:
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scope,
    )
    client = gspread.authorize(creds)

    spreadsheet_name = st.secrets.get("app", {}).get("spreadsheet_name", "cutting-production-db")
    ss = client.open(spreadsheet_name)

    ws_work = ss.worksheet("work_orders")
    ws_lots = ss.worksheet("lots")
    # locks 탭이 없다면 사용자가 만들어야 함. (여기서 만들 수도 있지만 권한/정책상 수동 생성 권장)
    ws_locks = ss.worksheet("locks")
    return SheetHandle(ws_work=ws_work, ws_lots=ws_lots, ws_locks=ws_locks)


def _normalize_header_values(vals: List[str]) -> List[str]:
    return [str(v).strip() for v in vals]


def ensure_schema(ws: gspread.Worksheet, required_cols: List[str], aliases: Dict[str, List[str]]) -> Dict[str, int]:
    """
    - 헤더가 비었거나 일부 누락이어도 앱이 죽지 않게 자동 보정
    - 반환: 표준컬럼명 -> 1-based col index
    """
    header = ws.row_values(1)
    header = _normalize_header_values(header)

    # 헤더가 아예 비어있으면 required_cols로 생성
    if len(header) == 0 or all(h == "" for h in header):
        ws.update("1:1", [required_cols])
        header = required_cols[:]

    # alias를 표준명으로 매핑하기 위한 lookup
    alias_to_std: Dict[str, str] = {}
    for std, als in aliases.items():
        alias_to_std[std.lower()] = std
        for a in als:
            alias_to_std[str(a).strip().lower()] = std

    # 현재 헤더를 표준명으로 인식 가능한지 매핑
    std_positions: Dict[str, int] = {}
    for idx, h in enumerate(header, start=1):
        key = str(h).strip().lower()
        if key in alias_to_std:
            std_positions[alias_to_std[key]] = idx

    # 누락 컬럼은 맨 뒤에 추가(기존 데이터 재배열 없이 안전하게)
    updated = False
    for col in required_cols:
        if col not in std_positions:
            header.append(col)
            std_positions[col] = len(header)
            updated = True

    if updated:
        ws.update("1:1", [header])

    return std_positions


def read_all_as_df(ws: gspread.Worksheet) -> Tuple[pd.DataFrame, List[List[str]]]:
    """
    get_all_values() 기반으로 읽어서:
    - 헤더/행 위치를 우리가 통제 가능
    - row_map 생성(성능 및 find 제거)
    """
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame(), []

    header = [str(x).strip() for x in values[0]]
    rows = values[1:]

    if len(header) == 0:
        return pd.DataFrame(), values

    df = pd.DataFrame(rows, columns=header)
    return df, values


def build_row_map(values: List[List[str]], id_col_name: str) -> Dict[str, int]:
    """
    values: get_all_values() 결과(헤더 포함)
    반환: id(str) -> 실제 시트 row 번호(1-based)
    """
    if not values or len(values) < 2:
        return {}

    header = [str(x).strip() for x in values[0]]
    if id_col_name not in header:
        return {}

    id_idx = header.index(id_col_name)
    row_map: Dict[str, int] = {}

    for sheet_row, row in enumerate(values[1:], start=2):
        if id_idx >= len(row):
            continue
        rid = str(row[id_idx]).strip()
        if rid != "":
            row_map[rid] = sheet_row

    return row_map