# 구글시트 스키마(표준 컬럼)
WORK_ORDERS_COLS = ["id", "file_name", "equipment", "status", "created_at", "file_hash"]
LOTS_COLS = ["id", "work_order_id", "lot_key", "qty", "move_card_no", "status", "done_at"]
LOCKS_COLS = ["lock_key", "owner", "acquired_at", "expires_at"]

# 헤더가 사람이 바뀌어도 죽지 않게 alias 허용
WORK_ORDERS_ALIASES = {
    "id": ["ID", "Id"],
    "file_name": ["filename", "file", "파일명"],
    "equipment": ["equip", "설비", "설비명", "EQUIPMENT"],
    "status": ["상태", "STATUS"],
    "created_at": ["created", "등록일", "생성일", "uploaded_at", "업로드일"],
    "file_hash": ["hash", "md5", "sha", "FILE_HASH"],
}

LOTS_ALIASES = {
    "id": ["ID", "Id"],
    "work_order_id": ["workorder_id", "wo_id", "작업지시id", "작업지시ID"],
    "lot_key": ["lot", "원장", "원장키", "LOT_KEY"],
    "qty": ["수량", "매수", "QTY"],
    "move_card_no": ["move_card", "이동카드", "이동카드번호", "MOVE_CARD_NO"],
    "status": ["상태", "STATUS"],
    "done_at": ["완료일", "DONE_AT"],
}