"""伸缩缝测量回放工作台业务规则。

回放流程按「采集导入 → 整包校验 → 签认发布 → 材料建议」顺序推进：
- 前序未签认不得跳级生成材料建议；
- 整包校验、签认、发布绑在同一事务里，任何一步失败整体回滚；
- 发布结论一次写入伸缩缝台账、桥梁档案与材料待办，不重复发布；
- 复核仪器结论优先于历史读数，历史读数按采集时刻与当时采集口径留存；
- 上传中断保留待发布批次，内容重复按摘要直接消重。
"""
from __future__ import annotations

from typing import Any

from app.digest import readings_digest
from app.store import store

MODULE = "expansion"  # 伸缩缝台账
BATCH_MODULE = "expansion_batch"  # 测量回放批次
ARCHIVE_MODULE = "bridge_info"  # 桥梁档案
MATERIAL_MODULE = "material"  # 材料待办

REQUIRED_FIELDS = ["缝编号", "所属桥梁", "缝类型"]
BATCH_REQUIRED = ["所属桥梁", "采集时刻", "采集口径"]

# 桥面剖面顺序核对容差（毫米）：缝宽实测与设计、锚固偏差分开判定
WIDTH_TOLERANCE = 10.0
ANCHOR_TOLERANCE = 3.0

