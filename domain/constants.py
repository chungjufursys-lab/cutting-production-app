EQUIP_TABS = ["1호기", "2호기", "네스팅", "6호기", "곡면"]

EQUIPMENT_MAP = {
    "판넬컷터 #1": "1호기",
    "판넬컷터 #2": "2호기",
    "네스팅 #1": "네스팅",
    "판넬컷터 #6": "6호기",
    "판넬컷터 #3(곡면)": "곡면",
    # 이미 탭명으로 들어오는 경우도 허용
    "1호기": "1호기",
    "2호기": "2호기",
    "네스팅": "네스팅",
    "6호기": "6호기",
    "곡면": "곡면",
}

LOT_STATUS_WAITING = "WAITING"
LOT_STATUS_DONE = "DONE"

WO_STATUS_WAITING = "WAITING"
WO_STATUS_IN_PROGRESS = "IN_PROGRESS"
WO_STATUS_COMPLETED = "COMPLETED"
WO_STATUS_VOID = "VOID"