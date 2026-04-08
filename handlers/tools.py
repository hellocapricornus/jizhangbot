# handlers/tools.py - 完整版（修复循环导入）

import re
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from db import get_all_groups_from_db, get_all_categories, get_groups_by_category

# ========== 工具定义 ==========
TOOLS = [
    # ----- 记账统计分析 -----
    {
        "type": "function",
        "function": {
            "name": "get_today_stats",
            "description": "获取指定群组今日的记账统计",
            "parameters": {"type": "object", "properties": {"group_id": {"type": "string"}}, "required": ["group_id"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_week_stats",
            "description": "获取指定群组本周的记账统计",
            "parameters": {"type": "object", "properties": {"group_id": {"type": "string"}}, "required": ["group_id"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_month_stats",
            "description": "获取指定群组本月的记账统计",
            "parameters": {"type": "object", "properties": {"group_id": {"type": "string"}}, "required": ["group_id"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_total_stats",
            "description": "获取指定群组的总记账统计",
            "parameters": {"type": "object", "properties": {"group_id": {"type": "string"}}, "required": ["group_id"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_category_stats",
            "description": "获取指定群组某个分类的入款统计",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string"},
                    "category": {"type": "string", "description": "分类名称，如'德国'、'美国'"}
                },
                "required": ["group_id", "category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_stats",
            "description": "获取指定用户在群组中的记账统计",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string"},
                    "user_name": {"type": "string", "description": "用户昵称或用户名"}
                },
                "required": ["group_id", "user_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_users",
            "description": "获取入款金额最高的用户排行",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string"},
                    "limit": {"type": "integer", "description": "返回前几名，默认5", "default": 5},
                    "period": {"type": "string", "description": "周期：today/week/month/total", "default": "today"}
                },
                "required": ["group_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_category_percentage",
            "description": "获取各分类入款的占比",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string"},
                    "period": {"type": "string", "description": "周期：today/week/month/total", "default": "today"}
                },
                "required": ["group_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_trend",
            "description": "获取最近N天的每日入款趋势",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string"},
                    "days": {"type": "integer", "description": "天数，默认7", "default": 7}
                },
                "required": ["group_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_hourly_distribution",
            "description": "获取各时段的入款分布",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string"},
                    "period": {"type": "string", "description": "周期：today/week/month", "default": "today"}
                },
                "required": ["group_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_usdt",
            "description": "获取待下发的 USDT 金额",
            "parameters": {"type": "object", "properties": {"group_id": {"type": "string"}}, "required": ["group_id"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_average_order",
            "description": "获取平均每笔入款金额",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string"},
                    "period": {"type": "string", "description": "周期：today/week/month/total", "default": "today"}
                },
                "required": ["group_id"]
            }
        }
    },

    # ----- 群组管理 -----
    {
        "type": "function",
        "function": {
            "name": "get_group_count",
            "description": "获取机器人加入的群组总数",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_groups_by_category_stats",
            "description": "获取各个分类下的群组数量统计",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_list",
            "description": "获取所有群组列表",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_group",
            "description": "根据关键词搜索群组",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_newest_groups",
            "description": "获取最近加入的群组",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 5}},
                "required": []
            }
        }
    },

    # ----- USDT 监控 -----
    {
        "type": "function",
        "function": {
            "name": "get_monitored_addresses",
            "description": "获取所有监控地址列表",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_address_by_note",
            "description": "根据备注查找监控地址",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_address_stats",
            "description": "获取指定地址的 USDT 收支统计",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "period": {"type": "string", "enum": ["today", "week", "month", "total"]}
                },
                "required": ["address"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_address_balance",
            "description": "获取指定地址的当前 USDT 余额",
            "parameters": {
                "type": "object",
                "properties": {"address": {"type": "string"}},
                "required": ["address"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_transactions",
            "description": "获取最大金额的交易记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "可选，指定地址"},
                    "limit": {"type": "integer", "default": 5},
                    "period": {"type": "string", "default": "today"}
                },
                "required": []
            }
        }
    },

    # ----- 互转分析 -----
    {
        "type": "function",
        "function": {
            "name": "analyze_transfer_relation",
            "description": "分析两个地址之间的关系，找出共同交易对手",
            "parameters": {
                "type": "object",
                "properties": {
                    "addr_a": {"type": "string"},
                    "addr_b": {"type": "string"}
                },
                "required": ["addr_a", "addr_b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_transfer_volume",
            "description": "获取两个地址之间的交易总额",
            "parameters": {
                "type": "object",
                "properties": {
                    "addr_a": {"type": "string"},
                    "addr_b": {"type": "string"}
                },
                "required": ["addr_a", "addr_b"]
            }
        }
    },
]

# ========== 辅助函数 ==========
def _get_date_range(period: str):
    """获取时间范围的时间戳（秒）"""
    from datetime import datetime, timedelta
    now = datetime.now()
    if period == "today":
        start = int(now.replace(hour=0, minute=0, second=0).timestamp())
        end = int(now.timestamp())
    elif period == "week":
        start = int((now - timedelta(days=7)).timestamp())
        end = int(now.timestamp())
    elif period == "month":
        start = int(now.replace(day=1, hour=0, minute=0, second=0).timestamp())
        end = int(now.timestamp())
    else:
        start = 0
        end = int(now.timestamp())
    return start, end

def _get_date_range(period: str) -> Tuple[int, int]:
    """获取时间范围的时间戳（毫秒）"""
    now = datetime.now()
    if period == "today":
        start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        end = int(now.timestamp() * 1000)
    elif period == "week":
        start = int((now - timedelta(days=7)).timestamp() * 1000)
        end = int(now.timestamp() * 1000)
    elif period == "month":
        start = int((now - timedelta(days=30)).timestamp() * 1000)
        end = int(now.timestamp() * 1000)
    elif period == "total":
        start = 0
        end = int(now.timestamp() * 1000)
    else:
        start = 0
        end = int(now.timestamp() * 1000)
    return start, end


def _filter_records_by_date(records: List[Dict], start_ts: int, end_ts: int) -> List[Dict]:
    """按时间筛选记录"""
    result = []
    for r in records:
        created_at = r.get('created_at', 0)
        if start_ts <= created_at <= end_ts:
            result.append(r)
    return result


def _get_period_name(period: str) -> str:
    """获取周期名称"""
    names = {
        "today": "今日",
        "week": "本周",
        "month": "本月",
        "total": "总计"
    }
    return names.get(period, "今日")


async def _get_stats_by_period(group_id: str, period: str) -> Dict:
    """通用统计获取"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return None

    if period == "today":
        stats = accounting_manager.get_today_stats(group_id)
    elif period == "total":
        stats = accounting_manager.get_total_stats(group_id)
    else:
        # 对于 week/month，需要手动筛选
        stats = accounting_manager.get_total_stats(group_id)
        records = accounting_manager.get_total_records(group_id)
        start_ts, end_ts = _get_date_range(period)
        filtered = _filter_records_by_date(records, start_ts, end_ts)

        income_total = sum(r['amount'] for r in filtered if r['type'] == 'income')
        income_usdt = sum(r['amount_usdt'] for r in filtered if r['type'] == 'income')
        income_count = len([r for r in filtered if r['type'] == 'income'])
        expense_usdt = sum(r['amount_usdt'] for r in filtered if r['type'] == 'expense')
        expense_count = len([r for r in filtered if r['type'] == 'expense'])

        return {
            'fee_rate': stats['fee_rate'],
            'exchange_rate': stats['exchange_rate'],
            'income_total': income_total,
            'income_usdt': income_usdt,
            'income_count': income_count,
            'expense_usdt': expense_usdt,
            'expense_count': expense_count,
            'pending_usdt': income_usdt - expense_usdt
        }

    return stats

# ========== 工具函数实现 ==========

async def get_today_stats(group_id: str) -> str:
    """今日统计"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        stats = await _get_stats_by_period(group_id, "today")
        if stats['income_count'] == 0 and stats['expense_count'] == 0:
            return "今日暂无记账记录"

        return (f"📊 今日账单统计：\n"
                f"• 总入款：{stats['income_total']:.2f} 元 = {stats['income_usdt']:.2f} USDT\n"
                f"• 入款笔数：{stats['income_count']} 笔\n"
                f"• 总出款：{stats['expense_usdt']:.2f} USDT\n"
                f"• 出款笔数：{stats['expense_count']} 笔\n"
                f"• 待下发：{stats['pending_usdt']:.2f} USDT")
    except Exception as e:
        return f"获取统计失败：{e}"


async def get_week_stats(group_id: str) -> str:
    """本周统计"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        stats = await _get_stats_by_period(group_id, "week")
        if stats['income_count'] == 0 and stats['expense_count'] == 0:
            return "本周暂无记账记录"

        return (f"📊 本周账单统计：\n"
                f"• 总入款：{stats['income_total']:.2f} 元 = {stats['income_usdt']:.2f} USDT\n"
                f"• 入款笔数：{stats['income_count']} 笔\n"
                f"• 总出款：{stats['expense_usdt']:.2f} USDT\n"
                f"• 出款笔数：{stats['expense_count']} 笔\n"
                f"• 待下发：{stats['pending_usdt']:.2f} USDT")
    except Exception as e:
        return f"获取统计失败：{e}"


async def get_month_stats(group_id: str) -> str:
    """本月统计"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        stats = await _get_stats_by_period(group_id, "month")
        if stats['income_count'] == 0 and stats['expense_count'] == 0:
            return "本月暂无记账记录"

        return (f"📊 本月账单统计：\n"
                f"• 总入款：{stats['income_total']:.2f} 元 = {stats['income_usdt']:.2f} USDT\n"
                f"• 入款笔数：{stats['income_count']} 笔\n"
                f"• 总出款：{stats['expense_usdt']:.2f} USDT\n"
                f"• 出款笔数：{stats['expense_count']} 笔\n"
                f"• 待下发：{stats['pending_usdt']:.2f} USDT")
    except Exception as e:
        return f"获取统计失败：{e}"


async def get_total_stats(group_id: str) -> str:
    """总计统计"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        stats = await _get_stats_by_period(group_id, "total")
        if stats['income_count'] == 0 and stats['expense_count'] == 0:
            return "暂无记账记录"

        return (f"📊 总计账单统计：\n"
                f"• 总入款：{stats['income_total']:.2f} 元 = {stats['income_usdt']:.2f} USDT\n"
                f"• 入款笔数：{stats['income_count']} 笔\n"
                f"• 总出款：{stats['expense_usdt']:.2f} USDT\n"
                f"• 出款笔数：{stats['expense_count']} 笔\n"
                f"• 待下发：{stats['pending_usdt']:.2f} USDT")
    except Exception as e:
        return f"获取统计失败：{e}"


async def get_category_stats(group_id: str, category: str) -> str:
    """分类统计"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        records = accounting_manager.get_total_records(group_id)
        income_records = [r for r in records if r['type'] == 'income' and r.get('category', '') == category]

        if not income_records:
            return f"暂无「{category}」分类的入款记录"

        total_cny = sum(r['amount'] for r in income_records)
        total_usdt = sum(r['amount_usdt'] for r in income_records)

        # 计算占比
        all_income = sum(r['amount'] for r in records if r['type'] == 'income')
        percentage = (total_cny / all_income * 100) if all_income > 0 else 0

        return (f"📊 「{category}」分类统计：\n"
                f"• 总入款：{total_cny:.2f} 元 = {total_usdt:.2f} USDT\n"
                f"• 笔数：{len(income_records)} 笔\n"
                f"• 占总入款：{percentage:.1f}%")
    except Exception as e:
        return f"获取统计失败：{e}"


async def get_user_stats(group_id: str, user_name: str) -> str:
    """用户统计"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        records = accounting_manager.get_total_records(group_id)
        user_records = [r for r in records if user_name.lower() in r.get('display_name', '').lower()]

        if not user_records:
            return f"未找到用户「{user_name}」的记账记录"

        income = sum(r['amount'] for r in user_records if r['type'] == 'income')
        income_usdt = sum(r['amount_usdt'] for r in user_records if r['type'] == 'income')
        expense = sum(r['amount_usdt'] for r in user_records if r['type'] == 'expense')
        income_count = len([r for r in user_records if r['type'] == 'income'])
        expense_count = len([r for r in user_records if r['type'] == 'expense'])

        # 获取用户实际显示名
        display_name = user_records[0].get('display_name', user_name)

        return (f"📊 用户「{display_name}」记账统计：\n"
                f"• 入款：{income:.2f} 元 = {income_usdt:.2f} USDT（{income_count}笔）\n"
                f"• 出款：{expense:.2f} USDT（{expense_count}笔）")
    except Exception as e:
        return f"获取统计失败：{e}"


async def get_top_users(group_id: str, limit: int = 5, period: str = "today") -> str:
    """入款排行"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        records = accounting_manager.get_total_records(group_id)

        # 筛选时间范围
        if period != "total":
            start_ts, end_ts = _get_date_range(period)
            records = _filter_records_by_date(records, start_ts, end_ts)

        # 统计每个用户的入款
        user_income = defaultdict(float)
        user_count = defaultdict(int)
        user_name_map = {}

        for r in records:
            if r['type'] == 'income':
                user_id = r.get('user_id')
                display_name = r.get('display_name', str(user_id))
                user_name_map[user_id] = display_name
                user_income[user_id] += r['amount']
                user_count[user_id] += 1

        if not user_income:
            return f"{_get_period_name(period)}暂无入款记录"

        # 排序取前N
        sorted_users = sorted(user_income.items(), key=lambda x: x[1], reverse=True)[:limit]

        period_name = _get_period_name(period)
        result = f"🏆 {period_name}入款排行 TOP{limit}：\n"
        for i, (user_id, amount) in enumerate(sorted_users, 1):
            name = user_name_map.get(user_id, str(user_id))
            count = user_count[user_id]
            result += f"{i}. {name}：{amount:.2f} 元（{count}笔）\n"

        return result
    except Exception as e:
        return f"获取排行失败：{e}"


async def get_category_percentage(group_id: str, period: str = "today") -> str:
    """分类占比"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        records = accounting_manager.get_total_records(group_id)

        if period != "total":
            start_ts, end_ts = _get_date_range(period)
            records = _filter_records_by_date(records, start_ts, end_ts)

        # 统计各分类入款
        category_amount = defaultdict(float)
        total = 0

        for r in records:
            if r['type'] == 'income':
                category = r.get('category', '未分类')
                if not category:
                    category = '未分类'
                category_amount[category] += r['amount']
                total += r['amount']

        if total == 0:
            return f"{_get_period_name(period)}暂无入款记录"

        # 排序
        sorted_cats = sorted(category_amount.items(), key=lambda x: x[1], reverse=True)

        period_name = _get_period_name(period)
        result = f"📊 {period_name}入款分类占比：\n"
        for category, amount in sorted_cats:
            percentage = amount / total * 100
            result += f"• {category}：{amount:.2f} 元（{percentage:.1f}%）\n"

        return result
    except Exception as e:
        return f"获取占比失败：{e}"


async def get_daily_trend(group_id: str, days: int = 7) -> str:
    """每日趋势"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        records = accounting_manager.get_total_records(group_id)

        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        start_ts = int(start_date.replace(hour=0, minute=0, second=0).timestamp())

        # 按日期统计
        daily_amount = defaultdict(float)

        for r in records:
            if r['type'] == 'income':
                created_at = r.get('created_at', 0)
                if created_at >= start_ts:
                    date_str = datetime.fromtimestamp(created_at).strftime('%Y-%m-%d')
                    daily_amount[date_str] += r['amount']

        if not daily_amount:
            return f"最近{days}天暂无入款记录"

        # 生成趋势图
        result = f"📈 最近{days}天入款趋势：\n"
        for i in range(days):
            date = (end_date - timedelta(days=days-1-i)).strftime('%Y-%m-%d')
            amount = daily_amount.get(date, 0)
            bar_length = int(amount / 100) if amount > 0 else 0
            bar = "█" * min(bar_length, 30)
            result += f"{date[5:]} {amount:>8.0f}元 {bar}\n"

        return result
    except Exception as e:
        return f"获取趋势失败：{e}"


async def get_hourly_distribution(group_id: str, period: str = "today") -> str:
    """时段分布"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        records = accounting_manager.get_total_records(group_id)

        if period != "total":
            start_ts, end_ts = _get_date_range(period)
            records = _filter_records_by_date(records, start_ts, end_ts)

        # 按时段统计
        hourly_amount = [0] * 24
        hourly_count = [0] * 24

        for r in records:
            if r['type'] == 'income':
                created_at = r.get('created_at', 0)
                hour = datetime.fromtimestamp(created_at).hour
                hourly_amount[hour] += r['amount']
                hourly_count[hour] += 1

        period_name = _get_period_name(period)

        # 找出高峰时段
        peak_hour = max(range(24), key=lambda x: hourly_amount[x])
        peak_amount = hourly_amount[peak_hour]

        result = f"⏰ {period_name}入款时段分布：\n"
        result += f"• 高峰时段：{peak_hour}:00-{peak_hour+1}:00，入款 {peak_amount:.0f} 元\n"

        # 显示活跃时段
        active_hours = [(h, hourly_amount[h]) for h in range(24) if hourly_amount[h] > 0]
        if active_hours:
            active_str = ", ".join([f"{h}:00" for h, _ in active_hours[:5]])
            result += f"• 活跃时段：{active_str}\n"

        return result
    except Exception as e:
        return f"获取时段分布失败：{e}"


async def get_pending_usdt(group_id: str) -> str:
    """待下发金额"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        stats = await _get_stats_by_period(group_id, "today")
        return f"⏳ 当前待下发：{stats['pending_usdt']:.2f} USDT"
    except Exception as e:
        return f"获取失败：{e}"


async def get_average_order(group_id: str, period: str = "today") -> str:
    """平均单笔金额"""
    from handlers.accounting import accounting_manager

    if not accounting_manager:
        return "记账模块未初始化"
    try:
        stats = await _get_stats_by_period(group_id, period)
        if stats['income_count'] == 0:
            return f"{_get_period_name(period)}暂无入款记录"

        avg = stats['income_total'] / stats['income_count']
        period_name = _get_period_name(period)

        return f"💰 {period_name}平均每笔入款：{avg:.2f} 元"
    except Exception as e:
        return f"获取失败：{e}"


# ========== 群组管理函数 ==========

async def get_group_count() -> str:
    """群组总数"""
    groups = get_all_groups_from_db()
    return f"📊 当前共加入 {len(groups)} 个群组"


async def get_groups_by_category_stats() -> str:
    """分类统计"""
    groups_by_cat = get_groups_by_category()
    categories = get_all_categories()

    if not groups_by_cat:
        return "暂无群组数据"

    result = "📊 群组分类统计：\n"
    for cat in categories:
        cat_name = cat['name']
        count = groups_by_cat.get(cat_name, 0)
        if count > 0:
            result += f"• {cat_name}：{count} 个\n"

    total = sum(groups_by_cat.values())
    result += f"\n总计：{total} 个群组"
    return result


async def get_group_list() -> str:
    """群组列表"""
    groups = get_all_groups_from_db()
    if not groups:
        return "暂无群组"

    result = "📋 群组列表：\n"
    for i, group in enumerate(groups[:15], 1):
        result += f"{i}. {group['title']} ({group.get('category', '未分类')})\n"

    if len(groups) > 15:
        result += f"\n... 还有 {len(groups) - 15} 个群组"
    return result


async def search_group(keyword: str) -> str:
    """搜索群组"""
    groups = get_all_groups_from_db()
    matched = [g for g in groups if keyword.lower() in g['title'].lower()]

    if not matched:
        return f"未找到包含「{keyword}」的群组"

    result = f"🔍 搜索「{keyword}」结果（{len(matched)}个）：\n"
    for i, group in enumerate(matched[:10], 1):
        result += f"{i}. {group['title']} ({group.get('category', '未分类')})\n"

    if len(matched) > 10:
        result += f"\n... 还有 {len(matched) - 10} 个"
    return result


async def get_newest_groups(limit: int = 5) -> str:
    """最新加入的群组"""
    groups = get_all_groups_from_db()
    if not groups:
        return "暂无群组"

    # 按 last_seen 排序
    sorted_groups = sorted(groups, key=lambda x: x.get('last_seen', 0), reverse=True)[:limit]

    result = f"🆕 最近加入的 {len(sorted_groups)} 个群组：\n"
    for i, group in enumerate(sorted_groups, 1):
        result += f"{i}. {group['title']} ({group.get('category', '未分类')})\n"

    return result


# ========== USDT 监控函数 ==========

async def get_monitored_addresses() -> str:
    """监控地址列表"""
    from db import get_monitored_addresses as get_addrs
    addresses = get_addrs()

    if not addresses:
        return "暂无监控地址"

    result = "🔔 监控地址列表：\n"
    for addr in addresses:
        short_addr = f"{addr['address'][:8]}...{addr['address'][-6:]}"
        note = f" ({addr['note']})" if addr['note'] else ""
        result += f"• {short_addr}{note} - {addr['chain_type']}\n"
    return result


async def get_address_by_note(note: str) -> str:
    """根据备注查找地址"""
    from db import get_monitored_addresses as get_addrs
    addresses = get_addrs()

    matched = [a for a in addresses if note.lower() in a.get('note', '').lower()]

    if not matched:
        return f"未找到备注为「{note}」的监控地址"

    result = f"🔍 搜索备注「{note}」结果：\n"
    for addr in matched:
        result += f"• 地址：`{addr['address']}`\n"
        result += f"  备注：{addr['note']}\n"
        result += f"  网络：{addr['chain_type']}\n"
    return result


# handlers/tools.py - 修改 get_address_stats 函数

async def get_address_stats(address: str, period: str = "today") -> str:
    """获取地址的 USDT 收支统计（分页获取全部记录）"""
    from handlers.monitor import get_trc20_transactions
    from db import get_monitored_addresses as get_addrs
    import asyncio

    start_ts, _ = _get_date_range(period)
    period_name = _get_period_name(period)

    # 分页获取所有交易记录
    all_txs = []
    page = 0
    limit = 200

    print(f"[DEBUG] 开始获取 {period_name} 交易记录，时间戳起点: {start_ts}")

    while True:
        txs = await get_trc20_transactions(address, start_ts, limit=limit, offset=page * limit)
        if not txs:
            print(f"[DEBUG] 第 {page + 1} 页无数据，停止获取")
            break

        all_txs.extend(txs)
        print(f"[DEBUG] 第 {page + 1} 页获取到 {len(txs)} 条，累计 {len(all_txs)} 条")

        # 如果返回的数量少于 limit，说明是最后一页
        if len(txs) < limit:
            break

        page += 1
        await asyncio.sleep(0.1)  # 避免请求过快

    print(f"[DEBUG] 共获取 {len(all_txs)} 条交易记录")

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

    profit = received - sent

    # 获取备注
    addresses = get_addrs()
    note = ""
    for a in addresses:
        if a['address'] == address:
            note = a.get('note', '')
            break

    short_addr = f"{address[:8]}...{address[-6:]}"
    addr_display = f"{short_addr} ({note})" if note else short_addr

    return (f"💰 地址 {addr_display} {period_name}统计：\n\n"
            f"• 收到：{received:.2f} USDT\n"
            f"• 转出：{sent:.2f} USDT\n"
            f"• 净收入：{profit:.2f} USDT\n"
            f"• 交易笔数：{len(all_txs)} 笔")


async def get_address_balance(address: str) -> str:
    """地址余额"""
    from handlers.monitor import get_address_balance as get_balance
    from db import get_monitored_addresses as get_addrs

    balance = await get_balance(address)

    if balance is None:
        return f"查询地址余额失败"

    addresses = get_addrs()
    note = ""
    for a in addresses:
        if a['address'] == address:
            note = a.get('note', '')
            break

    short_addr = f"{address[:8]}...{address[-6:]}"
    addr_display = f"{short_addr} ({note})" if note else short_addr

    return f"💰 地址 {addr_display} 当前余额：{balance:.2f} USDT"


async def get_top_transactions(address: str = None, limit: int = 5, period: str = "today") -> str:
    """大额交易"""
    from handlers.monitor import get_trc20_transactions
    from db import get_monitored_addresses as get_addrs

    start_ts, _ = _get_date_range(period)
    period_name = _get_period_name(period)

    if address:
        txs = await get_trc20_transactions(address, start_ts)
        # 获取备注
        addresses = get_addrs()
        note = ""
        for a in addresses:
            if a['address'] == address:
                note = a.get('note', '')
                break
        short_addr = f"{address[:8]}...{address[-6:]}"
        title = f"地址 {short_addr} ({note})" if note else f"地址 {short_addr}"
    else:
        # 获取所有监控地址的交易
        addresses = get_addrs()
        all_txs = []
        for addr_info in addresses:
            txs = await get_trc20_transactions(addr_info['address'], start_ts)
            for tx in txs:
                tx['address_note'] = addr_info.get('note', '')
            all_txs.extend(txs)
        txs = all_txs
        title = "所有监控地址"

    if not txs:
        return f"{title} {period_name}暂无交易记录"

    # 按金额排序
    for tx in txs:
        raw_amount = tx.get("value", 0)
        tx['amount_usdt'] = int(raw_amount) / 1_000_000 if raw_amount else 0

    sorted_txs = sorted(txs, key=lambda x: x.get('amount_usdt', 0), reverse=True)[:limit]

    result = f"💰 {title} {period_name}大额交易 TOP{limit}：\n"
    for i, tx in enumerate(sorted_txs, 1):
        amount = tx.get('amount_usdt', 0)
        to_addr = tx.get("to", "")
        from_addr = tx.get("from", "")
        direction = "收到" if to_addr == address else "转出" if address else "交易"
        result += f"{i}. {direction} {amount:.2f} USDT\n"

    return result


# ========== 互转分析函数 ==========

async def analyze_transfer_relation(addr_a: str, addr_b: str) -> str:
    """分析地址关系"""
    from handlers.transfer import get_trc20_transfers, extract_counterparties

    history_a = get_trc20_transfers(addr_a, limit=200)
    history_b = get_trc20_transfers(addr_b, limit=200)

    set_a = extract_counterparties(history_a, addr_a)
    set_b = extract_counterparties(history_b, addr_b)

    common = list(set_a.intersection(set_b))
    common = [c for c in common if c != addr_a and c != addr_b]

    short_a = f"{addr_a[:8]}...{addr_a[-6:]}"
    short_b = f"{addr_b[:8]}...{addr_b[-6:]}"

    if not common:
        return f"地址 {short_a} 和 {short_b} 没有共同交易对手"

    result = f"🕸️ 地址 {short_a} 和 {short_b} 的共同交易对手：\n"
    for i, addr in enumerate(common[:10], 1):
        short_addr = f"{addr[:8]}...{addr[-6:]}"
        result += f"{i}. `{short_addr}`\n"

    if len(common) > 10:
        result += f"\n... 还有 {len(common) - 10} 个"

    return result


async def get_transfer_volume(addr_a: str, addr_b: str) -> str:
    """两地址间交易总额"""
    from handlers.transfer import get_trc20_transfers

    history = get_trc20_transfers(addr_a, limit=200)

    total = 0.0
    count = 0

    for tx in history:
        if tx.get("to") == addr_b or tx.get("from") == addr_b:
            raw_amount = tx.get("value", 0)
            amount = int(raw_amount) / 1_000_000 if raw_amount else 0
            total += amount
            count += 1

    short_a = f"{addr_a[:8]}...{addr_a[-6:]}"
    short_b = f"{addr_b[:8]}...{addr_b[-6:]}"

    if count == 0:
        return f"地址 {short_a} 和 {short_b} 之间没有直接转账记录"

    return f"💰 地址 {short_a} 和 {short_b} 之间共交易 {count} 笔，总额 {total:.2f} USDT"


# ========== 工具名称到函数的映射 ==========
TOOL_FUNCTIONS = {
    # 记账
    "get_today_stats": get_today_stats,
    "get_week_stats": get_week_stats,
    "get_month_stats": get_month_stats,
    "get_total_stats": get_total_stats,
    "get_category_stats": get_category_stats,
    "get_user_stats": get_user_stats,
    "get_top_users": get_top_users,
    "get_category_percentage": get_category_percentage,
    "get_daily_trend": get_daily_trend,
    "get_hourly_distribution": get_hourly_distribution,
    "get_pending_usdt": get_pending_usdt,
    "get_average_order": get_average_order,
    # 群组
    "get_group_count": get_group_count,
    "get_groups_by_category_stats": get_groups_by_category_stats,
    "get_group_list": get_group_list,
    "search_group": search_group,
    "get_newest_groups": get_newest_groups,
    # USDT
    "get_monitored_addresses": get_monitored_addresses,
    "get_address_by_note": get_address_by_note,
    "get_address_stats": get_address_stats,
    "get_address_balance": get_address_balance,
    "get_top_transactions": get_top_transactions,
    # 互转
    "analyze_transfer_relation": analyze_transfer_relation,
    "get_transfer_volume": get_transfer_volume,
}
