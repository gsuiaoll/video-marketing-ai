"""拍摄排班路由 — 摄影师CRUD + 拍摄商家CRUD + AI排班"""
import calendar
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import ShootingMerchant, ShootingTask, ShootingBlocked, ShootingPhotographer, MerchantPhotographer, ShootingIP
from services.scheduler import generate_schedule

router = APIRouter(prefix="/schedule", tags=["排班"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ==================== 摄影师 CRUD ====================

@router.post("/photographer/new")
async def add_photographer(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    db.add(ShootingPhotographer(name=form.get("name", ""), phone=form.get("phone", "")))
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.post("/photographer/{pid}/edit")
async def edit_photographer(pid: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    p = db.query(ShootingPhotographer).filter(ShootingPhotographer.id == pid).first()
    if p:
        form = await request.form()
        p.name = form.get("name", p.name)
        p.phone = form.get("phone", p.phone)
        db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.get("/photographer/{pid}/delete")
def delete_photographer(pid: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    # 解除商家关联 + 商家缺少摄影师时自动分配剩余摄影师 + 清空排班任务 + 删除
    # 1. 找出只关联了该摄影师的商家
    all_links = db.query(MerchantPhotographer).all()
    merchant_pg_count = {}
    for link in all_links:
        merchant_pg_count.setdefault(link.merchant_id, []).append(link.photographer_id)
    orphan_mids = [mid for mid, pids in merchant_pg_count.items() if pids == [pid]]

    # 2. 删除该摄影师的所有关联
    db.query(MerchantPhotographer).filter(MerchantPhotographer.photographer_id == pid).delete()

    # 3. 为孤寡商家自动分配剩余摄影师
    if orphan_mids:
        remaining_pg = db.query(ShootingPhotographer).filter(
            ShootingPhotographer.id != pid, ShootingPhotographer.status == "active"
        ).first()
        if remaining_pg:
            for mid in orphan_mids:
                db.add(MerchantPhotographer(merchant_id=mid, photographer_id=remaining_pg.id))

    # 4. 清空该摄影师的排班任务
    db.query(ShootingTask).filter(ShootingTask.photographer_id == pid).delete()

    # 5. 删除摄影师
    p = db.query(ShootingPhotographer).filter(ShootingPhotographer.id == pid).first()
    if p:
        db.delete(p)
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


# ==================== 拍摄商家 CRUD ====================

@router.post("/merchant/new")
async def create_shooting_merchant(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    sel_pids = [int(v) for v in form.getlist("photographer_ids") if v and v.isdigit()]

    # 从主商家库关联（快速通道）
    from_main_id = form.get("from_main_id", "")
    if from_main_id:
        from models import Merchant as MainMerchant
        main_m = db.query(MainMerchant).filter(MainMerchant.id == int(from_main_id)).first()
        if main_m:
            sm = db.query(ShootingMerchant).filter(
                ShootingMerchant.name == main_m.name
            ).first()
            if not sm and main_m.name:
                sm = db.query(ShootingMerchant).filter(
                    ShootingMerchant.name.like(main_m.name[:2] + "%")
                ).first()
            if not sm:
                sm = ShootingMerchant(
                    name=main_m.name or "",
                    district=main_m.district or "",
                    address=main_m.address or "",
                    contact_name=main_m.contact_name or "",
                    contact_phone=main_m.contact_phone or "",
                    monthly_quota=main_m.monthly_quota or 25
                )
                db.add(sm)
                db.flush()
            for p in sel_pids:
                exists_link = db.query(MerchantPhotographer).filter(
                    MerchantPhotographer.merchant_id == sm.id,
                    MerchantPhotographer.photographer_id == p
                ).first()
                if not exists_link:
                    db.add(MerchantPhotographer(merchant_id=sm.id, photographer_id=p))
            db.commit()
        redir = "/schedule"
        if sel_pids:
            redir += f"?photographer_id={sel_pids[0]}"
        return RedirectResponse(url=redir, status_code=302)

    # 手动新建
    m = ShootingMerchant(
        name=form.get("name", ""),
        district=form.get("district", ""),
        address=form.get("address", ""),
        contact_name=form.get("contact_name", ""),
        contact_phone=form.get("contact_phone", ""),
        monthly_quota=int(form.get("monthly_quota", "25"))
    )
    db.add(m)
    db.flush()
    for p in sel_pids:
        db.add(MerchantPhotographer(merchant_id=m.id, photographer_id=p))
    db.commit()
    redir = f"/schedule?photographer_id={sel_pids[0]}" if sel_pids else "/schedule"
    return RedirectResponse(url=redir, status_code=302)


@router.post("/merchant/{merchant_id}/edit")
async def update_shooting_merchant(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    m = db.query(ShootingMerchant).filter(ShootingMerchant.id == merchant_id).first()
    if not m:
        raise HTTPException(status_code=404)
    form = await request.form()
    m.name = form.get("name", m.name)
    m.district = form.get("district", m.district)
    m.address = form.get("address", m.address)
    m.contact_name = form.get("contact_name", m.contact_name)
    m.contact_phone = form.get("contact_phone", m.contact_phone)
    m.monthly_quota = int(form.get("monthly_quota", str(m.monthly_quota or 25)))
    m.need_shooting = 1 if form.get("need_shooting", "1") == "1" else 0
    linked_raw = form.get("linked_merchant_id", "")
    m.linked_merchant_id = int(linked_raw) if linked_raw else None
    # 多对多：更新摄影师关联
    sel_pids = [int(v) for v in form.getlist("photographer_ids") if v and v.isdigit()]
    db.query(MerchantPhotographer).filter(MerchantPhotographer.merchant_id == merchant_id).delete()
    for p in sel_pids:
        db.add(MerchantPhotographer(merchant_id=merchant_id, photographer_id=p))
    db.commit()
    redir = f"/schedule?photographer_id={sel_pids[0]}" if sel_pids else "/schedule"
    return RedirectResponse(url=redir, status_code=302)


@router.get("/merchant/{merchant_id}/delete")
def delete_shooting_merchant(merchant_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    db.query(ShootingTask).filter(ShootingTask.merchant_id == merchant_id).delete()
    db.query(ShootingBlocked).filter(ShootingBlocked.merchant_id == merchant_id).delete()
    db.query(MerchantPhotographer).filter(MerchantPhotographer.merchant_id == merchant_id).delete()
    m = db.query(ShootingMerchant).filter(ShootingMerchant.id == merchant_id).first()
    if m:
        db.delete(m)
    db.commit()
    return RedirectResponse(url=_redir(request), status_code=302)


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

    # 当前选中的摄影师
    raw_pid = request.query_params.get("photographer_id")
    sel_pid = int(raw_pid) if raw_pid else 0

    # 摄影师列表
    photographers = db.query(ShootingPhotographer).filter(
        ShootingPhotographer.status == "active"
    ).order_by(ShootingPhotographer.name).all()

    # 拍摄商家列表（多对多：通过 junction 表按摄影师过滤）
    merchant_query = db.query(ShootingMerchant).filter(ShootingMerchant.status == "active")
    if sel_pid > 0:
        linked_ids = db.query(MerchantPhotographer.merchant_id).filter(
            MerchantPhotographer.photographer_id == sel_pid
        ).all()
        merchant_ids = [r[0] for r in linked_ids]
        if merchant_ids:
            merchant_query = merchant_query.filter(ShootingMerchant.id.in_(merchant_ids))
        else:
            merchant_query = merchant_query.filter(ShootingMerchant.id == -1)  # 空结果
    shooting_merchants = merchant_query.order_by(ShootingMerchant.created_at.desc()).all()

    # 出镜IP人物列表 + 按商家分组
    all_ips = db.query(ShootingIP).filter(ShootingIP.status == "active").order_by(ShootingIP.name).all()
    merchant_ips = {}
    for ip in all_ips:
        merchant_ips.setdefault(ip.merchant_id, []).append(ip)

    # 每个商家对应的摄影师列表（用于显示）
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

    # 当前选中的排班范围
    selected_range = request.query_params.get("range", "month")

    # 当月排班
    month_start = f"{year}-{month:02d}-01"
    month_end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"

    from sqlalchemy.orm import joinedload
    task_query = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer),
        joinedload(ShootingTask.ip)
    ).filter(
        ShootingTask.scheduled_date >= month_start,
        ShootingTask.scheduled_date < month_end,
        ShootingTask.status != "cancelled"  # 已取消的不显示在日历
    )
    if sel_pid > 0:
        task_query = task_query.filter(ShootingTask.photographer_id == sel_pid)
    tasks = task_query.order_by(ShootingTask.scheduled_date).all()

    # 今天和明天
    today_str = today.strftime("%Y-%m-%d")
    from datetime import timedelta
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # 检查今天是否有排班
    has_today = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date == today_str,
        ShootingTask.status != "cancelled"
    ).first() is not None

    # 找到最后一个有排班的日期
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
            # 全天任务也填入 am/pm
            am_map.setdefault(t.scheduled_date, []).append(t)
            pm_map.setdefault(t.scheduled_date, []).append(t)

    # 屏蔽
    blocked_times = db.query(ShootingBlocked).filter(
        ShootingBlocked.blocked_date >= month_start,
        ShootingBlocked.blocked_date < month_end
    ).all()
    blocked_map = {}
    for b in blocked_times:
        blocked_map.setdefault(b.blocked_date, {}).setdefault(b.merchant_id, []).append(b.time_slot)

    # 月历
    cal = calendar.Calendar(firstweekday=0)  # 周一开始
    month_days = cal.monthdayscalendar(year, month)

    prev_month = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    next_month = f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"

    # 主商家库（供下拉选择，全显示，重复名选了会更新而非新建）
    from models import Merchant as MainMerchant
    all_merchants = db.query(MainMerchant).filter(MainMerchant.status == "active").order_by(MainMerchant.name).all()

    # 手动锁定的任务
    locked_tasks = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer),
        joinedload(ShootingTask.ip)
    ).filter(
        ShootingTask.locked == 1,
        ShootingTask.status == "scheduled"
    ).order_by(ShootingTask.scheduled_date).all()

    # 已完成的历史记录（近30天）
    from datetime import timedelta
    thirty_days_ago = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    done_tasks = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer)
    ).filter(
        ShootingTask.status == "done",
        ShootingTask.scheduled_date >= thirty_days_ago
    ).order_by(ShootingTask.scheduled_date.desc()).limit(50).all()

    templates = get_templates()
    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "photographers": photographers,
        "all_merchants": all_merchants,
        "merchant_photographers": merchant_photographers,
        "sel_pid": sel_pid,
        "shooting_merchants": shooting_merchants,
        "year": year, "month": month,
        "month_days": month_days,
        "task_map": task_map, "am_map": am_map, "pm_map": pm_map, "fd_list": fd_list,
        "all_tasks": tasks,  # 供特殊情况面板使用
        "blocked_map": blocked_map,
        "prev_month": prev_month, "next_month": next_month,
        "today": today, "month_name": f"{year}年{month}月",
        "selected_range": selected_range,
        "has_today": has_today,
        "last_date": last_date,
        "today_str": today_str,
        "tomorrow_str": tomorrow_str,
        "locked_tasks": locked_tasks,
        "all_ips": all_ips,
        "merchant_ips": merchant_ips,
        "done_tasks": done_tasks,
    })


