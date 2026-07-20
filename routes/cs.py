"""客服路由 — 接收抖音Webhook + 人工兜底页面"""
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import CSMessage
from services.openclaw_service import process_message, OPENCLAW_MOCK, _get_api_key
from services.douyin_api import send_private_message, verify_webhook_signature

router = APIRouter(prefix="/cs", tags=["客服"])


def get_templates():
    from fastapi.templating import Jinja2Templates
    from config import BASE_DIR
    return Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/inbox")
def inbox(request: Request, db: Session = Depends(get_db)):
    """人工客服兜底页面 — 查看需要人工处理的消息"""
    from routes.merchants import check_auth
    check_auth(request)

    # 判断客服模式
    if OPENCLAW_MOCK:
        cs_mode = "mock"
    elif _get_api_key():
        cs_mode = "ai"
    else:
        cs_mode = "mock"

    # 从数据库读取待处理消息（支持渠道筛选）
    platform_filter = request.query_params.get("platform", "")
    q = db.query(CSMessage).filter(CSMessage.status == "pending")
    if platform_filter:
        q = q.filter(CSMessage.platform == platform_filter)
    db_messages = q.order_by(CSMessage.created_at.desc()).all()

    # 转成模板需要的格式
    messages = []
    for m in db_messages:
        try:
            confidence = float(m.confidence) if m.confidence else 0
        except (ValueError, TypeError):
            confidence = 0
        messages.append({
            "id": m.msg_id or str(m.id),
            "db_id": m.id,
            "platform": m.platform,
            "user_name": m.user_name,
            "user_id": m.user_id,
            "content": m.content,
            "ai_suggestion": m.ai_suggestion,
            "confidence": confidence,
            "intent": m.intent
        })

    templates = get_templates()
    from models import Merchant
    merchants = db.query(Merchant).filter(Merchant.status == "active").order_by(Merchant.name).all()
    return templates.TemplateResponse("cs_inbox.html", {
        "request": request,
        "messages": messages,
        "cs_mode": cs_mode,
        "merchants": merchants,
    })


def _save_message(db: Session, msg_id: str, platform: str, user_id: str,
                  user_name: str, content: str, result: dict, status: str = "pending"):
    """保存消息到数据库"""
    msg = CSMessage(
        msg_id=msg_id,
        platform=platform,
        user_id=user_id,
        user_name=user_name,
        content=content,
        ai_suggestion=result.get("reply", ""),
        confidence=str(result.get("confidence", 0)),
        intent=result.get("intent", ""),
        status=status
    )
    db.add(msg)
    db.commit()


@router.post("/webhook/douyin")
async def douyin_webhook(request: Request, db: Session = Depends(get_db)):
    """抖音私信 Webhook 接收端点"""
    body = await request.body()
    signature = request.headers.get("douyin-signature", "")

    if signature and not verify_webhook_signature(body, signature):
        return JSONResponse({"error": "签名验证失败"}, status_code=403)

    try:
        payload = json.loads(body)
    except Exception:
        return JSONResponse({"error": "无效的JSON"}, status_code=400)

    user_id = payload.get("from_user_id", "unknown")
    user_name = payload.get("from_user_name", "用户")
    content = payload.get("content", "")

    result = process_message(
        platform="douyin",
        user_id=user_id,
        user_name=user_name,
        content=content
    )

    if result.get("needs_human"):
        # 低置信度 → 落库转人工
        _save_message(db, payload.get("msg_id", ""), "douyin",
                      user_id, user_name, content, result, "pending")
    else:
        # 高置信度 → 自动回复
        from models import DouyinAccount
        account = db.query(DouyinAccount).filter(
            DouyinAccount.status == "active"
        ).first()
        if account and account.access_token:
            try:
                send_private_message(
                    access_token=account.access_token,
                    to_user_id=user_id,
                    content=result["reply"]
                )
                # 自动回复成功，落库标记已回复
                _save_message(db, payload.get("msg_id", ""), "douyin",
                              user_id, user_name, content, result, "replied")
            except Exception:
                _save_message(db, payload.get("msg_id", ""), "douyin",
                              user_id, user_name, content, result, "pending")
        else:
            _save_message(db, payload.get("msg_id", ""), "douyin",
                          user_id, user_name, content, result, "pending")

    return JSONResponse({"status": "ok"})


@router.post("/webhook/wechat")
async def wechat_webhook(request: Request, db: Session = Depends(get_db)):
    """微信客服消息 Webhook 接收端点"""
    try:
        body = await request.body()
        payload = json.loads(body)
    except Exception:
        return JSONResponse({"error": "无效的JSON"}, status_code=400)

    user_id = payload.get("from_user_id", "unknown")
    user_name = payload.get("from_user_name", "用户")
    content = payload.get("content", "")

    result = process_message(
        platform="wechat",
        user_id=user_id,
        user_name=user_name,
        content=content
    )

    # 微信客服：统一落库转人工（微信需要人工跟进）
    _save_message(db, payload.get("msg_id", ""), "wechat",
                  user_id, user_name, content, result, "pending")

    return JSONResponse({"status": "ok"})


@router.post("/test-message")
async def test_message(request: Request, db: Session = Depends(get_db)):
    """模拟测试：发送一条消息给 AI，返回回复（落库保存）"""
    from routes.merchants import check_auth
    check_auth(request)
    form = await request.form()
    content = form.get("content", "").strip()
    if not content:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)

    try:
        result = process_message(
            platform="test",
            user_id="test_user",
            user_name="测试用户",
            content=content
        )
        # 高置信度自动回复的不进待处理列表
        status = "pending" if result.get("needs_human") else "replied"
        _save_message(db, "", "test", "test_user", "测试用户", content, result, status)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/inbox/{msg_id}/reply")
async def manual_reply(msg_id: str, request: Request, db: Session = Depends(get_db)):
    """人工发送回复"""
    from routes.merchants import check_auth
    check_auth(request)

    form = await request.form()
    reply_text = form.get("reply_text", "")

    # 从数据库找到这条消息
    msg = db.query(CSMessage).filter(
        (CSMessage.msg_id == msg_id) | (CSMessage.id == int(msg_id) if msg_id.isdigit() else 0)
    ).first()

    if msg:
        from models import DouyinAccount
        account = db.query(DouyinAccount).filter(
            DouyinAccount.status == "active"
        ).first()
        if account and account.access_token:
            try:
                send_private_message(account.access_token, msg.user_id, reply_text)
            except Exception as e:
                return {"error": str(e)}

        msg.status = "replied"
        db.commit()

    return RedirectResponse(url="/cs/inbox", status_code=302)
