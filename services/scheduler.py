"""拍摄排班算法 — 全局排班，每天可有多组上下午（取决于摄影师数量）"""
import calendar
from datetime import date

FAR_DISTRICTS = {"清远", "从化", "花都", "增城", "南沙", "佛山", "东莞", "中山", "惠州"}
MIN_MERCHANT_GAP = 1  # 同一商家两次拍摄之间最少间隔天数（0=可连拍）


def generate_schedule(merchants: list[dict], year: int, month: int,
                      start_day: int = 1, num_days: int | None = None,
                      blocked: dict | None = None,
                      end_date: str | None = None,
                      locked_tasks: dict | None = None,
                      merchant_ips: dict | None = None) -> list[dict]:
    """
    全局排班。
    locked_tasks: {date: [{merchant_id, photographer_id, time_slot}, ...]} 已锁定的任务
    merchant_ips: {merchant_id: [ip_id, ...]} 每个商家的出镜IP列表，轮转分配
    """
    if blocked is None:
        blocked = {}
    if locked_tasks is None:
        locked_tasks = {}
    if merchant_ips is None:
        merchant_ips = {}

    # IP 轮转计数器：每个商家独立轮转
    ip_round_robin = {}

    from datetime import date as dt, timedelta
    if end_date:
        # 跨月模式：生成从 start 到 end_date 的连续日期列表
        end_dt = dt.fromisoformat(end_date)
        all_days = []
        cur = dt(year, month, start_day)
        while cur <= end_dt:
            all_days.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        days_in_month = calendar.monthrange(year, month)[1]
    else:
        days_in_month = calendar.monthrange(year, month)[1]
        end_day = days_in_month + 1
        if num_days is not None:
            end_day = min(start_day + num_days, days_in_month + 1)
        all_days = [f"{year}-{month:02d}-{d:02d}" for d in range(start_day, end_day)]
    total_days = len(all_days)

    # ── 构建商家需求 ──
    merchant_list = []
    for m in merchants:
        remaining = m.get("monthly_quota", 25) - m.get("done_this_month", 0)
        if remaining <= 0:
            continue
        is_far = m.get("district", "") in FAR_DISTRICTS
        # 远途：全天拍摄产出 4 条/趟；近途：半天拍摄产出 2 条/趟
        if is_far:
            trips_needed = remaining // 4
        else:
            trips_needed = remaining // 2
        if trips_needed <= 0:
            continue  # 配额为 0，跳过
        pids = m.get("photographer_ids", [])
        merchant_list.append({
            "id": m["id"], "name": m["name"],
            "is_far": is_far, "trips_needed": trips_needed,
            "photographer_ids": pids, "pg_idx": 0,
        })

    if not merchant_list:
        return []

    # ── 所有摄影师（用于计算每天容量）──
    all_pg_ids = set()
    for m in merchant_list:
        for pid in m["photographer_ids"]:
            all_pg_ids.add(pid)
    total_pgs = len(all_pg_ids)

    # ── 展开远途/近途 slot（交替穿插，公平分配）──
    far = [m for m in merchant_list if m["is_far"]]
    near = [m for m in merchant_list if not m["is_far"]]

    far_slots = []
    if far:
        max_far = max(m["trips_needed"] for m in far)
        for rnd in range(max_far):
            for m in far:
                if rnd < m["trips_needed"]:
                    far_slots.append(m)

    near_slots = []
    if near:
        max_near = max(m["trips_needed"] for m in near)
        for rnd in range(max_near):
            for m in near:
                if rnd < m["trips_needed"]:
                    near_slots.append(m)

    def pick_ip(mid):
        """轮转选择该商家的出镜IP"""
        ips = merchant_ips.get(mid, [])
        if not ips:
            return None
        idx = ip_round_robin.get(mid, 0) % len(ips)
        ip_round_robin[mid] = idx + 1
        return ips[idx]

    def is_blocked(mid, date_str, slot):
        day_blocks = blocked.get(date_str, {})
        blocked_slots = day_blocks.get(mid, [])
        return slot in blocked_slots or "full_day" in blocked_slots

    def pick_photographer(m):
        """轮转选择摄影师"""
        pids = m["photographer_ids"]
        if not pids:
            return None
        idx = m["pg_idx"] % len(pids)
        m["pg_idx"] += 1
        return pids[idx]

    # ── 远途间隔排 ──
    far_spacing = max(1, total_days // max(1, len(far_slots))) if far_slots else 0
    far_positions = set()
    for i in range(len(far_slots)):
        pos = i * far_spacing
        if pos < total_days:
            far_positions.add(pos)

    # ── 近途排班日（均匀分散到整月，避免连续拍摄）──
    near_per_day_max = total_pgs * 2  # 每天最大近途 slot 数
    near_total = len(near_slots)
    if near_total > 0 and total_pgs > 0:
        # 预留远途日容量减半的缓冲（远途日只 ~2 slot vs 正常 ~4 slot）
        near_days_needed = max(1, (near_total + near_per_day_max - 1) // near_per_day_max)
        far_day_count = len(far_positions)
        # 每个远途日损失 2 slot，需额外 ceil(2*far_days / near_per_day_max) 天
        extra_days = (far_day_count * 2 + near_per_day_max - 1) // near_per_day_max
        near_days_needed += extra_days
        near_day_spacing = max(1, total_days // max(1, near_days_needed))
        # 确保最小 2 天间隔（仅当有足够空间时）
        if near_day_spacing < 2 and near_days_needed <= total_days // 2:
            near_day_spacing = 2
        near_day_positions = set()
        for i in range(near_days_needed):
            pos = i * near_day_spacing
            if pos < total_days:
                near_day_positions.add(pos)
    else:
        near_day_positions = set()

    # ── 填日历 ──
    schedule = []
    fi = 0
    near_consumed = set()  # 已消费的 near_slots 索引
    last_merchant_day = {}  # {merchant_id: day_idx} 上次排班日，用于强制最小间隔

    def can_schedule_merchant(mid, day_idx):
        """检查该商家是否满足最小间隔约束"""
        last = last_merchant_day.get(mid, -999)
        return (day_idx - last) > MIN_MERCHANT_GAP

    for day_idx in range(total_days):
        date = all_days[day_idx]
        tasks_today = []
        booked_merchants = set()       # 当天已排的商家
        pg_on_far = set()              # 当天在远途的摄影师
        pg_used_am = set()             # 上午已用的摄影师
        pg_used_pm = set()             # 下午已用的摄影师

        # 锁定任务占位：标记已被手动锁定的商家/摄影师/时段
        for lt in locked_tasks.get(date, []):
            booked_merchants.add(lt["merchant_id"])
            if lt["time_slot"] == "full_day":
                pg_on_far.add(lt["photographer_id"])
            elif lt["time_slot"] == "morning":
                pg_used_am.add(lt["photographer_id"])
            elif lt["time_slot"] == "afternoon":
                pg_used_pm.add(lt["photographer_id"])

        # ── 远途（每个远途任务占一个摄影师一整天）──
        while fi < len(far_slots) and day_idx in far_positions:
            fm = far_slots[fi]
            assigned = False
            if not is_blocked(fm["id"], date, "full_day") and fm["id"] not in booked_merchants and can_schedule_merchant(fm["id"], day_idx):
                pg = pick_photographer(fm)
                if pg is not None and pg not in pg_on_far and pg not in pg_used_am and pg not in pg_used_pm:
                    tasks_today.append({
                        "merchant_name": fm["name"], "merchant_id": fm["id"],
                        "photographer_id": pg,
                        "time_slot": "full_day", "video_count": 4,
                        "ip_id": pick_ip(fm["id"]),
                    })
                    booked_merchants.add(fm["id"])
                    pg_on_far.add(pg)
                    last_merchant_day[fm["id"]] = day_idx
                    assigned = True
            if assigned:
                fi += 1
            break  # 每天至多一个远途

        # ── 近途：仅在近途日排 ──
        available_pgs = [pid for pid in all_pg_ids
                         if pid not in pg_on_far]

        if day_idx not in near_day_positions:
            available_pgs = []  # 跳过该天近途排班

        def _find_near_slot(exclude_ids, slot_type):
            """找一个可排的近途商家索引。必须满足严格间隔，宁愿空着也不连排。"""
            for idx in range(len(near_slots)):
                if idx in near_consumed:
                    continue
                m = near_slots[idx]
                if m["id"] in exclude_ids:
                    continue
                if pg not in m["photographer_ids"]:
                    continue
                if is_blocked(m["id"], date, slot_type):
                    continue
                if can_schedule_merchant(m["id"], day_idx):
                    return idx
            return None  # 没有满足间隔的，留空

        for pg in available_pgs:
            # 跳过已被锁定占用的时段
            if pg in pg_used_am and pg in pg_used_pm:
                continue  # 该摄影师上下午都被占了

            # — 找上午商家 —
            am_idx = None
            if pg not in pg_used_am:
                am_idx = _find_near_slot(booked_merchants, "morning")

            if am_idx is None:
                continue

            near_consumed.add(am_idx)
            am_m = near_slots[am_idx]
            tasks_today.append({
                "merchant_name": am_m["name"], "merchant_id": am_m["id"],
                "photographer_id": pg,
                "time_slot": "morning", "video_count": 2,
                "ip_id": pick_ip(am_m["id"]),
            })
            booked_merchants.add(am_m["id"])
            last_merchant_day[am_m["id"]] = day_idx
            pg_used_am.add(pg)

            # — 找下午商家 —
            pm_idx = None
            if pg not in pg_used_pm:
                pm_idx = _find_near_slot(booked_merchants, "afternoon")

            if pm_idx is not None:
                near_consumed.add(pm_idx)
                pm_m = near_slots[pm_idx]
                tasks_today.append({
                    "merchant_name": pm_m["name"], "merchant_id": pm_m["id"],
                    "photographer_id": pg,
                    "time_slot": "afternoon", "video_count": 2,
                    "ip_id": pick_ip(pm_m["id"]),
                })
                booked_merchants.add(pm_m["id"])
                last_merchant_day[pm_m["id"]] = day_idx
                pg_used_pm.add(pg)

        if tasks_today:
            schedule.append({"date": date, "tasks": tasks_today})

    return schedule