REVIEW_INSTRUMENT = "复核仪器"


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _conclusion_readings(readings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按剖面点归并读数：复核仪器结论优先于历史读数，其余读数原样保留在批次里。"""
    by_point: dict[str, list[dict[str, Any]]] = {}
    for reading in readings:
        by_point.setdefault(str(reading.get("剖面点", "")), []).append(reading)
    conclusions: list[dict[str, Any]] = []
    for point, group in by_point.items():
        reviewed = [r for r in group if str(r.get("仪器类别", "")).strip() == REVIEW_INSTRUMENT]
        chosen = reviewed[-1] if reviewed else group[-1]
        conclusions.append({**chosen, "剖面点": point, "结论来源": REVIEW_INSTRUMENT if reviewed else "采集仪器"})
    return conclusions


class ExpansionService:
    # ---------- 伸缩缝台账 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("缝编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = "正常"
        entry["pending"] = True
        entry["abnormal"] = False
        entry["读数历史"] = []
        rows.append(entry)
        return entry, []

    # ---------- 采集导入 ----------
    def list_batches(
        self,
        *,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(BATCH_MODULE)
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        return store.find(BATCH_MODULE, batch_id)

    def import_batch(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """采集导入：内容算摘要消重；上传中断的批次保留为待补传，可补传完成。"""
        missing = [field for field in BATCH_REQUIRED if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        readings = values.get("读数") or []
        if not isinstance(readings, list) or not readings:
            return None, "测量读数为空，无法导入批次"
        interrupted = bool(values.get("上传中断"))
        normalized = [self._normalize_reading(item, values) for item in readings]
        digest = readings_digest(normalized)
        rows = store.rows(BATCH_MODULE)
        for row in rows:
            if row.get("摘要") != digest:
                continue
            if row.get("上传中断") and not interrupted:
                row["上传中断"] = False
                row["状态"] = "待校验"
                return row, "中断批次已补传完成，内容按摘要消重"
            return row, "内容重复，已按摘要消重"
        batch = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "批次号": f"EXPB-{len(rows) + 1:04d}",
            "所属桥梁": str(values.get("所属桥梁")).strip(),
            "采集时刻": str(values.get("采集时刻")).strip(),
            "采集口径": str(values.get("采集口径")).strip(),
            "采集单位": str(values.get("采集单位") or "").strip(),
            "摘要": digest,
            "上传中断": interrupted,
            "状态": "待补传" if interrupted else "待校验",
            "读数": normalized,
            "校验记录": [],
            "校验通过": None,
            "更换建议": [],
            "签认人": None,
            "签认时刻": None,
            "发布结论": None,
            "材料建议": None,
            "pending": True,
            "abnormal": False,
        }
        rows.append(batch)
        if interrupted:
            return batch, "上传中断，批次已保留为待补传，可继续补传"
        return batch, "测量批次已导入，等待整包校验"

    def _normalize_reading(self, item: Any, batch_values: dict[str, Any]) -> dict[str, Any]:
        """读数落盘时带上采集时刻与当时采集口径，历史读数以后不回头改。"""
        reading = dict(item) if isinstance(item, dict) else {}
        reading.setdefault("仪器类别", "采集仪器")
        reading["采集时刻"] = str(reading.get("采集时刻") or batch_values.get("采集时刻") or "")
        reading["采集口径"] = str(reading.get("采集口径") or batch_values.get("采集口径") or "")
        return reading

    # ---------- 整包校验 ----------
    def validate_batch(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"测量批次 {batch_id} 不存在或已归档"
        status = str(batch.get("状态"))
        if status == "待补传":
            return None, "上传中断的批次需先补传完成，再整包校验"
        if status != "待校验":
            return None, f"批次当前为「{status}」，不在待校验环节"
        records, suggestions, ok = self._run_profile_checks(batch)
        batch["校验记录"] = records
        batch["更换建议"] = suggestions
        batch["校验通过"] = ok
        if not ok:
            batch["abnormal"] = True
            return batch, "整包校验未通过：读数缺项或无法解析，请补测后重新导入"
        batch["状态"] = "待签认"
        return batch, "整包校验通过，批次进入待签认"

    def _run_profile_checks(
        self, batch: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        """在桥面剖面上按顺序核对缝宽、设计、锚固偏差，再形成更换建议。"""
        records: list[dict[str, Any]] = []
        suggestions: list[dict[str, Any]] = []
        package_ok = True
        for reading in _conclusion_readings(list(batch.get("读数") or [])):
            steps: list[dict[str, str]] = []
            point_ok = True
            over_limits: list[str] = []

            width = _to_float(reading.get("缝宽实测"))
            design = _to_float(reading.get("设计缝宽"))
            anchor = _to_float(reading.get("锚固偏差"))

            # 第一步：缝宽核对
            if width is None:
                steps.append({"核对项": "缝宽核对", "结果": "缺项", "说明": "缝宽实测缺失或无法解析"})
                point_ok = False
            elif design is not None and abs(width - design) > WIDTH_TOLERANCE:
                steps.append({"核对项": "缝宽核对", "结果": "超差", "说明": f"实测 {width}mm 与设计 {design}mm 偏差超过 {WIDTH_TOLERANCE}mm"})
                over_limits.append("缝宽超差")
            else:
                steps.append({"核对项": "缝宽核对", "结果": "合格", "说明": f"实测 {width}mm"})

            # 第二步：设计核对
            if design is None or design <= 0:
                steps.append({"核对项": "设计核对", "结果": "缺项", "说明": "设计缝宽缺失或不合法"})
                point_ok = False
            else:
                steps.append({"核对项": "设计核对", "结果": "合格", "说明": f"设计缝宽 {design}mm"})

            # 第三步：锚固偏差核对
            if anchor is None:
                steps.append({"核对项": "锚固偏差核对", "结果": "缺项", "说明": "锚固偏差缺失或无法解析"})
                point_ok = False
            elif abs(anchor) > ANCHOR_TOLERANCE:
                steps.append({"核对项": "锚固偏差核对", "结果": "超差", "说明": f"锚固偏差 {anchor}mm 超过 {ANCHOR_TOLERANCE}mm"})
                over_limits.append("锚固偏差超限")
            else:
                steps.append({"核对项": "锚固偏差核对", "结果": "合格", "说明": f"锚固偏差 {anchor}mm"})

            package_ok = package_ok and point_ok
            records.append({
                "剖面点": reading.get("剖面点"),
                "缝编号": reading.get("缝编号"),
                "结论来源": reading.get("结论来源"),
                "采集时刻": reading.get("采集时刻"),
                "采集口径": reading.get("采集口径"),
                "步骤": steps,
                "结论": "、".join(over_limits) if over_limits else ("缺项" if not point_ok else "合格"),
            })
            if over_limits:
                suggestions.append({
                    "缝编号": reading.get("缝编号"),
                    "剖面点": reading.get("剖面点"),
                    "原因": "、".join(over_limits),
                    "建议": "建议更换伸缩缝",
                    "设计缝宽": reading.get("设计缝宽"),
                })
        return records, suggestions, package_ok

    # ---------- 签认发布 ----------
    def publish_batch(self, batch_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """签认发布：整包校验、签认、写入台账/档案/材料待办在同一事务里，失败回滚。"""
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"测量批次 {batch_id} 不存在或已归档"
        status = str(batch.get("状态"))
        if status == "已发布":
            return None, "整包校验通过后一次发布，该批次已发布，请勿重复操作"
        if status != "待签认":
            return None, f"批次当前为「{status}」，整包校验未通过，不得签认发布"
        signer = str(values.get("签认人") or "").strip()
        if not signer:
            return None, "缺少签认人，无法签认发布"
        sign_time = str(values.get("签认时刻") or batch.get("采集时刻") or "").strip()
        try:
            with store.transaction(BATCH_MODULE, MODULE, ARCHIVE_MODULE, MATERIAL_MODULE):
                records, suggestions, ok = self._run_profile_checks(batch)
                if not ok or not batch.get("校验通过"):
                    raise ValueError("整包校验复核未通过，发布已回滚")
                batch["校验记录"] = records
                batch["更换建议"] = suggestions
                batch["签认人"] = signer
                batch["签认时刻"] = sign_time
                ledger_hits = self._write_ledger(batch)
                self._write_archive(batch, suggestions)
                material_hits = self._write_material_todos(batch, suggestions)
                batch["发布结论"] = {
                    "结论": "建议更换" if suggestions else "合格",
                    "台账更新": ledger_hits,
                    "档案更新": 1,
                    "材料待办": material_hits,
                    "发布时刻": sign_time,
                }
                batch["状态"] = "已发布"
                batch["pending"] = False
                batch["abnormal"] = bool(suggestions)
        except ValueError as exc:
            return None, str(exc)
        return store.find(BATCH_MODULE, batch_id), "签认发布完成，结论已写入伸缩缝台账、桥梁档案与材料待办"

    def _write_ledger(self, batch: dict[str, Any]) -> int:
        """结论写回伸缩缝台账；历史读数按采集时刻与当时口径追加，不覆盖旧值。"""
        hits = 0
        for reading in _conclusion_readings(list(batch.get("读数") or [])):
            joint_no = str(reading.get("缝编号") or "").strip()
            entry = next(
                (row for row in store.rows(MODULE) if str(row.get("缝编号", "")) == joint_no),
                None,
            )
            if entry is None:
                raise ValueError(f"伸缩缝台账中找不到 {joint_no}，发布已回滚")
            history = entry.setdefault("读数历史", [])
            history.append({
                "批次号": batch.get("批次号"),
                "采集时刻": reading.get("采集时刻"),
                "采集口径": reading.get("采集口径"),
                "仪器类别": reading.get("仪器类别"),
                "缝宽实测": reading.get("缝宽实测"),
                "锚固偏差": reading.get("锚固偏差"),
            })
            width = _to_float(reading.get("缝宽实测"))
            design = _to_float(reading.get("设计缝宽"))
            anchor = _to_float(reading.get("锚固偏差"))
            width_over = width is not None and design is not None and abs(width - design) > WIDTH_TOLERANCE
            anchor_over = anchor is not None and abs(anchor) > ANCHOR_TOLERANCE
            entry["当前缝宽"] = reading.get("缝宽实测")
            entry["锚固状态"] = "偏差超限" if anchor_over else "正常"
            entry["status"] = "锚固损坏" if anchor_over else ("堵塞" if width_over else "正常")
            entry["abnormal"] = width_over or anchor_over
            entry["pending"] = width_over or anchor_over
            hits += 1
        return hits

    def _write_archive(self, batch: dict[str, Any], suggestions: list[dict[str, Any]]) -> None:
        """结论写入桥梁档案；找不到对应桥梁时抛错，由事务整体回滚。"""
        bridge_name = str(batch.get("所属桥梁") or "").strip()
        archive = next(
            (row for row in store.rows(ARCHIVE_MODULE) if str(row.get("桥梁名称", "")) == bridge_name),
            None,
        )
        if archive is None:
            raise ValueError(f"桥梁档案中找不到「{bridge_name}」，发布已回滚")
        archive["最近伸缩缝复核"] = batch.get("签认时刻")
        archive["伸缩缝复核结论"] = "建议更换" if suggestions else "合格"
        archive["上次评定等级"] = archive["伸缩缝复核结论"]

    def _write_material_todos(self, batch: dict[str, Any], suggestions: list[dict[str, Any]]) -> int:
        """每条更换建议生成一条材料待办，进入养护材料清单。"""
        rows = store.rows(MATERIAL_MODULE)
        hits = 0
        for suggestion in suggestions:
            rows.append({
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "材料编号": f"MATE-{max((int(row.get('id', 0)) for row in rows), default=0) + 1:04d}",
                "材料名称": f"伸缩缝更换（{suggestion.get('缝编号')}）",
                "材料类别": "伸缩缝更换待办",
                "规格型号": f"设计缝宽{suggestion.get('设计缝宽')}mm",
                "供应商": "",
                "进场日期": "",
                "存放地点": "",
                "材料状态": "待采购",
                "status": "待采购",
                "pending": True,
                "abnormal": False,
                "来源批次": batch.get("批次号"),
            })
            hits += 1
        return hits

    # ---------- 材料建议 ----------
    def generate_suggestions(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """材料建议是流程最后一步：前序未签认发布，不得跳级生成。"""
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"测量批次 {batch_id} 不存在或已归档"
        if str(batch.get("状态")) != "已发布":
            return None, "前序未签认，不得跳级生成材料建议"
        if batch.get("材料建议") is not None:
            return batch, "材料建议已生成，直接返回既有结论"
        suggestions = []
        for item in batch.get("更换建议") or []:
            suggestions.append({
                "缝编号": item.get("缝编号"),
                "材料名称": f"伸缩缝装置（{item.get('缝编号')}）",
                "规格建议": f"设计缝宽{item.get('设计缝宽')}mm",
                "数量": 1,
                "优先级": "高" if "锚固" in str(item.get("原因")) else "中",
                "依据": item.get("原因"),
            })
        batch["材料建议"] = suggestions
        return batch, "材料建议已生成" if suggestions else "剖面核对全部合格，无需更换材料"
