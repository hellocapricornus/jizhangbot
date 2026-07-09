# handlers/response_speed.py

import asyncio
import time
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, CommandHandler, CallbackContext, filters
from auth import list_operators, safe_escape_markdown, OWNER_ID
from db import (
    add_response_record, get_all_employee_response_stats, get_employee_response_stats,
    set_employee_work_time, get_employee_work_time, is_in_work_time,
    get_response_rating_config, update_response_rating_config, cleanup_old_response_records,
    get_months_with_response_records, get_response_rating_for_seconds,
    init_response_tables
)
from logger import bot_logger as logger

RESPONSE_MAIN = 1
RESPONSE_MONTH_SELECT = 2
RESPONSE_EMPLOYEE_DETAIL = 3
RESPONSE_WORK_TIME_MENU = 4
RESPONSE_WORK_TIME_SET = 5
RESPONSE_RATING_CONFIG = 6
RESPONSE_RATING_EDIT = 7

pending_customer_messages = {}


def format_seconds(seconds: float) -> str:
    """格式化秒数为可读时间"""
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}小时{minutes}分"


MAX_RESPONSE_SECONDS = 3 * 60 * 60

async def monitor_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """监听群消息，检测员工响应速度"""
    if not update.message:
        return

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id
    message_time = int(message.date.timestamp())

    operators = list_operators()

    if user_id in operators:
        if chat_id in pending_customer_messages and pending_customer_messages[chat_id]:
            sorted_msg_ids = sorted(pending_customer_messages[chat_id].keys())
            latest_msg_id = sorted_msg_ids[-1]
            customer_info = pending_customer_messages[chat_id][latest_msg_id]

            if not customer_info['responded']:
                customer_info['responded'] = True
                customer_info['responder_id'] = user_id
                customer_info['responder_time'] = message_time

                customer_msg_time = customer_info['message_time']
                response_seconds = message_time - customer_msg_time

                is_customer_in_work = is_in_work_time(user_id, customer_msg_time)
                is_responder_in_work = is_in_work_time(user_id, message_time)

                if is_customer_in_work and is_responder_in_work and response_seconds <= MAX_RESPONSE_SECONDS:
                    add_response_record(
                        customer_info['user_id'],
                        customer_msg_time,
                        user_id,
                        message_time,
                        True
                    )

            pending_customer_messages[chat_id] = {}
    else:
        if message.text and message.text.startswith('/'):
            return

        customer_msg_time = message_time
        is_in_work = is_in_work_time(user_id, customer_msg_time)

        if not is_in_work:
            return

        if chat_id not in pending_customer_messages:
            pending_customer_messages[chat_id] = {}

        pending_customer_messages[chat_id][message.message_id] = {
            'user_id': user_id,
            'message_time': message_time,
            'responded': False,
            'responder_id': None,
            'responder_time': None
        }

        cleanup_task = context.application.create_task(
            cleanup_pending_messages(chat_id, message.message_id),
            name=f"cleanup_pending_{chat_id}_{message.message_id}"
        )


async def cleanup_pending_messages(chat_id: int, message_id: int):
    """清理超时未响应的客户消息"""
    await asyncio.sleep(MAX_RESPONSE_SECONDS)
    if chat_id in pending_customer_messages:
        if message_id in pending_customer_messages[chat_id]:
            del pending_customer_messages[chat_id][message_id]


async def response_cancel(update: Update, context: CallbackContext):
    """取消操作，返回主菜单"""
    await update.message.reply_text("✅ 已取消")
    return ConversationHandler.END


