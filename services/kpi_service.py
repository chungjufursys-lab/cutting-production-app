from __future__ import annotations

from datetime import datetime
import pandas as pd

from domain.constants import LOT_STATUS_DONE, WO_STATUS_VOID


def compute_kpis(work_df: pd.DataFrame, lots_df: pd.DataFrame, equip: str) -> dict:
    """
    내부DB용 KPI 3종:
    - 진행중 작업지시 건수
    - 미완료 원장 매수 합계(qty 합)
    - 오늘 완료 매수 합계
    VOID는 제외
    """
    if work_df.empty or lots_df.empty:
        return {"in_progress_cnt": 0, "unfinished_qty": 0, "today_done_qty": 0}

    work_df = work_df.copy()
    work_df["equipment"] = work_df["equipment"].astype(str).str.strip()
    work_df["status"] = work_df["status"].astype(str).str.strip()

    w = work_df[(work_df["equipment"] == equip) & (work_df["status"] != WO_STATUS_VOID)]
    if w.empty:
        return {"in_progress_cnt": 0, "unfinished_qty": 0, "today_done_qty": 0}

    lots_df = lots_df.copy()
    lots_df["work_order_id"] = lots_df["work_order_id"].astype(str).str.strip()
    lots_df["status"] = lots_df["status"].astype(str).str.strip()
    lots_df["qty"] = pd.to_numeric(lots_df["qty"], errors="coerce").fillna(0).astype(int)
    lots_df["done_at"] = lots_df["done_at"].astype(str)

    valid_ids = set(w["id"].astype(str).tolist())
    l = lots_df[lots_df["work_order_id"].isin(valid_ids)]

    unfinished_qty = int(l[l["status"] != LOT_STATUS_DONE]["qty"].sum())

    today = datetime.now().strftime("%Y-%m-%d")
    today_done_qty = int(l[(l["status"] == LOT_STATUS_DONE) & (l["done_at"].str.startswith(today))]["qty"].sum())

    in_progress_cnt = int((w["status"] == "IN_PROGRESS").sum())

    return {
        "in_progress_cnt": in_progress_cnt,
        "unfinished_qty": unfinished_qty,
        "today_done_qty": today_done_qty,
    }