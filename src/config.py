from dataclasses import dataclass
from pathlib import Path
import streamlit as st


@dataclass(frozen=True)
class SheetConfig:
    spreadsheet_id: str
    workorders_sheet: str
    ledger_sheet: str


@dataclass(frozen=True)
class PathsConfig:
    base_dir: Path
    data_dir: Path
    db_file: Path
    log_file: Path


@dataclass(frozen=True)
class FilesConfig:
    retention_days: int = 10


@dataclass(frozen=True)
class SyncConfig:
    pull_ttl_seconds: int = 60
    push_batch_size: int = 50


@dataclass(frozen=True)
class ColumnMap:
    # Sheets 컬럼명(현장 시트에 맞춰 여기만 바꾸면 됨)
    wo_id: str = "wo_id"
    item: str = "item"
    lot: str = "lot"
    qty: str = "qty"
    move_card: str = "move_card"
    status: str = "status"  # NEW / IN_PROGRESS / DONE / CANCELED
    updated_at: str = "updated_at"

    led_id: str = "led_id"
    wo_id_fk: str = "wo_id"
    action: str = "action"  # DONE / UNDONE / CANCEL / UPLOAD
    note: str = "note"
    ts: str = "ts"


@dataclass(frozen=True)
class AppConfig:
    sheets: SheetConfig
    paths: PathsConfig
    files: FilesConfig
    sync: SyncConfig
    cols: ColumnMap

    @staticmethod
    def from_streamlit_secrets() -> "AppConfig":
        base_dir = Path(".").resolve()
        data_dir = base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        sheets = SheetConfig(
            spreadsheet_id=st.secrets["sheets"]["spreadsheet_id"],
            workorders_sheet=st.secrets["sheets"]["workorders_sheet"],
            ledger_sheet=st.secrets["sheets"]["ledger_sheet"],
        )

        paths = PathsConfig(
            base_dir=base_dir,
            data_dir=data_dir,
            db_file=data_dir / "app.db",
            log_file=data_dir / "logs" / "app.log",
        )
        (data_dir / "logs").mkdir(parents=True, exist_ok=True)

        return AppConfig(
            sheets=sheets,
            paths=paths,
            files=FilesConfig(retention_days=10),
            sync=SyncConfig(pull_ttl_seconds=60, push_batch_size=50),
            cols=ColumnMap(),
        )