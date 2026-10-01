"""测量读数内容摘要：采集导入按摘要消重，种子数据与接口共用同一口径。"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def readings_digest(readings: list[dict[str, Any]]) -> str:
    """按读数内容算摘要：内容重复直接消重，与批次号、导入时刻无关。"""
    canonical = json.dumps(readings, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
