"""采集包内容摘要：同一份采集内容重复导入时，按摘要直接消重。

摘要只覆盖决定测量内容的字段（桥梁、采集日期与逐测点读数），
与批次编号、导入时间无关，保证同一包内容算出来的摘要稳定一致。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

READING_DIGEST_FIELDS = ["测点桩号", "缝编号", "实测缝宽", "设计缝宽", "锚固偏差", "采集时刻", "采集口径"]


def expansion_batch_digest(payload: dict[str, Any]) -> str:
    """对采集包做规范化摘要：读数先按桩号排序再序列化，避免导入顺序影响结果。"""
    readings = [
        {field: reading.get(field) for field in READING_DIGEST_FIELDS}
        for reading in payload.get("readings", [])
    ]
    readings.sort(key=lambda item: str(item.get("测点桩号") or ""))
    canonical = {
        "所属桥梁": payload.get("所属桥梁"),
        "采集日期": payload.get("采集日期"),
        "readings": readings,
    }
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
