# handlers/attendance_admin.py

import calendar
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackContext
from auth import list_operators, safe_escape_markdown, OWNER_ID
from db import (
    get_all_operators_today_status,
    get_employee_monthly_attendance,
    get_employee_work_time,
    get_months_with_response_records,
)
from logger import bot_logger as logger

CST = timezone(timedelta(hours=8))

STATUS_DISPLAY = {
    'online': '🟢 在线',
    'away': '🟡 离开',
    'offline': '⚫ 已下班',
    'scheduled_on': '🔵 在岗(未打卡)',
    'scheduled_off': '⚪ 休息',
}

DAY_STATUS_TEXT = {
    'normal': '✅ 正常',
    'late': '⚠️ 迟到',
    'no_record': '❌ 缺勤',
    'rest': '📅 休息',
}


def _fmt_time(ts):
    if not ts:
        return '—'
    return datetime.fromtimestamp(ts, CST).strftime('%H:%M')


def _fmt_duration(seconds):
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h:
        return f"{h}时{m}分"
    return f"{m}分"


async def attendance_dashboard(update: Update, context: CallbackContext):
    """管理员考勤看板 - 全员今日实时状态"""
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return
    await query.answer()

    records = get_all_operators_today_status()

    text = "📋 **考勤看板（今日实时）**\n\n"
    if not records:
        text += "暂无操作员\n"
    else:
        for r in records:
            status_text = STATUS_DISPLAY.get(r['status'], r['status'])
            ci = _fmt_time(r['check_in_time'])
            dur = _fmt_duration(r['online_duration'])
            name = safe_escape_markdown(r['name'])
            text += f"{status_text} {name}\n"
            text += f"  上班打卡：{ci}  在线时长：{dur}\n\n"

    now = datetime.now(CST)
    text += f"更新时间：{now.strftime('%H:%M:%S')}"

    keyboard = []
    if records:
        keyboard.append([InlineKeyboardButton("📊 月度考勤明细", callback_data='att_month_select')])
    keyboard.append([InlineKeyboardButton("🔄 刷新", callback_data='attendance_dashboard')])
    keyboard.append([InlineKeyboardButton("⬅️ 返回员工管理", callback_data='employee_menu')])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def attendance_month_select(update: Update, context: CallbackContext):
    """选择员工查看月度考勤"""
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return
    await query.answer()

    operators = {uid: info for uid, info in list_operators().items() if uid != OWNER_ID}
    keyboard = []
    for emp_id, op_info in operators.items():
        name = op_info.get('first_name', f"员工{emp_id}")
        keyboard.append([InlineKeyboardButton(
            f"👤 {name}",
            callback_data=f'att_emp_{emp_id}'
        )])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='attendance_dashboard')])

    await query.edit_message_text(
        "📊 **月度考勤明细**\n\n选择要查看的员工：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def attendance_emp_months(update: Update, context: CallbackContext):
    """选择员工后，选择月份"""
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return
    await query.answer()

    emp_id = int(query.data.split('_')[-1])
    context.user_data['att_emp_id'] = emp_id

    operators = list_operators()
    name = operators.get(emp_id, {}).get('first_name', f"员工{emp_id}")

    now = datetime.now(CST)
    keyboard = []
    row = []
    for i in range(6):
        dt = now.replace(day=1) - timedelta(days=i * 30)
        # 取月初
        first = dt.replace(day=1)
        label = f"{first.year}年{first.month}月"
        if first.year == now.year and first.month == now.month:
            label += "（本月）"
        row.append(InlineKeyboardButton(label, callback_data=f'att_month_{emp_id}_{first.year}_{first.month}'))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='att_month_select')])

    await query.edit_message_text(
        f"📅 **{safe_escape_markdown(name)} 的考勤**\n\n选择月份：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def attendance_month_detail(update: Update, context: CallbackContext):
    """查看员工某月考勤明细"""
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("❌ 无权限", show_alert=True)
        return
    await query.answer()

    parts = query.data.split('_')
    emp_id = int(parts[-3])
    year = int(parts[-2])
    month = int(parts[-1])

    operators = list_operators()
    name = operators.get(emp_id, {}).get('first_name', f"员工{emp_id}")

    records = get_employee_monthly_attendance(emp_id, year, month)

    text = f"📊 **{safe_escape_markdown(name)} {year}年{month}月考勤**\n\n"

    if not records:
        text += "本月无打卡记录\n"
    else:
        total_online = 0
        normal_count = late_count = absent_count = rest_count = 0
        lines = []
        for r in records:
            date_md = r['date'][5:]  # MM-DD
            status_text = DAY_STATUS_TEXT.get(r['status'], r['status'])
            ci = _fmt_time(r['check_in'])
            co = _fmt_time(r['check_out'])
            dur = _fmt_duration(r['online_duration'])
            total_online += r['online_duration']

            if r['status'] == 'normal':
                normal_count += 1
            elif r['status'] == 'late':
                late_count += 1
            elif r['status'] == 'no_record':
                absent_count += 1
            elif r['status'] == 'rest':
                rest_count += 1

            lines.append(f"{date_md}  {status_text}  上班{ci}  下班{co}  在线{dur}")

        text += "\n".join(lines)
        text += f"\n\n━━━━━━━━━━━━━━━\n"
        text += f"出勤：{normal_count}天  迟到：{late_count}天  缺勤：{absent_count}天  休息：{rest_count}天\n"
        text += f"累计在线：{_fmt_duration(total_online)}"

    keyboard = [
        [InlineKeyboardButton("⬅️ 更换月份", callback_data=f'att_emp_{emp_id}')],
        [InlineKeyboardButton("⬅️ 返回看板", callback_data='attendance_dashboard')],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


def register_attendance_admin_handlers(application):
    """注册管理员考勤看板处理器（独立 group，避免被 button_router 同组抢占）"""
    from telegram.ext import CallbackQueryHandler

    application.add_handler(
        CallbackQueryHandler(attendance_dashboard, pattern='^attendance_dashboard$'),
        group=5
    )
    application.add_handler(
        CallbackQueryHandler(attendance_month_select, pattern='^att_month_select$'),
        group=5
    )
    application.add_handler(
        CallbackQueryHandler(attendance_emp_months, pattern='^att_emp_\\d+$'),
        group=5
    )
    application.add_handler(
        CallbackQueryHandler(attendance_month_detail, pattern='^att_month_\\d+_\\d+_\\d+$'),
        group=5
    )
