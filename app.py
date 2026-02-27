import streamlit as st

from src.infra.logger import setup_logger
from src.infra.sqlite_repo import SQLiteRepo
from src.infra.filestore import FileStore
from src.infra.sheets_gateway import SheetsGateway
from src.services.sync_service import SyncService
from src.services.workorder_service import WorkOrderService
from src.services.kpi_service import KPIService
from src.ui.layout import render_app
from src.config import AppConfig


def bootstrap():
    cfg = AppConfig.from_streamlit_secrets()

    logger = setup_logger(cfg.paths.log_file)

    repo = SQLiteRepo(cfg.paths.db_file, logger=logger)
    repo.init_schema()

    filestore = FileStore(cfg.paths.data_dir, retention_days=cfg.files.retention_days, logger=logger)
    filestore.cleanup_old_files()

    sheets = SheetsGateway(cfg.sheets, logger=logger)

    sync = SyncService(repo=repo, sheets=sheets, logger=logger, cfg=cfg)
    workorders = WorkOrderService(repo=repo, filestore=filestore, logger=logger, cfg=cfg)
    kpis = KPIService(repo=repo)

    return cfg, repo, sync, workorders, kpis


def main():
    st.set_page_config(page_title="재단공정 작업관리 v1.0", layout="wide")

    cfg, repo, sync, workorders, kpis = bootstrap()

    render_app(cfg=cfg, repo=repo, sync=sync, workorders=workorders, kpis=kpis)


if __name__ == "__main__":
    main()