"""伸缩缝测量回放工作台接口：采集导入、整包校验、签认发布、材料建议顺序推进。

前序未签认不得跳级生成建议；签认发布与整包校验在同一事务内完成，
发布结论一次写入伸缩缝台账、桥梁档案与材料待办，失败整体回滚。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.expansion import ExpansionReplayService, ExpansionService, WorkflowError

router = APIRouter(prefix="/api/expansion", tags=["伸缩缝测量回放"])

ledger = ExpansionService()
replay = ExpansionReplayService()

STATUSES = ["正常", "堵塞", "锚固损坏", "待更换", "已更换"]
BATCH_STATUSES = ["待校验", "待签认", "已发布", "校验失败"]


# ---- 测量批次：采集导入 → 整包校验 → 签认发布 → 材料建议 ----

@router.get("/batches", response_model=PageResult[dict])
def list_batches(
    status: str | None = Query(default=None, description="待校验、待签认、已发布、校验失败"),
    pending: bool = Query(default=False, description="只看待发布批次（待校验、待签认、校验失败）"),
    page: int = 1,
    size: int = 50,
) -> PageResult[dict]:
    """批次列表；上传中断后未走完流程的批次保留在这里，可继续处理。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = replay.list_batches(status=status, pending_only=pending, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/batches", response_model=ActionResult)
def import_batch(payload: EntryPayload) -> ActionResult:
    """采集导入：内容重复的采集包按摘要直接消重，沿用已有待发布批次。"""
    batch, message = replay.import_batch(payload.values)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/batches/{batch_id}", response_model=dict)
def get_batch(batch_id: int) -> dict:
    """批次明细：读数按桥面剖面桩号顺序返回，附逐点缝宽偏差。"""
    batch = replay.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"测量批次 {batch_id} 不存在")
    return batch


@router.post("/batches/{batch_id}/validate", response_model=ActionResult)
def validate_batch(batch_id: int) -> ActionResult:
    """整包校验：按桥面剖面顺序核对缝宽、设计和锚固偏差，通过后进入待签认。"""
    batch, message = replay.validate_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/batches/{batch_id}/publish", response_model=ActionResult)
def publish_batch(batch_id: int, payload: EntryPayload) -> ActionResult:
    """签认发布：与整包校验同一事务，结论一次写入台账、桥梁档案与材料待办，失败回滚。"""
    try:
        batch, message = replay.publish_batch(batch_id, payload.values)
    except WorkflowError as error:
        return ActionResult(ok=False, message=str(error))
    if batch is None:
        raise HTTPException(status_code=404, detail=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/batches/{batch_id}/suggestions", response_model=ActionResult)
def generate_suggestions(batch_id: int) -> ActionResult:
    """材料建议：必须已签认发布，前序未签认不得跳级生成；结果同步材料计划。"""
    try:
        batch, message = replay.generate_suggestions(batch_id)
    except WorkflowError as error:
        return ActionResult(ok=False, message=str(error))
    if batch is None:
        raise HTTPException(status_code=404, detail=message)
    return ActionResult(ok=True, message=message, entry=batch)


# ---- 伸缩缝台账：发布结论的落点，保留登记与处置动作 ----

@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出伸缩缝台账清单：返回当前过滤条件下的全量数据。"""
    items, total = ledger.list_entries(page=1, size=10000)
    return {"module": "expansion", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按缝编号检索"),
    status: str | None = Query(default=None, description="正常、堵塞、锚固损坏、待更换、已更换"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按缝编号与状态过滤伸缩缝台账；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = ledger.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条伸缩缝台账，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = ledger.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="伸缩缝已登记", entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条伸缩缝台账明细；不存在时给出可读的错误说明。"""
    entry = ledger.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"伸缩缝 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对台账执行清理堵塞、修补锚固、更换伸缩缝；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = ledger.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
