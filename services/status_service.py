from __future__ import annotations

import pandas as pd

from domain.constants import (
    LOT_STATUS_DONE,
    WO_STATUS_WAITING,
    WO_STATUS_IN_PROGRESS,
    WO_STATUS_COMPLETED,
    WO_STATUS_VOID,
)


def compute_work_order_status(lots_df: pd.DataFrame, work_order_id: str, current_wo_status: str) -> str:
    """
    내부DB용 로직과 동일한 철학:
    - VOID면 그대로 유지
    - lot DONE 개수에 따라 WAITING/IN_PROGRESS/COMPLETED
    """
    if str(current_wo_status).strip().upper() == WO_STATUS_VOID:
        return WO_STATUS_VOID

    wlots = lots_df[lots_df["work_order_id"].astype(str) == str(work_order_id)]
    total = len(wlots)
    if total == 0:
        return WO_STATUS_WAITING

    done = (wlots["status"].astype(str) == LOT_STATUS_DONE).sum()

    if done == 0:
        return WO_STATUS_WAITING
    if done < total:
        return WO_STATUS_IN_PROGRESS
    return WO_STATUS_COMPLETED


def count_done_total(lots_df: pd.DataFrame, work_order_id: str) -> tuple[int, int]:
    wlots = lots_df[lots_df["work_order_id"].astype(str) == str(work_order_id)]
    total = len(wlots)
    done = (wlots["status"].astype(str) == LOT_STATUS_DONE).sum()
    return int(done), int(total)