"""
短视频营销AI系统 — 主入口

启动: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from config import BASE_DIR
from database import init_db

app = FastAPI(title="短视频营销AI系统", version="0.1.0")

# 静态文件
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# 注册路由
from routes.auth import router as auth_router
from routes.merchants import router as merchants_router
from routes.scripts import router as scripts_router
from routes.videos import router as videos_router
from routes.douyin import router as douyin_router
from routes.cs import router as cs_router
from routes.settings import router as settings_router
from routes.dashboard import router as dashboard_router
from routes.schedule import router as schedule_router
from routes.schedule_crud import router as schedule_crud_router
from routes.schedule_tasks import router as schedule_tasks_router
from routes.schedule_scripts import router as schedule_scripts_router
from routes.advertising import router as advertising_router
from routes.short_videos import router as short_videos_router
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(merchants_router)
app.include_router(scripts_router)
app.include_router(videos_router)
app.include_router(advertising_router)
app.include_router(short_videos_router)
app.include_router(schedule_router)
app.include_router(schedule_crud_router)
app.include_router(schedule_tasks_router)
app.include_router(schedule_scripts_router)
app.include_router(douyin_router)
app.include_router(cs_router)
app.include_router(settings_router)


async def _weekly_refresh_loop():
    """后台任务：每 7 天执行一次商家画像批量刷新"""
    # 首次启动后等待 1 小时再开始，避免阻塞启动流程
    await asyncio.sleep(3600)
    while True:
        try:
            from scripts.weekly_refresh import run_weekly_refresh
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, run_weekly_refresh)
        except Exception as e:
            print(f"[WeeklyRefresh] Error: {e}")
        await asyncio.sleep(7 * 24 * 3600)


@app.on_event("startup")
def startup():
    """启动时初始化数据库"""
    init_db()
    print("[OK] Database initialized")
    db_path = BASE_DIR / "data" / "app.db"
    print(f"  DB file: {db_path}")
    # 启动每周商家画像刷新后台任务
    loop = asyncio.get_event_loop()
    loop.create_task(_weekly_refresh_loop())


@app.get("/")
def index(request: Request):
    """首页 → 有登录就跳商家页，没有就跳登录"""
    user_id = request.cookies.get("user_id")
    if user_id:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/auth/login")


@app.get("/health")
def health():
    return {"status": "ok", "service": "短视频营销AI系统"}
