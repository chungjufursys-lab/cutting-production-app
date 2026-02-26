from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

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
    Google Sheets 기반 간단 분산락.
    - lock_key가 살아있으면 False
    - 없거나 만료되었으면 갱신 후 True
    """

    # 헤더 보장
    header = ws_locks.row_values(1)
    if not header or all(h.strip() == "" for h in header):
        ws_locks.update("A1:D1", [LOCKS_COLS])

    values = ws_locks.get_all_values()

    # 비어있으면 새로 생성
    if len(values) < 2:
        expires = (datetime.now() + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        ws_locks.append_row([lock_key, owner, _now_str(), expires])
        return True

    header = values[0]

    # locks 시트 구조 고정 전제
    # A: lock_key, B: owner, C: acquired_at, D: expires_at
    for sheet_row, row in enumerate(values[1:], start=2):
        if len(row) == 0:
            continue

        if str(row[0]).strip() == lock_key:
            exp = _parse_dt(row[3] if len(row) > 3 else "")
            if exp and exp > datetime.now():
                return False  # 아직 살아있는 락

            # 만료 → 갱신
            expires = (datetime.now() + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")

            ws_locks.update(f"B{sheet_row}", owner)
            ws_locks.update(f"C{sheet_row}", _now_str())
            ws_locks.update(f"D{sheet_row}", expires)
            return True

    # lock_key가 아예 없음 → 새로 생성
    expires = (datetime.now() + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    ws_locks.append_row([lock_key, owner, _now_str(), expires])
    return True


def release_lock(ws_locks: gspread.Worksheet, lock_key: str, owner: str) -> None:
    """
    expires_at을 과거로 만들어 강제 해제.
    절대 실패하지 않도록 예외 무시.
    """

    try:
        values = ws_locks.get_all_values()
        if len(values) < 2:
            return

        for sheet_row, row in enumerate(values[1:], start=2):
            if len(row) == 0:
                continue

            if str(row[0]).strip() == lock_key:
                # owner가 다르면 건드리지 않음
                if len(row) > 1 and str(row[1]).strip() != owner:
                    return

                # D열(expires_at)을 과거로
                ws_locks.update(f"D{sheet_row}", "2000-01-01 00:00:00")
                return

    except Exception:
        # release는 실패해도 앱 죽이면 안 됨
        return
