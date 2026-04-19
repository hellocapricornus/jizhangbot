# handlers/data_provider.py - 完整版

import sqlite3
import asyncio
import re
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
        return {"group_count": len(groups), "message": f"当前共加入 {len(groups)} 个群组"}

    def get_group_categories(self) -> Dict:
        """获取群组分类统计"""
        from db import get_groups_by_category, get_all_categories
        categories = get_groups_by_category()
        all_cats = get_all_categories()

        if not categories:
            return {"message": "暂无群组分类数据", "categories": {}, "category_list": [], "total": 0}

        # 生成友好格式
        cat_list = "\n".join([f"• {cat}：{count}个" for cat, count in categories.items()])

        return {
            "categories": categories,
            "category_list": [c['name'] for c in all_cats],
            "total": sum(categories.values()),
            "summary": f"📊 群组分类统计：\n{cat_list}\n\n总计：{sum(categories.values())} 个群组"
        }

    def get_groups_by_category(self, category_name: str = None) -> Dict:
        """获取指定分类下的群组"""
        groups = get_all_groups_from_db()
        if category_name:
            filtered = [g for g in groups if g.get('category', '未分类') == category_name]
        else:
            filtered = groups

        if not filtered and category_name:
            return {"error": f"未找到分类「{category_name}」下的群组", "groups": [], "count": 0}

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
            cat_groups = [g for g in groups if g.get('category', '未分类') == cat_name]
            if cat_groups:
                result[cat_name] = [
                    {"name": g['title'], "id": g['id']}
                    for g in cat_groups
                ]

        # 生成友好格式
        summary = "📁 **所有分类及群组列表**\n\n"
        for cat_name, cat_groups in result.items():
            summary += f"📂 **{cat_name}** ({len(cat_groups)}个)\n"
            for g in cat_groups[:10]:
                summary += f"  • {g['name']}\n"
            if len(cat_groups) > 10:
                summary += f"  ... 还有 {len(cat_groups) - 10} 个\n"
            summary += "\n"

        return {
            "categories": result,
            "total_categories": len(categories),
            "total_groups": len(groups),
            "summary": summary
        }

    # ==================== 2. 新加入群组相关 ====================

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

        if not today_joined:
            return {"message": "今天没有新加入的群组", "groups": [], "count": 0}

        return {"date": "今天", "groups": today_joined, "count": len(today_joined)}

    def get_yesterday_joined_groups(self) -> Dict:
        """获取昨天新加入的群组"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        yesterday_end = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        yesterday_joined = []
        for g in groups:
            joined_at = g.get('joined_at', 0)
            if yesterday_start <= joined_at < yesterday_end:
                yesterday_joined.append({
                    "name": g['title'],
                    "joined_at": timestamp_to_beijing_str(joined_at),
                    "category": g.get('category', '未分类')
                })

        yesterday_joined.sort(key=lambda x: x['joined_at'])

        if not yesterday_joined:
            return {"message": "昨天没有新加入的群组", "groups": [], "count": 0}

        return {"date": "昨天", "groups": yesterday_joined, "count": len(yesterday_joined)}

    def get_weekly_joined_groups(self) -> Dict:
        """获取本周每天新加入的群组"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        daily_groups = {}
        for i in range(7):
            day = week_start + timedelta(days=i)
            day_start = day.timestamp()
            day_end = (day + timedelta(days=1)).timestamp()
            day_str = day.strftime('%Y-%m-%d')
            daily_groups[day_str] = []

            for g in groups:
                joined_at = g.get('joined_at', 0)
                if day_start <= joined_at < day_end:
                    daily_groups[day_str].append({
                        "name": g['title'],
                        "time": timestamp_to_beijing_str(joined_at)
                    })

        # 过滤掉没有新群组的日子
        result = []
        for date, group_list in daily_groups.items():
            if group_list:
                result.append({
                    "date": date,
                    "count": len(group_list),
                    "groups": group_list
                })

        if not result:
            return {"message": "本周没有新加入的群组", "daily_groups": [], "total": 0}

        # 生成友好格式
        summary = "📅 **本周每天新加入的群组**\n\n"
        for day in result:
            summary += f"📌 {day['date']}：{day['count']}个\n"
            for g in day['groups'][:5]:
                summary += f"  • {g['name']}（{g['time']}）\n"
            if day['count'] > 5:
                summary += f"  ... 还有 {day['count'] - 5} 个\n"
            summary += "\n"

        return {"daily_groups": result, "total": sum(d['count'] for d in result), "summary": summary}

    def get_monthly_joined_groups(self) -> Dict:
        """获取本月每天新加入的群组"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # 获取本月天数
        if now.month == 12:
            next_month = now.replace(year=now.year+1, month=1, day=1)
        else:
            next_month = now.replace(month=now.month+1, day=1)
        days_in_month = (next_month - month_start).days

        daily_groups = {}
        for i in range(days_in_month):
            day = month_start + timedelta(days=i)
            day_start = day.timestamp()
            day_end = (day + timedelta(days=1)).timestamp()
            day_str = day.strftime('%Y-%m-%d')
            daily_groups[day_str] = []

            for g in groups:
                joined_at = g.get('joined_at', 0)
                if day_start <= joined_at < day_end:
                    daily_groups[day_str].append({
                        "name": g['title'],
                        "time": timestamp_to_beijing_str(joined_at)
                    })

        # 过滤掉没有新群组的日子
        result = []
        for date, group_list in daily_groups.items():
            if group_list:
                result.append({
                    "date": date,
                    "count": len(group_list),
                    "groups": group_list
                })

        if not result:
            return {"message": "本月没有新加入的群组", "daily_groups": [], "total": 0}

        # 生成友好格式
        summary = f"📅 **{now.strftime('%Y年%m月')}每天新加入的群组**\n\n"
        for day in result[:15]:
            summary += f"📌 {day['date']}：{day['count']}个\n"
            for g in day['groups'][:3]:
                summary += f"  • {g['name']}（{g['time']}）\n"
            if day['count'] > 3:
                summary += f"  ... 还有 {day['count'] - 3} 个\n"
            summary += "\n"

        if len(result) > 15:
            summary += f"... 还有 {len(result) - 15} 天有新增群组\n"

        return {"daily_groups": result, "total": sum(d['count'] for d in result), "summary": summary}

    def get_joined_groups_by_date(self, date_str: str) -> Dict:
        """获取指定日期新加入的群组"""
        groups = get_all_groups_from_db()

        try:
            # 🔥 支持多种日期格式
            if '-' in date_str:
                target_date = datetime.strptime(date_str, '%Y-%m-%d')
            elif '年' in date_str:
                # 处理 "2024年4月5日" 格式
                match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
                if match:
                    year = int(match.group(1))
                    month = int(match.group(2))
                    day = int(match.group(3))
                    target_date = datetime(year, month, day)
                else:
                    return {"error": f"日期格式错误: {date_str}"}
            else:
                target_date = datetime.strptime(date_str, '%Y-%m-%d')

            day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            day_end = (target_date + timedelta(days=1)).timestamp()
        except Exception as e:
            return {"error": f"日期格式错误: {date_str}, {e}"}

        joined = []
        for g in groups:
            joined_at = g.get('joined_at', 0)
            if day_start <= joined_at < day_end:
                joined.append({
                    "name": g['title'],
                    "joined_at": timestamp_to_beijing_str(joined_at),
                    "category": g.get('category', '未分类')
                })

        joined.sort(key=lambda x: x['joined_at'])

        if not joined:
            return {"message": f"{date_str} 没有新加入的群组", "groups": [], "count": 0}

        return {"date": date_str, "groups": joined, "count": len(joined)}

    # ==================== 3. 活跃度相关 ====================

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

        if not group_stats:
            return {"message": "暂无群组活跃数据", "ranking": [], "count": 0}

        # 生成友好格式
        summary = "📊 **群组活跃度排行**\n\n"
        for i, g in enumerate(group_stats[:20], 1):
            summary += f"{i}. {g['name']}\n"
            summary += f"   总交易：{g['total_count']}笔（入款{g['income_count']}笔，出款{g['expense_count']}笔）\n"
            summary += f"   总入款：{g['total_income_usdt']:.2f} USDT\n\n"

        return {"ranking": group_stats[:20], "count": len(group_stats), "summary": summary}

    def get_today_active_groups(self) -> Dict:
        """获取今日有交易的群组"""
        groups = get_all_groups_from_db()
        active_groups = []
        today = beijing_now().strftime('%Y-%m-%d')

        print(f"[DEBUG] get_today_active_groups - 今日日期: {today}")

        for group in groups:
            try:
                # 直接获取今日记录
                records = accounting_manager.get_today_records(group['id'])

                # 过滤：只要有入款或出款记录就算活跃
                income_count = len([r for r in records if r['type'] == 'income'])
                expense_count = len([r for r in records if r['type'] == 'expense'])

                if income_count > 0 or expense_count > 0:
                    stats = accounting_manager.get_today_stats(group['id'])
                    active_groups.append({
                        "name": group['title'],
                        "income_usdt": round(stats['income_usdt'], 2),
                        "income_cny": round(stats['income_total'], 2),
                        "income_count": income_count,
                        "expense_count": expense_count
                    })
                    print(f"[DEBUG] 活跃群组: {group['title']}, 入款: {income_count}笔, 出款: {expense_count}笔")
            except Exception as e:
                print(f"[DEBUG] 获取群组 {group['title']} 今日记录失败: {e}")
                pass

        active_groups.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not active_groups:
            return {
                "date": today,
                "message": f"今天（{today}）没有群组使用记账功能",
                "active_groups": [],
                "total_active": 0,
                "summary": f"📊 今天（{today}）没有群组使用记账功能"
            }

        # 构建友好格式
        group_list = []
        for g in active_groups:
            income_cny_str = f"{int(g['income_cny'])}" if g['income_cny'] == int(g['income_cny']) else f"{g['income_cny']:.2f}"
            income_usdt_str = f"{int(g['income_usdt'])}" if g['income_usdt'] == int(g['income_usdt']) else f"{g['income_usdt']:.2f}"
            group_list.append(f"• {g['name']}：{income_cny_str}元 = {income_usdt_str} USDT（入款{g['income_count']}笔，出款{g['expense_count']}笔）")

        summary = f"📊 **今天（{today}）使用记账功能的群组**\n\n" + "\n".join(group_list)

        return {
            "date": today,
            "active_groups": active_groups,
            "total_active": len(active_groups),
            "summary": summary
        }

    def get_yesterday_active_groups(self) -> Dict:
        """获取昨日有交易的群组"""
        groups = get_all_groups_from_db()
        active_groups = []
        yesterday = (beijing_now() - timedelta(days=1)).strftime('%Y-%m-%d')

        for group in groups:
            try:
                records = accounting_manager.get_records_by_date(group['id'], yesterday)
                income_count = len([r for r in records if r['type'] == 'income'])
                expense_count = len([r for r in records if r['type'] == 'expense'])

                if income_count > 0 or expense_count > 0:
                    total_income_usdt = sum(r['amount_usdt'] for r in records if r['type'] == 'income')
                    total_income_cny = sum(r['amount'] for r in records if r['type'] == 'income')
                    active_groups.append({
                        "name": group['title'],
                        "income_usdt": round(total_income_usdt, 2),
                        "income_cny": round(total_income_cny, 2),
                        "income_count": income_count,
                        "expense_count": expense_count
                    })
            except:
                pass

        active_groups.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not active_groups:
            return {"date": yesterday, "message": f"昨日（{yesterday}）没有群组使用记账功能", "active_groups": [], "total_active": 0}

        group_list = [f"• {g['name']}：{g['income_cny']:.2f}元 = {g['income_usdt']:.2f} USDT" for g in active_groups]
        summary = f"📊 **昨日（{yesterday}）使用记账功能的群组**\n\n" + "\n".join(group_list)

        return {"date": yesterday, "active_groups": active_groups, "total_active": len(active_groups), "summary": summary}

    def get_week_active_groups(self) -> Dict:
        """获取本周有交易的群组"""
        groups = get_all_groups_from_db()
        active_groups = []
        now = beijing_now()
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        start_ts = int(week_start.timestamp())

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                week_records = [r for r in records if r.get('created_at', 0) >= start_ts]
                income_count = len([r for r in week_records if r['type'] == 'income'])
                expense_count = len([r for r in week_records if r['type'] == 'expense'])

                if income_count > 0 or expense_count > 0:
                    total_income_usdt = sum(r['amount_usdt'] for r in week_records if r['type'] == 'income')
                    total_income_cny = sum(r['amount'] for r in week_records if r['type'] == 'income')
                    active_groups.append({
                        "name": group['title'],
                        "income_usdt": round(total_income_usdt, 2),
                        "income_cny": round(total_income_cny, 2),
                        "income_count": income_count,
                        "expense_count": expense_count
                    })
            except:
                pass

        active_groups.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not active_groups:
            return {"date": "本周", "message": "本周没有群组使用记账功能", "active_groups": [], "total_active": 0}

        group_list = [f"• {g['name']}：{g['income_cny']:.2f}元 = {g['income_usdt']:.2f} USDT" for g in active_groups]
        summary = f"📊 **本周使用记账功能的群组**\n\n" + "\n".join(group_list)

        return {"date": "本周", "active_groups": active_groups, "total_active": len(active_groups), "summary": summary}

    def get_month_active_groups(self) -> Dict:
        """获取本月有交易的群组"""
        groups = get_all_groups_from_db()
        active_groups = []
        now = beijing_now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        start_ts = int(month_start.timestamp())

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                month_records = [r for r in records if r.get('created_at', 0) >= start_ts]
                income_count = len([r for r in month_records if r['type'] == 'income'])
                expense_count = len([r for r in month_records if r['type'] == 'expense'])

                if income_count > 0 or expense_count > 0:
                    total_income_usdt = sum(r['amount_usdt'] for r in month_records if r['type'] == 'income')
                    total_income_cny = sum(r['amount'] for r in month_records if r['type'] == 'income')
                    active_groups.append({
                        "name": group['title'],
                        "income_usdt": round(total_income_usdt, 2),
                        "income_cny": round(total_income_cny, 2),
                        "income_count": income_count,
                        "expense_count": expense_count
                    })
            except:
                pass

        active_groups.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not active_groups:
            return {"date": "本月", "message": "本月没有群组使用记账功能", "active_groups": [], "total_active": 0}

        group_list = [f"• {g['name']}：{g['income_cny']:.2f}元 = {g['income_usdt']:.2f} USDT" for g in active_groups]
        summary = f"📊 **本月使用记账功能的群组**\n\n" + "\n".join(group_list)

        return {"date": "本月", "active_groups": active_groups, "total_active": len(active_groups), "summary": summary}

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

        return {"message": "今日没有交易记录", "group_name": None}

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

        top_users_list = [
            {"name": user_name_map.get(uid, str(uid)), "income_cny": round(amount, 2)}
            for uid, amount in sorted_users
        ]

        if not top_users_list:
            return {"message": "今日没有入款记录", "top_users": []}

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "top_users": top_users_list
        }

    def get_today_active_users(self) -> Dict:
        """获取今日使用记账的用户"""
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

        if not user_activity:
            return {"message": "今日没有用户使用记账功能", "active_users": [], "total_users": 0}

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "active_users": list(user_activity.values())[:30],
            "total_users": len(user_activity)
        }

    # ==================== 5. 记账统计相关 ====================

    def get_group_today_bill(self, group_name: str) -> Dict:
        """获取指定群组的今日账单（支持模糊匹配）"""
        groups = get_all_groups_from_db()

        # 模糊匹配群组名称
        target = self._find_group(groups, group_name)

        if not target:
            available_groups = [g['title'] for g in groups[:10]]
            return {
                "error": f"未找到群组「{group_name}」",
                "available_groups": available_groups,
                "suggestion": f"可用的群组有：{', '.join(available_groups[:5])}{'...' if len(available_groups) > 5 else ''}"
            }

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

    def get_group_yesterday_bill(self, group_name: str) -> Dict:
        """获取指定群组的昨日账单"""
        yesterday = (beijing_now() - timedelta(days=1)).strftime('%Y-%m-%d')
        return self.get_group_bill_by_date(group_name, yesterday)

    def get_group_week_bill(self, group_name: str) -> Dict:
        """获取指定群组的本周账单"""
        groups = get_all_groups_from_db()
        target = self._find_group(groups, group_name)

        if not target:
            available_groups = [g['title'] for g in groups[:10]]
            return {
                "error": f"未找到群组「{group_name}」",
                "available_groups": available_groups,
                "suggestion": f"可用的群组有：{', '.join(available_groups[:5])}{'...' if len(available_groups) > 5 else ''}"
            }

        now = beijing_now()
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        start_ts = int(week_start.timestamp())

        records = accounting_manager.get_total_records(target['id'])
        week_records = [r for r in records if r.get('created_at', 0) >= start_ts]

        income_records = [r for r in week_records if r['type'] == 'income']
        expense_records = [r for r in week_records if r['type'] == 'expense']

        total_income_usdt = sum(r['amount_usdt'] for r in income_records)
        total_income_cny = sum(r['amount'] for r in income_records)
        total_expense_usdt = sum(r['amount_usdt'] for r in expense_records)

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
            "date": "本周",
            "income_usdt": round(total_income_usdt, 2),
            "income_cny": round(total_income_cny, 2),
            "income_count": len(income_records),
            "expense_usdt": round(total_expense_usdt, 2),
            "expense_count": len(expense_records),
            "pending_usdt": round(total_income_usdt - total_expense_usdt, 2),
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

    def get_group_month_bill(self, group_name: str) -> Dict:
        """获取指定群组的本月账单"""
        groups = get_all_groups_from_db()
        target = self._find_group(groups, group_name)

        if not target:
            available_groups = [g['title'] for g in groups[:10]]
            return {
                "error": f"未找到群组「{group_name}」",
                "available_groups": available_groups,
                "suggestion": f"可用的群组有：{', '.join(available_groups[:5])}{'...' if len(available_groups) > 5 else ''}"
            }

        now = beijing_now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        start_ts = int(month_start.timestamp())

        records = accounting_manager.get_total_records(target['id'])
        month_records = [r for r in records if r.get('created_at', 0) >= start_ts]

        income_records = [r for r in month_records if r['type'] == 'income']
        expense_records = [r for r in month_records if r['type'] == 'expense']

        total_income_usdt = sum(r['amount_usdt'] for r in income_records)
        total_income_cny = sum(r['amount'] for r in income_records)
        total_expense_usdt = sum(r['amount_usdt'] for r in expense_records)

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
            "date": "本月",
            "income_usdt": round(total_income_usdt, 2),
            "income_cny": round(total_income_cny, 2),
            "income_count": len(income_records),
            "expense_usdt": round(total_expense_usdt, 2),
            "expense_count": len(expense_records),
            "pending_usdt": round(total_income_usdt - total_expense_usdt, 2),
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
        target = self._find_group(groups, group_name)

        if not target:
            available_groups = [g['title'] for g in groups[:10]]
            return {
                "error": f"未找到群组「{group_name}」",
                "available_groups": available_groups,
                "suggestion": f"可用的群组有：{', '.join(available_groups[:5])}{'...' if len(available_groups) > 5 else ''}"
            }

        records = accounting_manager.get_records_by_date(target['id'], date_str)

        if not records:
            return {
                "group_name": target['title'],
                "date": date_str,
                "message": f"{date_str} 没有记账记录",
                "income_usdt": 0,
                "expense_usdt": 0,
                "pending_usdt": 0,
                "income_count": 0,
                "expense_count": 0
            }

        income_records = [r for r in records if r['type'] == 'income']
        expense_records = [r for r in records if r['type'] == 'expense']

        total_income_usdt = sum(r['amount_usdt'] for r in income_records)
        total_income_cny = sum(r['amount'] for r in income_records)
        total_expense_usdt = sum(r['amount_usdt'] for r in expense_records)

        return {
            "group_name": target['title'],
            "date": date_str,
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

    def get_group_bill_range(self, group_name: str, start_date: str, end_date: str) -> Dict:
        """获取指定群组指定日期范围的账单"""
        groups = get_all_groups_from_db()
        target = self._find_group(groups, group_name)

        if not target:
            available_groups = [g['title'] for g in groups[:10]]
            return {
                "error": f"未找到群组「{group_name}」",
                "available_groups": available_groups,
                "suggestion": f"可用的群组有：{', '.join(available_groups[:5])}{'...' if len(available_groups) > 5 else ''}"
            }

        try:
            start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp())
            end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp()) + 86400
        except:
            return {"error": f"日期格式错误: {start_date} - {end_date}"}

        all_records = accounting_manager.get_total_records(target['id'])
        range_records = [r for r in all_records if start_ts <= r.get('created_at', 0) < end_ts]

        if not range_records:
            return {
                "group_name": target['title'],
                "date": f"{start_date} 至 {end_date}",
                "message": "该时间段没有记账记录",
                "income_usdt": 0,
                "expense_usdt": 0,
                "pending_usdt": 0,
                "income_count": 0,
                "expense_count": 0
            }

        income_records = [r for r in range_records if r['type'] == 'income']
        expense_records = [r for r in range_records if r['type'] == 'expense']

        total_income_usdt = sum(r['amount_usdt'] for r in income_records)
        total_income_cny = sum(r['amount'] for r in income_records)
        total_expense_usdt = sum(r['amount_usdt'] for r in expense_records)

        return {
            "group_name": target['title'],
            "date": f"{start_date} 至 {end_date}",
            "income_usdt": round(total_income_usdt, 2),
            "income_cny": round(total_income_cny, 2),
            "income_count": len(income_records),
            "expense_usdt": round(total_expense_usdt, 2),
            "expense_count": len(expense_records),
            "pending_usdt": round(total_income_usdt - total_expense_usdt, 2),
            "records": [
                {
                    "date": timestamp_to_date(r['created_at']),
                    "time": timestamp_to_beijing_str(r['created_at'])[-8:-3],
                    "type": r['type'],
                    "amount_usdt": round(r['amount_usdt'], 2),
                    "amount_cny": round(r['amount'], 2) if r['type'] == 'income' else None,
                    "user": r.get('display_name', ''),
                    "category": r.get('category', '')
                }
                for r in range_records[:30]
            ]
        }

    # ==================== 6. 所有群组收入 ====================

    def get_today_all_income(self) -> Dict:
        """获取所有群组今日收入统计"""
        groups = get_all_groups_from_db()
        group_details = []
        total_income_usdt = 0
        total_income_cny = 0

        for group in groups:
            try:
                stats = accounting_manager.get_today_stats(group['id'])
                if stats['income_usdt'] > 0:
                    income_usdt = stats['income_usdt']
                    income_cny = stats['income_total']
                    total_income_usdt += income_usdt
                    total_income_cny += income_cny

                    # 🔥 获取待下发金额
                    pending_stats = accounting_manager.get_current_stats(group['id'])
                    pending_usdt = pending_stats.get('pending_usdt', 0)

                    group_details.append({
                        "name": group['title'],
                        "category": group.get('category', '未分类'),
                        "income_usdt": round(income_usdt, 2),
                        "income_cny": round(income_cny, 2),
                        "income_count": stats['income_count'],
                        "pending_usdt": round(pending_usdt, 2)  # 🔥 添加待下发
                    })
            except:
                pass

        group_details.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not group_details:
            return {"message": "今日没有群组有收入记录", "groups": [], "total_income_usdt": 0}

        # 🔥 构建详细 summary
        group_list = []
        for g in group_details:
            income_cny_str = f"{int(g['income_cny'])}" if g['income_cny'] == int(g['income_cny']) else f"{g['income_cny']:.2f}"
            income_usdt_str = f"{int(g['income_usdt'])}" if g['income_usdt'] == int(g['income_usdt']) else f"{g['income_usdt']:.2f}"
            pending_str = f"{int(g['pending_usdt'])}" if g['pending_usdt'] == int(g['pending_usdt']) else f"{g['pending_usdt']:.2f}"
            group_list.append(f"• {g['name']}：{income_cny_str}元 = {income_usdt_str} USDT（待下发 {pending_str} USDT）")

        total_cny_str = f"{int(total_income_cny)}" if total_income_cny == int(total_income_cny) else f"{total_income_cny:.2f}"
        total_usdt_str = f"{int(total_income_usdt)}" if total_income_usdt == int(total_income_usdt) else f"{total_income_usdt:.2f}"

        summary = f"📊 **今日所有群组收入**\n\n💰 总收入：{total_cny_str}元 = {total_usdt_str} USDT\n📈 有收入群组：{len(group_details)}个\n\n" + "\n".join(group_list)

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "groups": group_details,
            "total_income_usdt": round(total_income_usdt, 2),
            "total_income_cny": round(total_income_cny, 2),
            "active_group_count": len(group_details),
            "summary": summary
        }

    def get_yesterday_all_income(self) -> Dict:
        """获取昨日所有群组收入统计"""
        yesterday = (beijing_now() - timedelta(days=1)).strftime('%Y-%m-%d')

        groups = get_all_groups_from_db()
        group_details = []
        total_income_usdt = 0
        total_income_cny = 0

        for group in groups:
            try:
                records = accounting_manager.get_records_by_date(group['id'], yesterday)
                income_records = [r for r in records if r['type'] == 'income']
                if income_records:
                    income_usdt = sum(r['amount_usdt'] for r in income_records)
                    income_cny = sum(r['amount'] for r in income_records)
                    total_income_usdt += income_usdt
                    total_income_cny += income_cny

                    # 🔥 获取待下发金额
                    pending_stats = accounting_manager.get_current_stats(group['id'])
                    pending_usdt = pending_stats.get('pending_usdt', 0)

                    group_details.append({
                        "name": group['title'],
                        "income_usdt": round(income_usdt, 2),
                        "income_cny": round(income_cny, 2),
                        "income_count": len(income_records),
                        "pending_usdt": round(pending_usdt, 2)  # 🔥 添加待下发
                    })
            except:
                pass

        group_details.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not group_details:
            return {"message": "昨日没有群组有收入记录", "groups": [], "total_income_usdt": 0}

        # 🔥 构建详细 summary
        group_list = []
        for g in group_details:
            income_cny_str = f"{int(g['income_cny'])}" if g['income_cny'] == int(g['income_cny']) else f"{g['income_cny']:.2f}"
            income_usdt_str = f"{int(g['income_usdt'])}" if g['income_usdt'] == int(g['income_usdt']) else f"{g['income_usdt']:.2f}"
            pending_str = f"{int(g['pending_usdt'])}" if g['pending_usdt'] == int(g['pending_usdt']) else f"{g['pending_usdt']:.2f}"
            group_list.append(f"• {g['name']}：{income_cny_str}元 = {income_usdt_str} USDT（待下发 {pending_str} USDT）")

        total_cny_str = f"{int(total_income_cny)}" if total_income_cny == int(total_income_cny) else f"{total_income_cny:.2f}"
        total_usdt_str = f"{int(total_income_usdt)}" if total_income_usdt == int(total_income_usdt) else f"{total_income_usdt:.2f}"

        summary = f"📊 **昨日所有群组收入**\n\n💰 总收入：{total_cny_str}元 = {total_usdt_str} USDT\n📈 有收入群组：{len(group_details)}个\n\n" + "\n".join(group_list)

        return {
            "date": yesterday,
            "groups": group_details,
            "total_income_usdt": round(total_income_usdt, 2),
            "total_income_cny": round(total_income_cny, 2),
            "active_group_count": len(group_details),
            "summary": summary
        }

    def get_week_all_income(self) -> Dict:
        """获取本周所有群组收入统计"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        start_ts = int(week_start.timestamp())

        group_details = []
        total_income_usdt = 0
        total_income_cny = 0

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                week_records = [r for r in records if r.get('created_at', 0) >= start_ts and r['type'] == 'income']
                if week_records:
                    income_usdt = sum(r['amount_usdt'] for r in week_records)
                    income_cny = sum(r['amount'] for r in week_records)
                    total_income_usdt += income_usdt
                    total_income_cny += income_cny

                    # 🔥 获取待下发金额
                    pending_stats = accounting_manager.get_current_stats(group['id'])
                    pending_usdt = pending_stats.get('pending_usdt', 0)

                    group_details.append({
                        "name": group['title'],
                        "income_usdt": round(income_usdt, 2),
                        "income_cny": round(income_cny, 2),
                        "income_count": len(week_records),
                        "pending_usdt": round(pending_usdt, 2)  # 🔥 添加待下发
                    })
            except:
                pass

        group_details.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not group_details:
            return {"message": "本周没有群组有收入记录", "groups": [], "total_income_usdt": 0}

        # 🔥 构建详细 summary
        group_list = []
        for g in group_details:
            income_cny_str = f"{int(g['income_cny'])}" if g['income_cny'] == int(g['income_cny']) else f"{g['income_cny']:.2f}"
            income_usdt_str = f"{int(g['income_usdt'])}" if g['income_usdt'] == int(g['income_usdt']) else f"{g['income_usdt']:.2f}"
            pending_str = f"{int(g['pending_usdt'])}" if g['pending_usdt'] == int(g['pending_usdt']) else f"{g['pending_usdt']:.2f}"
            group_list.append(f"• {g['name']}：{income_cny_str}元 = {income_usdt_str} USDT（待下发 {pending_str} USDT）")

        total_cny_str = f"{int(total_income_cny)}" if total_income_cny == int(total_income_cny) else f"{total_income_cny:.2f}"
        total_usdt_str = f"{int(total_income_usdt)}" if total_income_usdt == int(total_income_usdt) else f"{total_income_usdt:.2f}"

        summary = f"📊 **本周所有群组收入**\n\n💰 总收入：{total_cny_str}元 = {total_usdt_str} USDT\n📈 有收入群组：{len(group_details)}个\n\n" + "\n".join(group_list)

        return {
            "date": "本周",
            "groups": group_details,
            "total_income_usdt": round(total_income_usdt, 2),
            "total_income_cny": round(total_income_cny, 2),
            "active_group_count": len(group_details),
            "summary": summary
        }

    def get_month_all_income(self) -> Dict:
        """获取本月所有群组收入统计（带详细列表）"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        start_ts = int(month_start.timestamp())

        print(f"[DEBUG] 本月开始时间戳: {start_ts}, 日期: {month_start}")  # 添加

        group_details = []
        total_income_usdt = 0
        total_income_cny = 0

        for group in groups:
            try:
                records = accounting_manager.get_total_records(group['id'])
                print(f"[DEBUG] 群组 {group['title']} 总记录数: {len(records)}")  # 添加

                month_records = [r for r in records if r.get('created_at', 0) >= start_ts and r['type'] == 'income']
                print(f"[DEBUG] 群组 {group['title']} 本月入款记录数: {len(month_records)}")  # 添加

                if month_records:
                    income_usdt = sum(r['amount_usdt'] for r in month_records)
                    income_cny = sum(r['amount'] for r in month_records)
                    total_income_usdt += income_usdt
                    total_income_cny += income_cny

                    # 🔥 获取待下发金额
                    pending_stats = accounting_manager.get_current_stats(group['id'])
                    pending_usdt = pending_stats.get('pending_usdt', 0)

                    group_details.append({
                        "name": group['title'],
                        "category": group.get('category', '未分类'),
                        "income_usdt": round(income_usdt, 2),
                        "income_cny": round(income_cny, 2),
                        "income_count": len(month_records),
                        "pending_usdt": round(pending_usdt, 2)  # 🔥 添加待下发
                    })
            except:
                pass

        group_details.sort(key=lambda x: x['income_usdt'], reverse=True)

        if not group_details:
            return {"message": "本月没有群组有收入记录", "groups": [], "total_income_usdt": 0}

        # 🔥 构建详细列表字符串，包含待下发
        group_list = []
        for g in group_details:
            income_cny_str = f"{int(g['income_cny'])}" if g['income_cny'] == int(g['income_cny']) else f"{g['income_cny']:.2f}"
            income_usdt_str = f"{int(g['income_usdt'])}" if g['income_usdt'] == int(g['income_usdt']) else f"{g['income_usdt']:.2f}"
            pending_str = f"{int(g['pending_usdt'])}" if g['pending_usdt'] == int(g['pending_usdt']) else f"{g['pending_usdt']:.2f}"
            group_list.append(f"• {g['name']}：{income_cny_str}元 = {income_usdt_str} USDT（待下发 {pending_str} USDT）")

        total_cny_str = f"{int(total_income_cny)}" if total_income_cny == int(total_income_cny) else f"{total_income_cny:.2f}"
        total_usdt_str = f"{int(total_income_usdt)}" if total_income_usdt == int(total_income_usdt) else f"{total_income_usdt:.2f}"

        summary = f"📊 **本月所有群组收入**\n\n💰 总收入：{total_cny_str}元 = {total_usdt_str} USDT\n📈 有收入群组：{len(group_details)}个\n\n" + "\n".join(group_list)

        return {
            "date": "本月",
            "groups": group_details,
            "total_income_usdt": round(total_income_usdt, 2),
            "total_income_cny": round(total_income_cny, 2),
            "active_group_count": len(group_details),
            "summary": summary
        }

    # ==================== 7. 对比分析 ====================

    def get_group_compare(self, group_name: str, period: str) -> Dict:
        """获取群组的对比分析"""
        groups = get_all_groups_from_db()
        target = self._find_group(groups, group_name)

        if not target:
            return {"error": f"未找到群组「{group_name}」"}

        if period == "today_vs_yesterday":
            today_stats = accounting_manager.get_today_stats(target['id'])
            yesterday = (beijing_now() - timedelta(days=1)).strftime('%Y-%m-%d')
            yesterday_records = accounting_manager.get_records_by_date(target['id'], yesterday)
            yesterday_income = sum(r['amount_usdt'] for r in yesterday_records if r['type'] == 'income')

            change = today_stats['income_usdt'] - yesterday_income
            change_percent = (change / yesterday_income * 100) if yesterday_income > 0 else 100 if today_stats['income_usdt'] > 0 else 0

            return {
                "group_name": target['title'],
                "period": "昨天 vs 今天",
                "today_income": round(today_stats['income_usdt'], 2),
                "yesterday_income": round(yesterday_income, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 1),
                "trend": "上涨" if change >= 0 else "下跌"
            }

        elif period == "week_vs_lastweek":
            now = beijing_now()
            this_week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
            last_week_start = this_week_start - timedelta(days=7)

            this_week_ts = int(this_week_start.timestamp())
            last_week_ts = int(last_week_start.timestamp())
            last_week_end = this_week_ts

            records = accounting_manager.get_total_records(target['id'])

            this_week_income = sum(r['amount_usdt'] for r in records if r['type'] == 'income' and r.get('created_at', 0) >= this_week_ts)
            last_week_income = sum(r['amount_usdt'] for r in records if r['type'] == 'income' and last_week_ts <= r.get('created_at', 0) < last_week_end)

            change = this_week_income - last_week_income
            change_percent = (change / last_week_income * 100) if last_week_income > 0 else 100 if this_week_income > 0 else 0

            return {
                "group_name": target['title'],
                "period": "上周 vs 本周",
                "this_week_income": round(this_week_income, 2),
                "last_week_income": round(last_week_income, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 1),
                "trend": "上涨" if change >= 0 else "下跌"
            }

        elif period == "month_vs_lastmonth":
            now = beijing_now()
            this_month_start = now.replace(day=1, hour=0, minute=0, second=0)

            if now.month == 1:
                last_month_start = now.replace(year=now.year-1, month=12, day=1)
            else:
                last_month_start = now.replace(month=now.month-1, day=1)

            this_month_ts = int(this_month_start.timestamp())
            last_month_ts = int(last_month_start.timestamp())
            last_month_end = this_month_ts

            records = accounting_manager.get_total_records(target['id'])

            this_month_income = sum(r['amount_usdt'] for r in records if r['type'] == 'income' and r.get('created_at', 0) >= this_month_ts)
            last_month_income = sum(r['amount_usdt'] for r in records if r['type'] == 'income' and last_month_ts <= r.get('created_at', 0) < last_month_end)

            change = this_month_income - last_month_income
            change_percent = (change / last_month_income * 100) if last_month_income > 0 else 100 if this_month_income > 0 else 0

            return {
                "group_name": target['title'],
                "period": "上月 vs 本月",
                "this_month_income": round(this_month_income, 2),
                "last_month_income": round(last_month_income, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 1),
                "trend": "上涨" if change >= 0 else "下跌"
            }

        elif period.startswith("date_"):
            date_str = period.replace("date_", "")
            target_date = datetime.strptime(date_str, '%Y-%m-%d')
            records = accounting_manager.get_records_by_date(target['id'], date_str)
            income = sum(r['amount_usdt'] for r in records if r['type'] == 'income')

            return {
                "group_name": target['title'],
                "period": date_str,
                "income": round(income, 2),
                "income_count": len([r for r in records if r['type'] == 'income'])
            }

        return {"error": f"无法识别的对比周期: {period}"}

    def get_all_compare(self, period: str) -> Dict:
        """获取所有群组的对比分析"""
        groups = get_all_groups_from_db()

        if period == "today_vs_yesterday":
            today_total = 0
            yesterday_total = 0

            for group in groups:
                try:
                    today_stats = accounting_manager.get_today_stats(group['id'])
                    today_total += today_stats['income_usdt']

                    yesterday = (beijing_now() - timedelta(days=1)).strftime('%Y-%m-%d')
                    yesterday_records = accounting_manager.get_records_by_date(group['id'], yesterday)
                    yesterday_total += sum(r['amount_usdt'] for r in yesterday_records if r['type'] == 'income')
                except:
                    pass

            change = today_total - yesterday_total
            change_percent = (change / yesterday_total * 100) if yesterday_total > 0 else 100 if today_total > 0 else 0

            return {
                "period": "昨天 vs 今天",
                "today_total": round(today_total, 2),
                "yesterday_total": round(yesterday_total, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 1),
                "trend": "上涨" if change >= 0 else "下跌"
            }

        elif period == "week_vs_lastweek":
            now = beijing_now()
            this_week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
            last_week_start = this_week_start - timedelta(days=7)

            this_week_ts = int(this_week_start.timestamp())
            last_week_ts = int(last_week_start.timestamp())
            last_week_end = this_week_ts

            this_week_total = 0
            last_week_total = 0

            for group in groups:
                try:
                    records = accounting_manager.get_total_records(group['id'])
                    this_week_total += sum(r['amount_usdt'] for r in records if r['type'] == 'income' and r.get('created_at', 0) >= this_week_ts)
                    last_week_total += sum(r['amount_usdt'] for r in records if r['type'] == 'income' and last_week_ts <= r.get('created_at', 0) < last_week_end)
                except:
                    pass

            change = this_week_total - last_week_total
            change_percent = (change / last_week_total * 100) if last_week_total > 0 else 100 if this_week_total > 0 else 0

            return {
                "period": "上周 vs 本周",
                "this_week_total": round(this_week_total, 2),
                "last_week_total": round(last_week_total, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 1),
                "trend": "上涨" if change >= 0 else "下跌"
            }

        elif period == "month_vs_lastmonth":
            now = beijing_now()
            this_month_start = now.replace(day=1, hour=0, minute=0, second=0)

            if now.month == 1:
                last_month_start = now.replace(year=now.year-1, month=12, day=1)
            else:
                last_month_start = now.replace(month=now.month-1, day=1)

            this_month_ts = int(this_month_start.timestamp())
            last_month_ts = int(last_month_start.timestamp())
            last_month_end = this_month_ts

            this_month_total = 0
            last_month_total = 0

            for group in groups:
                try:
                    records = accounting_manager.get_total_records(group['id'])
                    this_month_total += sum(r['amount_usdt'] for r in records if r['type'] == 'income' and r.get('created_at', 0) >= this_month_ts)
                    last_month_total += sum(r['amount_usdt'] for r in records if r['type'] == 'income' and last_month_ts <= r.get('created_at', 0) < last_month_end)
                except:
                    pass

            change = this_month_total - last_month_total
            change_percent = (change / last_month_total * 100) if last_month_total > 0 else 100 if this_month_total > 0 else 0

            return {
                "period": "上月 vs 本月",
                "this_month_total": round(this_month_total, 2),
                "last_month_total": round(last_month_total, 2),
                "change": round(change, 2),
                "change_percent": round(change_percent, 1),
                "trend": "上涨" if change >= 0 else "下跌"
            }

        return {"error": f"无法识别的对比周期: {period}"}

    # ==================== 8. 待下发 ====================
    def get_pending_usdt_groups(self) -> Dict:
        """获取有待下发 USDT 的群组（查询所有历史账单）"""
        groups = get_all_groups_from_db()
        pending_groups = []
        total_pending = 0

        for group in groups:
            try:
                # 🔥 使用新方法，查询所有历史账单
                stats = accounting_manager.get_total_pending_stats(group['id'])
                if stats['pending_usdt'] > 0:
                    pending_groups.append({
                        "name": group['title'],
                        "pending_usdt": round(stats['pending_usdt'], 2)
                    })
                    total_pending += stats['pending_usdt']
            except:
                pass

        pending_groups.sort(key=lambda x: x['pending_usdt'], reverse=True)

        if not pending_groups:
            return {
                "message": "✅ 所有群组都没有待下发的 USDT",
                "pending_groups": [],
                "total_pending_usdt": 0,
                "count": 0
            }

        group_list = []
        for g in pending_groups:
            group_list.append(f"{g['name']}：{g['pending_usdt']:.0f} USDT")

        summary = f"共有 {len(pending_groups)} 个群组有待下发，总计 {total_pending:.0f} USDT\n\n" + "\n".join(group_list)

        return {
            "pending_groups": pending_groups,
            "total_pending_usdt": round(total_pending, 2),
            "count": len(pending_groups),
            "summary": summary
        }

    # ==================== 9. 操作员 ====================

    def get_operators(self) -> Dict:
        """获取操作员列表"""
        ops = list_operators()

        # 获取操作员的详细信息（昵称、用户名）
        operator_details = []
        for op_id in ops:
            details = self._get_user_details(op_id)
            operator_details.append(details)

        # 获取超级管理员信息
        owner_details = self._get_user_details(OWNER_ID)

        if not ops:
            return {
                "message": f"当前只有超级管理员，没有其他操作员",
                "owner": owner_details,
                "operators": [],
                "operator_count": 0
            }

        return {
            "owner": owner_details,
            "operators": operator_details,
            "operator_count": len(ops),
            "all_authorized": [OWNER_ID] + ops
        }

    def _get_user_details(self, user_id: int) -> Dict:
        """获取用户详细信息（从数据库或默认）"""
        # 尝试从 group_users 表获取用户信息
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT username, first_name, last_name 
                    FROM group_users 
                    WHERE user_id = ? 
                    LIMIT 1
                """, (user_id,))
                row = c.fetchone()
                if row:
                    username = row[0] or ""
                    first_name = row[1] or ""
                    last_name = row[2] or ""
                    full_name = f"{first_name} {last_name}".strip()
                    return {
                        "user_id": user_id,
                        "username": username,
                        "full_name": full_name,
                        "display_name": full_name if full_name else (f"@{username}" if username else str(user_id))
                    }
        except:
            pass

        return {
            "user_id": user_id,
            "username": None,
            "full_name": None,
            "display_name": str(user_id)
        }

    # ==================== 10. 地址相关 ====================

    async def get_address_stats(self, address: str, date_range: str = "today") -> Dict:
        """获取地址的收支统计"""
        from handlers.monitor import get_trc20_transactions, get_address_balance

        now = beijing_now()

        if date_range == "today":
            start_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            end_ts = None  # 不需要结束时间，查到现在
            period_name = "今日"
        elif date_range == "yesterday":
            yesterday = now - timedelta(days=1)
            start_ts = int(yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            end_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            period_name = "昨日"
        elif date_range == "week":
            start_ts = int((now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            end_ts = None
            period_name = "本周"
        elif date_range == "month":
            start_ts = int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            end_ts = None
            period_name = "本月"
        elif date_range == "last2days":
            start_ts = int((now - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            end_ts = None
            period_name = "最近两天"
        else:
            start_ts = 0
            end_ts = None
            period_name = "全部"

        # 🔥 修复：获取交易记录时支持结束时间
        all_txs = []
        page = 0
        limit = 200
        while True:
            txs = await get_trc20_transactions(address, start_ts, limit=limit, offset=page * limit)
            if not txs:
                break

            # 🔥 如果是昨天查询，过滤掉今天的数据
            if end_ts:
                txs = [tx for tx in txs if tx.get("block_timestamp", 0) < end_ts]

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

        balance = await get_address_balance(address)

        # 获取备注
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
            "period": period_name,
            "received_usdt": round(received, 2),
            "sent_usdt": round(sent, 2),
            "net_usdt": round(received - sent, 2),
            "balance_usdt": round(balance, 2),
            "transaction_count": len(all_txs)
        }

    async def get_address_monthly_stats(self, address: str) -> Dict:
        """获取地址的月度统计"""
        from handlers.monitor import get_address_balance, get_monthly_stats

        balance = await get_address_balance(address)
        monthly_stats = await get_monthly_stats(address)

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
            "current_balance": round(balance, 2),
            "monthly_received": round(monthly_stats.get('received', 0), 2),
            "monthly_sent": round(monthly_stats.get('sent', 0), 2),
            "monthly_net": round(monthly_stats.get('net', 0), 2)
        }

    # ==================== 11. 数据分析 ====================

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

        # 生成友好格式
        active_hours = [(h, hourly_data[h]) for h in range(24) if hourly_data[h] > 0]

        if not active_hours:
            return {"message": "今日没有入款记录", "hourly": [], "peak_hour": None}

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "hourly": [{"hour": h, "usdt": round(hourly_data[h], 2)} for h, _ in active_hours],
            "peak_hour": peak_hour,
            "peak_usdt": round(hourly_data[peak_hour], 2)
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

        if total == 0:
            return {"message": "暂无入款记录", "categories": [], "total_usdt": 0}

        categories = []
        for cat, amount in sorted(category_income.items(), key=lambda x: x[1], reverse=True):
            categories.append({
                "name": cat,
                "usdt": round(amount, 2),
                "percentage": round(amount / total * 100, 1)
            })

        return {"categories": categories, "total_usdt": round(total, 2)}

    def get_weekly_trend(self) -> Dict:
        """获取最近7天收入趋势"""
        groups = get_all_groups_from_db()
        now = beijing_now()
        daily_data = {}

        for i in range(7):
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

        if all(t['usdt'] == 0 for t in trend):
            return {"message": "最近7天没有收入记录", "trend": [], "days": 7}

        return {"trend": trend, "days": 7}

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

        if not large_transactions:
            return {"message": f"今日没有超过 {threshold} 元的大额交易", "transactions": [], "count": 0}

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "threshold": threshold,
            "transactions": large_transactions,
            "count": len(large_transactions)
        }

    def get_today_summary(self) -> Dict:
        """获取今日汇总（总入款和待下发）"""
        groups = get_all_groups_from_db()
        total_income_usdt = 0
        total_pending_usdt = 0

        for group in groups:
            try:
                stats = accounting_manager.get_today_stats(group['id'])
                total_income_usdt += stats['income_usdt']

                current_stats = accounting_manager.get_current_stats(group['id'])
                total_pending_usdt += current_stats['pending_usdt']
            except:
                pass

        return {
            "date": beijing_now().strftime('%Y-%m-%d'),
            "total_income_usdt": round(total_income_usdt, 2),
            "total_pending_usdt": round(total_pending_usdt, 2)
        }

    # ==================== 辅助方法 ====================

    def _find_group(self, groups: List[Dict], group_name: str) -> Optional[Dict]:
        """模糊匹配群组名称"""
        group_name_lower = group_name.lower()

        for group in groups:
            title_lower = group['title'].lower()
            # 完全匹配
            if group_name_lower == title_lower:
                return group
            # 包含匹配
            if group_name_lower in title_lower or title_lower in group_name_lower:
                return group

        # 尝试提取数字ID匹配
        numbers = re.findall(r'\d+', group_name)
        for num in numbers:
            for group in groups:
                if num in group['title']:
                    return group

        return None


# 全局实例
data_provider = DataProvider()
