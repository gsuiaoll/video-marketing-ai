"""排班 CRUD — 摄影师 + 拍摄商家 + 出镜IP 增删改"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import ShootingMerchant, ShootingTask, ShootingBlocked, ShootingPhotographer, MerchantPhotographer, ShootingIP
from routes.schedule_utils import redirect_back

router = APIRouter(prefix="/schedule", tags=["排班CRUD"])


# ==================== 摄影师 CRUD ====================

@router.post("/photographer/new")
async def add_photographer(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    db.add(ShootingPhotographer(
        name=form.get("name", ""),
        phone=form.get("phone", ""),
        role=form.get("role", "fulltime"),
        days_off_per_week=int(form.get("days_off_per_week", "1")),
        max_slots_per_day=int(form.get("max_slots_per_day", "2")),
        preferences=form.get("preferences", ""),
        auto_schedule=1 if form.get("auto_schedule", "1") == "1" else 0,
    ))
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
        p.role = form.get("role", p.role)
        p.days_off_per_week = int(form.get("days_off_per_week", str(p.days_off_per_week or 1)))
        p.max_slots_per_day = int(form.get("max_slots_per_day", str(p.max_slots_per_day or 2)))
        p.preferences = form.get("preferences", p.preferences)
        p.auto_schedule = 1 if form.get("auto_schedule", "1") == "1" else 0
        db.commit()
    return RedirectResponse(url="/schedule", status_code=302)


@router.get("/photographer/{pid}/delete")
def delete_photographer(pid: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
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

    # 4. 清空该摄影师的排班任务 + 删除
    db.query(ShootingTask).filter(ShootingTask.photographer_id == pid).delete()
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
        monthly_quota=int(form.get("monthly_quota", "25")),
        need_shooting=1 if form.get("need_shooting", "1") == "1" else 0,
        auto_schedule=1 if form.get("auto_schedule", "1") == "1" else 0,
    )
    linked_raw = form.get("linked_merchant_id", "")
    if linked_raw:
        m.linked_merchant_id = int(linked_raw)
    main_raw = form.get("main_merchant_id", "")
    if main_raw:
        m.main_merchant_id = int(main_raw)
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
    m.auto_schedule = 1 if form.get("auto_schedule", "1") == "1" else 0
    linked_raw = form.get("linked_merchant_id", "")
    m.linked_merchant_id = int(linked_raw) if linked_raw else None
    main_raw = form.get("main_merchant_id", "")
    m.main_merchant_id = int(main_raw) if main_raw else None
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
    return RedirectResponse(url=redirect_back(request), status_code=302)


# ==================== 出镜IP CRUD ====================

@router.post("/ip/new")
async def create_or_update_ip(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    ip_id = form.get("id", "")
    if ip_id and ip_id.isdigit():
        # 编辑模式
        ip = db.query(ShootingIP).filter(ShootingIP.id == int(ip_id)).first()
        if ip:
            ip.name = form.get("name", ip.name)
            ip.role = form.get("role", ip.role)
            ip.merchant_id = int(form.get("merchant_id", str(ip.merchant_id)))
            ip.monthly_quota = int(form.get("monthly_quota", str(ip.monthly_quota or 25)))
            ip.share_parent_quota = 1 if form.get("share_parent_quota") == "1" else 0
            ip.auto_schedule = 1 if form.get("auto_schedule", "1") == "1" else 0
            ip.gender = form.get("gender", ip.gender)
            ip.age_range = form.get("age_range", ip.age_range)
            ip.appearance = form.get("appearance", ip.appearance)
            ip.personality = form.get("personality", ip.personality)
            ip.speaking_style = form.get("speaking_style", ip.speaking_style)
            ip.specialties = form.get("specialties", ip.specialties)
            ip.preferred_products = form.get("preferred_products", ip.preferred_products)
            ip.shooting_notes = form.get("shooting_notes", ip.shooting_notes)
            parent_raw = form.get("parent_ip_id", "")
            ip.parent_ip_id = int(parent_raw) if parent_raw else None
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
                gender=form.get("gender", ""),
                age_range=form.get("age_range", ""),
                appearance=form.get("appearance", ""),
                personality=form.get("personality", ""),
                speaking_style=form.get("speaking_style", ""),
                specialties=form.get("specialties", ""),
                preferred_products=form.get("preferred_products", ""),
                shooting_notes=form.get("shooting_notes", ""),
                monthly_quota=int(form.get("monthly_quota", "25")),
                share_parent_quota=1 if form.get("share_parent_quota") == "1" else 0,
                auto_schedule=1 if form.get("auto_schedule", "1") == "1" else 0,
            ))
            db.flush()  # 先写入DB，否则下面查不到
            # 设置主IP层级
            parent_raw = form.get("parent_ip_id", "")
            if parent_raw:
                ip_new = db.query(ShootingIP).filter(
                    ShootingIP.merchant_id == mid, ShootingIP.name == name,
                    ShootingIP.status == "active"
                ).first()
                if ip_new:
                    ip_new.parent_ip_id = int(parent_raw)
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
        ip.merchant_id = int(form.get("merchant_id", str(ip.merchant_id)))
        ip.monthly_quota = int(form.get("monthly_quota", str(ip.monthly_quota or 25)))
        ip.share_parent_quota = 1 if form.get("share_parent_quota") == "1" else 0
        ip.auto_schedule = 1 if form.get("auto_schedule", "1") == "1" else 0
        ip.gender = form.get("gender", ip.gender)
        ip.age_range = form.get("age_range", ip.age_range)
        ip.appearance = form.get("appearance", ip.appearance)
        ip.personality = form.get("personality", ip.personality)
        ip.speaking_style = form.get("speaking_style", ip.speaking_style)
        ip.specialties = form.get("specialties", ip.specialties)
        ip.preferred_products = form.get("preferred_products", ip.preferred_products)
        ip.shooting_notes = form.get("shooting_notes", ip.shooting_notes)
        parent_raw = form.get("parent_ip_id", "")
        ip.parent_ip_id = int(parent_raw) if parent_raw else None
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
    return RedirectResponse(url="/schedule", status_code=302)
