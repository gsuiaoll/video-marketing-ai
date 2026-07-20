from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="staff")  # admin | staff
    created_at = Column(TIMESTAMP, default=datetime.utcnow)


class Merchant(Base):
    __tablename__ = "merchants"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    industry = Column(String)
    contact_name = Column(String)
    contact_phone = Column(String)
    address = Column(String)
    district = Column(String)
    monthly_quota = Column(Integer, default=25)
    linked_merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=True)  # 总公司-分厂关联
    need_shooting = Column(Integer, default=1)  # 1=需要拍摄，0=不需要
    # 商家画像
    products_dishes = Column(Text, default="")
    recent_updates = Column(Text, default="")
    business_model = Column(Text, default="")
    service_features = Column(Text, default="")
    target_customers = Column(Text, default="")
    competitive_advantages = Column(Text, default="")
    promotions = Column(Text, default="")
    shooting_notes = Column(Text, default="")
    status = Column(String, default="active")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    douyin_accounts = relationship("DouyinAccount", back_populates="merchant")
    ad_accounts = relationship("OceanEngineAccount", back_populates="merchant")
    redbook_accounts = relationship("RedBookAccount", back_populates="merchant")
    adq_accounts = relationship("ADQAccount", back_populates="merchant")
    scripts = relationship("Script", back_populates="merchant")
    videos = relationship("Video", back_populates="merchant")


class ShootingPhotographer(Base):
    """摄影师"""
    __tablename__ = "shooting_photographers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    phone = Column(String)
    status = Column(String, default="active")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    merchant_links = relationship("MerchantPhotographer", back_populates="photographer")
    tasks = relationship("ShootingTask", back_populates="photographer")


class ShootingMerchant(Base):
    """拍摄商家 — 独立于主商家表，专门用于排班"""
    __tablename__ = "shooting_merchants"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    district = Column(String)
    address = Column(String)
    contact_name = Column(String)
    contact_phone = Column(String)
    monthly_quota = Column(Integer, default=25)
    linked_merchant_id = Column(Integer, ForeignKey("shooting_merchants.id"), nullable=True)  # 同一公司不同地点
    need_shooting = Column(Integer, default=1)  # 1=需要拍摄，0=不需要
    status = Column(String, default="active")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    shooting_tasks = relationship("ShootingTask", back_populates="shooting_merchant")
    blocked_times = relationship("ShootingBlocked", back_populates="shooting_merchant")
    photographer_links = relationship("MerchantPhotographer", back_populates="merchant")
    ips = relationship("ShootingIP", back_populates="merchant")


class MerchantPhotographer(Base):
    """商家↔摄影师 多对多关联"""
    __tablename__ = "merchant_photographers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("shooting_merchants.id"), nullable=False)
    photographer_id = Column(Integer, ForeignKey("shooting_photographers.id"), nullable=False)

    merchant = relationship("ShootingMerchant", back_populates="photographer_links")
    photographer = relationship("ShootingPhotographer", back_populates="merchant_links")


class OceanEngineAccount(Base):
    """巨量引擎广告账户 — 每个商家可绑定多个投放账户"""
    __tablename__ = "oceanengine_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"))
    advertiser_id = Column(String, nullable=False)  # 巨量引擎广告主 ID
    account_name = Column(String)                    # 账户备注名
    access_token = Column(Text)
    refresh_token = Column(Text)
    status = Column(String, default="active")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="ad_accounts")


class RedBookAccount(Base):
    """小红书账号 — 每个商家可绑定多个"""
    __tablename__ = "redbook_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"))
    account_name = Column(String)
    user_id = Column(String)
    access_token = Column(Text)
    refresh_token = Column(Text)
    status = Column(String, default="active")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="redbook_accounts")


class ADQAccount(Base):
    """腾讯广告 ADQ 账号 — 每个商家可绑定多个"""
    __tablename__ = "adq_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"))
    account_name = Column(String)
    advertiser_id = Column(String, nullable=False)
    access_token = Column(Text)
    refresh_token = Column(Text)
    status = Column(String, default="active")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="adq_accounts")


class DouyinAccount(Base):
    __tablename__ = "douyin_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"))
    account_name = Column(String)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expires_at = Column(TIMESTAMP)
    status = Column(String, default="active")

    merchant = relationship("Merchant", back_populates="douyin_accounts")


