"""拍摄文案路由 — 每个排班任务配2条文案，手动录入或AI生成"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import ShootingTask, ShootingScript, ShootingMerchant, ShootingIP
from routes.schedule_utils import redirect_back

router = APIRouter(prefix="/schedule", tags=["文案"])


def get_scripts_data(db: Session, today_str: str, days: int = 30):
    """获取近期排班任务及关联文案"""
    end_str = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
    tasks = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.photographer),
        joinedload(ShootingTask.ip)
    ).filter(
        ShootingTask.scheduled_date >= today_str,
        ShootingTask.scheduled_date <= end_str,
        ShootingTask.status == "scheduled"
    ).order_by(ShootingTask.scheduled_date).all()

    # 查询已有文案
    task_ids = [t.id for t in tasks]
    scripts_map = {}
    if task_ids:
        scripts = db.query(ShootingScript).filter(
            ShootingScript.task_id.in_(task_ids)
        ).order_by(ShootingScript.id).all()
        for s in scripts:
            scripts_map.setdefault(s.task_id, []).append(s)

    return tasks, scripts_map


@router.get("/scripts")
def scripts_page(request: Request, db: Session = Depends(get_db)):
    """文案分页 — 重定向到排班主页并自动打开文案tab"""
    from routes.merchants import check_auth
    check_auth(request)
    return RedirectResponse(url="/schedule?tab=scripts", status_code=302)


@router.post("/script/new")
async def create_script(request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    task_id = int(form.get("task_id", 0))
    topic = form.get("topic", "").strip()
    content = form.get("content", "").strip()
    if task_id:
        db.add(ShootingScript(
            task_id=task_id,
            topic=topic,
            content=content,
            source="manual",
        ))
        db.commit()
    return RedirectResponse(url="/schedule?tab=scripts", status_code=302)


@router.post("/script/ai-generate")
async def ai_generate_script(request: Request, db: Session = Depends(get_db)):
    """AI生成文案 — 基于商家信息、IP画像、摄影师风格"""
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    task_id = int(form.get("task_id", 0))
    count = int(form.get("count", "2"))
    topic = form.get("topic", "").strip()

    task = db.query(ShootingTask).options(
        joinedload(ShootingTask.shooting_merchant),
        joinedload(ShootingTask.ip)
    ).filter(ShootingTask.id == task_id).first()

    if not task:
        return RedirectResponse(url="/schedule?tab=scripts", status_code=302)

    merchant = task.shooting_merchant
    ip_person = task.ip

    # 构建AI提示词
    prompt_parts = [f"为以下商家拍摄短视频写{count}条口播文案，每条50-100字，口语化、有吸引力。"]
    if topic:
        prompt_parts.append(f"⚠️ 本次拍摄主题/选题：{topic}。文案必须紧扣此主题。")
    if merchant:
        prompt_parts.append(f"商家：{merchant.name}，{merchant.district or ''}，主营{getattr(merchant, 'products_dishes', '') or '餐饮'}")
    if ip_person:
        profile = []
        if ip_person.personality:
            profile.append(f"人设：{ip_person.personality}")
        if ip_person.speaking_style:
            profile.append(f"风格：{ip_person.speaking_style}")
        if ip_person.specialties:
            profile.append(f"擅长：{ip_person.specialties}")
        if profile:
            prompt_parts.append(f"出镜人物「{ip_person.name}」" + "，".join(profile))
    prompt_parts.append("格式：每行一条文案，不要编号。")

    prompt = "\n".join(prompt_parts)

    # 调用AI服务
    scripts_generated = []
    try:
        from services.ai_script import call_ai
        result = call_ai(prompt, system="你是一个专业的短视频口播文案撰写专家。", temperature=0.8)
        if result:
            scripts_generated = [s.strip() for s in result.strip().split("\n") if s.strip() and len(s.strip()) > 10]
    except Exception:
        pass

    # 如果AI不可用，生成模板文案
    if not scripts_generated:
        ip_name = ip_person.name if ip_person else "主播"
        biz_name = merchant.name if merchant else "本店"
        district = merchant.district if merchant else ""
        if topic:
            templates = [
                f"📢 {topic}｜{biz_name}新品实测，{ip_name}带你深度体验",
                f"🔥 {topic}到底值不值？{ip_name}在{biz_name}亲测告诉你",
            ]
        else:
            templates = [
                f"📍{district}{biz_name}又来啦！今天{ip_name}带你看点不一样的～",
                f"💡{biz_name}的隐藏款被我发现了！{ip_name}亲测推荐",
            ]
        scripts_generated = templates[:count]

    for s in scripts_generated:
        db.add(ShootingScript(
            task_id=task_id,
            topic="",
            content=s,
            source="ai",
        ))

    db.commit()
    return RedirectResponse(url="/schedule?tab=scripts", status_code=302)


@router.get("/script/{script_id}/delete")
def delete_script(script_id: int, request: Request, db: Session = Depends(get_db)):
    from routes.merchants import check_auth
    check_auth(request)
    s = db.query(ShootingScript).filter(ShootingScript.id == script_id).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse(url="/schedule?tab=scripts", status_code=302)
