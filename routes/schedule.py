"""排班核心路由 — 日历视图 + AI生成 + 屏蔽管理"""
import calendar
import re
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from database import get_db
from models import (ShootingMerchant, ShootingTask, ShootingBlocked,
                    ShootingPhotographer, MerchantPhotographer, ShootingIP)
from services.scheduler import generate_schedule
from routes.schedule_utils import get_templates, redirect_back

router = APIRouter(prefix="/schedule", tags=["排班"])


# ==================== 排班视图 ====================

@router.get("")
def schedule_view(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)

    raw_ym = request.query_params.get("month")
    today = date.today()
    if raw_ym:
        parts = raw_ym.split("-")
        year, month = int(parts[0]), int(parts[1])
    else:
        year, month = today.year, today.month

    raw_pid = request.query_params.get("photographer_id")
    sel_pid = int(raw_pid) if raw_pid else 0

    photographers = db.query(ShootingPhotographer).filter(
        ShootingPhotographer.status == "active"
    ).order_by(ShootingPhotographer.name).all()

    merchant_query = db.query(ShootingMerchant).filter(ShootingMerchant.status == "active")
    if sel_pid > 0:
        linked_ids = db.query(MerchantPhotographer.merchant_id).filter(
            MerchantPhotographer.photographer_id == sel_pid
        ).all()
        merchant_ids = [r[0] for r in linked_ids]
        if merchant_ids:
            merchant_query = merchant_query.filter(ShootingMerchant.id.in_(merchant_ids))
        else:
            merchant_query = merchant_query.filter(ShootingMerchant.id == -1)
    shooting_merchants = merchant_query.order_by(ShootingMerchant.created_at.desc()).all()

    all_ips = db.query(ShootingIP).filter(ShootingIP.status == "active").order_by(ShootingIP.name).all()
    merchant_ips = {}
    ip_children = {}
    for ip in all_ips:
        merchant_ips.setdefault(ip.merchant_id, []).append(ip)
        if ip.parent_ip_id:
            ip_children.setdefault(ip.parent_ip_id, []).append(ip)

    merchant_photographers = {}
    for sm in shooting_merchants:
        links = db.query(MerchantPhotographer).filter(
            MerchantPhotographer.merchant_id == sm.id
        ).all()
        pids = [l.photographer_id for l in links]
        if pids:
            pgs = db.query(ShootingPhotographer).filter(ShootingPhotographer.id.in_(pids)).all()
            merchant_photographers[sm.id] = pgs
        else:
            merchant_photographers[sm.id] = []

    selected_range = request.query_params.get("range", "month")

    month_start = f"{year}-{month:02d}-01"
    month_end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"

    task_query = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer),
        joinedload(ShootingTask.ip)
    ).filter(
        ShootingTask.scheduled_date >= month_start,
        ShootingTask.scheduled_date < month_end,
        ShootingTask.status != "cancelled"
    )
    if sel_pid > 0:
        task_query = task_query.filter(ShootingTask.photographer_id == sel_pid)
    tasks = task_query.order_by(ShootingTask.scheduled_date).all()

    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    has_today = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date == today_str,
        ShootingTask.status != "cancelled"
    ).first() is not None

    last_task = db.query(ShootingTask).filter(
        ShootingTask.status != "cancelled"
    ).order_by(ShootingTask.scheduled_date.desc()).first()
    last_date = last_task.scheduled_date if last_task else None

    task_map, am_map, pm_map, fd_list = {}, {}, {}, []
    for t in tasks:
        task_map.setdefault(t.scheduled_date, []).append(t)
        if t.time_slot == "morning":
            am_map.setdefault(t.scheduled_date, []).append(t)
        elif t.time_slot == "afternoon":
            pm_map.setdefault(t.scheduled_date, []).append(t)
        else:
            fd_list.append(t)
            am_map.setdefault(t.scheduled_date, []).append(t)
            pm_map.setdefault(t.scheduled_date, []).append(t)

    blocked_times = db.query(ShootingBlocked).filter(
        ShootingBlocked.blocked_date >= month_start,
        ShootingBlocked.blocked_date < month_end
    ).all()
    blocked_map = {}
    for b in blocked_times:
        blocked_map.setdefault(b.blocked_date, {}).setdefault(b.merchant_id, []).append(b.time_slot)

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(year, month)

    prev_month = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    next_month = f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"

    from models import Merchant as MainMerchant
    all_merchants = db.query(MainMerchant).filter(MainMerchant.status == "active").order_by(MainMerchant.name).all()

    locked_tasks = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer),
        joinedload(ShootingTask.ip)
    ).filter(
        ShootingTask.locked == 1,
        ShootingTask.status == "scheduled"
    ).order_by(ShootingTask.scheduled_date).all()

    thirty_days_ago = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    done_tasks = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer)
    ).filter(
        ShootingTask.status == "done",
        ShootingTask.scheduled_date >= thirty_days_ago
    ).order_by(ShootingTask.scheduled_date.desc()).limit(30).all()

    cancelled_tasks = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer)
    ).filter(
        ShootingTask.status == "cancelled",
        ShootingTask.scheduled_date >= thirty_days_ago
    ).order_by(ShootingTask.scheduled_date.desc()).limit(30).all()

    cancel_ranges = {}
    cancelled_groups = []
    _seen_groups = {}
    for ct in cancelled_tasks:
        if ct.notes:
            m = re.search(r'(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})', ct.notes)
            range_key = (m.group(1), m.group(2)) if m else (ct.scheduled_date, ct.scheduled_date)
        else:
            range_key = (ct.scheduled_date, ct.scheduled_date)
        if m:
            cancel_ranges[ct.id] = (m.group(1), m.group(2))

        group_key = (ct.merchant_id, range_key[0], range_key[1])
        if group_key in _seen_groups:
            idx = _seen_groups[group_key]
            cancelled_groups[idx]["tasks"].append(ct)
            cancelled_groups[idx]["video_count"] += ct.video_count or 0
        else:
            reason = ""
            if ct.notes:
                reason_match = re.search(r'取消原因:\s*(.+?)(?:（|$)', ct.notes)
                reason = reason_match.group(1) if reason_match else (ct.notes if not re.search(r'\d{4}-\d{2}-\d{2}~\d{4}-\d{2}-\d{2}', ct.notes) else "")
            _seen_groups[group_key] = len(cancelled_groups)
            cancelled_groups.append({
                "merchant": ct.shooting_merchant,
                "range_start": range_key[0], "range_end": range_key[1],
                "reason": reason, "tasks": [ct], "video_count": ct.video_count or 0,
            })

    # ── 排班汇总统计 ──
    schedule_end = today + timedelta(days=30)
    schedule_end_str = schedule_end.strftime("%Y-%m-%d")

    total_quota = 0
    child_ids_set = set()
    parent_child_map = {}
    for sm in shooting_merchants:
        if sm.linked_merchant_id and sm.need_shooting == 1:
            parent_child_map.setdefault(sm.linked_merchant_id, []).append(sm.id)
            child_ids_set.add(sm.id)
    for sm in shooting_merchants:
        if sm.id in child_ids_set or sm.need_shooting != 1:
            continue
        parent_total = sm.monthly_quota or 25
        children_sum = sum(
            (db.query(ShootingMerchant).filter(ShootingMerchant.id == cid).first().monthly_quota or 0)
            for cid in parent_child_map.get(sm.id, [])
        )
        total_quota += max(0, parent_total - children_sum)
        for cid in parent_child_map.get(sm.id, []):
            child = db.query(ShootingMerchant).filter(ShootingMerchant.id == cid).first()
            if child:
                total_quota += child.monthly_quota or 0

    all_period_tasks = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date >= today_str,
        ShootingTask.scheduled_date <= schedule_end_str,
        ShootingTask.status.in_(["scheduled", "done"])
    ).all()
    active_30d = [t for t in all_period_tasks if t.status == "scheduled"]
    done_30d = [t for t in all_period_tasks if t.status == "done"]

    def slot_count(tasks):
        return sum(2 if t.time_slot == "full_day" else 1 for t in tasks)

    def video_sum(tasks):
        return sum((t.actual_video_count if t.actual_video_count else t.video_count or 0) for t in tasks)

    total_slots = slot_count(active_30d) + slot_count(done_30d)
    total_videos = video_sum(active_30d) + video_sum(done_30d)

    flexible_merchant_ids = set(
        m.id for m in shooting_merchants
        if m.need_shooting == 1 and m.auto_schedule == 0
    )
    flexible_quota = sum(
        m.monthly_quota or 0 for m in shooting_merchants
        if m.id in flexible_merchant_ids and not m.linked_merchant_id
    )
    all_active = active_30d + done_30d
    flexible_tasks = [t for t in all_active if t.merchant_id in flexible_merchant_ids]
    flexible_videos = video_sum(flexible_tasks)
    flexible_slots = slot_count(flexible_tasks)
    auto_quota = total_quota - flexible_quota
    auto_videos = total_videos - flexible_videos
    auto_slots = total_slots - flexible_slots

    pg_stats = {}
    for p in photographers:
        pg_tasks = [t for t in all_active if t.photographer_id == p.id]
        if pg_tasks:
            am_count = len([t for t in pg_tasks if t.time_slot == "morning"])
            pm_count = len([t for t in pg_tasks if t.time_slot == "afternoon"])
            fd_count = len([t for t in pg_tasks if t.time_slot == "full_day"])
            pg_videos = video_sum(pg_tasks)
            pg_stats[p.id] = {
                "name": p.name, "slots": slot_count(pg_tasks),
                "am": am_count, "pm": pm_count, "fd": fd_count, "videos": pg_videos,
            }

    total_days_30 = 31
    work_days = sum(1 for d in range(total_days_30)
                    if (today + timedelta(days=d)).weekday() < 6)

    pg_max_capacity = {}
    for p in photographers:
        if p.role == "flexible" or p.auto_schedule == 0:
            continue
        if p.role == "founder":
            available_days = total_days_30
        else:
            days_off = (p.days_off_per_week or 1) * 4
            available_days = max(0, work_days - days_off)
        max_slots = available_days * (p.max_slots_per_day or 2)
        pg_max_capacity[p.id] = {
            "available_days": available_days, "max_slots": max_slots,
            "role": p.role or "fulltime",
            "days_off_per_week": p.days_off_per_week or 1,
            "max_slots_per_day": p.max_slots_per_day or 2,
        }

    for p in photographers:
        if p.id not in pg_stats and pg_max_capacity.get(p.id):
            pg_stats[p.id] = {"name": p.name, "slots": 0, "am": 0, "pm": 0, "fd": 0, "videos": 0}

    quota_gap = total_quota - total_videos

    # ── 冲突检测：同一天同一摄影师同时段被重复排 ──
    conflicts = []
    pg_day_slots = {}  # (pid, date, slot) -> [task_ids]
    for t in tasks:
        if t.status == "scheduled" and t.photographer_id:
            key = (t.photographer_id, t.scheduled_date, t.time_slot)
            pg_day_slots.setdefault(key, []).append(t.id)
    for (pid, d, slot), tids in pg_day_slots.items():
        if len(tids) > 1:
            pg_name = next((p.name for p in photographers if p.id == pid), str(pid))
            conflicts.append(f"{pg_name} 在 {d} {slot} 有 {len(tids)} 个任务冲突")

    # 文案数据（供文案tab使用）
    from models import ShootingScript
    script_tasks, scripts_map_data = [], {}
    schedule_end_scripts = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    script_task_query = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer),
        joinedload(ShootingTask.ip)
    ).filter(
        ShootingTask.scheduled_date >= today_str,
        ShootingTask.scheduled_date <= schedule_end_scripts,
        ShootingTask.status == "scheduled"
    ).order_by(ShootingTask.scheduled_date).all()
    script_tasks = script_task_query
    st_ids = [t.id for t in script_tasks]
    if st_ids:
        st_scripts = db.query(ShootingScript).filter(ShootingScript.task_id.in_(st_ids)).order_by(ShootingScript.id).all()
        for s in st_scripts:
            scripts_map_data.setdefault(s.task_id, []).append(s)

    seven_days_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_completed = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer),
        joinedload(ShootingTask.ip)
    ).filter(
        ShootingTask.scheduled_date >= seven_days_ago,
        ShootingTask.scheduled_date <= today_str,
        ShootingTask.status.in_(["done", "scheduled"])
    ).order_by(ShootingTask.scheduled_date.desc()).all()

    templates = get_templates()
    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "active_tab": "schedule",
        "photographers": photographers,
        "all_merchants": all_merchants,
        "merchant_photographers": merchant_photographers,
        "sel_pid": sel_pid,
        "shooting_merchants": shooting_merchants,
        "year": year, "month": month,
        "month_days": month_days,
        "task_map": task_map, "am_map": am_map, "pm_map": pm_map, "fd_list": fd_list,
        "all_tasks": tasks,
        "blocked_map": blocked_map,
        "prev_month": prev_month, "next_month": next_month,
        "today": today, "month_name": f"{year}年{month}月",
        "selected_range": selected_range,
        "has_today": has_today, "last_date": last_date,
        "today_str": today_str, "tomorrow_str": tomorrow_str,
        "locked_tasks": locked_tasks,
        "all_ips": all_ips, "merchant_ips": merchant_ips, "ip_children": ip_children,
        "done_tasks": done_tasks,
        "cancelled_tasks": cancelled_tasks, "cancel_ranges": cancel_ranges,
        "cancelled_groups": cancelled_groups,
        "total_quota": total_quota, "total_slots": total_slots, "total_videos": total_videos,
        "pg_stats": pg_stats, "pg_max_capacity": pg_max_capacity,
        "work_days": work_days, "quota_gap": quota_gap,
        "flexible_quota": flexible_quota, "flexible_videos": flexible_videos,
        "flexible_slots": flexible_slots,
        "auto_quota": auto_quota, "auto_videos": auto_videos, "auto_slots": auto_slots,
        "end_30_str": schedule_end_str,
        "recent_completed": recent_completed,
        "script_tasks": script_tasks,
        "scripts_map": scripts_map_data,
        "conflicts": conflicts,
    })