# ==================== 排班生成 ====================

@router.post("/generate")
async def do_generate(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    today = date.today()

    import calendar as cal_mod
    sel_pid = int(form.get("photographer_id", 0))
    # 统一生成：从今往后 30 天（跨月合并为一份连续排班）
    from datetime import timedelta
    end_date = today + timedelta(days=30)
    range_type = form.get("range", "month")

    # 全局排班：取所有商家，含摄影师列表
    all_merchants = db.query(ShootingMerchant).filter(
        ShootingMerchant.status == "active",
        ShootingMerchant.need_shooting == 1  # 仅需要拍摄的商家
    ).all()
    if sel_pid > 0:
        linked = db.query(MerchantPhotographer.merchant_id).filter(
            MerchantPhotographer.photographer_id == sel_pid
        ).all()
        mids = {r[0] for r in linked}
        all_merchants = [m for m in all_merchants if m.id in mids]

    if not all_merchants:
        return RedirectResponse(url="/schedule", status_code=302)

    # 构建关联商家映射（同一公司不同地点共享配额）
    linked_map = {}  # parent_id -> [child_id, ...]
    for m in all_merchants:
        if m.linked_merchant_id:
            linked_map.setdefault(m.linked_merchant_id, []).append(m.id)
    child_ids = set()
    for children in linked_map.values():
        child_ids.update(children)

    merchant_data = []
    for m in all_merchants:
        if m.id in child_ids:
            continue  # 子商家跟随父商家一起处理

        # 该父商家自己的配额 = 总量 - 各子商家配额之和
        total_quota = m.monthly_quota or 25
        children_quota_sum = 0
        for child_id in linked_map.get(m.id, []):
            child_m = next((x for x in all_merchants if x.id == child_id), None)
            if child_m:
                children_quota_sum += child_m.monthly_quota or 0
        parent_quota = max(0, total_quota - children_quota_sum)

        # 添加父商家（总部）
        parent_done = db.query(ShootingTask).filter(
            ShootingTask.merchant_id == m.id,
            ShootingTask.status == "done"
        ).count()
        links = db.query(MerchantPhotographer).filter(
            MerchantPhotographer.merchant_id == m.id
        ).all()
        pids = [l.photographer_id for l in links]
        if sel_pid > 0 and sel_pid not in pids:
            pids.append(sel_pid)
        merchant_data.append({
            "id": m.id, "name": m.name, "district": m.district or "",
            "monthly_quota": parent_quota, "done_this_month": parent_done,
            "photographer_ids": pids
        })

        # 添加关联子商家（分厂），各自用自己的配额
        for child_id in linked_map.get(m.id, []):
            child_m = next((x for x in all_merchants if x.id == child_id), None)
            if not child_m:
                continue
            child_done = db.query(ShootingTask).filter(
                ShootingTask.merchant_id == child_id,
                ShootingTask.status == "done"
            ).count()
            child_links = db.query(MerchantPhotographer).filter(
                MerchantPhotographer.merchant_id == child_id
            ).all()
            child_pids = [l.photographer_id for l in child_links]
            if not child_pids:
                # 子商家未指定摄影师，继承父商家的摄影师
                child_pids = list(pids)
            if sel_pid > 0 and sel_pid not in child_pids:
                child_pids.append(sel_pid)
            merchant_data.append({
                "id": child_id, "name": child_m.name, "district": child_m.district or "",
                "monthly_quota": child_m.monthly_quota or 0, "done_this_month": child_done,
                "photographer_ids": child_pids
            })

    blocked_times = db.query(ShootingBlocked).all()
    blocked = {}
    for b in blocked_times:
        blocked.setdefault(b.blocked_date, {}).setdefault(b.merchant_id, []).append(b.time_slot)

    # 1. 今日之前的锁定任务自动标记为完成（留作历史记录）
    today_str = today.strftime("%Y-%m-%d")
    past_locked = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date < today_str,
        ShootingTask.locked == 1,
        ShootingTask.status == "scheduled"
    ).all()
    for pt in past_locked:
        pt.status = "done"
        pt.notes = (pt.notes or "") + " [过期自动归档]"

    # 2. 清空非锁定的 scheduled 任务（保留手动锁定的）
    end_str = end_date.strftime("%Y-%m-%d")
    del_q = db.query(ShootingTask).filter(
        ShootingTask.scheduled_date <= end_str,
        ShootingTask.status == "scheduled",
        ShootingTask.locked == 0
    )
    if sel_pid > 0:
        del_q = del_q.filter(ShootingTask.photographer_id == sel_pid)
    del_q.delete()

    # 3. 读取剩余锁定的任务，传给算法作为"已占用"
    remaining_locked = db.query(ShootingTask).filter(
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

    # 4. 构建 IP 映射（商家 → IP ID 列表），供排班算法轮转分配
    all_ips = db.query(ShootingIP).filter(ShootingIP.status == "active").all()
    merchant_ip_map = {}
    for ip in all_ips:
        merchant_ip_map.setdefault(ip.merchant_id, []).append(ip.id)

    # 5. 在锁定任务基础上生成排班（填空）
    result = generate_schedule(merchant_data, today.year, today.month,
                                start_day=today.day, blocked=blocked,
                                end_date=end_date.strftime("%Y-%m-%d"),
                                locked_tasks=locked_map,
                                merchant_ips=merchant_ip_map)

    # 6. 保存所有任务
    for day_plan in result:
        for task in day_plan.get("tasks", []):
            mid = task.get("merchant_id", 0)
            pg_id = task.get("photographer_id")
            ip_id = task.get("ip_id")
            if not mid:
                continue
            if sel_pid > 0 and pg_id != sel_pid:
                continue
            db.add(ShootingTask(
                merchant_id=mid, photographer_id=pg_id,
                ip_id=ip_id,
                scheduled_date=day_plan["date"],
                time_slot=task.get("time_slot", "morning"),
                video_count=task.get("video_count", 2),
                status="scheduled"
            ))

    db.commit()
    redir = f"/schedule?month={today.year}-{today.month:02d}"
    if sel_pid > 0:
        redir += f"&photographer_id={sel_pid}"
    return RedirectResponse(url=redir, status_code=302)


# ==================== 任务操作 ====================

def _redir(request: Request, path: str = "/schedule") -> str:
    """保留摄影师筛选参数"""
    pid = request.query_params.get("photographer_id", "")
    if pid:
        sep = "&" if "?" in path else "?"
        return f"{path}{sep}photographer_id={pid}"
    return path


@router.get("/task/{task_id}/done")
def mark_done(task_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if task:
        task.status = "done"
        db.commit()
    return RedirectResponse(url=_redir(request), status_code=302)


@router.get("/task/{task_id}/cancel")
def cancel_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if task:
        task.status = "cancelled"
        db.commit()
    return RedirectResponse(url=_redir(request), status_code=302)


@router.get("/task/{task_id}/delete")
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """彻底删除排班任务（客户或摄影师临时不能拍）"""
    from routes.merchants import check_auth
    check_auth(request)
    task = db.query(ShootingTask).filter(ShootingTask.id == task_id).first()
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse(url=_redir(request), status_code=302)


@router.post("/task/batch-cancel")
async def batch_cancel_tasks(request: Request, db: Session = Depends(get_db)):
    """批量取消排班任务，带原因备注"""
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
    task.locked = 1  # 手动移动 = 锁定
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.post("/task/new")
async def create_manual_task(request: Request, db: Session = Depends(get_db)):
    """手动添加排班任务（自动锁定）"""
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    ip_raw = form.get("ip_id", "0")
    # 防止重复：同商家+同日期+同时段已存在锁定任务则跳过
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
    return RedirectResponse(url="/schedule", status_code=302)  # 手动排班后自动重新生成


# ==================== 出镜IP CRUD ====================

@router.post("/ip/new")
async def add_or_edit_ip(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    ip_id = form.get("ip_id", "")
    if ip_id and ip_id.isdigit():
        # 编辑模式
        ip = db.query(ShootingIP).filter(ShootingIP.id == int(ip_id)).first()
        if ip:
            ip.name = form.get("name", ip.name)
            ip.role = form.get("role", ip.role)
            ip.merchant_id = int(form.get("merchant_id", ip.merchant_id))
            ip.monthly_quota = int(form.get("monthly_quota", str(ip.monthly_quota or 25)))
            ip.share_parent_quota = 1 if form.get("share_parent_quota") == "1" else 0
    else:
        # 新增模式 — 防止同名+同商家重复
        name = form.get("name", "").strip()
        mid = int(form.get("merchant_id", 0))
        exists = db.query(ShootingIP).filter(
            ShootingIP.merchant_id == mid,
            ShootingIP.name == name,
            ShootingIP.status == "active"
        ).first()
        if not exists and name:
            db.add(ShootingIP(
                merchant_id=mid, name=name,
                role=form.get("role", ""),
                monthly_quota=int(form.get("monthly_quota", "25")),
                share_parent_quota=1 if form.get("share_parent_quota") == "1" else 0,
            ))
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.post("/ip/{ip_id}/edit")
async def edit_ip(ip_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    ip = db.query(ShootingIP).filter(ShootingIP.id == ip_id).first()
    if ip:
        form = await request.form()
        ip.name = form.get("name", ip.name)
        ip.role = form.get("role", ip.role)
        ip.monthly_quota = int(form.get("monthly_quota", str(ip.monthly_quota or 25)))
        ip.share_parent_quota = 1 if form.get("share_parent_quota") == "1" else 0
        db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.get("/ip/{ip_id}/delete")
def delete_ip(ip_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    ip = db.query(ShootingIP).filter(ShootingIP.id == ip_id).first()
    if ip:
        ip.status = "inactive"
        db.commit()
    return RedirectResponse(url="/schedule", status_code=302)  # 取消后自动重新生成


# ==================== 屏蔽 ====================

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


@router.get("/clear-past")
def clear_past_tasks(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    today = date.today().strftime("%Y-%m-%d")
    db.query(ShootingTask).filter(
        ShootingTask.scheduled_date < today,
        ShootingTask.status == "scheduled"
    ).delete()
    db.commit()
    return RedirectResponse(url="/schedule", status_code=302)
