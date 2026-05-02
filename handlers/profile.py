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
        f"📞 管理员：@ChinaEdward\n"
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