# ==================== 排班生成 ====================

@router.post("/generate")
async def do_generate(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    today = date.today()

    sel_pid = int(form.get("photographer_id", 0))
    end_date = today + timedelta(days=30)

    all_merchants = db.query(ShootingMerchant).filter(
        ShootingMerchant.status == "active",
        ShootingMerchant.need_shooting == 1,
        ShootingMerchant.auto_schedule == 1
    ).all()
    if sel_pid > 0:
        linked = db.query(MerchantPhotographer.merchant_id).filter(
            MerchantPhotographer.photographer_id == sel_pid
        ).all()
        mids = {r[0] for r in linked}
        all_merchants = [m for m in all_merchants if m.id in mids]

    if not all_merchants:
        return RedirectResponse(url="/schedule", status_code=302)

    flexible_pg_ids = set(
        p.id for p in db.query(ShootingPhotographer).filter(
            ShootingPhotographer.status == "active",
            ShootingPhotographer.auto_schedule == 0
        ).all()
    )

    linked_map = {}
    for m in all_merchants:
        if m.linked_merchant_id:
            linked_map.setdefault(m.linked_merchant_id, []).append(m.id)
    child_ids = set()
    for children in linked_map.values():
        child_ids.update(children)

    merchant_data = []
    for m in all_merchants:
        if m.id in child_ids:
            continue
        total_quota = m.monthly_quota or 25
        children_quota_sum = 0
        for cid in linked_map.get(m.id, []):
            cm = next((x for x in all_merchants if x.id == cid), None)
            if cm:
                children_quota_sum += cm.monthly_quota or 0
        parent_quota = max(0, total_quota - children_quota_sum)

        parent_done = db.query(func.coalesce(
            func.sum(func.coalesce(ShootingTask.actual_video_count, ShootingTask.video_count)), 0
        )).filter(
            ShootingTask.merchant_id == m.id,
            ShootingTask.status == "done"
        ).scalar()
        links = db.query(MerchantPhotographer).filter(
            MerchantPhotographer.merchant_id == m.id
        ).all()
        pids = [l.photographer_id for l in links if l.photographer_id not in flexible_pg_ids]
        if sel_pid > 0 and sel_pid not in pids:
            pids.append(sel_pid)
        merchant_data.append({
            "id": m.id, "name": m.name, "district": m.district or "",
            "monthly_quota": parent_quota, "done_this_month": parent_done,
            "photographer_ids": pids
        })

        for cid in linked_map.get(m.id, []):
            cm = next((x for x in all_merchants if x.id == cid), None)
            if not cm:
                continue
            child_done = db.query(func.coalesce(
                func.sum(func.coalesce(ShootingTask.actual_video_count, ShootingTask.video_count)), 0
            )).filter(
                ShootingTask.merchant_id == cid,
                ShootingTask.status == "done"
            ).scalar()
            child_links = db.query(MerchantPhotographer).filter(
                MerchantPhotographer.merchant_id == cid
            ).all()
            child_pids = [l.photographer_id for l in child_links if l.photographer_id not in flexible_pg_ids]
            if not child_pids:
                child_pids = list(pids)
            if sel_pid > 0 and sel_pid not in child_pids:
                child_pids.append(sel_pid)
            merchant_data.append({
                "id": cid, "name": cm.name, "district": cm.district or "",
                "monthly_quota": cm.monthly_quota or 0, "done_this_month": child_done,
                "photographer_ids": child_pids
            })

    blocked_times = db.query(ShootingBlocked).all()
    blocked = {}
    for b in blocked_times:
        blocked.setdefault(b.blocked_date, {}).setdefault(b.merchant_id, []).append(b.time_slot)

    today_str = today.strftime("%Y-%m-%d")
    past_locked = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date < today_str,
        ShootingTask.locked == 1,
        ShootingTask.status == "scheduled"
    ).all()
    for pt in past_locked:
        pt.status = "done"
        pt.notes = (pt.notes or "") + " [过期自动归档]"

    end_str = end_date.strftime("%Y-%m-%d")
    del_q = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date >= today_str,
        ShootingTask.scheduled_date <= end_str,
        ShootingTask.status == "scheduled",
        ShootingTask.locked == 0
    ).delete(synchronize_session="fetch")

    remaining_locked = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date >= today_str,
        ShootingTask.scheduled_date <= end_str,
        ShootingTask.locked == 1,
        ShootingTask.status == "scheduled"
    ).all()
    locked_map = {}
    for lt in remaining_locked:
        d = lt.scheduled_date
        locked_map.setdefault(d, []).append({
            "merchant_id": lt.merchant_id,
            "photographer_id": lt.photographer_id,
            "time_slot": lt.time_slot,
        })

    cancelled_tasks = db.query(ShootingTask).filter(
        ShootingTask.status == "cancelled",
        ShootingTask.scheduled_date >= today_str
    ).all()
    for ct in cancelled_tasks:
        blocked.setdefault(ct.scheduled_date, {}).setdefault(ct.merchant_id, []).append(ct.time_slot)

    # IP 冷却（汇总最近30天所有超额拍摄）
    ip_cooldown_until = {}
    for ip in db.query(ShootingIP).filter(ShootingIP.status == "active").all():
        recent_done = db.query(ShootingTask).filter(
            ShootingTask.ip_id == ip.id,
            ShootingTask.status == "done",
            ShootingTask.actual_video_count.isnot(None),
            ShootingTask.scheduled_date >= (today - timedelta(days=30)).strftime("%Y-%m-%d")
        ).order_by(ShootingTask.scheduled_date.desc()).all()
        if recent_done:
            total_actual = sum(t.actual_video_count or 0 for t in recent_done)
            total_planned = sum(t.video_count or 0 for t in recent_done)
            surplus = total_actual - total_planned
            if surplus > 0:
                last_date = recent_done[0].scheduled_date
                cool_until = datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=total_actual // 2)  # 按每天2条视频算冷却天数
                ip_cooldown_until[ip.id] = cool_until.strftime("%Y-%m-%d")

    all_ips = db.query(ShootingIP).filter(
        ShootingIP.status == "active", ShootingIP.auto_schedule == 1
    ).all()
    merchant_ip_map = {}
    for ip in all_ips:
        if ip.id in ip_cooldown_until and ip_cooldown_until[ip.id] >= today_str:
            continue
        merchant_ip_map.setdefault(ip.merchant_id, []).append(ip.id)

    result = generate_schedule(merchant_data, today.year, today.month,
                                start_day=today.day, blocked=blocked,
                                end_date=end_date.strftime("%Y-%m-%d"),
                                locked_tasks=locked_map,
                                merchant_ips=merchant_ip_map)

    for day_plan in result:
        for task in day_plan.get("tasks", []):
            mid = task.get("merchant_id", 0)
            pid = task.get("photographer_id", 0)
            db.add(ShootingTask(
                merchant_id=mid,
                photographer_id=pid,
                ip_id=task.get("ip_id"),
                scheduled_date=day_plan["date"],
                time_slot=task.get("time_slot", "morning"),
                video_count=task.get("video_count", 2),
                status="scheduled",
            ))

    db.commit()
    redir = "/schedule"
    if sel_pid:
        redir += f"?photographer_id={sel_pid}"
    return RedirectResponse(url=redir, status_code=302)


# ==================== 屏蔽管理 ====================

@router.post("/block")
async def block_slot(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    merchant_id = int(form.get("merchant_id", 0))
    blocked_date = form.get("date", "")
    time_slot = form.get("time_slot", "morning")
    if not merchant_id or not blocked_date:
        return RedirectResponse(url="/schedule", status_code=302)
    existing = db.query(ShootingBlocked).filter(
        ShootingBlocked.merchant_id == merchant_id,
        ShootingBlocked.blocked_date == blocked_date,
        ShootingBlocked.time_slot == time_slot
    ).first()
    if not existing:
        db.add(ShootingBlocked(merchant_id=merchant_id, blocked_date=blocked_date, time_slot=time_slot))
        db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.get("/unblock/{block_id}")
def unblock_slot(block_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    b = db.query(ShootingBlocked).filter(ShootingBlocked.id == block_id).first()
    if b:
        db.delete(b)
        db.commit()
    return RedirectResponse(url="/schedule", status_code=302)
