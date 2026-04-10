# handlers/data_provider.py - 完整版（覆盖所有数据）

import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from db import DB_PATH, get_all_groups_from_db, get_monitored_addresses
from handlers.accounting import accounting_manager
from auth import list_operators, OWNER_ID

# 北京时间时区
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_now():
    """获取当前北京时间"""
    return datetime.now(BEIJING_TZ)

def timestamp_to_beijing_str(ts: int) -> str:
    """时间戳转北京时间字符串"""
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')

def timestamp_to_date(ts: int) -> str:
    """时间戳转日期"""
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=BEIJING_TZ).strftime('%Y-%m-%d')


def run_async(coro):
    """运行异步函数（用于同步环境中调用异步函数）"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


class DataProvider:
    """数据提供者 - 为 AI 提供所有 Bot 数据"""

    def __init__(self):
        self.db_path = DB_PATH

    # ==================== 1. 群组相关数据 ====================

    def get_all_groups(self, limit: int = 100) -> Dict:
        """获取所有群组列表"""
        groups = get_all_groups_from_db()
        return {
            "total": len(groups),
            "groups": [
                {
                    "id": g['id'],
                    "name": g['title'],
                    "category": g.get('category', '未分类'),
                    "joined_at": timestamp_to_beijing_str(g.get('joined_at', 0)),
                    "last_seen": timestamp_to_beijing_str(g.get('last_seen', 0))
                }
                for g in groups[:limit]
            ]
        }

    def get_group_count(self) -> Dict:
        """获取群组总数"""
        groups = get_all_groups_from_db()
        return {"group_count": len(groups)}

    def get_group_categories(self) -> Dict:
        """获取群组分类统计"""
        from db import get_groups_by_category, get_all_categories
        categories = get_groups_by_category()
        all_cats = get_all_categories()
        return {
            "categories": categories,
            "category_list": [c['name'] for c in all_cats],
            "total": sum(categories.values())
        }

    def get_groups_by_category(self, category_name: str = None) -> Dict:
        """获取指定分类下的群组"""
        groups = get_all_groups_from_db()
        if category_name:
            filtered = [g for g in groups if g.get('category', '未分类') == category_name]
        else:
            filtered = groups

        return {
            "category": category_name or "全部",
            "count": len(filtered),
            "groups": [
                {"name": g['title'], "id": g['id']}
                for g in filtered[:50]
            ]
        }

    def get_all_groups_by_category(self) -> Dict:
        """获取所有分类及其下的群组"""
        from db import get_all_categories, get_all_groups_from_db

        categories = get_all_categories()
        groups = get_all_groups_from_db()

        result = {}
        for cat in categories:
            cat_name = cat['name']
            result[cat_name] = [
                {"name": g['title'], "id": g['id']}
                for g in groups if g.get('category', '未分类') == cat_name
            ]

        return {
            "categories": result,
            "total_categories": len(categories),
            "total_groups": len(groups)
        }

    def get_today_joined_groups(self) -> Dict:
        """获取今天新加入的群组"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        today_joined = []
        for g in groups:
            joined_at = g.get('joined_at', 0)
            if joined_at >= today_start:
                today_joined.append({
                    "name": g['title'],
                    "joined_at": timestamp_to_beijing_str(joined_at),
                    "category": g.get('category', '未分类')
                })

        today_joined.sort(key=lambda x: x['joined_at'])
        return {"today_joined": today_joined, "count": len(today_joined)}

    def get_monthly_joined_groups(self) -> Dict:
        """获取本月每天新加入的群组"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

        daily_count = {}
        daily_groups = {}

        for g in groups:
            joined_at = g.get('joined_at', 0)
            if joined_at >= month_start:
                date_str = timestamp_to_date(joined_at)
                daily_count[date_str] = daily_count.get(date_str, 0) + 1
                if date_str not in daily_groups:
                    daily_groups[date_str] = []
                daily_groups[date_str].append(g['title'])

        result = []
        for date_str in sorted(daily_count.keys()):
            result.append({
                "date": date_str,
                "count": daily_count[date_str],
                "groups": daily_groups[date_str][:10]
            })

        return {"daily_joined": result, "total_new": sum(daily_count.values()), "month": now.strftime('%Y年%m月')}

    def get_group_by_name(self, group_name: str) -> Dict:
        """根据名称搜索群组"""
        groups = get_all_groups_from_db()
        matched = []
        for g in groups:
            if group_name.lower() in g['title'].lower():
                matched.append({
                    "id": g['id'],
                    "name": g['title'],
                    "category": g.get('category', '未分类'),
                    "joined_at": timestamp_to_beijing_str(g.get('joined_at', 0))
                })

        return {"keyword": group_name, "matched": matched, "count": len(matched)}

    # ==================== 2. 操作员相关数据 ====================

    def get_operators(self) -> Dict:
        """获取操作员列表"""
        ops = list_operators()
        return {
            "owner_id": OWNER_ID,
            "operators": ops,
            "operator_count": len(ops),
            "all_authorized": [OWNER_ID] + ops
        }

    def is_authorized_user(self, user_id: int) -> Dict:
        """检查用户是否授权"""
        from auth import is_authorized
        return {"user_id": user_id, "is_authorized": is_authorized(user_id)}

    # ==================== 3. 记账相关数据 ====================

    def get_group_today_bill(self, group_name: str) -> Dict:
        """获取指定群组的今日账单"""
        groups = get_all_groups_from_db()

        target = None
        for group in groups:
            if group_name.lower() in group['title'].lower():
                target = group
                break

        if not target:
            return {"error": f"未找到群组「{group_name}」"}

        stats = accounting_manager.get_today_stats(target['id'])
        records = accounting_manager.get_today_records(target['id'])

        income_records = [r for r in records if r['type'] == 'income']
        expense_records = [r for r in records if r['type'] == 'expense']

        # 按备注分组
        categories = {}
        for r in income_records:
            cat = r.get('category', '') or '未分类'
            if cat not in categories:
                categories[cat] = {"cny": 0, "usdt": 0, "count": 0}
            categories[cat]["cny"] += r['amount']
            categories[cat]["usdt"] += r['amount_usdt']
            categories[cat]["count"] += 1

        return {
            "group_name": target['title'],
            "category": target.get('category', '未分类'),
            "date": beijing_now().strftime('%Y-%m-%d'),
            "fee_rate": stats.get('fee_rate', 0),
            "exchange_rate": stats.get('exchange_rate', 1),
            "per_transaction_fee": stats.get('per_transaction_fee', 0),
            "income_usdt": round(stats['income_usdt'], 2),
            "income_cny": round(stats['income_total'], 2),
            "income_count": stats['income_count'],
            "expense_usdt": round(stats['expense_usdt'], 2),
            "expense_count": stats['expense_count'],
            "pending_usdt": round(stats['pending_usdt'], 2),
            "categories": categories,
            "recent_income": [
                {
                    "time": timestamp_to_beijing_str(r['created_at'])[-8:-3],
                    "amount_cny": round(r['amount'], 2),
                    "amount_usdt": round(r['amount_usdt'], 2),
                    "user": r.get('display_name', ''),
                    "category": r.get('category', '')
                }
                for r in income_records[:10]
            ],
            "recent_expense": [
                {
                    "time": timestamp_to_beijing_str(r['created_at'])[-8:-3],
                    "amount_usdt": round(r['amount_usdt'], 2),
                    "user": r.get('display_name', '')
                }
                for r in expense_records[:10]
            ]
        }

    def get_group_bill_by_date(self, group_name: str, date_str: str) -> Dict:
        """获取指定群组指定日期的账单"""
        groups = get_all_groups_from_db()

        target = None
        for group in groups:
            if group_name.lower() in group['title'].lower():
                target = group
                break

        if not target:
            return {"error": f"未找到群组「{group_name}」"}

        records = accounting_manager.get_records_by_date(target['id'], date_str)

        if not records:
            return {
                "group_name": target['title'],
                "date": date_str,
                "message": f"{date_str} 没有记账记录"
            }

        income_records = [r for r in records if r['type'] == 'income']
        expense_records = [r for r in records if r['type'] == 'expense']

        total_income_usdt = sum(r['amount_usdt'] for r in income_records)
        total_income_cny = sum(r['amount'] for r in income_records)
        total_expense_usdt = sum(r['amount_usdt'] for r in expense_records)

        return {
            "group_name": target['title'],
            "date": date_str,
            "per_transaction_fee": 0,
            "income_usdt": round(total_income_usdt, 2),
            "income_cny": round(total_income_cny, 2),
            "income_count": len(income_records),
            "expense_usdt": round(total_expense_usdt, 2),
            "expense_count": len(expense_records),
            "pending_usdt": round(total_income_usdt - total_expense_usdt, 2),
            "records": [
                {
                    "time": timestamp_to_beijing_str(r['created_at'])[-8:-3],
                    "type": r['type'],
                    "amount_usdt": round(r['amount_usdt'], 2),
                    "amount_cny": round(r['amount'], 2) if r['type'] == 'income' else None,
                    "user": r.get('display_name', ''),
                    "category": r.get('category', '')
                }
                for r in records[:20]
            ]
        }

    def get_group_config(self, group_name: str = None) -> Dict:
        """获取群组配置（费率、汇率）"""
        groups = get_all_groups_from_db()
        result = []

        for group in groups:
            if group_name and group_name.lower() not in group['title'].lower():
                continue

            try:
                stats = accounting_manager.get_current_stats(group['id'])
                result.append({
                    "group_name": group['title'],
                    "fee_rate": stats.get('fee_rate', 0),
                    "exchange_rate": stats.get('exchange_rate', 1),
                    "per_transaction_fee": stats.get('per_transaction_fee', 0)
                })
            except:
                pass

        return {"configs": result, "count": len(result)}

    def get_today_all_income(self) -> Dict:
        """获取所有群组今日收入统计"""
        groups = get_all_groups_from_db()
        group_details = []
        total_income_usdt = 0
        total_expense_usdt = 0

        for group in groups:
            try:
                stats = accounting_manager.get_today_stats(group['id'])
                if stats['income_count'] > 0 or stats['expense_count'] > 0:
                    group_details.append({
                        "name": group['title'],
                        "category": group.get('category', '未分类'),
                        "income_usdt": round(stats['income_usdt'], 2),
                        "income_cny": round(stats['income_total'], 2),
                        "income_count": stats['income_count'],
                        "expense_usdt": round(stats['expense_usdt'], 2),
                        "expense_count": stats['expense_count'],
                        "pending_usdt": round(stats['pending_usdt'], 2)
                    })
                    total_income_usdt += stats['income_usdt']
                    total_expense_usdt += stats['expense_usdt']
            except:
                pass

        group_details.sort(key=lambda x: x['income_usdt'], reverse=True)

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "groups": group_details[:30],
            "total_income_usdt": round(total_income_usdt, 2),
            "total_expense_usdt": round(total_expense_usdt, 2),
            "net_usdt": round(total_income_usdt - total_expense_usdt, 2),
            "active_group_count": len(group_details)
        }

    def get_month_total_income(self) -> Dict:
        """获取本月所有群组总收入"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

        total_income_cny = 0
        total_income_usdt = 0

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                for record in records:
                    if record['type'] == 'income' and record.get('created_at', 0) >= month_start:
                        total_income_cny += record['amount']
                        total_income_usdt += record['amount_usdt']
            except:
                pass

        return {
            "month": now.strftime('%Y年%m月'),
            "total_income_cny": round(total_income_cny, 2),
            "total_income_usdt": round(total_income_usdt, 2)
        }

    def get_total_all_income(self) -> Dict:
        """获取所有群组历史总收入"""
        groups = get_all_groups_from_db()
        total_income_usdt = 0
        total_income_cny = 0
        total_expense_usdt = 0

        for group in groups:
            try:
                stats = accounting_manager.get_total_stats(group['id'])
                total_income_usdt += stats['income_usdt']
                total_income_cny += stats['income_total']
                total_expense_usdt += stats['expense_usdt']
            except:
                pass

        return {
            "total_income_usdt": round(total_income_usdt, 2),
            "total_income_cny": round(total_income_cny, 2),
            "total_expense_usdt": round(total_expense_usdt, 2),
            "net_usdt": round(total_income_usdt - total_expense_usdt, 2)
        }

    def get_week_comparison(self) -> Dict:
        """获取本周 vs 上周对比"""
        groups = get_all_groups_from_db()
        now = beijing_now()

        this_week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(seconds=1)

        this_week_total = 0
        last_week_total = 0

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                for record in records:
                    if record['type'] == 'income':
                        ts = record.get('created_at', 0)
                        if this_week_start.timestamp() <= ts:
                            this_week_total += record['amount_usdt']
                        elif last_week_start.timestamp() <= ts < last_week_end.timestamp():
                            last_week_total += record['amount_usdt']
            except:
                pass

        change = ((this_week_total - last_week_total) / last_week_total * 100) if last_week_total > 0 else 100 if this_week_total > 0 else 0

        return {
            "this_week_usdt": round(this_week_total, 2),
            "last_week_usdt": round(last_week_total, 2),
            "change_percent": round(change, 1),
            "trend": "上涨" if change >= 0 else "下跌"
        }

    def get_category_income_percentage(self) -> Dict:
        """获取各分类入款占比"""
        groups = get_all_groups_from_db()
        category_income = {}
        total = 0

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                for record in records:
                    if record['type'] == 'income':
                        category = record.get('category', '未分类')
                        if not category:
                            category = '未分类'
                        category_income[category] = category_income.get(category, 0) + record['amount_usdt']
                        total += record['amount_usdt']
            except:
                pass

        categories = []
        for cat, amount in sorted(category_income.items(), key=lambda x: x[1], reverse=True):
            categories.append({
                "name": cat,
                "usdt": round(amount, 2),
                "percentage": round(amount / total * 100, 1) if total > 0 else 0
            })

        return {"categories": categories, "total_usdt": round(total, 2)}

    def get_weekly_trend(self, days: int = 7) -> Dict:
        """获取最近N天每日收入趋势"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        daily_data = {}

        for i in range(days):
            date = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            daily_data[date] = 0

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                for record in records:
                    if record['type'] == 'income':
                        date = timestamp_to_date(record['created_at'])
                        if date in daily_data:
                            daily_data[date] += record['amount_usdt']
            except:
                pass

        trend = []
        for date in sorted(daily_data.keys()):
            trend.append({
                "date": date,
                "usdt": round(daily_data[date], 2)
            })

        return {"trend": trend, "days": days}

    def get_hourly_distribution(self) -> Dict:
        """获取今日各时段入款分布"""
        groups = get_all_groups_from_db()
        hourly_data = [0] * 24

        for group in groups:
            try:
                records = accounting_manager.get_today_records(group['id'])
                for record in records:
                    if record['type'] == 'income':
                        hour = datetime.fromtimestamp(record['created_at'], tz=BEIJING_TZ).hour
                        hourly_data[hour] += record['amount_usdt']
            except:
                pass

        peak_hour = max(range(24), key=lambda x: hourly_data[x])
        active_hours = [{"hour": h, "usdt": round(hourly_data[h], 2)} for h in range(24) if hourly_data[h] > 0]

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "hourly": active_hours[:12],
            "peak_hour": peak_hour,
            "peak_usdt": round(hourly_data[peak_hour], 2)
        }

    # ==================== 4. 用户相关数据 ====================

    def get_today_top_users(self, limit: int = 10) -> Dict:
        """获取今日入款最多的用户"""
        groups = get_all_groups_from_db()
        user_income = {}
        user_name_map = {}

        for group in groups:
            try:
                records = accounting_manager.get_today_records(group['id'])
                for record in records:
                    if record['type'] == 'income':
                        user_id_key = record.get('user_id')
                        if user_id_key:
                            user_name_map[user_id_key] = record.get('display_name', str(user_id_key))
                            user_income[user_id_key] = user_income.get(user_id_key, 0) + record['amount']
            except:
                pass

        sorted_users = sorted(user_income.items(), key=lambda x: x[1], reverse=True)[:limit]

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "top_users": [
                {"name": user_name_map.get(uid, str(uid)), "income_cny": round(amount, 2)}
                for uid, amount in sorted_users
            ]
        }

    def get_today_active_users(self) -> Dict:
        """获取今日使用记账命令的用户"""
        groups = get_all_groups_from_db()
        user_activity = {}

        for group in groups:
            try:
                records = accounting_manager.get_today_records(group['id'])
                for record in records:
                    user_id_key = record.get('user_id')
                    if user_id_key:
                        if user_id_key not in user_activity:
                            user_activity[user_id_key] = {
                                "name": record.get('display_name', str(user_id_key)),
                                "count": 0,
                                "income_usdt": 0,
                                "expense_usdt": 0
                            }
                        user_activity[user_id_key]["count"] += 1
                        if record['type'] == 'income':
                            user_activity[user_id_key]["income_usdt"] += record['amount_usdt']
                        else:
                            user_activity[user_id_key]["expense_usdt"] += record['amount_usdt']
            except:
                pass

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "active_users": list(user_activity.values())[:30],
            "total_users": len(user_activity)
        }

    def get_user_activity_history(self, user_name: str, limit: int = 20) -> Dict:
        """获取指定用户的历史活动记录"""
        groups = get_all_groups_from_db()
        records = []

        for group in groups:
            try:
                all_records = accounting_manager.get_total_records(group['id'])
                for record in all_records:
                    display_name = record.get('display_name', '')
                    if user_name.lower() in display_name.lower():
                        records.append({
                            "group": group['title'],
                            "type": record['type'],
                            "amount_usdt": round(record['amount_usdt'], 2),
                            "amount_cny": round(record['amount'], 2) if record['type'] == 'income' else None,
                            "time": timestamp_to_beijing_str(record['created_at']),
                            "category": record.get('category', '')
                        })
            except:
                pass

        records.sort(key=lambda x: x['time'], reverse=True)

        return {
            "user": user_name,
            "records": records[:limit],
            "total_count": len(records)
        }

    # ==================== 5. 群组活跃度数据 ====================

    def get_today_active_groups(self) -> Dict:
        """获取今日有交易的群组"""
        groups = get_all_groups_from_db()
        active_groups = []

        for group in groups:
            try:
                stats = accounting_manager.get_today_stats(group['id'])
                if stats['income_count'] > 0 or stats['expense_count'] > 0:
                    active_groups.append({
                        "name": group['title'],
                        "income_usdt": round(stats['income_usdt'], 2),
                        "income_count": stats['income_count'],
                        "expense_count": stats['expense_count']
                    })
            except:
                pass

        active_groups.sort(key=lambda x: x['income_usdt'], reverse=True)

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "active_groups": active_groups[:30],
            "total_active": len(active_groups)
        }

    def get_today_top_group(self) -> Dict:
        """获取今日交易最多的群组"""
        groups = get_all_groups_from_db()
        top_group = None
        max_income = 0
        top_stats = None

        for group in groups:
            try:
                stats = accounting_manager.get_today_stats(group['id'])
                if stats['income_usdt'] > max_income:
                    max_income = stats['income_usdt']
                    top_group = group
                    top_stats = stats
            except:
                pass

        if top_group:
            return {
                "group_name": top_group['title'],
                "category": top_group.get('category', '未分类'),
                "income_usdt": round(top_stats['income_usdt'], 2),
                "income_cny": round(top_stats['income_total'], 2),
                "income_count": top_stats['income_count']
            }

        return {"error": "今日没有交易记录"}

    def get_group_activity_ranking(self) -> Dict:
        """获取群组活跃度排行（按总交易笔数）"""
        groups = get_all_groups_from_db()
        group_stats = []

        for group in groups:
            try:
                stats = accounting_manager.get_total_stats(group['id'])
                if stats['income_count'] > 0 or stats['expense_count'] > 0:
                    group_stats.append({
                        "name": group['title'],
                        "total_income_usdt": round(stats['income_usdt'], 2),
                        "total_count": stats['income_count'] + stats['expense_count'],
                        "income_count": stats['income_count'],
                        "expense_count": stats['expense_count']
                    })
            except:
                pass

        group_stats.sort(key=lambda x: x['total_count'], reverse=True)

        return {"ranking": group_stats[:20]}

    # ==================== 6. 待处理数据 ====================

    def get_pending_usdt_groups(self) -> Dict:
        """获取有待下发 USDT 的群组"""
        groups = get_all_groups_from_db()
        pending_groups = []
        total_pending = 0

        for group in groups:
            try:
                stats = accounting_manager.get_current_stats(group['id'])
                if stats['pending_usdt'] > 0:
                    pending_groups.append({
                        "name": group['title'],
                        "pending_usdt": round(stats['pending_usdt'], 2)
                    })
                    total_pending += stats['pending_usdt']
            except:
                pass

        pending_groups.sort(key=lambda x: x['pending_usdt'], reverse=True)

        return {
            "pending_groups": pending_groups,
            "total_pending_usdt": round(total_pending, 2),
            "count": len(pending_groups)
        }

    # ==================== 7. 异常检测数据 ====================

    def get_large_transactions(self, threshold: int = 5000) -> Dict:
        """获取今日大额交易（≥ threshold 元）"""
        groups = get_all_groups_from_db()
        large_transactions = []

        for group in groups:
            try:
                records = accounting_manager.get_today_records(group['id'])
                for record in records:
                    if record['type'] == 'income' and record['amount'] >= threshold:
                        large_transactions.append({
                            "group": group['title'],
                            "user": record.get('display_name', '未知'),
                            "amount_cny": round(record['amount'], 2),
                            "amount_usdt": round(record['amount_usdt'], 2),
                            "time": timestamp_to_beijing_str(record['created_at'])[-8:-3]
                        })
            except:
                pass

        large_transactions.sort(key=lambda x: x['amount_cny'], reverse=True)

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "threshold": threshold,
            "transactions": large_transactions,
            "count": len(large_transactions)
        }

    # ==================== 8. USDT 监控地址数据 ====================

    def get_monitored_addresses_list(self) -> Dict:
        """获取监控地址列表"""
        addresses = get_monitored_addresses()

        return {
            "addresses": [
                {
                    "address": a['address'][:12] + "..." + a['address'][-8:],
                    "full_address": a['address'],
                    "note": a.get('note', '无备注'),
                    "chain_type": a['chain_type'],
                    "added_at": timestamp_to_beijing_str(a['added_at']),
                    "added_by": a['added_by']
                }
                for a in addresses
            ],
            "count": len(addresses)
        }

    def get_address_today_stats(self, address: str) -> Dict:
        """获取指定地址今日收支统计"""
        from handlers.monitor import get_trc20_transactions, get_address_balance

        now = beijing_now()
        today_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

        txs = run_async(get_trc20_transactions(address, today_start))

        received = 0.0
        sent = 0.0
        for tx in txs:
            to_addr = tx.get("to", "")
            raw_amount = tx.get("value", 0)
            amount = int(raw_amount) / 1_000_000 if raw_amount else 0
            if to_addr == address:
                received += amount
            else:
                sent += amount

        balance = run_async(get_address_balance(address))

        addresses = get_monitored_addresses()
        note = ""
        for a in addresses:
            if a['address'] == address:
                note = a.get('note', '')
                break

        return {
            "address": address[:12] + "..." + address[-8:],
            "full_address": address,
            "note": note,
            "date": now.strftime('%Y-%m-%d'),
            "received_usdt": round(received, 2),
            "sent_usdt": round(sent, 2),
            "net_usdt": round(received - sent, 2),
            "balance_usdt": round(balance, 2),
            "transaction_count": len(txs)
        }

    def get_address_stats_by_period(self, address: str, period: str) -> Dict:
        """获取指定地址指定周期的收支统计（today/week/month）"""
        from handlers.monitor import get_trc20_transactions, get_address_balance

        now = beijing_now()

        if period == "today":
            start_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        elif period == "week":
            start_ts = int((now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        elif period == "month":
            start_ts = int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        else:
            start_ts = 0

        all_txs = []
        page = 0
        limit = 200
        while True:
            txs = run_async(get_trc20_transactions(address, start_ts, limit=limit, offset=page * limit))
            if not txs:
                break
            all_txs.extend(txs)
            if len(txs) < limit:
                break
            page += 1

        received = 0.0
        sent = 0.0
        for tx in all_txs:
            to_addr = tx.get("to", "")
            raw_amount = tx.get("value", 0)
            amount = int(raw_amount) / 1_000_000 if raw_amount else 0
            if to_addr == address:
                received += amount
            else:
                sent += amount

        period_names = {"today": "今日", "week": "本周", "month": "本月"}

        return {
            "address": address[:12] + "..." + address[-8:],
            "period": period_names.get(period, period),
            "received_usdt": round(received, 2),
            "sent_usdt": round(sent, 2),
            "net_usdt": round(received - sent, 2),
            "transaction_count": len(all_txs)
        }

    def get_all_address_transactions(self, address: str = None, limit: int = 50) -> Dict:
        """获取地址交易记录（支持分页）"""
        from handlers.monitor import get_trc20_transactions

        if not address:
            addresses = get_monitored_addresses()
            if not addresses:
                return {"error": "没有监控地址"}
            address = addresses[0]['address']

        txs = run_async(get_trc20_transactions(address, 0, limit=limit))

        transactions = []
        for tx in txs:
            to_addr = tx.get("to", "")
            raw_amount = tx.get("value", 0)
            amount = int(raw_amount) / 1_000_000 if raw_amount else 0
            transactions.append({
                "tx_id": tx.get("transaction_id", "")[:16] + "...",
                "from": tx.get("from", "")[:12] + "...",
                "to": to_addr[:12] + "...",
                "amount_usdt": round(amount, 2),
                "direction": "收到" if to_addr == address else "转出",
                "time": timestamp_to_beijing_str(int(tx.get("block_timestamp", 0) / 1000))
            })

        return {"address": address[:12] + "...", "transactions": transactions, "count": len(transactions)}

    # ==================== 9. 历史会话数据 ====================

    def get_accounting_sessions(self, group_name: str = None, limit: int = 20) -> Dict:
        """获取记账历史会话"""
        groups = get_all_groups_from_db()
        sessions = []

        target_groups = []
        if group_name:
            for group in groups:
                if group_name.lower() in group['title'].lower():
                    target_groups.append(group)
        else:
            target_groups = groups[:10]

        for group in target_groups:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    c = conn.cursor()
                    c.execute("""
                        SELECT session_id, date, start_time, end_time, fee_rate, exchange_rate
                        FROM accounting_sessions
                        WHERE group_id = ?
                        ORDER BY date DESC
                        LIMIT ?
                    """, (group['id'], limit // len(target_groups) if len(target_groups) > 0 else limit))
                    rows = c.fetchall()

                    for row in rows:
                        sessions.append({
                            "group_name": group['title'],
                            "date": row[1],
                            "start_time": timestamp_to_beijing_str(row[2]),
                            "end_time": timestamp_to_beijing_str(row[3]),
                            "fee_rate": row[4],
                            "exchange_rate": row[5]
                        })
            except:
                pass

        sessions.sort(key=lambda x: x['date'], reverse=True)

        return {"sessions": sessions[:limit], "count": len(sessions)}

    # ==================== 10. USDT 查询记录数据 ====================

    def get_address_query_stats(self, address: str = None) -> Dict:
        """获取地址被查询的统计"""
        queries = []

        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()

            if address:
                c.execute("""
                    SELECT address, chain_type, query_time, user_id, username, balance
                    FROM address_queries
                    WHERE address LIKE ?
                    ORDER BY query_time DESC
                    LIMIT 20
                """, (f'%{address}%',))
            else:
                c.execute("""
                    SELECT address, chain_type, query_time, user_id, username, balance
                    FROM address_queries
                    ORDER BY query_time DESC
                    LIMIT 30
                """)

            rows = c.fetchall()

            for row in rows:
                queries.append({
                    "address": row[0][:12] + "..." + row[0][-8:] if row[0] else "",
                    "chain_type": row[1],
                    "query_time": timestamp_to_beijing_str(row[2]),
                    "user": row[4] or str(row[3]),
                    "balance": round(row[5], 2) if row[5] else 0
                })

        return {"queries": queries, "count": len(queries)}

    def get_most_queried_addresses(self, limit: int = 10) -> Dict:
        """获取被查询最多的地址"""
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT address, COUNT(*) as query_count
                FROM address_query_log
                GROUP BY address
                ORDER BY query_count DESC
                LIMIT ?
            """, (limit,))
            rows = c.fetchall()

            addresses = []
            for row in rows:
                addresses.append({
                    "address": row[0][:12] + "..." + row[0][-8:] if row[0] else "",
                    "query_count": row[1]
                })

        return {"most_queried": addresses}

    # ==================== 11. 群组用户数据 ====================

    def get_group_users(self, group_name: str, limit: int = 50) -> Dict:
        """获取群组中的用户列表"""
        groups = get_all_groups_from_db()

        target = None
        for group in groups:
            if group_name.lower() in group['title'].lower():
                target = group
                break

        if not target:
            return {"error": f"未找到群组「{group_name}」"}

        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, username, first_name, last_seen
                FROM group_users
                WHERE group_id = ?
                ORDER BY last_seen DESC
                LIMIT ?
            """, (target['id'], limit))
            rows = c.fetchall()

            users = []
            for row in rows:
                users.append({
                    "user_id": row[0],
                    "name": row[2] if row[2] else (row[1] if row[1] else str(row[0])),
                    "last_seen": timestamp_to_beijing_str(row[3])
                })

        return {"group_name": target['title'], "users": users, "count": len(users)}

    # ==================== 12. 广播记录数据 ====================

    def get_broadcast_history(self, limit: int = 20) -> Dict:
        """获取广播历史记录"""
        # 注意：当前代码没有广播记录表，这里查询 message_send_log 如果存在
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='broadcast_history'")
                if c.fetchone():
                    c.execute("""
                        SELECT id, message_preview, target_count, success_count, failed_count, created_at
                        FROM broadcast_history
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (limit,))
                    rows = c.fetchall()

                    history = []
                    for row in rows:
                        history.append({
                            "id": row[0],
                            "message_preview": row[1][:50] if row[1] else "",
                            "target_count": row[2],
                            "success_count": row[3],
                            "failed_count": row[4],
                            "created_at": timestamp_to_beijing_str(row[5])
                        })

                    return {"history": history, "count": len(history)}
        except:
            pass

        return {"message": "暂无广播历史记录", "history": []}


# 全局实例
data_provider = DataProvider()
