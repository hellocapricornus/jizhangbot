# handlers/profile.py
import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from handlers.menu import get_main_menu
from auth import is_authorized, OWNER_ID
from db import get_monitored_addresses, get_user_preferences, set_user_preference
from handlers.accounting import get_today_beijing
from handlers.monitor import get_monthly_stats, get_trc20_transactions, get_address_balance
from logger import bot_logger as logger

# 状态定义
PROFILE_MAIN = 1
SET_SIGNATURE = 2
FEEDBACK = 3
EXPORT_DATA = 4
# ========== 规则管理状态 ==========
RULE_MENU = 5
RULE_ADD_NAME = 6
RULE_ADD_CONTENT = 7
RULE_UPDATE_SELECT = 8
RULE_UPDATE_CONTENT = 9
RULE_DELETE_SELECT = 10
RULE_TOGGLE_SELECT = 11
RULE_VIEW = 12

# ========== 业绩汇总状态 ==========
PERFORMANCE_MENU = 17
PERFORMANCE_RECORD = 18
PERFORMANCE_VIEW = 19
PERFORMANCE_MONTH_SELECT = 20
PERFORMANCE_EDIT = 21
PERFORMANCE_DELETE = 22

def _is_keyboard_button(text: str) -> bool:
    """检查是否是键盘按钮"""
    keyboard_buttons = {
        "◀️ 返回主菜单", "📒 记账", "🔔 USDT监控", "📢 群发", "💰 USDT查询",
        "👤 操作人管理", "🔄 互转查询", "📁 群组管理", "📖 使用说明", "👤 个人中心",
        "➕ 添加操作人", "➖ 删除操作人", "📋 操作人列表", "🔄 更新操作人信息", "👥 临时操作人",
        "➕ 添加临时操作人", "➖ 删除临时操作人", "📋 临时操作人列表", "◀️ 返回操作人管理",
        "➕ 添加监控地址", "📋 监控列表", "📊 月度统计", "❌ 删除监控地址",
        "📊 群组统计", "📁 查看分类", "➕ 创建分类", "🏷️ 设置群组分类", "🗑️ 删除分类",
        "🔍 转账查询", "🕸️ 转账分析",
    }
    return text in keyboard_buttons
    
# ---------- 辅助：构建个人中心菜单 ----------
async def _build_profile_menu(user_id: int, prefs: dict = None, display_name: str = "") -> tuple:
    """返回 (消息文本, InlineKeyboardMarkup)"""
    if prefs is None:
        prefs = get_user_preferences(user_id)

    full_access = is_authorized(user_id, require_full_access=True)
    limited_access = is_authorized(user_id, require_full_access=False) and not full_access  # 临时操作员
    # 普通用户: not is_authorized at all

    # 获取监控地址数量
    addresses = get_monitored_addresses(user_id=user_id)

    # 身份文本
    if user_id == OWNER_ID:
        role = "👑 控制人"
    elif full_access:
        role = "👤 正式操作员"
    elif limited_access:
        role = "👥 临时操作员"
    else:
        role = "🙍 普通用户"

    keyboard = []

    # 个人记账统计：控制人、正式操作员、临时操作员可见
    if full_access or limited_access:
        keyboard.append([InlineKeyboardButton("📊 个人记账统计", callback_data="profile_stats")])

    # 我的监控地址：仅完整权限可见
    if full_access:
        keyboard.append([InlineKeyboardButton("📁 我的监控地址", callback_data="profile_addresses")])

    # 监控交易提醒：仅完整权限且添加了监控地址时显示
    if full_access and addresses:
        notify = "🟢 已开启" if prefs["monitor_notify"] else "🔴 已关闭"
        keyboard.append([InlineKeyboardButton(f"🔔 监控交易提醒：{notify}", callback_data="profile_toggle_notify")])

    # 联系管理员、发送反馈：非超级管理员可见
    if user_id != OWNER_ID:
        keyboard.append([InlineKeyboardButton("📞 联系管理员", callback_data="profile_contact")])
        keyboard.append([InlineKeyboardButton("💬 发送反馈", callback_data="profile_feedback")])

    # 默认群发附言、数据分析导出：仅完整权限
    if full_access:
        keyboard.append([InlineKeyboardButton("📝 默认群发附言", callback_data="profile_signature")])
        # 早报：仅完整权限可见
        if is_authorized(user_id, require_full_access=True):
            prefs_early = prefs if prefs else get_user_preferences(user_id)
            report_enabled = prefs_early.get('daily_report_enabled', False)
            status = "🟢 已开启" if report_enabled else "🔴 已关闭"
            keyboard.append([InlineKeyboardButton(f"📋 每日早报 {status}", callback_data="profile_report_toggle")])
        keyboard.append([InlineKeyboardButton("📈 数据分析导出", callback_data="profile_export")])

    # ========== 规则管理（仅完整权限可见） ==========
    if full_access:
        from db import get_all_rules
        rules = get_all_rules(active_only=True)
        rule_count = len(rules)
        keyboard.append([InlineKeyboardButton(f"📋 规则管理（{rule_count}个）", callback_data="profile_rules_menu")])

    # ========== 业绩汇总（所有有权限的人可见） ==========
    if full_access:
        keyboard.append([InlineKeyboardButton("📊 业绩汇总", callback_data="profile_performance_menu")])

    keyboard.append([InlineKeyboardButton("◀️ 返回主菜单", callback_data="profile_back")])

    # 构建提示文本
    if full_access and addresses:
        notify_status = f"📢 监控交易提醒：{'🟢 已开启' if prefs['monitor_notify'] else '🔴 已关闭'}\n"
    else:
        notify_status = ""
    user_info_line = f"👤 用户名：{display_name}\n" if display_name else ""
    text = (f"👤 个人中心\n\n"
            f"{user_info_line}"
            f"🆔 用户 ID：`{user_id}`\n"
            f"🏷️ 当前身份：{role}\n"
            f"{notify_status}"
            )
    return text, InlineKeyboardMarkup(keyboard)

# ---------- 入口 ----------
async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """个人中心入口，支持消息和回调"""
    context.user_data.pop("profile_input_state", None)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user = query.from_user
        msg = query.message
    else:
        user = update.effective_user
        msg = update.message

    user_id = user.id
    display_name = user.username or user.first_name or ""
    prefs = get_user_preferences(user_id)
    text, markup = await _build_profile_menu(user_id, prefs, display_name)

    if update.callback_query:
        await msg.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await msg.reply_text(text, reply_markup=markup, parse_mode="Markdown")

    return PROFILE_MAIN


# ---------- 个人记账统计 ----------
async def profile_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    from handlers.accounting import accounting_manager
    if not accounting_manager:
        await query.message.edit_text("❌ 记账模块未初始化")
        return

    from db import get_all_groups_from_db
    groups = get_all_groups_from_db()

    total_income_cny = 0.0
    total_income_usdt = 0.0
    total_income_count = 0
    total_expense_usdt = 0.0
    total_expense_count = 0
    today = get_today_beijing()
    today_income = 0.0
    month_income = 0.0
    now = datetime.now()

    for g in groups:
        records = accounting_manager.get_total_records(g['id'])
        for r in records:
            if r.get('user_id') != user_id:
                continue
            if r['type'] == 'income':
                total_income_cny += r['amount']
                total_income_usdt += r['amount_usdt']
                total_income_count += 1
                ts = r.get('created_at')
                if ts:
                    dt = datetime.fromtimestamp(ts)
                    if dt.strftime('%Y-%m-%d') == today:
                        today_income += r['amount']
                    if dt.year == now.year and dt.month == now.month:
                        month_income += r['amount']
            else:
                total_expense_usdt += r['amount_usdt']
                total_expense_count += 1

    text = "📊 个人记账统计（所有群组）\n\n"
    text += f"• 今日入款：{today_income:.2f} 元\n"
    text += f"• 本月入款：{month_income:.2f} 元\n"
    text += f"• 总入款：{total_income_cny:.2f} 元（{total_income_count}笔）\n"
    text += f"• 总入款(USDT)：{total_income_usdt:.2f} USDT\n"
    text += f"• 总出款：{total_expense_usdt:.2f} USDT（{total_expense_count}笔）\n"
    text += "\n💡 数据包含所有群组，未区分未结算会话。"

    await query.message.edit_text(text, parse_mode="Markdown")


# ---------- 我的监控地址 ----------
async def profile_addresses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    addresses = get_monitored_addresses(user_id=user_id)
    if not addresses:
        await query.message.edit_text("📭 您还没有添加监控地址")
        return

    text = "📁 我的监控地址\n\n"
    for addr in addresses:
        stats = await get_monthly_stats(addr['address'])
        note = f" ({addr['note']})" if addr['note'] else ""
        short = f"{addr['address'][:8]}...{addr['address'][-6:]}"
        text += f"📌 {short}{note}\n"
        text += f"   ⛓️ {addr['chain_type']}  |  本月净收入：{stats['net']:.2f} USDT\n\n"

    await query.message.edit_text(text, parse_mode="Markdown")


# ---------- 通知开关 ----------
async def profile_toggle_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    display_name = query.from_user.username or query.from_user.first_name or ""
    await query.answer()

    prefs = get_user_preferences(user_id)
    new_state = not prefs["monitor_notify"]
    set_user_preference(user_id, "monitor_notify", new_state)

    prefs = get_user_preferences(user_id)
    text, markup = await _build_profile_menu(user_id, prefs, display_name)
    await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")


