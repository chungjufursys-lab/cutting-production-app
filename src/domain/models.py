from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class WorkOrder:
    wo_id: str
    item: str
    lot: str
    qty: float
    move_card: str
    status: str  # NEW / IN_PROGRESS / DONE / CANCELED
    updated_at: str  # ISO string


@dataclass
class LedgerEntry:
    led_id: str
    wo_id: str
    action: str
    note: str
    ts: str  # ISO string


@dataclass
class Event:
    event_id: str
    event_type: str     # UPDATE_WORKORDER_STATUS / APPEND_LEDGER
    payload_json: str
    created_at: str
    pushed_at: Optional[str] = None
    push_error: Optional[str] = None