class Script(Base):
    __tablename__ = "scripts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"))
    title = Column(String, nullable=False)
    platform = Column(String)          # douyin | tiktok | wechat
    content = Column(Text, nullable=False)  # JSON: 结构化脚本
    ai_generated = Column(Integer, default=0)
    is_starred = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="scripts")


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"))
    title = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    platform = Column(String)
    description = Column(Text, default="")
    tags = Column(String, default="")           # 逗号分隔标签
    publish_status = Column(String, default="")  # 逗号分隔: 抖音,视频号 (空=未发布)
    status = Column(String, default="ready")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    merchant = relationship("Merchant", back_populates="videos")


class ShootingTask(Base):
    """拍摄排班任务"""
    __tablename__ = "shooting_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("shooting_merchants.id"))
    photographer_id = Column(Integer, ForeignKey("shooting_photographers.id"), nullable=True)
    ip_id = Column(Integer, ForeignKey("shooting_ips.id"), nullable=True)  # 出镜IP人物
    scheduled_date = Column(String)
    time_slot = Column(String, default="morning")
    video_count = Column(Integer, default=2)
    status = Column(String, default="scheduled")
    locked = Column(Integer, default=0)  # 1=手动锁定，生成时不覆盖
    notes = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    shooting_merchant = relationship("ShootingMerchant", back_populates="shooting_tasks")
    photographer = relationship("ShootingPhotographer", back_populates="tasks")
    ip = relationship("ShootingIP", back_populates="tasks")


class ShootingIP(Base):
    """出镜IP人物 — 商家旗下的出境拍摄人物，各可有独立配额"""
    __tablename__ = "shooting_ips"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("shooting_merchants.id"))
    name = Column(String, nullable=False)       # IP人物名称
    role = Column(String, default="")            # 角色（老板/员工/达人）
    monthly_quota = Column(Integer, default=25)  # 单人月配额，0=共享总公司配额
    share_parent_quota = Column(Integer, default=0)  # 1=共享总公司配额
    status = Column(String, default="active")
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    merchant = relationship("ShootingMerchant", back_populates="ips")
    tasks = relationship("ShootingTask", back_populates="ip")


class ShootingBlocked(Base):
    """商家屏蔽时间段 — 某天某个时段该商家不能排班"""
    __tablename__ = "shooting_blocked"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("shooting_merchants.id"))
    blocked_date = Column(String)              # "2026-08-15"
    time_slot = Column(String, default="morning")  # morning | afternoon | full_day
    reason = Column(String, default="")

    shooting_merchant = relationship("ShootingMerchant", back_populates="blocked_times")


class DouyinVideo(Base):
    """抖音视频数据 — 通过 Webhook 同步的视频信息"""
    __tablename__ = "douyin_videos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=True)
    douyin_account_id = Column(Integer, ForeignKey("douyin_accounts.id"), nullable=True)
    video_id = Column(String)            # 抖音视频ID
    title = Column(String)               # 视频标题
    cover_url = Column(String)           # 封面图
    share_url = Column(String)           # 分享链接
    play_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    share_count = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    status = Column(String, default="synced")  # synced / published / failed
    raw_data = Column(Text)              # 原始 JSON 数据
    created_at = Column(TIMESTAMP, default=datetime.utcnow)


class WebhookEvent(Base):
    """Webhook 事件日志 — 记录所有抖音推送的事件"""
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event = Column(String)          # 事件类型
    from_user_id = Column(String)   # 发起用户 open_id
    to_user_id = Column(String)     # 目标用户 open_id
    client_key = Column(String)     # 应用 client_key
    content = Column(Text)          # 事件内容 JSON
    raw_body = Column(Text)         # 原始请求体
    status = Column(String, default="received")  # received / processed / error
    created_at = Column(TIMESTAMP, default=datetime.utcnow)


class CSMessage(Base):
    """客服消息 — 持久化存储，刷新不丢失"""
    __tablename__ = "cs_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    msg_id = Column(String)           # 抖音消息ID
    platform = Column(String)         # douyin | wechat | test
    user_id = Column(String)
    user_name = Column(String)
    content = Column(Text)
    ai_suggestion = Column(Text)      # AI建议回复
    confidence = Column(String)       # 置信度 (float as string for simplicity)
    intent = Column(String)           # 意图类别
    status = Column(String, default="pending")  # pending | replied
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