# ---------- 默认群发附言 ----------
async def profile_signature_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    prefs = get_user_preferences(user_id)
    current_sig = prefs.get("broadcast_signature", "")
    if current_sig:
        hint = f"当前附言：\n「{current_sig}」\n\n"
    else:
        hint = "当前没有默认附言。\n\n"

    context.user_data["profile_input_state"] = True

    await query.message.edit_text(
        hint +
        "📝 请发送新的附言内容（直接发送文字即可）。\n"
        "若要去除附言，请发送 /remove\n"
        "取消请发送 /cancel",
        parse_mode="Markdown"
    )
    return SET_SIGNATURE


async def profile_signature_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    display_name = update.effective_user.username or update.effective_user.first_name or ""
    text = update.message.text.strip()

    if text == '/cancel':
        await update.message.reply_text("❌ 已取消")
        prefs = get_user_preferences(user_id)
        _, markup = await _build_profile_menu(user_id, prefs)
        await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
        return ConversationHandler.END

    if text == '/remove':
        set_user_preference(user_id, "broadcast_signature", "")
        await update.message.reply_text("✅ 默认附言已删除")
    else:
        set_user_preference(user_id, "broadcast_signature", text)
        await update.message.reply_text(f"✅ 默认附言已设置为：\n附言：{text}")

    prefs = get_user_preferences(user_id)
    _, markup = await _build_profile_menu(user_id, prefs, display_name)
    await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END


# ---------- 联系管理员 ----------
async def profile_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        f"📞 管理员：@ChineseNo1\n"
        f"或直接私聊 [点击联系](tg://user?id={OWNER_ID})",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


# ---------- 发送反馈 ----------
async def profile_feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["profile_input_state"] = True
    await query.message.edit_text(
        "💬 请输入您的反馈内容（支持文字）。\n发送 /cancel 取消。",
        parse_mode="Markdown"
    )
    return FEEDBACK


async def profile_feedback_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    display_name = user.username or user.first_name or ""
    text = update.message.text.strip()

    if text == '/cancel':
        await update.message.reply_text("❌ 已取消")
        prefs = get_user_preferences(user.id)
        _, markup = await _build_profile_menu(user_id, prefs, display_name)
        await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
        return ConversationHandler.END

    feedback_msg = (
        f"📨 用户反馈\n"
        f"来自：{user.mention_html()}\n"
        f"内容：{text}"
    )
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=feedback_msg, parse_mode="HTML")
        await update.message.reply_text("✅ 反馈已发送，感谢您的意见！")
    except Exception as e:
        await update.message.reply_text(f"❌ 发送失败：{e}")

    prefs = get_user_preferences(user.id)
    _, markup = await _build_profile_menu(user.id, prefs, display_name)
    await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END


# ================== 数据分析导出相关函数 ==================
def _get_period_timestamps(period: str, now: datetime):
    """根据周期返回毫秒级时间戳范围"""
    beijing_tz = now.tzinfo if now.tzinfo else timezone(timedelta(hours=8))
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        start = today_start
    elif period == "week":
        start = today_start - timedelta(days=now.weekday())
    elif period == "month":
        start = today_start.replace(day=1)
    elif period == "year":
        start = today_start.replace(month=1, day=1)
    else:
        start = today_start
    return int(start.timestamp() * 1000), int(now.timestamp() * 1000)


