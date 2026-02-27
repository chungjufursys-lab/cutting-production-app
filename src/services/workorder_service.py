from typing import Optional
from datetime import datetime
from src.domain.exceptions import AppError
from src.services.excel_detect import parse_excel


class WorkOrderService:
    def __init__(self, repo, filestore, logger, cfg):
        self.repo = repo
        self.filestore = filestore
        self.logger = logger
        self.cfg = cfg

    def complete(self, wo_id: str, note: str = ""):
        wo = self.repo.get_workorder(wo_id)
        if not wo:
            raise AppError("작업지시를 찾을 수 없습니다.", f"wo_id={wo_id}")

        if wo["status"] == "CANCELED":
            raise AppError("취소된 작업은 완료 처리할 수 없습니다.")

        self.repo.update_workorder_status(wo_id, "DONE")
        self.repo.append_ledger(wo_id, "DONE", note)

        # 이벤트 큐 적재(시트 반영용)
        now = datetime.now().isoformat(timespec="seconds")
        self.repo.enqueue_event("UPDATE_WORKORDER_STATUS", {"wo_id": wo_id, "status": "DONE", "updated_at": now})
        self.repo.enqueue_event("APPEND_LEDGER", {"wo_id": wo_id, "action": "DONE", "note": note, "ts": now})

    def undo_complete(self, wo_id: str, note: str = ""):
        wo = self.repo.get_workorder(wo_id)
        if not wo:
            raise AppError("작업지시를 찾을 수 없습니다.", f"wo_id={wo_id}")

        if wo["status"] != "DONE":
            raise AppError("완료 상태가 아니라서 완료취소를 할 수 없습니다.")

        self.repo.update_workorder_status(wo_id, "IN_PROGRESS")
        self.repo.append_ledger(wo_id, "UNDONE", note)

        now = datetime.now().isoformat(timespec="seconds")
        self.repo.enqueue_event("UPDATE_WORKORDER_STATUS", {"wo_id": wo_id, "status": "IN_PROGRESS", "updated_at": now})
        self.repo.enqueue_event("APPEND_LEDGER", {"wo_id": wo_id, "action": "UNDONE", "note": note, "ts": now})

    def cancel(self, wo_id: str, note: str = ""):
        wo = self.repo.get_workorder(wo_id)
        if not wo:
            raise AppError("작업지시를 찾을 수 없습니다.", f"wo_id={wo_id}")

        if wo["status"] == "DONE":
            raise AppError("완료된 작업은 작업취소할 수 없습니다. (완료취소 후 취소 가능)")

        self.repo.update_workorder_status(wo_id, "CANCELED")
        self.repo.append_ledger(wo_id, "CANCEL", note)

        now = datetime.now().isoformat(timespec="seconds")
        self.repo.enqueue_event("UPDATE_WORKORDER_STATUS", {"wo_id": wo_id, "status": "CANCELED", "updated_at": now})
        self.repo.enqueue_event("APPEND_LEDGER", {"wo_id": wo_id, "action": "CANCEL", "note": note, "ts": now})

    def upload_excel_and_parse(self, uploaded_file) -> dict:
        if not uploaded_file:
            raise AppError("업로드된 파일이 없습니다.")

        saved = self.filestore.save_upload(uploaded_file.name, uploaded_file.getvalue())
        parsed = parse_excel(str(saved))
        self.filestore.save_parsed_json(saved.stem, parsed)

        # 원장에도 기록(업로드 이력)
        self.repo.append_ledger(wo_id="(UPLOAD)", action="UPLOAD", note=f"{uploaded_file.name} / rows={parsed['count']}")

        return {"saved_path": str(saved), "parsed": parsed}