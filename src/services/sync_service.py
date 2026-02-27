from datetime import datetime
from src.domain.exceptions import AppError
from src.infra.lock import SimpleFileLock


class SyncService:
    def __init__(self, repo, sheets, logger, cfg):
        self.repo = repo
        self.sheets = sheets
        self.logger = logger
        self.cfg = cfg

    def pull_from_sheets(self):
        """
        Sheets -> SQLite (한 번에 크게 가져오기)
        """
        lock_path = str(self.cfg.paths.data_dir / "sync.lock")
        with SimpleFileLock(lock_path, timeout_sec=5):
            try:
                wo_rows = self.sheets.fetch_workorders()
                led_rows = self.sheets.fetch_ledger()
            except Exception as e:
                self.logger.error(f"pull failed: {e}")
                raise AppError("시트에서 데이터를 가져오지 못했습니다. 네트워크/권한을 확인해주세요.", str(e))

            # 컬럼 매핑
            c = self.cfg.cols
            wos = []
            for r in wo_rows:
                wos.append({
                    "wo_id": str(r.get(c.wo_id, "")).strip(),
                    "item": str(r.get(c.item, "")).strip(),
                    "lot": str(r.get(c.lot, "")).strip(),
                    "qty": r.get(c.qty, 0) or 0,
                    "move_card": str(r.get(c.move_card, "")).strip(),
                    "status": str(r.get(c.status, "NEW")).strip() or "NEW",
                    "updated_at": str(r.get(c.updated_at, "")).strip() or datetime.now().isoformat(timespec="seconds")
                })

            # 빈 wo_id 제거
            wos = [x for x in wos if x["wo_id"]]

            self.repo.upsert_workorders(wos)

            # ledger는 시트가 진짜 원장이라면 “당겨오는 것”도 가능하지만,
            # v1.0에서는 로컬 ledger를 운영기록으로 사용하고, 시트 ledger는 push로만 늘리는 전략이 더 안전합니다.
            # 따라서 여기서는 pull ledger는 생략(원하면 활성화 가능).
            self.logger.info(f"pull ok: workorders={len(wos)}")

            return {"workorders": len(wos)}

    def push_to_sheets(self):
        """
        SQLite events -> Sheets (배치 반영)
        """
        lock_path = str(self.cfg.paths.data_dir / "sync.lock")
        with SimpleFileLock(lock_path, timeout_sec=5):
            pending = self.repo.list_pending_events(limit=self.cfg.sync.push_batch_size)
            if not pending:
                return {"pushed": 0}

            c = self.cfg.cols

            # 이벤트를 타입별로 묶기
            status_updates = []
            ledger_appends = []

            for ev in pending:
                try:
                    import json
                    payload = json.loads(ev["payload_json"])
                    if ev["event_type"] == "UPDATE_WORKORDER_STATUS":
                        status_updates.append({
                            "wo_id": payload["wo_id"],
                            "status": payload["status"],
                            "updated_at": payload["updated_at"],
                            "_event_id": ev["event_id"],
                        })
                    elif ev["event_type"] == "APPEND_LEDGER":
                        ledger_appends.append({
                            c.led_id: payload.get("led_id", ""),  # optional
                            c.wo_id_fk: payload["wo_id"],
                            c.action: payload["action"],
                            c.note: payload.get("note", ""),
                            c.ts: payload.get("ts", datetime.now().isoformat(timespec="seconds")),
                            "_event_id": ev["event_id"],
                        })
                    else:
                        self.repo.mark_event_failed(ev["event_id"], "Unknown event_type")
                except Exception as e:
                    self.repo.mark_event_failed(ev["event_id"], str(e))

            # 1) workorder status 업데이트
            try:
                self.sheets.batch_update_workorder_status(
                    updates=status_updates,
                    wo_id_col_name=c.wo_id,
                    status_col_name=c.status,
                    updated_at_col_name=c.updated_at
                )
                for u in status_updates:
                    self.repo.mark_event_pushed(u["_event_id"])
            except Exception as e:
                err = str(e)
                self.logger.error(f"push status failed: {err}")
                for u in status_updates:
                    self.repo.mark_event_failed(u["_event_id"], err)

            # 2) ledger append
            try:
                rows_for_sheet = []
                for r in ledger_appends:
                    # 시트 헤더 순서에 맞춰 gateway에서 정렬하므로 dict로 전달
                    rr = dict(r)
                    rr.pop("_event_id", None)
                    rows_for_sheet.append(rr)

                self.sheets.append_ledger_rows(rows_for_sheet)
                for r in ledger_appends:
                    self.repo.mark_event_pushed(r["_event_id"])
            except Exception as e:
                err = str(e)
                self.logger.error(f"push ledger failed: {err}")
                for r in ledger_appends:
                    self.repo.mark_event_failed(r["_event_id"], err)

            pushed = len([x for x in pending if x.get("pushed_at") is not None])
            return {"pushed": len(pending)}