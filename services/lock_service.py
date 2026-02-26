from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import streamlit as st
import gspread

from domain.schema import LOCKS_COLS


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def acquire_lock(ws_locks: gspread.Worksheet, lock_key: str, owner: str, ttl_seconds: int = 90) -> bool:
    """
    Google Sheets에 간단한 분산락 구현.
    - lock_key가 살아있으면 실패
    - 만료되었으면 갱신
    """
    # locks 시트는 헤더가 있어야 함
    header = ws_locks.row_values(1)
    if not header or all(h.strip() == "" for h in header):
        ws_locks.update("1:1", [LOCKS_COLS])

    # 전체 읽기(락 시트는 작으므로 OK)
    values = ws_locks.get_all_values()
    if len(values) < 2:
        # 첫 락 생성
        expires = (datetime.now() + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        ws_locks.append_row([lock_key, owner, _now_str(), expires])
        return True

    header = [h.strip() for h in values[0]]
    try:
        k_idx = header.index("lock_key")
        owner_idx = header.index("owner")
        expires_idx = header.index("expires_at")
        acquired_idx = header.index("acquired_at")
    except ValueError:
        ws_locks.update("1:1", [LOCKS_COLS])
        return acquire_lock(ws_locks, lock_key, owner, ttl_seconds)

    # lock_key row 찾기
    target_row = None
    for sheet_row, row in enumerate(values[1:], start=2):
        if k_idx < len(row) and str(row[k_idx]).strip() == lock_key:
            target_row = sheet_row
            exp = _parse_dt(row[expires_idx] if expires_idx < len(row) else "")
            if exp and exp > datetime.now():
                # 아직 유효: 락 획득 실패
                return False
            break

    expires = (datetime.now() + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")

    if target_row is None:
        ws_locks.append_row([lock_key, owner, _now_str(), expires])
        return True

    # 만료되어 갱신
    ws_locks.update(f"B{target_row}", owner)        # owner
    ws_locks.update(f"C{target_row}", _now_str())   # acquired_at
    ws_locks.update(f"D{target_row}", expires)      # expires_at
    return True


def release_lock(ws_locks: gspread.Worksheet, lock_key: str, owner: str) -> None:
    """
    강제 해제: expires_at을 과거로 설정
    """
    values = ws_locks.get_all_values()
    if len(values) < 2:
        return

    header = [h.strip() for h in values[0]]
    if "lock_key" not in header or "expires_at" not in header or "owner" not in header:
        return

    k_idx = header.index("lock_key")
    owner_idx = header.index("owner")
    expires_idx = header.index("expires_at")

    for sheet_row, row in enumerate(values[1:], start=2):
        if k_idx < len(row) and str(row[k_idx]).strip() == lock_key:
            if owner_idx < len(row) and str(row[owner_idx]).strip() != owner:
                return
            ws_locks.update(f"{chr(ord('A') + expires_idx)}{sheet_row}", "2000-01-01 00:00:00")
            return