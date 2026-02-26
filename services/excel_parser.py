from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

from domain.constants import EQUIPMENT_MAP

# lot_key 패턴(당신 설명 기반 + 약간 확장)
LOT_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?T-[A-Za-z]+\b")

# 이동카드 패턴
MOVE_PATTERN = re.compile(r"\bC\d{6}-\d+\b")


@dataclass
class ParsedUpload:
    equipment: str
    lots: pd.DataFrame  # columns: lot_key, qty, move_card_no


def _normalize_equipment(raw: str) -> Optional[str]:
    return EQUIPMENT_MAP.get(str(raw).strip())


def detect_equipment(df: pd.DataFrame) -> str:
    """
    기본: A열 첫 값
    예외: 비었을 때 상단 30행에서 설비 키워드 탐색
    """
    try:
        raw = str(df.iloc[0, 0]).strip()
    except Exception:
        raw = ""

    eq = _normalize_equipment(raw)
    if eq:
        return eq

    # fallback: 상단 범위에서 텍스트 탐색
    sample = df.head(30).astype(str).fillna("")
    flat = "\n".join(sample.values.flatten().tolist())
    # 키워드 기반 후보
    for key in EQUIPMENT_MAP.keys():
        if key in flat:
            eq2 = _normalize_equipment(key)
            if eq2:
                return eq2

    # 그래도 실패면 원본 문자열을 던져서 UI에서 안내
    raise ValueError(f"설비 매핑 실패: A1='{raw}'")


def detect_lot_col(df: pd.DataFrame) -> Optional[str]:
    # 오른쪽부터 lot 패턴이 있는 열 탐색(내부DB용 로직에 가깝게)
    for col in reversed(list(df.columns)):
        s = df[col].dropna().astype(str).head(200)
        if s.str.contains(LOT_PATTERN).any():
            return col
    return None


def detect_qty_col(df: pd.DataFrame, lot_col: str) -> Optional[str]:
    cols = list(df.columns)
    idx = cols.index(lot_col)

    # lot_col 오른쪽 1~6칸에서 수치형 열 탐색
    for j in range(idx + 1, min(idx + 7, len(cols))):
        cand = df[cols[j]]
        if pd.to_numeric(cand, errors="coerce").notna().any():
            return cols[j]
    return None


def detect_move_col(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        s = df[col].dropna().astype(str).head(500)
        if s.str.contains(MOVE_PATTERN).any():
            return col
    return None


def parse_excel(file_path: str) -> ParsedUpload:
    df = pd.read_excel(file_path)

    equipment = detect_equipment(df)

    lot_col = detect_lot_col(df)
    if not lot_col:
        raise ValueError("원장(lot_key) 열을 찾을 수 없습니다.")

    qty_col = detect_qty_col(df, lot_col)
    if not qty_col:
        raise ValueError("수량(qty) 열을 찾을 수 없습니다.")

    move_col = detect_move_col(df)

    sub = df[[lot_col, qty_col] + ([move_col] if move_col else [])].copy()
    sub.columns = ["lot_key", "qty"] + (["move_card_no"] if move_col else [])

    sub["lot_key"] = sub["lot_key"].astype(str).str.strip()
    sub = sub[sub["lot_key"].str.contains(LOT_PATTERN, na=False)]

    # SUBTOTAL / TOTAL 계열 제거
    sub = sub[~sub["lot_key"].str.contains("SUBTOTAL|TOTAL|소계|합계", case=False, na=False)]

    sub["qty"] = pd.to_numeric(sub["qty"], errors="coerce").fillna(0).astype(int)
    sub = sub[sub["qty"] > 0]

    if "move_card_no" not in sub.columns:
        sub["move_card_no"] = ""

    # 최종 컬럼 정리
    sub = sub[["lot_key", "qty", "move_card_no"]].reset_index(drop=True)

    if sub.empty:
        raise ValueError("유효한 lot/qty 데이터를 찾지 못했습니다.")

    return ParsedUpload(equipment=equipment, lots=sub)