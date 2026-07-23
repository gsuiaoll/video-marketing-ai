"""每周自动刷新商家画像 — 定时任务

由 main.py 后台 asyncio 任务每 7 天调度一次。
也可独立运行: python scripts/weekly_refresh.py
"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path，确保独立运行时也能导入项目模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SessionLocal
from models import Merchant
from services.ai_script import scheduled_merchant_refresh
from datetime import datetime


def run_weekly_refresh():
    """遍历所有 need_shooting=1 的活跃商家，用 AI 搜索最新动态并更新 recent_updates 字段"""
    db = SessionLocal()
    try:
        merchants = db.query(Merchant).filter(
            Merchant.need_shooting == 1,
            Merchant.status == 'active'
        ).all()

        if not merchants:
            print("[WeeklyRefresh] 没有需要刷新的商家")
            return 0

        print(f"[WeeklyRefresh] 开始刷新 {len(merchants)} 家商家画像...")
        updated = 0
        for m in merchants:
            try:
                result = scheduled_merchant_refresh(
                    m.name,
                    district=m.district or '',
                    industry=m.industry or ''
                )
                if result and '近期情况' in result:
                    m.recent_updates = result['近期情况']
                    db.commit()
                    updated += 1
                    print(f"  [OK] {m.name}")
                else:
                    print(f"  [SKIP] {m.name}: AI 无返回")
            except Exception as e:
                db.rollback()
                print(f"  [ERR] {m.name}: {e}")

        print(f"\n{'='*50}")
        print(f"[WeeklyRefresh] 本轮完成: {updated}/{len(merchants)} 家商家画像已更新")
        return updated
    finally:
        db.close()


if __name__ == '__main__':
    run_weekly_refresh()
