from typing import Dict, Any
import pandas as pd
import re
from src.domain.exceptions import AppError


def detect_columns(df: pd.DataFrame) -> Dict[str, str]:
    """
    엑셀 컬럼명이 제각각이어도 lot/qty/move_card를 자동 탐지.
    - lot: LOT, lot, 로트, Lot No 등
    - qty: 수량, QTY, qty, quantity
    - move_card: 이동카드, move card, card, MC
    """
    cols = list(df.columns)

    def pick(patterns):
        for c in cols:
            s = str(c).strip().lower()
            for p in patterns:
                if re.search(p, s):
                    return c
        return None

    lot_col = pick([r"\blot\b", r"로트", r"lot\s*no", r"batch"])
    qty_col = pick([r"\bqty\b", r"수량", r"quantity", r"ea"])
    mc_col = pick([r"이동", r"move", r"card", r"\bmc\b"])

    if not (lot_col and qty_col and mc_col):
        raise AppError(
            user_message="엑셀에서 LOT/수량/이동카드 컬럼을 자동으로 찾지 못했습니다. 컬럼명을 확인해주세요.",
            debug_message=f"detected: lot={lot_col}, qty={qty_col}, move_card={mc_col}, all={cols}",
        )

    return {"lot": lot_col, "qty": qty_col, "move_card": mc_col}


def parse_excel(file_path: str) -> Dict[str, Any]:
    try:
        df = pd.read_excel(file_path)
        df = df.dropna(how="all")
    except Exception as e:
        raise AppError("엑셀 파일을 읽을 수 없습니다. 파일 형식을 확인해주세요.", str(e))

    mapping = detect_columns(df)

    # 첫 행부터 유효값만 추출
    items = []
    for _, row in df.iterrows():
        lot = str(row.get(mapping["lot"], "")).strip()
        mc = str(row.get(mapping["move_card"], "")).strip()
        qty_raw = row.get(mapping["qty"], None)

        if not lot and not mc:
            continue

        try:
            qty = float(qty_raw) if qty_raw is not None and qty_raw != "" else 0.0
        except Exception:
            qty = 0.0

        items.append({"lot": lot, "move_card": mc, "qty": qty})

    return {"mapping": mapping, "count": len(items), "rows": items}