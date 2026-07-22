"""排班任务操作 — 完成/取消/恢复/移动/批量操作"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import ShootingTask, ShootingBlocked
from routes.schedule_utils import redirect_back

router = APIRouter(prefix="/schedule", tags=["排班任务"])


@router.post("/task/update-actual")
async def update_actual_counts(request: Request, db: Session = Depends(get_db)):
    """批量更新实际拍摄数"""
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    count = 0
    for key in form:
        if key.startswith("actual_"):
            task_id = int(key.split("_")[1])
            val = form.get(key, "")
            if val and val.isdigit():
                task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
                if task:
                    task.actual_video_count = int(val)
                    if task.status == "scheduled":
                        task.status = "done"
                    count += 1
    db.commit()
    return RedirectResponse(url=redirect_back(request), status_code=302)


@router.get("/task/{task_id}/done")
def mark_done(task_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if task:
        task.status = "done"
        actual = request.query_params.get("actual", "")
        if actual and actual.isdigit():
            task.actual_video_count = int(actual)
        else:
            task.actual_video_count = task.video_count
        db.commit()
    return RedirectResponse(url=redirect_back(request), status_code=302)


@router.get("/task/{task_id}/cancel")
def cancel_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if task:
        reason = request.query_params.get("reason", "")
        start_date = request.query_params.get("start_date", task.scheduled_date)
        end_date = request.query_params.get("end_date", task.scheduled_date)
        # 兼容旧的 cancel_days 参数
        if "cancel_days" in request.query_params and "start_date" not in request.query_params:
            cancel_days = int(request.query_params.get("cancel_days", "1"))
            start_date = task.scheduled_date
            end_date = (datetime.strptime(task.scheduled_date, "%Y-%m-%d") + timedelta(days=cancel_days - 1)).strftime("%Y-%m-%d")

        tasks_to_cancel = db.query(ShootingTask).filter(
            ShootingTask.merchant_id == task.merchant_id,
            ShootingTask.scheduled_date >= start_date,
            ShootingTask.scheduled_date <= end_date,
            ShootingTask.status == "scheduled"
        ).all()
        for t in tasks_to_cancel:
            t.status = "cancelled"
            note = f"取消原因: {reason}（{start_date}~{end_date}）" if reason else f"取消（{start_date}~{end_date}）"
            t.notes = (t.notes or "") + (" | " if t.notes else "") + note

        d = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_in_range = (end_dt - d).days + 1
        for i in range(days_in_range):
            day_str = (d + timedelta(days=i)).strftime("%Y-%m-%d")
            for slot in ["morning", "afternoon", "full_day"]:
                exists = db.query(ShootingBlocked).filter(
                    ShootingBlocked.merchant_id == task.merchant_id,
                    ShootingBlocked.blocked_date == day_str,
                    ShootingBlocked.time_slot == slot
                ).first()
                if not exists:
                    db.add(ShootingBlocked(
                        merchant_id=task.merchant_id, blocked_date=day_str, time_slot=slot,
                        reason=f"自动屏蔽: {reason}" if reason else "自动屏蔽: 商家取消"
                    ))
        db.commit()
    return RedirectResponse(url=redirect_back(request), status_code=302)


@router.get("/task/{task_id}/delete")
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """彻底删除排班任务"""
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse(url=redirect_back(request), status_code=302)


@router.post("/task/batch-cancel")
async def batch_cancel_tasks(request: Request, db: Session = Depends(get_db)):
    """批量取消排班任务"""
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    task_ids_str = form.get("task_ids", "")
    reason = form.get("reason", "").strip()
    if not task_ids_str:
        return RedirectResponse(url="/schedule", status_code=302)
    ids = [int(x) for x in task_ids_str.split(",") if x.strip().isdigit()]
    for tid in ids:
        task = db.query(ShootingTask).filter(ShootingTask.id == tid).first()
        if task:
            task.status = "cancelled"
            task.notes = reason if reason else task.notes
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.get("/task/{task_id}/restore")
def restore_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """恢复已取消的排班任务"""
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if task and task.status == "cancelled":
        task.status = "scheduled"
        task.notes = (task.notes or "") + " | 已恢复"
        db.commit()
    return RedirectResponse(url=redirect_back(request), status_code=302)


@router.post("/task/{task_id}/move")
async def move_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404)
    form = await request.form()
    new_date = form.get("date", "")
    new_slot = form.get("time_slot", "")
    if new_date:
        task.scheduled_date = new_date
    if new_slot:
        task.time_slot = new_slot
    task.locked = 1
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.post("/task/new")
async def create_manual_task(request: Request, db: Session = Depends(get_db)):
    """手动添加排班任务（自动锁定）"""
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    ip_raw = form.get("ip_id", "0")
    dup = db.query(ShootingTask).filter(
        ShootingTask.merchant_id == int(form.get("merchant_id", 0)),
        ShootingTask.scheduled_date == form.get("date", ""),
        ShootingTask.time_slot == form.get("time_slot", "morning"),
        ShootingTask.locked == 1,
        ShootingTask.status == "scheduled"
    ).first()
    if dup:
        return RedirectResponse(url="/schedule", status_code=302)
    db.add(ShootingTask(
        merchant_id=int(form.get("merchant_id", 0)),
        photographer_id=int(form.get("photographer_id", 0)),
        ip_id=int(ip_raw) if ip_raw and ip_raw.isdigit() and int(ip_raw) > 0 else None,
        scheduled_date=form.get("date", ""),
        time_slot=form.get("time_slot", "morning"),
        video_count=int(form.get("video_count", "2")),
        locked=1,
        status="scheduled",
        notes=form.get("notes", ""),
    ))
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.get("/clear-past")
def clear_past_tasks(request: Request, db: Session = Depends(get_db)):
    """清理过去30天的已完成/已取消任务"""
    from routes.merchants import check_auth
    check_auth(request)
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    db.query(ShootingTask).filter(
        ShootingTask.scheduled_date < thirty_days_ago,
        ShootingTask.status.in_(["done", "cancelled"])
    ).delete(synchronize_session="fetch")
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)
