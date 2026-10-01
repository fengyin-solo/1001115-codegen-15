"""伸缩缝测量回放业务规则：采集导入、整包校验、签认发布、材料建议的顺序与事务都收在这里。

流程约定：采集导入 → 整包校验 → 签认发布 → 材料建议，前序未签认不得跳级生成建议。
整包校验、签认和发布在同一事务内完成，任一环节失败整体回滚；
复核仪器结论优先于历史读数，历史读数始终保留当时采集口径，不被改写。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.digest import expansion_batch_digest
from app.store import store

MODULE = "expansion"
BATCH_MODULE = "expansion_batch"
BRIDGE_MODULE = "bridge_info"
MATERIAL_MODULE = "material"

REQUIRED_FIELDS = ["缝编号", "所属桥梁", "缝类型"]
STATUS_ORDER = ["正常", "堵塞", "锚固损坏", "待更换", "已更换"]
ACTION_RULES = {"清理堵塞": "正常", "修补锚固": "正常", "更换伸缩缝": "已更换"}
NEGATIVE_ACTIONS = []

BATCH_REQUIRED_FIELDS = ["所属桥梁", "采集日期", "采集仪器", "采集口径"]
READING_REQUIRED_FIELDS = ["测点桩号", "缝编号", "实测缝宽", "设计缝宽", "锚固偏差", "采集时刻", "采集口径"]
REVIEW_FIELDS = ["复核缝宽", "复核锚固偏差", "复核结论"]
PENDING_BATCH_STATUSES = ["待校验", "待签认", "校验失败"]

WIDTH_TOLERANCE_MM = 10.0  # 缝宽允许偏差
ANCHOR_TOLERANCE_MM = 5.0  # 锚固允许偏差
CONCLUSION_REPLACE = "建议更换"
CONCLUSION_NORMAL = "正常"


class WorkflowError(ValueError):
    """流程顺序或数据不满足时的可读错误，路由层转成 ok=False 返回。"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _stake_sort_key(stake: Any) -> tuple[int, int, int, str]:
    """桩号排序键：K12+300 → (0, 12, 300)，解析不了的排到最后按原文排。"""
    text = str(stake or "").strip().upper().lstrip("K")
    main, _, plus = text.partition("+")
    try:
        return (0, int(main), int(plus or 0), "")
    except ValueError:
        return (1, 0, 0, str(stake or ""))


def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    """按已有编号的最大序号续号，如 MATE-0003 之后是 MATE-0004。"""
    max_no = 0
    for row in rows:
        code = str(row.get(field) or "")
        if code.startswith(prefix):
            try:
                max_no = max(max_no, int(code[len(prefix):]))
            except ValueError:
                continue
    return f"{prefix}{max_no + 1:04d}"


class ExpansionService:
    """伸缩缝台账：发布结论的落点之一，保留原有的登记与处置动作。"""

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
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"伸缩缝 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于伸缩缝台账可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["缝状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"伸缩缝已{action}"


