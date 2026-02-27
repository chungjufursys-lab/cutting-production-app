from datetime import datetime, date


class KPIService:
    def __init__(self, repo):
        self.repo = repo

    def compute(self):
        # 아주 기본 KPI: 오늘 DONE/CANCEL/UNDONE 건수
        led = self.repo.list_ledger(None)
        today = date.today().isoformat()

        done = 0
        cancel = 0
        undone = 0

        for r in led:
            ts = (r.get("ts") or "")[:10]
            if ts != today:
                continue
            if r["action"] == "DONE":
                done += 1
            elif r["action"] == "CANCEL":
                cancel += 1
            elif r["action"] == "UNDONE":
                undone += 1

        return {"today_done": done, "today_cancel": cancel, "today_undone": undone}