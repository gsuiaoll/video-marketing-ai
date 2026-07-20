from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表 + 迁移旧表 + 默认管理员账号"""
    import bcrypt
    from models import User
    from sqlalchemy import text

    # 创建新表
    Base.metadata.create_all(bind=engine)

    # 迁移旧表（SQLite 不支持 create_all 自动加列）
    db = SessionLocal()
    migrations = [
        "ALTER TABLE merchants ADD COLUMN address TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN district TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN monthly_quota INTEGER DEFAULT 25",
        "ALTER TABLE shooting_merchants ADD COLUMN linked_merchant_id INTEGER",
        "ALTER TABLE merchants ADD COLUMN products_dishes TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN recent_updates TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN business_model TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN service_features TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN target_customers TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN competitive_advantages TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN promotions TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN shooting_notes TEXT DEFAULT ''",
        "ALTER TABLE merchants ADD COLUMN linked_merchant_id INTEGER",
        # 巨量引擎广告账户表（create_all 会自动创建，但以防版本不一致）
        "ALTER TABLE videos ADD COLUMN description TEXT DEFAULT ''",
        "ALTER TABLE videos ADD COLUMN tags TEXT DEFAULT ''",
        "ALTER TABLE videos ADD COLUMN publish_status TEXT DEFAULT ''",
        "ALTER TABLE shooting_merchants ADD COLUMN need_shooting INTEGER DEFAULT 1",
        "ALTER TABLE merchants ADD COLUMN need_shooting INTEGER DEFAULT 1",
        "ALTER TABLE shooting_tasks ADD COLUMN locked INTEGER DEFAULT 0",
        "ALTER TABLE shooting_tasks ADD COLUMN ip_id INTEGER",
    ]
    for sql in migrations:
        try:
            db.execute(text(sql))
            db.commit()
        except Exception:
            db.rollback()

    # 创建默认管理员（如果不存在）
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(
            username="admin",
            password_hash=bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode(),
            role="admin"
        ))
        db.commit()
    db.close()