class ExpansionReplayService:
    """测量回放工作台：批次按 采集导入→整包校验→签认发布→材料建议 顺序推进。"""

    # ---- 查询 ----

    def list_batches(
        self,
        *,
        status: str | None = None,
        pending_only: bool = False,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(BATCH_MODULE))
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if pending_only:
            rows = [row for row in rows if row.get("status") in PENDING_BATCH_STATUSES]
        rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._batch_summary(row) for row in rows[start:start + size]], total

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None
        return self._batch_detail(batch)

    def _batch_summary(self, batch: dict[str, Any]) -> dict[str, Any]:
        summary = {key: value for key, value in batch.items() if key != "readings"}
        summary["读数条数"] = len(batch.get("readings", []))
        return summary

    def _batch_detail(self, batch: dict[str, Any]) -> dict[str, Any]:
        """批次明细：读数按桥面剖面桩号顺序排列，并附上逐点缝宽偏差。"""
        detail = dict(batch)
        readings = sorted(batch.get("readings", []), key=lambda r: _stake_sort_key(r.get("测点桩号")))
        detail["readings"] = []
        for reading in readings:
            view = dict(reading)
            measured = _to_float(reading.get("实测缝宽"))
            designed = _to_float(reading.get("设计缝宽"))
            view["缝宽偏差"] = round(measured - designed, 2) if measured is not None and designed is not None else None
            detail["readings"].append(view)
        return detail

    # ---- 第一步：采集导入 ----

    def import_batch(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """导入采集包；上传中断后批次保留为待发布批次，内容重复按摘要直接消重。"""
        missing = [field for field in BATCH_REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        readings = values.get("readings")
        if not isinstance(readings, list) or not readings:
            missing.append("readings（至少一条测点读数）")
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        digest = expansion_batch_digest({
            "所属桥梁": values.get("所属桥梁"),
            "采集日期": values.get("采集日期"),
            "readings": readings,
        })
        for row in store.rows(BATCH_MODULE):
            if row.get("digest") == digest:
                return self._batch_detail(row), "内容重复，已按摘要消重，沿用待发布批次"

        rows = store.rows(BATCH_MODULE)
        batch: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "批次编号": _next_code(rows, "批次编号", "EXPB-"),
            "所属桥梁": str(values.get("所属桥梁")).strip(),
            "采集日期": str(values.get("采集日期")).strip(),
            "采集仪器": str(values.get("采集仪器")).strip(),
            "采集口径": str(values.get("采集口径")).strip(),
            "status": "待校验",
            "pending": True,
            "abnormal": False,
            "digest": digest,
            "readings": [
                {field: reading.get(field) for field in READING_REQUIRED_FIELDS}
                for reading in readings
            ],
            "校验结果": None,
            "签认人": None,
            "签认时间": None,
            "签认意见": None,
            "发布时间": None,
            "发布结论": None,
            "材料建议": None,
        }
        rows.append(batch)
        return self._batch_detail(batch), "采集包已导入，保留为待发布批次，可继续整包校验"

    # ---- 第二步：整包校验 ----

    def validate_batch(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"测量批次 {batch_id} 不存在"
        if batch.get("status") == "已发布":
            return self._batch_detail(batch), "批次已发布，无需重复校验"
        problems = self._check_package(batch)
        profile = self._profile_checks(batch)
        with store.transaction(BATCH_MODULE):
            batch["校验结果"] = {"通过": not problems, "问题": problems, "剖面核对": profile, "校验时间": _now()}
            batch["status"] = "待签认" if not problems else "校验失败"
            batch["pending"] = True
            batch["abnormal"] = bool(problems)
        if problems:
            return self._batch_detail(batch), f"整包校验未通过，共 {len(problems)} 项问题，请修正后重新校验"
        return self._batch_detail(batch), "整包校验通过，进入待签认"

    def _check_package(self, batch: dict[str, Any]) -> list[str]:
        """整包校验：按桥面剖面桩号顺序逐点核对，问题全部收集后一次性返回。"""
        problems: list[str] = []
        readings = sorted(batch.get("readings", []), key=lambda r: _stake_sort_key(r.get("测点桩号")))
        if not readings:
            return ["采集包内没有测点读数"]
        archive_names = {
            str(row.get("桥梁名称") or "") for row in store.rows(BRIDGE_MODULE)
        } | {
            str(row.get("桥梁编号") or "") for row in store.rows(BRIDGE_MODULE)
        }
        if str(batch.get("所属桥梁") or "") not in archive_names:
            problems.append(f"所属桥梁「{batch.get('所属桥梁')}」不在桥梁档案中，发布将无法写入档案")
        seen_stakes: set[str] = set()
        for index, reading in enumerate(readings, start=1):
            stake = str(reading.get("测点桩号") or "").strip() or f"第{index}条"
            missing = [field for field in READING_REQUIRED_FIELDS if not str(reading.get(field) or "").strip()]
            if missing:
                problems.append(f"测点{stake}缺少字段：{'、'.join(missing)}")
                continue
            if stake in seen_stakes:
                problems.append(f"测点{stake}在包内重复，同一剖面位置只允许一条读数")
            seen_stakes.add(stake)
            for field in ("实测缝宽", "设计缝宽", "锚固偏差"):
                if _to_float(reading.get(field)) is None:
                    problems.append(f"测点{stake}的{field}不是有效数值")
            designed = _to_float(reading.get("设计缝宽"))
            if designed is not None and designed <= 0:
                problems.append(f"测点{stake}的设计缝宽必须大于 0")
        return problems

    def _profile_checks(self, batch: dict[str, Any]) -> list[dict[str, Any]]:
        """桥面剖面顺序核对：沿桩号逐点比对缝宽、设计与锚固偏差，供前端剖面展示。"""
        profile: list[dict[str, Any]] = []
        readings = sorted(batch.get("readings", []), key=lambda r: _stake_sort_key(r.get("测点桩号")))
        for reading in readings:
            measured = _to_float(reading.get("实测缝宽"))
            designed = _to_float(reading.get("设计缝宽"))
            anchor = _to_float(reading.get("锚固偏差"))
            width_dev = round(measured - designed, 2) if measured is not None and designed is not None else None
            profile.append({
                "测点桩号": reading.get("测点桩号"),
                "缝编号": reading.get("缝编号"),
                "缝宽偏差": width_dev,
                "锚固偏差": anchor,
                "缝宽超标": width_dev is not None and abs(width_dev) > WIDTH_TOLERANCE_MM,
                "锚固超标": anchor is not None and abs(anchor) > ANCHOR_TOLERANCE_MM,
            })
        return profile

    # ---- 第三步：签认发布（与整包校验同一事务，失败整体回滚） ----

    def publish_batch(self, batch_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"测量批次 {batch_id} 不存在"
        if batch.get("status") == "已发布":
            return self._batch_detail(batch), "批次已发布，发布结论已写入台账，无需重复发布"
        if batch.get("status") != "待签认":
            raise WorkflowError("整包校验未通过，不得签认发布；请先完成整包校验")
        signer = str(values.get("签认人") or "").strip()
        if not signer:
            raise WorkflowError("签认发布必须填写签认人")
        reviews = values.get("复核")
        if reviews is not None and not isinstance(reviews, dict):
            raise WorkflowError("复核结论格式不正确，应按测点桩号组织")

        with store.transaction(BATCH_MODULE, MODULE, BRIDGE_MODULE, MATERIAL_MODULE):
            problems = self._check_package(batch)
            if problems:
                raise WorkflowError(f"整包校验未通过：{problems[0]}等 {len(problems)} 项，已整体回滚")
            conclusions = self._apply_reviews(batch, reviews or {})
            published_at = _now()
            ledger_count = self._write_ledger(batch, conclusions, published_at)
            archive_name = self._write_bridge_archive(batch, conclusions, published_at)
            todo_count = self._write_material_todos(batch, conclusions)
            replace_count = sum(1 for item in conclusions if item["结论"] == CONCLUSION_REPLACE)
            batch["签认人"] = signer
            batch["签认意见"] = str(values.get("签认意见") or "").strip()
            batch["签认时间"] = published_at
            batch["发布时间"] = published_at
            batch["status"] = "已发布"
            batch["pending"] = False
            batch["abnormal"] = replace_count > 0
            batch["发布结论"] = {
                "结论明细": conclusions,
                "正常数量": len(conclusions) - replace_count,
                "建议更换数量": replace_count,
                "台账写入": ledger_count,
                "桥梁档案": archive_name,
                "材料待办": todo_count,
            }
        return self._batch_detail(batch), "签认发布完成：结论已写入伸缩缝台账、桥梁档案与材料待办"

    def _apply_reviews(self, batch: dict[str, Any], reviews: dict[str, Any]) -> list[dict[str, Any]]:
        """复核仪器结论优先于历史读数；历史读数只读不写，继续按采集时刻保存。"""
        conclusions: list[dict[str, Any]] = []
        readings = sorted(batch.get("readings", []), key=lambda r: _stake_sort_key(r.get("测点桩号")))
        for reading in readings:
            stake = str(reading.get("测点桩号") or "")
            review = reviews.get(stake)
            if not isinstance(review, dict):
                review = {}
            review_width = _to_float(review.get("复核缝宽"))
            review_anchor = _to_float(review.get("复核锚固偏差"))
            review_verdict = str(review.get("复核结论") or "").strip()
            if review_width is not None:
                reading["复核缝宽"] = review_width
            if review_anchor is not None:
                reading["复核锚固偏差"] = review_anchor
            if review_verdict:
                reading["复核结论"] = review_verdict

            designed = _to_float(reading.get("设计缝宽")) or 0.0
            eff_width = review_width if review_width is not None else (_to_float(reading.get("实测缝宽")) or 0.0)
            eff_anchor = review_anchor if review_anchor is not None else (_to_float(reading.get("锚固偏差")) or 0.0)
            width_over = abs(eff_width - designed) > WIDTH_TOLERANCE_MM
            anchor_over = abs(eff_anchor) > ANCHOR_TOLERANCE_MM
            if review_verdict in (CONCLUSION_NORMAL, CONCLUSION_REPLACE):
                verdict = review_verdict  # 仪器结论优先于按历史读数推算的结果
            else:
                verdict = CONCLUSION_REPLACE if (width_over or anchor_over) else CONCLUSION_NORMAL
            conclusions.append({
                "测点桩号": stake,
                "缝编号": reading.get("缝编号"),
                "设计缝宽": designed,
                "采用缝宽": eff_width,
                "采用锚固偏差": eff_anchor,
                "采集口径": reading.get("采集口径"),
                "数据来源": "复核仪器" if review else "历史读数",
                "缝宽超标": width_over,
                "锚固超标": anchor_over,
                "结论": verdict,
            })
        return conclusions

    def _write_ledger(self, batch: dict[str, Any], conclusions: list[dict[str, Any]], published_at: str) -> int:
        """发布结论写入伸缩缝台账：已有缝更新，新缝登记，采集口径随读数保留。"""
        rows = store.rows(MODULE)
        written = 0
        for item in conclusions:
            verdict = item["结论"]
            entry = next((row for row in rows if str(row.get("缝编号")) == str(item["缝编号"])), None)
            if entry is None:
                entry = {
                    "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                    "缝编号": item["缝编号"],
                    "所属桥梁": batch.get("所属桥梁"),
                    "缝类型": "待核定",
                    "设计伸缩量": "-",
                    "堵塞情况": "-",
                }
                rows.append(entry)
            entry["当前缝宽"] = f"{item['采用缝宽']:g}mm"
            entry["锚固状态"] = "偏差超标" if item["锚固超标"] else "完好"
            entry["缝状态"] = "待更换" if verdict == CONCLUSION_REPLACE else "正常"
            entry["status"] = entry["缝状态"]
            entry["复核结论"] = verdict
            entry["最近复核批次"] = batch.get("批次编号")
            entry["最近复核时间"] = published_at
            entry["采集口径"] = item.get("采集口径")
            entry["pending"] = verdict == CONCLUSION_REPLACE
            entry["abnormal"] = verdict == CONCLUSION_REPLACE
            written += 1
        return written

    def _write_bridge_archive(self, batch: dict[str, Any], conclusions: list[dict[str, Any]], published_at: str) -> str:
        """发布结论写入桥梁档案：记录本批次的正常与建议更换数量。"""
        bridge = str(batch.get("所属桥梁") or "")
        entry = next(
            (row for row in store.rows(BRIDGE_MODULE)
             if bridge in (str(row.get("桥梁名称") or ""), str(row.get("桥梁编号") or ""))),
            None,
        )
        if entry is None:
            raise WorkflowError(f"桥梁档案中找不到「{bridge}」，发布已整体回滚")
        replace_count = sum(1 for item in conclusions if item["结论"] == CONCLUSION_REPLACE)
        entry["伸缩缝复核结论"] = f"{batch.get('批次编号')}：正常 {len(conclusions) - replace_count} 道、建议更换 {replace_count} 道"
        entry["最近伸缩缝复核"] = published_at
        entry["abnormal"] = bool(entry.get("abnormal")) or replace_count > 0
        return str(entry.get("桥梁名称") or bridge)

    def _write_material_todos(self, batch: dict[str, Any], conclusions: list[dict[str, Any]]) -> int:
        """发布结论写入材料待办：每条建议更换的缝生成一条待采购待办，重复发布不重复建。"""
        rows = store.rows(MATERIAL_MODULE)
        created = 0
        for item in conclusions:
            if item["结论"] != CONCLUSION_REPLACE:
                continue
            exists = any(
                str(row.get("来源批次")) == str(batch.get("批次编号"))
                and str(row.get("缝编号")) == str(item["缝编号"])
                for row in rows
            )
            if exists:
                continue
            rows.append({
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "材料编号": _next_code(rows, "材料编号", "MATE-"),
                "材料名称": f"伸缩缝更换（{item['缝编号']}）",
                "材料类别": "伸缩缝材料",
                "规格型号": "待材料建议",
                "供应商": "",
                "进场日期": "",
                "存放地点": "",
                "材料状态": "",
                "status": "待采购",
                "pending": True,
                "abnormal": False,
                "来源批次": batch.get("批次编号"),
                "所属桥梁": batch.get("所属桥梁"),
                "缝编号": item["缝编号"],
            })
            created += 1
        return created

    # ---- 第四步：材料建议 ----

    def generate_suggestions(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"测量批次 {batch_id} 不存在"
        if batch.get("status") != "已发布":
            raise WorkflowError("前序环节未签认发布，不得跳级生成材料建议")
        if batch.get("材料建议") is not None:
            return self._batch_detail(batch), "材料建议已生成，直接沿用既有结果"

        with store.transaction(BATCH_MODULE, MATERIAL_MODULE):
            conclusions = (batch.get("发布结论") or {}).get("结论明细") or []
            ledger_rows = store.rows(MODULE)
            suggestions: list[dict[str, Any]] = []
            for item in conclusions:
                if item.get("结论") != CONCLUSION_REPLACE:
                    continue
                ledger = next(
                    (row for row in ledger_rows if str(row.get("缝编号")) == str(item.get("缝编号"))),
                    {},
                )
                joint_type = str(ledger.get("缝类型") or "")
                material_name = {
                    "模数式": "模数式伸缩缝装置",
                    "梳齿板式": "梳齿板式伸缩缝装置",
                }.get(joint_type, "通用型伸缩缝装置")
                movement = str(ledger.get("设计伸缩量") or "").strip()
                designed = item.get("设计缝宽")
                spec = (
                    f"伸缩量{movement}"
                    if movement and movement != "-"
                    else (f"设计缝宽{designed:g}mm" if isinstance(designed, (int, float)) else "规格待定")
                )
                suggestions.append({
                    "缝编号": item.get("缝编号"),
                    "测点桩号": item.get("测点桩号"),
                    "建议材料": material_name,
                    "规格型号": spec,
                    "数量": 1,
                    "单位": "道",
                    "依据": f"{batch.get('批次编号')} 复核结论（{item.get('数据来源')}）",
                })
            # 建议同步进材料计划：把发布时生成的待办补全规格与材料名称
            for row in store.rows(MATERIAL_MODULE):
                if str(row.get("来源批次")) != str(batch.get("批次编号")):
                    continue
                match = next((s for s in suggestions if str(s["缝编号"]) == str(row.get("缝编号"))), None)
                if match:
                    row["材料名称"] = f"{match['建议材料']}（{match['缝编号']}）"
                    row["规格型号"] = match["规格型号"]
            batch["材料建议"] = suggestions
            batch["建议生成时间"] = _now()
        if not suggestions:
            return self._batch_detail(batch), "本批次无建议更换测点，材料建议为空"
        return self._batch_detail(batch), f"材料建议已生成 {len(suggestions)} 条，并同步材料计划"