async def response_speed_menu(update: Update, context: CallbackContext):
    """响应速度主菜单"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    is_admin = user_id == OWNER_ID

    now = datetime.now(timezone(timedelta(hours=8)))
    year, month = now.year, now.month

    stats = get_all_employee_response_stats(year, month)
    operators = list_operators()

    text = f"📊 **员工响应速度排名（{year}年{month}月）**\n\n"

    if not stats:
        text += "暂无响应记录\n\n"
    else:
        rank = 1
        total_avg = 0
        total_count = 0
        for emp_id, emp_stats in stats.items():
            if emp_id not in operators:
                continue

            op_info = operators[emp_id]
            name = op_info.get('first_name', f"员工{emp_id}")
            avg_time = format_seconds(emp_stats['avg_response_seconds'])
            rating = get_response_rating_for_seconds(emp_stats['avg_response_seconds'])
            rating_emoji = rating.get('emoji', '❓')
            rating_name = rating.get('level_name', '未知')

            text += f"{rank}️⃣ {rating_emoji}【{rating_name}】{safe_escape_markdown(name)} - 平均响应 {avg_time} - 响应 {emp_stats['total_count']}次\n"

            total_avg += emp_stats['avg_response_seconds'] * emp_stats['total_count']
            total_count += emp_stats['total_count']
            rank += 1

        if total_count > 0:
            overall_avg = total_avg / total_count
            overall_rating = get_response_rating_for_seconds(overall_avg)
            text += f"\n📊 整体统计：\n总响应次数：{total_count}\n平均响应时间：{format_seconds(overall_avg)} {overall_rating['emoji']}\n"

    keyboard = []

    months_with_records = get_months_with_response_records()
    if len(months_with_records) >= 1:
        keyboard.append([InlineKeyboardButton("📅 选择月份", callback_data='response_month_select')])

    if is_admin:
        keyboard.append([InlineKeyboardButton("⏰ 设置员工工作时间", callback_data='response_work_time_menu')])
        keyboard.append([InlineKeyboardButton("⚙️ 设置响应评级", callback_data='response_rating_config')])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='profile')])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RESPONSE_MAIN


async def response_month_select(update: Update, context: CallbackContext):
    """选择月份查看历史数据"""
    query = update.callback_query
    await query.answer()

    months_with_records = get_months_with_response_records()
    keyboard = []

    for month_data in months_with_records:
        year, month = month_data['year'], month_data['month']
        keyboard.append([InlineKeyboardButton(
            f"{year}年{month}月",
            callback_data=f'response_view_month_{year}_{month}'
        )])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='response_speed_menu')])

    await query.edit_message_text(
        "📅 选择要查看的月份：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RESPONSE_MONTH_SELECT


async def response_view_month(update: Update, context: CallbackContext):
    """查看指定月份的响应统计"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    year = int(parts[-2])
    month = int(parts[-1])

    stats = get_all_employee_response_stats(year, month)
    operators = list_operators()

    text = f"📊 **员工响应速度排名（{year}年{month}月）**\n\n"

    if not stats:
        text += "暂无响应记录\n\n"
    else:
        rank = 1
        total_avg = 0
        total_count = 0
        for emp_id, emp_stats in stats.items():
            if emp_id not in operators:
                continue

            op_info = operators[emp_id]
            name = op_info.get('first_name', f"员工{emp_id}")
            avg_time = format_seconds(emp_stats['avg_response_seconds'])
            rating = get_response_rating_for_seconds(emp_stats['avg_response_seconds'])
            rating_emoji = rating.get('emoji', '❓')
            rating_name = rating.get('level_name', '未知')

            text += f"{rank}️⃣ {rating_emoji}【{rating_name}】{safe_escape_markdown(name)} - 平均响应 {avg_time} - 响应 {emp_stats['total_count']}次\n"

            total_avg += emp_stats['avg_response_seconds'] * emp_stats['total_count']
            total_count += emp_stats['total_count']
            rank += 1

        if total_count > 0:
            overall_avg = total_avg / total_count
            overall_rating = get_response_rating_for_seconds(overall_avg)
            text += f"\n📊 整体统计：\n总响应次数：{total_count}\n平均响应时间：{format_seconds(overall_avg)} {overall_rating['emoji']}\n"

    months_with_records = get_months_with_response_records()
    keyboard = []
    if len(months_with_records) >= 1:
        keyboard.append([InlineKeyboardButton("📅 选择其他月份", callback_data='response_month_select')])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='response_speed_menu')])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RESPONSE_MONTH_SELECT


