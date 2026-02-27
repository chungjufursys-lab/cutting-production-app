import os
import time

class SimpleFileLock:
    """
    여러 사용자가 동시에 push/pull 할 때 충돌을 줄이기 위한 아주 단순한 락.
    (운영 v1.0에서는 이 정도로도 체감 안정성이 크게 올라갑니다.)
    """
    def __init__(self, lock_path: str, timeout_sec: int = 5):
        self.lock_path = lock_path
        self.timeout_sec = timeout_sec

    def __enter__(self):
        start = time.time()
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() - start > self.timeout_sec:
                    raise TimeoutError("다른 사용자가 동기화 중입니다. 잠시 후 다시 시도해주세요.")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb):
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass