"""伸缩缝测量回放工作台接口：采集导入、整包校验、签认发布、材料建议顺序推进。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.expansion import ExpansionService

router = APIRouter(prefix="/api/expansion", tags=["测量回放工作台"])

service = ExpansionService()

LEDGER_STATUSES = ["正常", "堵塞", "锚固损坏", "已更换"]
BATCH_STATUSES = ["待补传", "待校验", "待签认", "已发布"]


@router.get("/batches", response_model=PageResult[dict])
def list_batches(
    status: str | None = Query(default=None, description="待补传、待校验、待签认、已发布"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """测量批次列表：上传中断保留的待补传批次也在这里，可继续补传。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_batches(status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/batches", response_model=ActionResult)
def import_batch(payload: EntryPayload) -> ActionResult:
    """采集导入：内容按摘要消重；上传中断时保留待补传批次，不丢数据。"""
    batch, message = service.import_batch(payload.values)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/batches/{batch_id}", response_model=dict)
def get_batch(batch_id: int) -> dict:
    """批次明细：读数、剖面核对记录、更换建议、签认与发布结论。"""
    batch = service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"测量批次 {batch_id} 不存在或已归档")
    return batch


@router.post("/batches/{batch_id}/validate", response_model=ActionResult)
def validate_batch(batch_id: int) -> ActionResult:
    """整包校验：在桥面剖面上顺序核对缝宽、设计、锚固偏差，形成更换建议。"""
    batch, message = service.validate_batch(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/batches/{batch_id}/publish", response_model=ActionResult)
def publish_batch(batch_id: int, payload: EntryPayload) -> ActionResult:
    """签认发布：校验复核、签认、写入台账/档案/材料待办同一事务，失败整体回滚。"""
    batch, message = service.publish_batch(batch_id, payload.values)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/batches/{batch_id}/suggestions", response_model=ActionResult)
def generate_suggestions(batch_id: int) -> ActionResult:
    """材料建议：流程最后一步，前序未签认不得跳级生成。"""
    batch, message = service.generate_suggestions(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按缝编号检索"),
    status: str | None = Query(default=None, description="正常、堵塞、锚固损坏、已更换"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """伸缩缝台账列表：发布结论回写后的当前状态；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条伸缩缝台账，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="伸缩缝台账已登记", entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """台账明细：含读数历史，历史读数保留采集时刻与当时采集口径。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"伸缩缝 {entry_id} 不存在或已归档")
    return entry