async def response_work_time_menu(update: Update, context: CallbackContext):
    """设置员工工作时间菜单"""
    query = update.callback_query
    await query.answer()

    operators = list_operators()
    keyboard = []

    for emp_id, op_info in operators.items():
        name = op_info.get('first_name', f"员工{emp_id}")
        work_time = get_employee_work_time(emp_id)
        if work_time:
            time_text = f"⏰ {work_time['work_start']}-{work_time['work_end']}"
        else:
            time_text = "⏰ 未设置"
        keyboard.append([InlineKeyboardButton(
            f"{name} {time_text}",
            callback_data=f'response_set_work_time_{emp_id}'
        )])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='response_speed_menu')])

    await query.edit_message_text(
        "⏰ **设置员工工作时间**\n\n"
        "点击员工名称设置工作时间：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RESPONSE_WORK_TIME_MENU


async def response_set_work_time(update: Update, context: CallbackContext):
    """设置员工工作时间"""
    query = update.callback_query
    await query.answer()

    emp_id = int(query.data.split('_')[-1])
    operators = list_operators()
    op_info = operators.get(emp_id)
    name = op_info.get('first_name', f"员工{emp_id}") if op_info else f"员工{emp_id}"

    work_time = get_employee_work_time(emp_id)
    current_time = f"{work_time['work_start']}-{work_time['work_end']}" if work_time else "未设置"

    context.user_data['response_work_time_emp_id'] = emp_id
    context.user_data['profile_input_state'] = True

    await query.edit_message_text(
        f"⏰ **设置 {safe_escape_markdown(name)} 的工作时间**\n\n"
        f"当前设置：{current_time}\n\n"
        f"请输入工作时间范围（格式：HH:MM-HH:MM）\n"
        f"例如：12:00-22:00 或 12:00-02:00（跨天）\n\n"
        f"❌ 发送 /cancel 取消",
        parse_mode='Markdown'
    )
    return RESPONSE_WORK_TIME_SET


async def response_save_work_time(update: Update, context: CallbackContext):
    """保存员工工作时间"""
    text = update.message.text

    if text == '/cancel':
        await update.message.reply_text("✅ 已取消设置")
        return ConversationHandler.END

    parts = text.split('-')
    if len(parts) != 2:
        await update.message.reply_text(
            "❌ 格式不正确，请重新输入（格式：HH:MM-HH:MM）\n"
            "例如：12:00-22:00",
            parse_mode='Markdown'
        )
        return RESPONSE_WORK_TIME_SET

    work_start, work_end = parts[0].strip(), parts[1].strip()

    try:
        start_parts = work_start.split(':')
        end_parts = work_end.split(':')
        if len(start_parts) != 2 or len(end_parts) != 2:
            raise ValueError("格式错误")
        start_hour = int(start_parts[0])
        start_minute = int(start_parts[1])
        end_hour = int(end_parts[0])
        end_minute = int(end_parts[1])

        if start_hour < 0 or start_hour > 23 or start_minute < 0 or start_minute > 59:
            raise ValueError("开始时间无效")
        if end_hour < 0 or end_hour > 23 or end_minute < 0 or end_minute > 59:
            raise ValueError("结束时间无效")
    except ValueError:
        await update.message.reply_text(
            "❌ 格式不正确，请重新输入（格式：HH:MM-HH:MM）\n"
            "例如：12:00-22:00 或 12:00-02:00（跨天）",
            parse_mode='Markdown'
        )
        return RESPONSE_WORK_TIME_SET

    emp_id = context.user_data.get('response_work_time_emp_id')
    if set_employee_work_time(emp_id, work_start, work_end):
        await update.message.reply_text(f"✅ 工作时间设置成功：{work_start}-{work_end}")
    else:
        await update.message.reply_text("❌ 工作时间设置失败")

    context.user_data['response_message_processed'] = True
    context.user_data.pop('profile_input_state', None)
    context.user_data.pop('response_work_time_emp_id', None)
    return ConversationHandler.END


async def response_rating_config(update: Update, context: CallbackContext):
    """响应评级配置"""
    query = update.callback_query
    await query.answer()

    config = get_response_rating_config()

    text = "⚙️ **响应速度评级配置**\n\n"
    for item in config:
        text += f"{item['emoji']} {safe_escape_markdown(item['level_name'])}: " \
                f"{format_seconds(item['min_seconds'])} - {format_seconds(item['max_seconds'])}\n"

    keyboard = []
    for item in config:
        keyboard.append([InlineKeyboardButton(
            f"✏️ 修改 {item['emoji']} {item['level_name']}",
            callback_data=f'response_edit_rating_{item["level_name"]}'
        )])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='response_speed_menu')])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RESPONSE_RATING_CONFIG


