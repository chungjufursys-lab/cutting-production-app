from pathlib import Path
from datetime import datetime, timedelta
import shutil
import json


class FileStore:
    def __init__(self, data_dir: Path, retention_days: int, logger):
        self.data_dir = Path(data_dir)
        self.retention_days = retention_days
        self.logger = logger

        self.uploads = self.data_dir / "uploads"
        self.parsed = self.data_dir / "parsed"

        self.uploads.mkdir(parents=True, exist_ok=True)
        self.parsed.mkdir(parents=True, exist_ok=True)

    def _today_dir(self, root: Path) -> Path:
        d = root / datetime.now().strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_upload(self, filename: str, file_bytes: bytes) -> Path:
        target = self._today_dir(self.uploads) / filename
        target.write_bytes(file_bytes)
        return target

    def save_parsed_json(self, basename: str, data: dict) -> Path:
        target = self._today_dir(self.parsed) / f"{basename}.json"
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def cleanup_old_files(self):
        cutoff = datetime.now() - timedelta(days=self.retention_days)

        for root in [self.uploads, self.parsed]:
            if not root.exists():
                continue

            for day_dir in root.iterdir():
                if not day_dir.is_dir():
                    continue
                try:
                    day = datetime.strptime(day_dir.name, "%Y-%m-%d")
                except ValueError:
                    continue

                if day < cutoff:
                    try:
                        shutil.rmtree(day_dir)
                        self.logger.info(f"Deleted old folder: {day_dir}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete {day_dir}: {e}")