# ---------- 数据分析导出 ----------
async def profile_export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    await query.message.edit_text("⏳ 正在生成数据分析报告，请稍候...")

    from handlers.accounting import accounting_manager
    if not accounting_manager:
        await query.message.edit_text("❌ 记账模块未初始化")
        return

    from db import get_all_groups_from_db, get_monitored_addresses
    from auth import list_operators, OWNER_ID
    from auth import is_authorized as auth_is_authorized

    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now().astimezone(beijing_tz)
    is_owner = (user_id == OWNER_ID)

    # 身份
    if is_owner:
        role = "超级管理员"
        identity_color = "#e74c3c"
    elif auth_is_authorized(user_id, require_full_access=True):
        role = "正式操作员"
        identity_color = "#3498db"
    elif auth_is_authorized(user_id, require_full_access=False):
        role = "临时操作员"
        identity_color = "#f39c12"
    else:
        role = "普通用户"
        identity_color = "#95a5a6"

    # ---------- 记账数据（含群组明细） ----------
    all_groups = get_all_groups_from_db()
    records = []
    period_income_cny = {"today": 0.0, "week": 0.0, "month": 0.0, "total": 0.0}
    period_income_usdt = {"today": 0.0, "week": 0.0, "month": 0.0, "total": 0.0}
    period_expense = {"today": 0.0, "week": 0.0, "month": 0.0, "total": 0.0}

    group_detail = {"today": {}, "week": {}, "month": {}, "total": {}}
    today_str = now.strftime('%Y-%m-%d')

    for g in all_groups:
        gname = g['title']
        recs = accounting_manager.get_total_records(g['id'])
        if not is_owner:
            recs = [r for r in recs if r.get('user_id') == user_id]
        for r in recs:
            date = r.get('date', '')
            if r['type'] == 'income':
                cny = r['amount']
                usdt = r['amount_usdt']
                if date == today_str:
                    period_income_cny["today"] += cny
                    period_income_usdt["today"] += usdt
                    d = group_detail["today"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})
                    d["income_cny"] += cny
                    d["income_usdt"] += usdt
                dt = datetime.strptime(date, '%Y-%m-%d') if date and date != '' else None
                if dt:
                    if dt.isocalendar()[1] == now.isocalendar()[1] and dt.year == now.year:
                        period_income_cny["week"] += cny
                        period_income_usdt["week"] += usdt
                        dw = group_detail["week"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})
                        dw["income_cny"] += cny
                        dw["income_usdt"] += usdt
                    if dt.month == now.month and dt.year == now.year:
                        period_income_cny["month"] += cny
                        period_income_usdt["month"] += usdt
                        dm = group_detail["month"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})
                        dm["income_cny"] += cny
                        dm["income_usdt"] += usdt
                period_income_cny["total"] += cny
                period_income_usdt["total"] += usdt
                dtot = group_detail["total"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})
                dtot["income_cny"] += cny
                dtot["income_usdt"] += usdt
            else:
                usdt = r['amount_usdt']
                if date == today_str:
                    period_expense["today"] += usdt
                    group_detail["today"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})["expense"] += usdt
                dt = datetime.strptime(date, '%Y-%m-%d') if date and date != '' else None
                if dt:
                    if dt.isocalendar()[1] == now.isocalendar()[1] and dt.year == now.year:
                        period_expense["week"] += usdt
                        group_detail["week"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})["expense"] += usdt
                    if dt.month == now.month and dt.year == now.year:
                        period_expense["month"] += usdt
                        group_detail["month"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})["expense"] += usdt
                period_expense["total"] += usdt
                group_detail["total"].setdefault(gname, {"income_cny": 0.0, "income_usdt": 0.0, "expense": 0.0})["expense"] += usdt

    # 将群组明细转为列表
    def format_group_detail(detail):
        res = []
        for gname, v in sorted(detail.items(), key=lambda x: x[1].get("income_cny", 0), reverse=True):
            res.append({
                "name": gname,
                "income_cny": round(v.get("income_cny", 0.0), 2),
                "income_usdt": round(v.get("income_usdt", 0.0), 2),
                "expense": round(v.get("expense", 0.0), 2),
                "pending": round(v.get("income_usdt", 0.0) - v.get("expense", 0.0), 2)
            })
        return res

    accounting_tabs = {
        "today": {
            "income_cny": round(period_income_cny["today"], 2),
            "income_usdt": round(period_income_usdt["today"], 2),
            "expense": round(period_expense["today"], 2),
            "pending": round(period_income_usdt["today"] - period_expense["today"], 2),
            "groups": format_group_detail(group_detail["today"])
        },
        "week": {
            "income_cny": round(period_income_cny["week"], 2),
            "income_usdt": round(period_income_usdt["week"], 2),
            "expense": round(period_expense["week"], 2),
            "pending": round(period_income_usdt["week"] - period_expense["week"], 2),
            "groups": format_group_detail(group_detail["week"])
        },
        "month": {
            "income_cny": round(period_income_cny["month"], 2),
            "income_usdt": round(period_income_usdt["month"], 2),
            "expense": round(period_expense["month"], 2),
            "pending": round(period_income_usdt["month"] - period_expense["month"], 2),
            "groups": format_group_detail(group_detail["month"])
        },
        "total": {
            "income_cny": round(period_income_cny["total"], 2),
            "income_usdt": round(period_income_usdt["total"], 2),
            "expense": round(period_expense["total"], 2),
            "pending": round(period_income_usdt["total"] - period_expense["total"], 2),
            "groups": format_group_detail(group_detail["total"])
        }
    }

    # 30天趋势图数据
    daily_income = {}
    daily_expense = {}
    for r in records:
        date = r.get('date', '')
        if r['type'] == 'income':
            daily_income[date] = daily_income.get(date, 0.0) + r['amount']
        else:
            daily_expense[date] = daily_expense.get(date, 0.0) + r['amount_usdt']

    date_list = [(now - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(29, -1, -1)]
    income_series = [round(daily_income.get(d, 0.0), 2) for d in date_list]
    expense_series = [round(daily_expense.get(d, 0.0), 2) for d in date_list]

    # ---------- USDT 监控地址 ----------
    if is_owner:
        my_addresses = get_monitored_addresses()
    else:
        my_addresses = get_monitored_addresses(user_id=user_id)

    addr_stats = []
    for addr in my_addresses:
        address = addr['address']
        note = addr.get('note', '')

        async def fetch_period(period):
            start_ms, end_ms = _get_period_timestamps(period, now)
            txs = await get_trc20_transactions(address, start_ms)
            received = 0.0
            sent = 0.0
            for tx in txs:
                raw_amount = tx.get("value", 0)
                amount = int(raw_amount) / 1_000_000 if raw_amount else 0
                to_addr = tx.get("to", "")
                if to_addr == address:
                    received += amount
                else:
                    sent += amount
            return received, sent, received - sent

        p = {}
        for period in ["today", "week", "month", "year"]:
            p[period] = await fetch_period(period)

        addr_stats.append({
            "address": address,          # 完整地址
            "note": note,
            "periods": p,
        })

    # 地址统计数据结构
    address_tabs = {}
    for period in ["today", "week", "month", "year"]:
        address_tabs[period] = [{
            "address": a["address"],
            "note": a["note"],
            "received": round(a["periods"][period][0], 2),
            "sent": round(a["periods"][period][1], 2),
            "net": round(a["periods"][period][2], 2)
        } for a in addr_stats]

    # ---------- 群组加入统计（含详细列表） ----------
    group_join_detail = {"today": [], "week": [], "month": [], "year": []}
    for g in all_groups:
        jt = g.get('joined_at', 0)
        if jt:
            dt = datetime.fromtimestamp(jt, tz=beijing_tz)
            info = {"name": g['title'], "joined_at": dt.strftime('%Y-%m-%d %H:%M'), "category": g.get('category', '未分类')}
            if dt.date() == now.date():
                group_join_detail["today"].append(info)
            if dt.isocalendar()[1] == now.isocalendar()[1] and dt.year == now.year:
                group_join_detail["week"].append(info)
            if dt.month == now.month and dt.year == now.year:
                group_join_detail["month"].append(info)
            if dt.year == now.year:
                group_join_detail["year"].append(info)

    groups_data = {
        "today": {"count": len(group_join_detail["today"]), "list": group_join_detail["today"]},
        "week": {"count": len(group_join_detail["week"]), "list": group_join_detail["week"]},
        "month": {"count": len(group_join_detail["month"]), "list": group_join_detail["month"]},
        "year": {"count": len(group_join_detail["year"]), "list": group_join_detail["year"]}
    }

    # ---------- 操作人列表 ----------
    operator_list = []
    if is_owner or auth_is_authorized(user_id, require_full_access=True):
        ops = list_operators()
        from auth import temp_operators
        for op_id, info in ops.items():
            operator_list.append(f"{info.get('first_name','')} (@{info.get('username','')}) - 正式操作员")
        for temp_id, info in temp_operators.items():
            operator_list.append(f"{info.get('first_name','')} (@{info.get('username','')}) - 临时操作员")
    else:
        operator_list.append("您没有权限查看操作人列表")

    # ---------- 生成 HTML ----------
    html = _build_beautiful_html(
        user_id=user_id,
        role=role,
        identity_color=identity_color,
        accounting_tabs=accounting_tabs,
        chart_data={"dates": date_list, "income": income_series, "expense": expense_series},
        address_tabs=address_tabs,
        groups_data=groups_data,
        operators=operator_list,
    )

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
        f.write(html)
        temp_path = f.name
    await query.message.reply_document(
        document=open(temp_path, 'rb'),
        filename="数据分析报告.html",
        caption="📈 您的个人数据分析报告"
    )
    os.unlink(temp_path)

def _build_beautiful_html(user_id, role, identity_color, accounting_tabs, chart_data, address_tabs, groups_data, operators):
    import json as _json

    def safe_serialize(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return str(obj)

    acc_json = _json.dumps(accounting_tabs, default=safe_serialize)
    addr_json = _json.dumps(address_tabs, default=safe_serialize)
    grp_json = _json.dumps(groups_data, default=safe_serialize)
    trend_json = _json.dumps(chart_data, default=safe_serialize)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>数据分析报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #f0f2f5; color: #333; line-height: 1.6; -webkit-text-size-adjust: 100%;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; padding: 16px 12px 60px; }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 28px 20px; border-radius: 20px;
            margin-bottom: 20px; box-shadow: 0 8px 24px rgba(102,126,234,0.3);
        }}
        .header h1 {{ font-size: 24px; margin-bottom: 6px; }}
        .header .sub {{ opacity: 0.9; font-size: 14px; }}
        .identity-badge {{
            display: inline-block; padding: 4px 14px; border-radius: 20px;
            color: white; background: {identity_color}; font-weight: 600; margin-top: 10px; font-size: 13px;
        }}
        .card {{
            background: white; border-radius: 16px; padding: 18px 14px; margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.04);
        }}
        .card h2 {{ margin: 0 0 12px 0; font-size: 18px; color: #1e293b; display: flex; align-items: center; }}
        .card h2 .icon {{ margin-right: 8px; font-size: 20px; }}
        .tabs {{ display: flex; gap: 6px; margin-bottom: 16px; flex-wrap: wrap; }}
        .tab-btn {{
            padding: 7px 14px; border: none; border-radius: 20px; background: #e2e8f0;
            color: #475569; font-weight: 600; cursor: pointer; transition: 0.2s; font-size: 14px;
            touch-action: manipulation; user-select: none; -webkit-tap-highlight-color: transparent;
        }}
        .tab-btn.active {{ background: #667eea; color: white; }}
        .summary-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 12px; margin-bottom: 20px;
        }}
        .summary-item {{
            background: #f8fafc; border-radius: 12px; padding: 14px 10px; text-align: center;
            border: 1px solid #e2e8f0;
        }}
        .summary-item .label {{ font-size: 12px; color: #64748b; margin-bottom: 6px; }}
        .summary-item .value {{ font-size: 18px; font-weight: 700; }}
        .positive {{ color: #16a34a; }}
        .negative {{ color: #dc2626; }}
        .chart-container {{ position: relative; width: 100%; max-height: 300px; margin: 16px 0; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }}
        th, td {{ padding: 8px 6px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
        th {{ background: #f9fafb; font-weight: 600; color: #374151; white-space: nowrap; }}
        td {{ vertical-align: middle; }}
        .table-responsive {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 0 -4px; padding: 0 4px; }}
        ul {{ padding-left: 20px; }}
        .footer {{ text-align: center; color: #94a3b8; margin-top: 30px; font-size: 12px; }}
        @media (max-width: 640px) {{
            .header h1 {{ font-size: 20px; }}
            .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 数据分析报告</h1>
        <div class="sub">用户ID: {user_id} | 身份: <span class="identity-badge">{role}</span></div>
    </div>

    <!-- 记账总览 -->
    <div class="card">
        <h2><span class="icon">💰</span>记账总览</h2>
        <div class="tabs" id="accountTabs">
            <button class="tab-btn active" data-period="today">今日</button>
            <button class="tab-btn" data-period="week">本周</button>
            <button class="tab-btn" data-period="month">本月</button>
            <button class="tab-btn" data-period="total">总计</button>
        </div>
        <div id="accountTabContent">加载中...</div>
        <div class="chart-container">
            <canvas id="trendChart"></canvas>
        </div>
    </div>

    <!-- USDT 地址统计 -->
    <div class="card">
        <h2><span class="icon">🪙</span>USDT 地址统计</h2>
        <div class="tabs" id="addressTabs">
            <button class="tab-btn active" data-period="today">今日</button>
            <button class="tab-btn" data-period="week">本周</button>
            <button class="tab-btn" data-period="month">本月</button>
            <button class="tab-btn" data-period="year">本年</button>
        </div>
        <div id="addressTabContent">加载中...</div>
        <div class="chart-container">
            <canvas id="addressChart"></canvas>
        </div>
    </div>

    <!-- 群组加入统计 -->
    <div class="card">
        <h2><span class="icon">📁</span>群组加入统计</h2>
        <div class="tabs" id="groupTabs">
            <button class="tab-btn active" data-period="today">今日加入</button>
            <button class="tab-btn" data-period="week">本周加入</button>
            <button class="tab-btn" data-period="month">本月加入</button>
            <button class="tab-btn" data-period="year">本年加入</button>
        </div>
        <div id="groupTabContent">加载中...</div>
    </div>

    <!-- 操作人列表 -->
    <div class="card">
        <h2><span class="icon">👥</span>操作人列表</h2>
        <ul>{''.join(f'<li>{op}</li>' for op in operators)}</ul>
    </div>

    <div class="footer">由记账机器人自动生成 · 数据仅供参考</div>
</div>

<script>
    const accountingData = {acc_json};
    const addressData = {addr_json};
    const groupsData = {grp_json};
    const trendData = {trend_json};

    // ---- 通用选项卡绑定（兼容移动端） ----
    function setupTabs(tabContainerId, onSwitch) {{
        const container = document.getElementById(tabContainerId);
        if(!container) return;
        const buttons = container.querySelectorAll('.tab-btn');
        buttons.forEach(btn => {{
            const handler = function(e) {{
                e.preventDefault();
                const period = this.getAttribute('data-period');
                if(period) onSwitch(period, buttons);
            }};
            btn.addEventListener('click', handler);
            btn.addEventListener('touchend', handler);
        }});
    }}

    // ---- 记账总览 ----
    function renderAccountTab(period) {{
        const data = accountingData[period];
        if(!data) return;
        let html = `<div class="summary-grid">
            <div class="summary-item"><div class="label">入款 (元)</div><div class="value positive">${{data.income_cny.toFixed(2)}}</div></div>
            <div class="summary-item"><div class="label">入款 (USDT)</div><div class="value">${{data.income_usdt.toFixed(2)}}</div></div>
            <div class="summary-item"><div class="label">下发 (USDT)</div><div class="value negative">${{data.expense.toFixed(2)}}</div></div>
            <div class="summary-item"><div class="label">待下发 (USDT)</div><div class="value">${{data.pending.toFixed(2)}}</div></div>
        </div>`;
        if(data.groups && data.groups.length > 0) {{
            html += '<div class="table-responsive"><table><thead><tr><th>群组</th><th>入款 (元)</th><th>入款 (USDT)</th><th>下发 (USDT)</th><th>待下发</th></tr></thead><tbody>';
            data.groups.forEach(g => {{
                html += `<tr><td>${{g.name}}</td><td class="positive">${{g.income_cny.toFixed(2)}}</td><td>${{g.income_usdt.toFixed(2)}}</td><td class="negative">${{g.expense.toFixed(2)}}</td><td>${{g.pending.toFixed(2)}}</td></tr>`;
            }});
            html += '</tbody></table></div>';
        }} else {{
            html += '<p style="text-align:center;color:#94a3b8;">暂无群组数据</p>';
        }}
        document.getElementById('accountTabContent').innerHTML = html;
    }}

    function switchAccountTab(period, buttons) {{
        buttons.forEach(b => b.classList.remove('active'));
        const activeBtn = Array.from(buttons).find(b => b.getAttribute('data-period') === period);
        if(activeBtn) activeBtn.classList.add('active');
        renderAccountTab(period);
    }}

    setupTabs('accountTabs', switchAccountTab);

    // 趋势图
    const trendCtx = document.getElementById('trendChart').getContext('2d');
    new Chart(trendCtx, {{
        type: 'bar',
        data: {{
            labels: trendData.dates,
            datasets: [
                {{ label: '每日入款 (元)', data: trendData.income, backgroundColor: 'rgba(22,163,74,0.6)', borderColor: '#16a34a', borderWidth: 1 }},
                {{ label: '每日下发 (USDT)', data: trendData.expense, backgroundColor: 'rgba(220,38,38,0.6)', borderColor: '#dc2626', borderWidth: 1 }}
            ]
        }},
        options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'top' }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
    }});

    // ---- USDT 地址统计 ----
    let addressChart;
    function renderAddressTab(period) {{
        const list = addressData[period] || [];
        let html = '<div class="table-responsive"><table><thead><tr><th>地址</th><th>备注</th><th>收款</th><th>转出</th><th>净收入</th></tr></thead><tbody>';
        list.forEach(a => {{
            html += `<tr><td>${{a.address}}</td><td>${{a.note}}</td><td class="positive">${{a.received.toFixed(2)}}</td><td class="negative">${{a.sent.toFixed(2)}}</td><td>${{a.net.toFixed(2)}}</td></tr>`;
        }});
        html += '</tbody></table></div>';
        document.getElementById('addressTabContent').innerHTML = html;

        if(addressChart) addressChart.destroy();
        const ctx = document.getElementById('addressChart').getContext('2d');
        const labels = list.map(a => a.address);
        const data = list.map(a => a.net);
        addressChart = new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: labels,
                datasets: [{{ label: '净收入 (USDT)', data: data, backgroundColor: data.map(v => v>=0 ? 'rgba(22,163,74,0.6)' : 'rgba(220,38,38,0.6)') }}]
            }},
            options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});
    }}

    function switchAddressTab(period, buttons) {{
        buttons.forEach(b => b.classList.remove('active'));
        const activeBtn = Array.from(buttons).find(b => b.getAttribute('data-period') === period);
        if(activeBtn) activeBtn.classList.add('active');
        renderAddressTab(period);
    }}

    setupTabs('addressTabs', switchAddressTab);

    // ---- 群组加入统计 ----
    function renderGroupTab(period) {{
        const data = groupsData[period];
        if(!data) return;
        let html = `<div class="summary-item" style="margin-bottom:12px;"><div class="label">${{period==='today'?'今日':period==='week'?'本周':period==='month'?'本月':'本年'}}加入数量</div><div class="value">${{data.count}}</div></div>`;
        if(data.list && data.list.length > 0) {{
            html += '<div class="table-responsive"><table><thead><tr><th>群组名称</th><th>加入时间</th><th>分类</th></tr></thead><tbody>';
            data.list.forEach(g => {{
                html += `<tr><td>${{g.name}}</td><td>${{g.joined_at}}</td><td>${{g.category}}</td></tr>`;
            }});
            html += '</tbody></table></div>';
        }} else {{
            html += '<p style="text-align:center;color:#94a3b8;">暂无数据</p>';
        }}
        document.getElementById('groupTabContent').innerHTML = html;
    }}

    function switchGroupTab(period, buttons) {{
        buttons.forEach(b => b.classList.remove('active'));
        const activeBtn = Array.from(buttons).find(b => b.getAttribute('data-period') === period);
        if(activeBtn) activeBtn.classList.add('active');
        renderGroupTab(period);
    }}

    setupTabs('groupTabs', switchGroupTab);

    // 默认显示今日
    renderAccountTab('today');
    renderAddressTab('today');
    renderGroupTab('today');
</script>
</body>
</html>"""

# ---------- 返回主菜单 ----------
async def profile_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    try:
        await query.message.edit_text("请选择功能：", reply_markup=get_main_menu(user_id))
    except Exception:
        await context.bot.send_message(chat_id=user_id, text="请选择功能：", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END

async def profile_report_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    display_name = query.from_user.username or query.from_user.first_name or ""
    await query.answer()
    prefs = get_user_preferences(user_id)
    new_state = not prefs.get("daily_report_enabled", False)
    set_user_preference(user_id, "daily_report_enabled", new_state)
    prefs = get_user_preferences(user_id)
    text, markup = await _build_profile_menu(user_id, prefs, display_name)
    await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

# ==================== 规则管理 ====================
# ---- 规则管理主菜单 ----
async def profile_rules_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """规则管理主菜单"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    from db import get_all_rules, get_rule_global_status
    rules = get_all_rules(active_only=True)
    rule_enabled = get_rule_global_status()

    status_text = "🟢 已启用" if rule_enabled else "🔴 已停用"

    text = "📋 **规则管理**\n\n"
    text += f"⚙️ 规则功能状态：**{status_text}**\n\n"

    if rules:
        text += f"📊 当前已添加 **{len(rules)}** 个规则：\n"
        for rule in rules[:10]:
            text += f"  📌 {rule['rule_name']}\n"
        if len(rules) > 10:
            text += f"  ... 还有 {len(rules) - 10} 个\n"
    else:
        text += "📭 暂无规则\n"

    text += "\n请选择操作："

    keyboard = [
        [InlineKeyboardButton("➕ 添加规则", callback_data="profile_rule_add")],
    ]

    if rules:
        keyboard.append([InlineKeyboardButton("📖 查看所有规则", callback_data="profile_rule_view_all")])
        keyboard.append([InlineKeyboardButton("✏️ 更新规则", callback_data="profile_rule_update_select")])
        keyboard.append([InlineKeyboardButton("🗑️ 删除规则", callback_data="profile_rule_delete_select")])

    # 全局开关按钮
    toggle_text = "🔴 停用规则功能" if rule_enabled else "🟢 启用规则功能"
    keyboard.append([InlineKeyboardButton(toggle_text, callback_data="profile_rule_global_toggle")])

    keyboard.append([InlineKeyboardButton("◀️ 返回个人中心", callback_data="profile_back_to_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_MENU

# ---- 添加规则：输入名称 ----
async def profile_rule_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加规则 - 输入名称"""
    query = update.callback_query
    await query.answer()

    context.user_data["profile_input_state"] = True
    context.user_data["rule_action"] = "add_name"

    keyboard = [[InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")]]

    await query.message.edit_text(
        "➕ **添加规则**\n\n"
        "请输入规则名称（提示词）：\n"
        "例如：德国、美国、BPay手续费 等\n\n"
        "💡 群组内输入「发送名称规则」即可查询\n"
        "例如输入：发送德国规则\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_ADD_NAME

async def profile_rule_add_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收规则名称"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 检查是否是键盘按钮
    if _is_keyboard_button(text):
        # 清理所有状态
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        # 显示主菜单
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        await update.message.reply_text("❌ 已取消添加")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if len(text) < 1:
        await update.message.reply_text("❌ 规则名称不能为空，请重新输入：")
        return RULE_ADD_NAME

    # 检查是否已存在
    from db import get_rule
    existing = get_rule(text)
    if existing and existing['is_active']:
        await update.message.reply_text(
            f"⚠️ 规则「{text}」已存在\n"
            f"内容：{existing['rule_content'][:100]}\n\n"
            f"请使用其他名称，或先删除后再添加：\n"
            f"❌ 发送 /cancel 取消"
        )
        return RULE_ADD_NAME

    context.user_data["rule_name"] = text
    context.user_data["rule_action"] = "add_content"

    await update.message.reply_text(
        f"📝 规则名称：**{text}**\n\n"
        "请输入规则内容：\n"
        "例如：手续费5%，汇率7.2，使用TRC20地址...\n\n"
        "💡 支持 Markdown 格式\n"
        "❌ 发送 /cancel 取消",
        parse_mode="Markdown"
    )
    return RULE_ADD_CONTENT

async def profile_rule_add_content_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收规则内容并保存"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 先检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        await update.message.reply_text("❌ 已取消添加")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END
        
    rule_name = context.user_data.get("rule_name", "")
    if not rule_name:
        await update.message.reply_text("❌ 会话已过期，请重新添加")
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        return ConversationHandler.END

    from db import add_rule
    success = add_rule(rule_name, text, user_id)

    if success:
        await update.message.reply_text(
            f"✅ 规则「**{rule_name}**」已添加成功！\n\n"
            f"💡 有权限的人在群内发送「**发送{rule_name}规则**」即可查看该规则"
        )
    else:
        await update.message.reply_text("❌ 添加失败，该规则可能已存在")

    # 🔥 关键修复：在清除状态前，设置标记防止AI捕获
    context.user_data["_message_handled"] = True

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("rule_action", None)
    context.user_data.pop("rule_name", None)

    prefs = get_user_preferences(user_id)
    _, markup = await _build_profile_menu(user_id, prefs, 
                                          update.effective_user.username or update.effective_user.first_name or "")
    await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

# ---- 查看所有规则 ----
async def profile_rule_view_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有规则列表（可点击查看详情）"""
    query = update.callback_query
    await query.answer()

    from db import get_all_rules
    rules = get_all_rules(active_only=True)

    if not rules:
        await query.message.edit_text("📭 暂无规则")
        return RULE_MENU

    text = "📖 **规则列表**\n\n"
    text += f"共 **{len(rules)}** 个规则，点击查看详情：\n\n"

    keyboard = []
    for rule in rules:
        # 显示规则名称和内容预览（前30个字符）
        content_preview = rule['rule_content'][:40]
        text += f"📌 **{rule['rule_name']}**\n"
        text += f"   {content_preview}{'...' if len(rule['rule_content']) > 40 else ''}\n\n"

        keyboard.append([InlineKeyboardButton(
            f"📋 {rule['rule_name']}", 
            callback_data=f"profile_rule_detail_{rule['rule_name']}"
        )])

    keyboard.append([InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_VIEW

# ---- 更新规则：选择 ----
async def profile_rule_update_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """选择要更新的规则"""
    query = update.callback_query
    await query.answer()

    from db import get_all_rules
    rules = get_all_rules(active_only=True)

    if not rules:
        await query.message.edit_text("📭 暂无规则可更新")
        return RULE_MENU

    text = "✏️ **选择要更新的规则**\n\n"
    keyboard = []
    for rule in rules:
        text += f"📌 {rule['rule_name']}\n"
        keyboard.append([InlineKeyboardButton(f"✏️ {rule['rule_name']}", callback_data=f"profile_rule_upd_{rule['rule_name']}")])

    keyboard.append([InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_UPDATE_SELECT

async def profile_rule_update_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理更新规则的选择"""
    query = update.callback_query
    await query.answer()

    rule_name = query.data.replace("profile_rule_upd_", "")
    context.user_data["rule_name"] = rule_name
    context.user_data["profile_input_state"] = True
    context.user_data["rule_action"] = "update_content"

    from db import get_rule
    rule = get_rule(rule_name)
    current_content = rule['rule_content'] if rule else "无"

    keyboard = [[InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")]]

    await query.message.edit_text(
        f"✏️ **更新规则**\n\n"
        f"规则名称：**{rule_name}**\n"
        f"当前内容：{current_content[:200]}{'...' if len(current_content) > 200 else ''}\n\n"
        "请输入新的规则内容：\n\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_UPDATE_CONTENT

async def profile_rule_update_content_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收更新的规则内容"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 先检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("rule_action", None)
        context.user_data.pop("rule_name", None)
        await update.message.reply_text("❌ 已取消更新")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    rule_name = context.user_data.get("rule_name", "")

    from db import update_rule
    success = update_rule(rule_name, text)

    if success:
        await update.message.reply_text(f"✅ 规则「**{rule_name}**」已更新成功！")
    else:
        await update.message.reply_text("❌ 更新失败，请稍后重试")

    # 🔥 关键修复：在清除状态前，设置标记防止AI捕获
    context.user_data["_message_handled"] = True

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("rule_action", None)
    context.user_data.pop("rule_name", None)

    prefs = get_user_preferences(user_id)
    _, markup = await _build_profile_menu(user_id, prefs, 
                                          update.effective_user.username or update.effective_user.first_name or "")
    await update.message.reply_text("已返回个人中心", reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

# ---- 删除规则：选择 ----
async def profile_rule_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """选择要删除的规则"""
    query = update.callback_query
    await query.answer()

    from db import get_all_rules
    rules = get_all_rules(active_only=True)

    if not rules:
        await query.message.edit_text("📭 暂无规则可删除")
        return RULE_MENU

    text = "🗑️ **选择要删除的规则**\n\n"
    keyboard = []
    for rule in rules:
        text += f"📌 {rule['rule_name']}\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ {rule['rule_name']}", callback_data=f"profile_rule_del_{rule['rule_name']}")])

    keyboard.append([InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_DELETE_SELECT

async def profile_rule_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行删除规则"""
    query = update.callback_query
    await query.answer()

    rule_name = query.data.replace("profile_rule_del_", "")

    from db import delete_rule
    success = delete_rule(rule_name)

    if success:
        await query.message.edit_text(f"✅ 已删除规则「{rule_name}」")
    else:
        await query.message.edit_text("❌ 删除失败，请稍后重试")

    return ConversationHandler.END

async def profile_rule_global_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换规则功能的全局开关"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    from db import get_rule_global_status, set_rule_global_status

    current_status = get_rule_global_status()
    new_status = not current_status

    success = set_rule_global_status(new_status)

    if success:
        status_text = "启用" if new_status else "停用"
        await query.answer(f"✅ 已{status_text}规则功能", show_alert=True)
    else:
        await query.answer("❌ 操作失败", show_alert=True)

    # 刷新菜单
    return await profile_rules_menu(update, context)

async def profile_rule_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看单个规则完整详情"""
    query = update.callback_query
    await query.answer()

    rule_name = query.data.replace("profile_rule_detail_", "")

    from db import get_rule
    from datetime import datetime

    rule = get_rule(rule_name)

    if not rule:
        await query.message.edit_text("❌ 规则不存在")
        return RULE_VIEW

    text = f"📋 **{rule['rule_name']}规则**\n\n"
    text += f"{rule['rule_content']}\n\n"

    created_time = datetime.fromtimestamp(rule['created_at']).strftime('%Y-%m-%d %H:%M')
    updated_time = datetime.fromtimestamp(rule['updated_at']).strftime('%Y-%m-%d %H:%M')
    text += f"📅 创建时间：{created_time}\n"
    text += f"🔄 更新时间：{updated_time}\n"

    keyboard = [
        [InlineKeyboardButton("◀️ 返回规则列表", callback_data="profile_rule_view_all")],
        [InlineKeyboardButton("◀️ 返回规则管理", callback_data="profile_rules_menu")],
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RULE_VIEW

# ---- 返回个人中心 ----
async def profile_back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从规则管理返回个人中心"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    prefs = get_user_preferences(user_id)
    display_name = query.from_user.username or query.from_user.first_name or ""
    text, markup = await _build_profile_menu(user_id, prefs, display_name)
    await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    return ConversationHandler.END

# ==================== 业绩汇总 ====================
async def profile_performance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """业绩汇总 - 直接显示当前月业绩"""
    query = update.callback_query
    user_id = query.from_user.id
    # 权限检查：仅正式操作员和管理员
    if not is_authorized(user_id, require_full_access=True):
        await query.answer("❌ 临时操作员不能使用业绩汇总功能", show_alert=True)
        return
    await query.answer()

    from db import get_performance_available_months, get_performance_summary
    from datetime import datetime

    months = get_performance_available_months()

    # 当前月份
    now = datetime.now()
    current_month = f"{now.year}-{now.month:02d}"

    if not months:
        text = "📊 **业绩汇总**\n\n📭 暂无业绩记录\n\n请选择操作："
        keyboard = [
            [InlineKeyboardButton("➕ 记录业绩", callback_data="profile_performance_record")],
            [InlineKeyboardButton("◀️ 返回个人中心", callback_data="profile_return")],
        ]
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return PERFORMANCE_MENU

    # 默认显示当前月，如果没有则显示最近一个月
    if current_month in months:
        display_month = current_month
    else:
        display_month = months[0]

    year, month = display_month.split('-')
    year = int(year)
    month = int(month)
    summary = get_performance_summary(year, month)

    # 标题
    text = f"📊 **{year}年{month}月 业绩汇总**\n\n"
    text += f"<blockquote><b>公司总利润：{summary['total_profit']:.2f} USDT</b></blockquote>\n\n"

    if summary['records']:
        display_records = summary['records'][:20]

        # 表头
        text += f"`{'编号':<9}{'日期':<7}{'国家':<6}{'通道':>6}{'客户':>6}{'利润':>6}{'通道员工':<7}{'客户员工':<7}`\n"

        for r in display_records:
            date_str = r['date'][-5:] if r['date'] else ''
            country = r['country'][:4]
            ch_name = (r['channel_employee_name'] or f"ID{r['channel_employee_id']}")[:5]
            cu_name = (r['customer_employee_name'] or f"ID{r['customer_employee_id']}")[:5]
            text += f"`{r['id']:<9}{date_str:<7}{country:<6}{r['channel_income']:>6.0f}{r['customer_expense']:>6.0f}{r['profit']:>6.0f}{ch_name:<7}{cu_name:<7}`\n"

        if len(summary['records']) > 20:
            text += f"\n`... 仅显示20条，共 {len(summary['records'])} 条（导出HTML查看全部）`\n"

    # 员工提成
    text += "\n<blockquote><b>💰 员工提成汇总</b></blockquote>\n"
    for emp_id, data in summary['employee_commission'].items():
        perf = summary['employee_performance'].get(emp_id, {}).get('performance', 0)
        text += f"• {data['name']}：{data['commission']:.2f} USDT（业绩 {perf:.2f} USDT）\n"

    text += "\n💡 提成 = 利润×10% | 业绩 = 利润÷2"

    keyboard = [
        [InlineKeyboardButton("➕ 记录业绩", callback_data="profile_performance_record")],
        [InlineKeyboardButton("📅 查看其他月份", callback_data="profile_performance_view")],
        [InlineKeyboardButton("📥 导出HTML", callback_data="profile_performance_export_select")],
    ]
    from config import OWNER_ID
    if user_id == OWNER_ID:
        keyboard.append([
            InlineKeyboardButton("✏️ 修改业绩", callback_data="profile_performance_edit"),
            InlineKeyboardButton("🗑️ 删除业绩", callback_data="profile_performance_delete"),
        ])
        keyboard.append([InlineKeyboardButton("📝 记录追溯", callback_data="profile_performance_trace")])
    keyboard.append([InlineKeyboardButton("◀️ 返回个人中心", callback_data="profile_return")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return PERFORMANCE_MENU
    
async def profile_performance_record_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """记录业绩 - 输入信息"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_authorized(user_id, require_full_access=True):
        await query.answer("❌ 无权限", show_alert=True)
        return
    await query.answer()

    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "record"

    # 获取现有正式操作员列表
    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"
    else:
        employee_list = "\n\n⚠️ 暂无正式操作员，请先添加操作员"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        "➕ **记录业绩**\n\n"
        "请输入信息，用空格分隔：\n"
        "`国家 通道收入 客户支出 通道群名 客户群名 @通道员工 @客户员工`\n\n"
        "例如：\n"
        "`德国 5000 -3000 德国通道群 德国客户群 @张三 @李四`\n\n"
        "💡 **说明**：\n"
        "• 通道收入填正数（如5000）\n"
        "• 客户支出填负数（如-3000）\n"
        "• 利润 = 通道收入 + 客户支出\n"
        "• 员工用 @用户名 或 用户ID\n"
        "• 只能选择正式操作员\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_RECORD


async def profile_performance_record_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收业绩记录"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ✅ 检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        await update.message.reply_text("❌ 已取消记录")
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    # ✅ 如果输入看起来不像业绩记录（太短，不含数字），可能是想退出
    if len(text.split()) < 3 and not any(c.isdigit() for c in text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "已取消业绩记录\n\n请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    # 🔥 关键修复：标记消息已处理，防止 AI 捕获
    context.user_data["_message_handled"] = True

    # 解析输入
    import shlex
    try:
        parts = shlex.split(text)
    except:
        parts = text.split()

    if len(parts) < 7:
        await update.message.reply_text(
            "❌ 格式错误，至少需要7个参数\n"
            "格式：国家 通道收入 客户支出 通道群名 客户群名 通道员工 客户员工\n\n"
            "请重新输入："
        )
        return PERFORMANCE_RECORD

    country = parts[0]
    try:
        channel_income = float(parts[1])
        customer_expense = float(parts[2])
    except ValueError:
        await update.message.reply_text("❌ 金额格式错误，请输入数字\n请重新输入：")
        return PERFORMANCE_RECORD

    channel_group = parts[3]
    customer_group = parts[4]

    # 解析员工
    channel_employee_id = 0
    channel_employee_name = ""
    customer_employee_id = 0
    customer_employee_name = ""

    # 通道员工
    ch_emp = parts[5]
    if ch_emp.startswith('@'):
        ch_username = ch_emp[1:]
        # 从操作员中查找
        from auth import operators as auth_operators
        found = False
        for oid, info in auth_operators.items():
            if info.get('username') == ch_username:
                channel_employee_id = oid
                channel_employee_name = info.get('first_name') or ch_username
                found = True
                break
        if not found:
            await update.message.reply_text(f"❌ 未找到正式操作员：{ch_emp}\n请确认用户名正确\n请重新输入：")
            return PERFORMANCE_RECORD
    elif ch_emp.isdigit():
        channel_employee_id = int(ch_emp)
        from auth import operators as auth_operators
        if channel_employee_id in auth_operators:
            channel_employee_name = auth_operators[channel_employee_id].get('first_name') or str(channel_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{ch_emp}\n请重新输入：")
            return PERFORMANCE_RECORD
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{ch_emp}\n请使用 @用户名 或 用户ID\n请重新输入：")
        return PERFORMANCE_RECORD

    # 客户员工
    cu_emp = parts[6] if len(parts) > 6 else ""
    if cu_emp.startswith('@'):
        cu_username = cu_emp[1:]
        from auth import operators as auth_operators
        found = False
        for oid, info in auth_operators.items():
            if info.get('username') == cu_username:
                customer_employee_id = oid
                customer_employee_name = info.get('first_name') or cu_username
                found = True
                break
        if not found:
            await update.message.reply_text(f"❌ 未找到正式操作员：{cu_emp}\n请重新输入：")
            return PERFORMANCE_RECORD
    elif cu_emp.isdigit():
        customer_employee_id = int(cu_emp)
        from auth import operators as auth_operators
        if customer_employee_id in auth_operators:
            customer_employee_name = auth_operators[customer_employee_id].get('first_name') or str(customer_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{cu_emp}\n请重新输入：")
            return PERFORMANCE_RECORD
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{cu_emp}\n请使用 @用户名 或 用户ID\n请重新输入：")
        return PERFORMANCE_RECORD

    # 保存记录
    from db import add_performance_record

    profit = channel_income + customer_expense
    success = add_performance_record(
        country, channel_income, customer_expense,
        channel_group, customer_group,
        channel_employee_id, channel_employee_name,
        customer_employee_id, customer_employee_name,
        user_id
    )

    if success:
        ch_commission = profit * 0.1
        cu_commission = profit * 0.1
        ch_performance = profit / 2
        cu_performance = profit / 2

        reply = (
            f"✅ **已记录业绩！**\n\n"
            f"📋 **记录详情：**\n"
            f"• 国家：{country}\n"
            f"• 通道收入：{channel_income} USDT（群：{channel_group}）\n"
            f"• 客户支出：{customer_expense} USDT（群：{customer_group}）\n"
            f"• 利润：{profit} USDT\n\n"
            f"👤 **通道员工：{channel_employee_name}**\n"
            f"   提成：{ch_commission:.2f} USDT | 业绩：{ch_performance:.2f} USDT\n\n"
            f"👤 **客户员工：{customer_employee_name}**\n"
            f"   提成：{cu_commission:.2f} USDT | 业绩：{cu_performance:.2f} USDT"
        )
        if channel_employee_id == customer_employee_id:
            reply += f"\n\n💡 通道和客户为同一人，提成 {ch_commission * 2:.2f} USDT，业绩 {ch_performance * 2:.2f} USDT"

        await update.message.reply_text(reply, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ 记录失败，请稍后重试")

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("perf_action", None)

    from handlers.menu import get_main_menu
    await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END


async def profile_performance_view_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看汇总 - 选择月份"""
    query = update.callback_query
    await query.answer()

    from db import get_performance_available_months

    months = get_performance_available_months()

    if not months:
        await query.message.edit_text("📭 暂无业绩记录")
        return PERFORMANCE_MENU

    keyboard = []
    for m in months[:12]:
        year, month = m.split('-')
        keyboard.append([InlineKeyboardButton(
            f"📅 {year}年{int(month)}月",
            callback_data=f"perf_month_{m}"
        )])

    keyboard.append([InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")])

    await query.message.edit_text(
        "📊 **查看业绩汇总**\n\n请选择月份：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_MONTH_SELECT


async def profile_performance_view_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示指定月份的业绩汇总"""
    query = update.callback_query
    await query.answer()

    month_str = query.data.replace("perf_month_", "")
    year, month = month_str.split('-')
    year = int(year)
    month = int(month)

    from db import get_performance_summary
    summary = get_performance_summary(year, month)

    if not summary['records']:
        await query.message.edit_text(f"📭 {year}年{month}月暂无业绩记录")
        return PERFORMANCE_MONTH_SELECT

    text = f"📊 **{year}年{month}月 业绩汇总**\n\n"
    text += f"<blockquote><b>公司总利润：{summary['total_profit']:.2f} USDT</b></blockquote>\n\n"

    if summary['records']:
        display_records = summary['records'][:20]

        # 表头
        text += f"`{'编号':<9}{'日期':<7}{'国家':<6}{'通道':>6}{'客户':>6}{'利润':>6}{'通道员工':<7}{'客户员工':<7}`\n"

        for r in display_records:
            date_str = r['date'][-5:] if r['date'] else ''
            country = r['country'][:4]
            ch_name = (r['channel_employee_name'] or f"ID{r['channel_employee_id']}")[:5]
            cu_name = (r['customer_employee_name'] or f"ID{r['customer_employee_id']}")[:5]
            text += f"`{r['id']:<9}{date_str:<7}{country:<6}{r['channel_income']:>6.0f}{r['customer_expense']:>6.0f}{r['profit']:>6.0f}{ch_name:<7}{cu_name:<7}`\n"

        if len(summary['records']) > 20:
            text += f"\n`... 仅显示20条，共 {len(summary['records'])} 条（导出HTML查看全部）`\n"

    text += "\n<blockquote><b>💰 员工提成汇总</b></blockquote>\n"
    for emp_id, data in summary['employee_commission'].items():
        perf = summary['employee_performance'].get(emp_id, {}).get('performance', 0)
        text += f"• {data['name']}：{data['commission']:.2f} USDT（业绩 {perf:.2f} USDT）\n"

    text += "\n💡 提成 = 利润×10% | 业绩 = 利润÷2"

    keyboard = [[InlineKeyboardButton("◀️ 返回月份选择", callback_data="profile_performance_view")]]
    keyboard.append([InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")])

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return PERFORMANCE_VIEW

# ---- 修改业绩 ----
async def profile_performance_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """修改业绩 - 输入信息"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有超级管理员才能修改业绩", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "edit"

    from auth import operators as auth_operators
    employee_list = ""
    if auth_operators:
        employee_list = "\n\n📋 **现有员工列表：**\n"
        for uid, info in auth_operators.items():
            name = info.get('first_name') or ''
            uname = f" @{info['username']}" if info.get('username') else ''
            employee_list += f"• {name}{uname}（ID: `{uid}`）\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        "✏️ **修改业绩**\n\n"
        "请输入信息，用空格分隔：\n"
        "`编号 国家 通道收入 客户支出 通道群名 客户群名 @通道员工 @客户员工`\n\n"
        "例如：\n"
        "`1 德国 5000 -3000 德国通道群 德国客户群 @张三 @李四`\n\n"
        "💡 编号是汇总列表中第一列的序号\n"
        f"{employee_list}"
        "\n❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_EDIT


async def profile_performance_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收修改的业绩记录"""
    user_id = update.effective_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有超级管理员才能修改业绩")
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        return ConversationHandler.END
    text = update.message.text.strip()

    # ✅ 检查是否是键盘按钮
    if _is_keyboard_button(text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text(
            "请选择功能：",
            reply_markup=get_main_menu(user_id)
        )
        return ConversationHandler.END

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        await update.message.reply_text("❌ 已取消修改")
        from handlers.menu import get_main_menu
        await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    context.user_data["_message_handled"] = True

    import shlex
    try:
        parts = shlex.split(text)
    except:
        parts = text.split()

    if len(parts) < 8:
        await update.message.reply_text("❌ 格式错误，至少需要8个参数\n请重新输入：")
        return PERFORMANCE_EDIT

    try:
        record_id = int(parts[0])
    except ValueError:
        await update.message.reply_text("❌ 编号必须是数字\n请重新输入：")
        return PERFORMANCE_EDIT

    from db import get_performance_record_by_id
    record = get_performance_record_by_id(record_id)
    if not record:
        await update.message.reply_text(f"❌ 未找到编号 {record_id} 的业绩记录\n请重新输入：")
        return PERFORMANCE_EDIT

    country = parts[1]
    try:
        channel_income = float(parts[2])
        customer_expense = float(parts[3])
    except ValueError:
        await update.message.reply_text("❌ 金额格式错误\n请重新输入：")
        return PERFORMANCE_EDIT

    channel_group = parts[4]
    customer_group = parts[5]

    # 解析员工（和 record 一样的逻辑）
    channel_employee_id = 0
    channel_employee_name = ""
    customer_employee_id = 0
    customer_employee_name = ""

    ch_emp = parts[6]
    if ch_emp.startswith('@'):
        ch_username = ch_emp[1:]
        from auth import operators as auth_operators
        for oid, info in auth_operators.items():
            if info.get('username') == ch_username:
                channel_employee_id = oid
                channel_employee_name = info.get('first_name') or ch_username
                break
        if channel_employee_id == 0:
            await update.message.reply_text(f"❌ 未找到正式操作员：{ch_emp}\n请重新输入：")
            return PERFORMANCE_EDIT
    elif ch_emp.isdigit():
        channel_employee_id = int(ch_emp)
        from auth import operators as auth_operators
        if channel_employee_id in auth_operators:
            channel_employee_name = auth_operators[channel_employee_id].get('first_name') or str(channel_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{ch_emp}\n请重新输入：")
            return PERFORMANCE_EDIT
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{ch_emp}\n请重新输入：")
        return PERFORMANCE_EDIT

    cu_emp = parts[7]
    if cu_emp.startswith('@'):
        cu_username = cu_emp[1:]
        from auth import operators as auth_operators
        for oid, info in auth_operators.items():
            if info.get('username') == cu_username:
                customer_employee_id = oid
                customer_employee_name = info.get('first_name') or cu_username
                break
        if customer_employee_id == 0:
            await update.message.reply_text(f"❌ 未找到正式操作员：{cu_emp}\n请重新输入：")
            return PERFORMANCE_EDIT
    elif cu_emp.isdigit():
        customer_employee_id = int(cu_emp)
        from auth import operators as auth_operators
        if customer_employee_id in auth_operators:
            customer_employee_name = auth_operators[customer_employee_id].get('first_name') or str(customer_employee_id)
        else:
            await update.message.reply_text(f"❌ 未找到正式操作员ID：{cu_emp}\n请重新输入：")
            return PERFORMANCE_EDIT
    else:
        await update.message.reply_text(f"❌ 员工格式错误：{cu_emp}\n请重新输入：")
        return PERFORMANCE_EDIT

    from db import update_performance_record
    profit = channel_income + customer_expense
    success = update_performance_record(
        record_id, country, channel_income, customer_expense,
        channel_group, customer_group,
        channel_employee_id, channel_employee_name,
        customer_employee_id, customer_employee_name
    )

    if success:
        await update.message.reply_text(f"✅ 已修改编号 {record_id} 的业绩记录")
    else:
        await update.message.reply_text("❌ 修改失败")

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("perf_action", None)

    from handlers.menu import get_main_menu
    await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END


# ---- 删除业绩 ----
async def profile_performance_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除业绩 - 输入编号"""
    query = update.callback_query
    user_id = query.from_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有超级管理员才能删除业绩", show_alert=True)
        return

    await query.answer()
    context.user_data["profile_input_state"] = True
    context.user_data["perf_action"] = "delete"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩菜单", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        "🗑️ **删除业绩**\n\n"
        "请输入要删除的业绩编号：\n"
        "例如：`1`\n\n"
        "💡 编号是汇总列表中第一列的序号\n"
        "❌ 发送 /cancel 取消",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_DELETE


async def profile_performance_delete_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收删除编号"""
    user_id = update.effective_user.id
    from config import OWNER_ID
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ 只有超级管理员才能删除业绩")
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        return ConversationHandler.END
    text = update.message.text.strip()

    if text == '/cancel':
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        await update.message.reply_text("❌ 已取消删除")
        from handlers.menu import get_main_menu
        await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    # ✅ 如果输入看起来不像业绩记录（太短，不含数字），可能是想退出
    if len(text.split()) < 3 and not any(c.isdigit() for c in text):
        context.user_data.pop("profile_input_state", None)
        context.user_data.pop("perf_action", None)
        from handlers.menu import get_main_menu
        await update.message.reply_text("已返回主菜单", reply_markup=get_main_menu(user_id))
        return ConversationHandler.END

    context.user_data["_message_handled"] = True

    if not text.isdigit():
        await update.message.reply_text("❌ 请输入数字编号\n请重新输入：")
        return PERFORMANCE_DELETE

    record_id = int(text)

    from db import get_performance_record_by_id, delete_performance_record
    record = get_performance_record_by_id(record_id)
    if not record:
        await update.message.reply_text(f"❌ 未找到编号 {record_id} 的业绩记录\n请重新输入：")
        return PERFORMANCE_DELETE

    if delete_performance_record(record_id):
        await update.message.reply_text(f"✅ 已删除编号 {record_id} 的业绩记录")
    else:
        await update.message.reply_text("❌ 删除失败")

    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("perf_action", None)

    from handlers.menu import get_main_menu
    await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END

async def profile_performance_export_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """导出业绩 - 选择月份"""
    query = update.callback_query
    await query.answer()

    from db import get_performance_available_months

    months = get_performance_available_months()
    if not months:
        await query.message.edit_text("📭 暂无业绩记录可导出")
        return PERFORMANCE_MENU

    keyboard = []
    for m in months[:12]:
        year, month = m.split('-')
        keyboard.append([InlineKeyboardButton(
            f"📅 {year}年{int(month)}月",
            callback_data=f"perf_export_{m}"
        )])

    keyboard.append([InlineKeyboardButton("📥 导出全部", callback_data="perf_export_all")])
    keyboard.append([InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")])

    await query.message.edit_text(
        "📥 **导出业绩汇总**\n\n请选择要导出的月份，或导出全部：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return PERFORMANCE_MONTH_SELECT

async def profile_performance_export_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """执行导出"""
    query = update.callback_query
    data = query.data

    if data == "perf_export_all":
        # 导出全部
        from db import get_performance_records
        records = get_performance_records()
        if not records:
            await query.answer("暂无业绩记录", show_alert=True)
            return
        year_str = "全部"
        month_str = ""
        total_profit = sum(r['profit'] for r in records)

        # 按员工汇总
        employee_commission = {}
        employee_performance = {}
        for r in records:
            profit = r['profit']
            for emp_id, emp_name, key_prefix in [
                (r['channel_employee_id'], r['channel_employee_name'], 'ch'),
                (r['customer_employee_id'], r['customer_employee_name'], 'cu')
            ]:
                if emp_id not in employee_commission:
                    employee_commission[emp_id] = {"name": emp_name or f"ID{emp_id}", "commission": 0}
                    employee_performance[emp_id] = {"name": emp_name or f"ID{emp_id}", "performance": 0}
                employee_commission[emp_id]["commission"] += profit * 0.1
                employee_performance[emp_id]["performance"] += profit / 2
    else:
        month_str = data.replace("perf_export_", "")
        year, month = month_str.split('-')
        year = int(year)
        month = int(month)
        year_str = f"{year}年{month}月"

        from db import get_performance_summary
        summary = get_performance_summary(year, month)
        records = summary['records']
        total_profit = summary['total_profit']
        employee_commission = summary['employee_commission']
        employee_performance = summary['employee_performance']

    await query.answer("正在生成HTML...")

    # 生成HTML（和之前一样，用 records、total_profit、employee_commission、employee_performance）
    html = generate_performance_html(records, total_profit, employee_commission, employee_performance, year_str, month_str)

    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
        f.write(html)
        temp_path = f.name

    try:
        with open(temp_path, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename=f"业绩汇总_{year_str}.html",
                caption=f"📊 {year_str}业绩汇总已导出"
            )
    finally:
        os.unlink(temp_path)


def generate_performance_html(records, total_profit, employee_commission, employee_performance, title, subtitle=""):
    """生成业绩HTML"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title} 业绩汇总</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a, #1e3a5f);
            min-height: 100vh; padding: 40px 20px; color: #e2e8f0;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{
            text-align: center; padding: 30px; background: rgba(255,255,255,0.05);
            border-radius: 20px; margin-bottom: 30px; backdrop-filter: blur(10px);
        }}
        .header h1 {{ font-size: 28px; background: linear-gradient(135deg, #f59e0b, #ef4444); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .header .profit {{ font-size: 36px; font-weight: bold; color: #10b981; margin-top: 10px; }}
        .table-container {{
            background: rgba(255,255,255,0.05); border-radius: 16px; padding: 20px;
            margin-bottom: 30px; backdrop-filter: blur(10px); overflow-x: auto;
        }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th {{
            background: rgba(245,158,11,0.2); padding: 14px 12px; text-align: left;
            font-weight: 600; color: #f59e0b; border-bottom: 2px solid rgba(245,158,11,0.3);
            white-space: nowrap;
        }}
        td {{ padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); }}
        tr:hover {{ background: rgba(255,255,255,0.03); }}
        .income {{ color: #10b981; }}
        .expense {{ color: #ef4444; }}
        .profit-cell {{ color: #f59e0b; font-weight: 600; }}
        .employee-section {{
            background: rgba(255,255,255,0.05); border-radius: 16px; padding: 24px;
            margin-bottom: 30px; backdrop-filter: blur(10px);
        }}
        .employee-section h2 {{ color: #f59e0b; margin-bottom: 16px; }}
        .employee-card {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 16px; margin-bottom: 10px; background: rgba(255,255,255,0.03);
            border-radius: 12px; border: 1px solid rgba(255,255,255,0.06);
        }}
        .employee-name {{ font-size: 16px; font-weight: 600; }}
        .employee-commission {{ color: #10b981; font-size: 18px; font-weight: bold; }}
        .employee-perf {{ color: #94a3b8; font-size: 14px; margin-left: 10px; }}
        .footer {{ text-align: center; color: #64748b; font-size: 12px; padding: 20px; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 {title} 业绩汇总</h1>
        <div class="profit">公司总利润：{total_profit:.2f} USDT</div>
    </div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>编号</th><th>日期</th><th>国家</th><th>通道群名</th><th>客户群名</th><th>通道收入</th><th>客户支出</th><th>利润</th><th>通道员工</th><th>客户员工</th>
                </tr>
            </thead>
            <tbody>
"""
    for r in records:
        ch_name = r.get('channel_employee_name') or f"ID{r.get('channel_employee_id')}"
        cu_name = r.get('customer_employee_name') or f"ID{r.get('customer_employee_id')}"
        html += f"""                <tr>
                    <td>{r.get('id', '')}</td><td>{r.get('date', '')}</td><td>{r.get('country', '')}</td>
                    <td>{r.get('channel_group', '')}</td><td>{r.get('customer_group', '')}</td>
                    <td class="income">{r.get('channel_income', 0):.0f}</td>
                    <td class="expense">{r.get('customer_expense', 0):.0f}</td>
                    <td class="profit-cell">{r.get('profit', 0):.0f}</td>
                    <td>{ch_name}</td><td>{cu_name}</td>
                </tr>
"""
    html += """            </tbody>
        </table>
    </div>
    <div class="employee-section">
        <h2>💰 员工提成汇总</h2>
"""
    for emp_id, data in employee_commission.items():
        perf = employee_performance.get(emp_id, {}).get('performance', 0)
        html += f"""        <div class="employee-card">
            <span class="employee-name">{data['name']}</span>
            <span>
                <span class="employee-commission">{data['commission']:.2f} USDT</span>
                <span class="employee-perf">业绩 {perf:.2f} USDT</span>
            </span>
        </div>
"""
    html += """    </div>
    <div class="footer">由记账机器人自动生成 · 提成=利润×10% · 业绩=利润÷2</div>
</div>
</body>
</html>"""
    return html

async def profile_performance_trace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """记录追溯 - 显示本月操作日志"""
    query = update.callback_query
    user_id = query.from_user.id

    from config import OWNER_ID
    if user_id != OWNER_ID:
        await query.answer("❌ 只有超级管理员才能查看", show_alert=True)
        return

    await query.answer()

    from db import get_performance_records
    from datetime import datetime, timezone, timedelta
    from auth import operators as auth_operators

    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    current_month = now.strftime('%Y-%m')

    all_records = get_performance_records()
    # 筛选本月记录
    month_records = [r for r in all_records if r.get('date', '').startswith(current_month)]

    if not month_records:
        await query.message.edit_text(
            f"📝 **记录追溯 - {now.strftime('%Y年%m月')}**\n\n📭 本月暂无记录",
            parse_mode="Markdown"
        )
        return

    # 按时间倒序
    month_records.sort(key=lambda x: x.get('created_at', 0), reverse=True)

    # 获取操作人名称
    def get_user_name(uid):
        if uid in auth_operators:
            name = auth_operators[uid].get('first_name', '')
            uname = auth_operators[uid].get('username', '')
            return f"{name}(@{uname})" if uname else name or str(uid)
        return f"ID{uid}"

    text = f"📝 **记录追溯 - {now.strftime('%Y年%m月')}**\n"
    text += f"共 **{len(month_records)}** 条记录\n\n"

    for i, r in enumerate(month_records, 1):
        created_time = datetime.fromtimestamp(r['created_at'], tz=beijing_tz).strftime('%m-%d %H:%M')
        operator = get_user_name(r['created_by'])
        ch_name = r.get('channel_employee_name') or f"ID{r['channel_employee_id']}"
        cu_name = r.get('customer_employee_name') or f"ID{r['customer_employee_id']}"
        profit = r['channel_income'] + r['customer_expense']

        text += f"`{i:<3} {created_time}`\n"
        text += f"   编号：`{r['id']}` | {r['country']} | 通道:{r['channel_income']:.0f} | 客户:{r['customer_expense']:.0f} | 利润:{profit:.0f}\n"
        text += f"   通道员工：{ch_name} | 客户员工：{cu_name}\n"
        text += f"   操作人：{operator}\n\n"

    keyboard = [[InlineKeyboardButton("◀️ 返回业绩汇总", callback_data="profile_performance_menu")]]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def profile_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消所有个人中心相关操作"""
    user_id = update.effective_user.id

    # 清除所有相关状态
    context.user_data.pop("profile_input_state", None)
    context.user_data.pop("rule_action", None)
    context.user_data.pop("rule_name", None)
    context.user_data.pop("perf_action", None)
    context.user_data.pop("_message_handled", None)

    await update.message.reply_text("❌ 已取消")

    from handlers.menu import get_main_menu
    await update.message.reply_text("请选择功能：", reply_markup=get_main_menu(user_id))
    return ConversationHandler.END