async def response_edit_rating(update: Update, context: CallbackContext):
    """编辑响应评级"""
    query = update.callback_query
    await query.answer()

    level_name = query.data.split('_')[-1]
    config = get_response_rating_config()
    item = next((c for c in config if c['level_name'] == level_name), None)

    if not item:
        await query.edit_message_text("❌ 评级配置不存在")
        return RESPONSE_RATING_CONFIG

    context.user_data['response_rating_level'] = level_name
    context.user_data['profile_input_state'] = True

    await query.edit_message_text(
        f"✏️ **修改 {item['emoji']} {safe_escape_markdown(level_name)}**\n\n"
        f"当前范围：{format_seconds(item['min_seconds'])} - {format_seconds(item['max_seconds'])}\n\n"
        f"请输入新的时间范围（格式：秒数-秒数）\n"
        f"例如：0-300（表示0-5分钟）\n\n"
        f"❌ 发送 /cancel 取消",
        parse_mode='Markdown'
    )
    return RESPONSE_RATING_EDIT


async def response_save_rating(update: Update, context: CallbackContext):
    """保存响应评级"""
    text = update.message.text

    if text == '/cancel':
        await update.message.reply_text("✅ 已取消修改")
        return ConversationHandler.END

    parts = text.split('-')
    if len(parts) != 2:
        await update.message.reply_text(
            "❌ 格式不正确，请重新输入（格式：秒数-秒数）\n"
            "例如：0-300",
            parse_mode='Markdown'
        )
        return RESPONSE_RATING_EDIT

    try:
        min_seconds = float(parts[0].strip())
        max_seconds = float(parts[1].strip())
    except ValueError:
        await update.message.reply_text(
            "❌ 格式不正确，请输入数字",
            parse_mode='Markdown'
        )
        return RESPONSE_RATING_EDIT

    level_name = context.user_data.get('response_rating_level')
    if update_response_rating_config(level_name, min_seconds, max_seconds, ''):
        await update.message.reply_text(f"✅ 评级配置修改成功")
    else:
        await update.message.reply_text("❌ 评级配置修改失败")

    context.user_data['response_message_processed'] = True
    context.user_data.pop('profile_input_state', None)
    context.user_data.pop('response_rating_level', None)
    return ConversationHandler.END


async def response_cleanup(update: Update, context: CallbackContext):
    """清理旧数据"""
    query = update.callback_query
    await query.answer()

    deleted_count = cleanup_old_response_records(6)

    await query.edit_message_text(
        f"🗑️ **清理完成**\n\n"
        f"已清理 {deleted_count} 条6个月前的响应记录",
        parse_mode='Markdown'
    )

    await asyncio.sleep(2)
    await response_speed_menu(update, context)


def register_response_speed_handlers(application):
    """注册响应速度处理器"""
    main_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(response_speed_menu, pattern='^response_speed_menu$')],
        states={
            RESPONSE_MAIN: [
                CallbackQueryHandler(response_month_select, pattern='^response_month_select$'),
                CallbackQueryHandler(response_work_time_menu, pattern='^response_work_time_menu$'),
                CallbackQueryHandler(response_rating_config, pattern='^response_rating_config$'),
                CallbackQueryHandler(response_cleanup, pattern='^response_cleanup$'),
            ],
            RESPONSE_MONTH_SELECT: [
                CallbackQueryHandler(response_view_month, pattern='^response_view_month_'),
            ],
            RESPONSE_WORK_TIME_MENU: [
                CallbackQueryHandler(response_set_work_time, pattern='^response_set_work_time_'),
            ],
            RESPONSE_WORK_TIME_SET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, response_save_work_time),
            ],
            RESPONSE_RATING_CONFIG: [
                CallbackQueryHandler(response_edit_rating, pattern='^response_edit_rating_'),
            ],
            RESPONSE_RATING_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, response_save_rating),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(response_speed_menu, pattern='^response_speed_menu$'),
            CommandHandler('cancel', response_cancel),
        ],
        allow_reentry=True
    )

    application.add_handler(main_conv, group=-1)

    init_response_tables()
