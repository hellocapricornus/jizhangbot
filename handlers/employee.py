from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackContext, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)
from auth import list_operators, safe_escape_markdown
from db import (
    add_task, assign_task, get_tasks, get_task_by_id,
    get_task_assignments, get_employee_tasks, complete_task_assignment,
    confirm_task_assignment, get_pending_review_tasks,
    get_employee_monthly_completion_rate,
    delete_task, mark_task_notified, get_unnotified_tasks,
    get_tasks_needing_reminder, get_overdue_tasks, handle_overdue_task,
    set_employee_base_salary, get_employee_base_salary,
    get_all_employee_salaries, set_employee_incentive, get_employee_incentive_setting,
    get_all_employee_incentive_settings, get_task_completion_stats, get_employee_task_summary,
    get_db_connection, update_task_assignment_detail
)
import logging
logger = logging.getLogger(__name__)
from auth import OWNER_ID
import time
from datetime import datetime, timedelta, timezone

TASK_TITLE, TASK_DESCRIPTION, TASK_PERIOD, TASK_EMPLOYEES, TASK_REMIND, TASK_CONFIRM = range(6)
COMPLETE_DETAIL = range(1)
MODIFY_DETAIL = range(1)
SET_SALARY_AMOUNT = range(1)
SET_INCENTIVE_STATUS = range(1)

async def my_tasks(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    tasks = get_employee_tasks(user_id)

    if not tasks:
        keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='profile')]]
        await query.edit_message_text(
            "📋 **我的任务**\n\n"
            "暂无任务",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    keyboard = []
    for task in tasks:
        status = task['assignment_status']
        completion_percent = task.get('completion_percent', 0)

        if status == 'completed':
            status_emoji = "✅"
            status_text = "已完成"
        elif status == 'pending_review':
            status_emoji = "⏳"
            status_text = "待审核"
        else:
            status_emoji = "📝"
            status_text = "未提交"

        deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%m-%d %H:%M')

        now = int(time.time())
        is_overdue = now > task['deadline'] and status != 'completed'
        overdue_text = " ⚠️" if is_overdue else ""

        keyboard.append([InlineKeyboardButton(
            f"{status_emoji} {task['title']} {overdue_text}\n   {status_text} | 完成度: {completion_percent}% | 截止: {deadline_str}",
            callback_data=f'employee_view_my_task_{task["id"]}_{task.get("assignment_id", 0)}'
        )])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='profile')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📋 **我的任务**\n\n"
        "请选择要查看的任务：",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def view_my_task_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    task_id = int(parts[-2])
    assignment_id = int(parts[-1])

    task = get_task_by_id(task_id)

    if not task:
        await query.edit_message_text("❌ 任务不存在")
        return

    assignments = get_task_assignments(task_id)
    my_assignment = next((a for a in assignments if a['id'] == assignment_id), None)

    deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    created_at_str = datetime.fromtimestamp(task['created_at'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

    now = int(time.time())
    is_overdue = now > task['deadline'] and (not my_assignment or my_assignment['status'] != 'completed')

    status_text = "已完成" if task['status'] == 'completed' else "进行中"
    if is_overdue:
        status_text = "⏰ 已超时"

    completion_detail_text = ""
    if my_assignment and my_assignment['completion_detail']:
        completed_at_str = datetime.fromtimestamp(my_assignment['completed_at'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
        escaped_detail = safe_escape_markdown(my_assignment['completion_detail'])
        completion_detail_text = f"\n\n✅ **完成详情**：\n{escaped_detail}\n\n完成时间：{completed_at_str}"
        if my_assignment['status'] == 'completed' and my_assignment.get('completion_percent', 100) < 100:
            completion_detail_text += f"\n完成度：{my_assignment['completion_percent']}%"

    keyboard = []
    if my_assignment:
        if my_assignment['status'] == 'pending':
            keyboard.append([InlineKeyboardButton("提交任务", callback_data=f'employee_complete_task_{assignment_id}')])
        elif my_assignment['status'] == 'pending_review':
            keyboard.append([InlineKeyboardButton("⏳ 等待审核", callback_data=f'employee_wait_review_{assignment_id}')])
            keyboard.append([InlineKeyboardButton("✏️ 修改任务", callback_data=f'employee_modify_task_{assignment_id}')])
        elif my_assignment['status'] == 'completed':
            keyboard.append([InlineKeyboardButton("✏️ 修改任务", callback_data=f'employee_modify_task_{assignment_id}')])
        else:
            keyboard.append([InlineKeyboardButton("✏️ 修改任务", callback_data=f'employee_modify_task_{assignment_id}')])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='employee_my_tasks')])

    await query.edit_message_text(
        f"📋 **任务详情**\n\n"
        f"标题：{safe_escape_markdown(task['title'])}\n"
        f"描述：{safe_escape_markdown(task['description'])}\n"
        f"截止时间：{deadline_str}\n"
        f"状态：{status_text}\n"
        f"创建时间：{created_at_str}{completion_detail_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def employee_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    pending_count = len(get_pending_review_tasks())
    pending_text = f"待确认任务 ({pending_count})" if pending_count > 0 else "待确认任务"

    keyboard = [
        [InlineKeyboardButton("📝 发布任务", callback_data='employee_publish_task')],
        [InlineKeyboardButton("📋 任务管理", callback_data='employee_task_list')],
        [InlineKeyboardButton(f"✅ {pending_text}", callback_data='employee_pending_review')],
        [InlineKeyboardButton("💰 设置底薪", callback_data='employee_set_salary')],
        [InlineKeyboardButton("🏆 激励奖开关", callback_data='employee_incentive_settings')],
        [InlineKeyboardButton("📊 统计报表", callback_data='employee_statistics')],
        [InlineKeyboardButton("⬅️ 返回", callback_data='profile')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "👤 **员工管理**\n\n"
        "请选择需要操作的功能：",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def pending_review_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    pending_tasks = get_pending_review_tasks()

    if not pending_tasks:
        keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')]]
        await query.edit_message_text(
            "✅ **待确认任务**\n\n"
            "暂无待确认任务",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    keyboard = []
    for task in pending_tasks:
        deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%m-%d %H:%M')
        keyboard.append([InlineKeyboardButton(
            f"⏳ {task['employee_name']} - {task['title']} ({deadline_str})",
            callback_data=f'employee_review_task_{task["id"]}'
        )])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ **待确认任务**\n\n"
        f"共有 {len(pending_tasks)} 个任务等待确认：",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def review_task_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    assignment_id = int(parts[-1])

    pending_tasks = get_pending_review_tasks()
    task = next((t for t in pending_tasks if t['id'] == assignment_id), None)

    if not task:
        await query.edit_message_text("❌ 任务不存在或已被确认")
        return

    deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    submitted_at_str = datetime.fromtimestamp(task['completed_at'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

    keyboard = [
        [InlineKeyboardButton("0%", callback_data=f'employee_confirm_task_{assignment_id}_0'),
         InlineKeyboardButton("10%", callback_data=f'employee_confirm_task_{assignment_id}_10'),
         InlineKeyboardButton("20%", callback_data=f'employee_confirm_task_{assignment_id}_20')],
        [InlineKeyboardButton("30%", callback_data=f'employee_confirm_task_{assignment_id}_30'),
         InlineKeyboardButton("40%", callback_data=f'employee_confirm_task_{assignment_id}_40'),
         InlineKeyboardButton("50%", callback_data=f'employee_confirm_task_{assignment_id}_50')],
        [InlineKeyboardButton("60%", callback_data=f'employee_confirm_task_{assignment_id}_60'),
         InlineKeyboardButton("70%", callback_data=f'employee_confirm_task_{assignment_id}_70'),
         InlineKeyboardButton("80%", callback_data=f'employee_confirm_task_{assignment_id}_80')],
        [InlineKeyboardButton("90%", callback_data=f'employee_confirm_task_{assignment_id}_90'),
         InlineKeyboardButton("100%", callback_data=f'employee_confirm_task_{assignment_id}_100')],
        [InlineKeyboardButton("⬅️ 返回", callback_data='employee_pending_review')]
    ]

    await query.edit_message_text(
        f"✅ **任务审核**\n\n"
        f"员工：{safe_escape_markdown(task['employee_name'])}\n"
        f"任务标题：{safe_escape_markdown(task['title'])}\n"
        f"任务描述：{safe_escape_markdown(task['description'])}\n"
        f"截止时间：{deadline_str}\n\n"
        f"📝 **提交详情**：\n{safe_escape_markdown(task['completion_detail'])}\n\n"
        f"提交时间：{submitted_at_str}\n\n"
        f"请选择完成百分比：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def confirm_task(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    assignment_id = int(parts[-2])
    completion_percent = float(parts[-1])

    if confirm_task_assignment(assignment_id, completion_percent):
        await query.answer(f"✅ 任务已确认，完成度：{completion_percent}%")
    else:
        await query.answer("❌ 确认失败")

    await pending_review_menu(update, context)


async def employee_cancel(update: Update, context: CallbackContext):
    """取消员工操作"""
    await update.message.reply_text("✅ 已取消")
    return ConversationHandler.END


async def start_publish_task(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📝 **发布任务**\n\n"
        "请输入任务标题：\n"
        "❌ 发送 /cancel 取消发布",
        parse_mode='Markdown'
    )
    return TASK_TITLE


async def task_title(update: Update, context: CallbackContext):
    text = update.message.text
    if text == '/cancel':
        await update.message.reply_text("✅ 任务发布已取消")
        return ConversationHandler.END

    context.user_data['task_title'] = text
    await update.message.reply_text(
        "请输入任务描述：\n"
        "❌ 发送 /cancel 取消发布",
        parse_mode='Markdown'
    )
    return TASK_DESCRIPTION


async def task_description(update: Update, context: CallbackContext):
    text = update.message.text
    if text == '/cancel':
        await update.message.reply_text("✅ 任务发布已取消")
        return ConversationHandler.END

    context.user_data['task_description'] = text

    keyboard = [
        [InlineKeyboardButton("今日", callback_data='task_period_today')],
        [InlineKeyboardButton("本周", callback_data='task_period_week')],
        [InlineKeyboardButton("本月", callback_data='task_period_month')],
        [InlineKeyboardButton("❌ 取消发布", callback_data='task_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "请选择任务周期：",
        reply_markup=reply_markup
    )
    return TASK_PERIOD


async def task_period(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == 'task_cancel':
        await query.edit_message_text("✅ 任务发布已取消")
        return ConversationHandler.END

    period_type = query.data.split('_')[-1]
    context.user_data['task_period'] = period_type

    now = datetime.now(timezone(timedelta(hours=8)))
    if period_type == 'today':
        deadline = now.replace(hour=23, minute=59, second=59)
    elif period_type == 'week':
        deadline = now + timedelta(days=(6 - now.weekday()))
        deadline = deadline.replace(hour=23, minute=59, second=59)
    else:
        next_month = now.replace(day=1) + timedelta(days=32)
        last_day = next_month.replace(day=1) - timedelta(days=1)
        deadline = last_day.replace(hour=23, minute=59, second=59)

    context.user_data['task_deadline'] = int(deadline.timestamp())

    operators = list_operators()
    if not operators:
        await query.edit_message_text("❌ 暂无正式操作员，请先添加操作员")
        return ConversationHandler.END

    keyboard = []
    for op_id, op_info in operators.items():
        user_id = op_id
        name = op_info.get('first_name', f"员工{user_id}")
        keyboard.append([InlineKeyboardButton(f"✅ {name}", callback_data=f'task_employee_{user_id}')])
    keyboard.append([InlineKeyboardButton("✅ 确认选择", callback_data='task_employee_done')])
    keyboard.append([InlineKeyboardButton("❌ 取消发布", callback_data='task_cancel')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "请选择需要完成此任务的员工（可多选）：",
        reply_markup=reply_markup
    )
    context.user_data['selected_employees'] = []
    return TASK_EMPLOYEES


async def task_employees(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == 'task_cancel':
        await query.edit_message_text("✅ 任务发布已取消")
        return ConversationHandler.END

    if data == 'task_employee_done':
        if not context.user_data.get('selected_employees'):
            await query.edit_message_text("❌ 请至少选择一名员工")
            return TASK_EMPLOYEES

        keyboard = [
            [InlineKeyboardButton("开启提醒", callback_data='task_remind_on')],
            [InlineKeyboardButton("不开启提醒", callback_data='task_remind_off')],
            [InlineKeyboardButton("❌ 取消发布", callback_data='task_cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "是否开启超时提醒？",
            reply_markup=reply_markup
        )
        return TASK_REMIND

    user_id = int(data.split('_')[-1])
    selected = context.user_data.get('selected_employees', [])

    if user_id in selected:
        selected.remove(user_id)
    else:
        selected.append(user_id)

    context.user_data['selected_employees'] = selected

    operators = list_operators()
    keyboard = []
    for op_id, op_info in operators.items():
        op_user_id = op_id
        name = op_info.get('first_name', f"员工{op_user_id}")
        prefix = "✅ " if op_user_id in selected else "⬜ "
        keyboard.append([InlineKeyboardButton(f"{prefix}{name}", callback_data=f'task_employee_{op_user_id}')])
    keyboard.append([InlineKeyboardButton("✅ 确认选择", callback_data='task_employee_done')])
    keyboard.append([InlineKeyboardButton("❌ 取消发布", callback_data='task_cancel')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "请选择需要完成此任务的员工（可多选）：",
        reply_markup=reply_markup
    )
    return TASK_EMPLOYEES


async def task_remind(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == 'task_cancel':
        await query.edit_message_text("✅ 任务发布已取消")
        return ConversationHandler.END

    if data == 'task_remind_on':
        context.user_data['task_remind_enabled'] = 1

        deadline = context.user_data.get('task_deadline')
        remind_time = deadline - 3600

        context.user_data['task_remind_time'] = remind_time

        await query.edit_message_text(
            f"⏰ 提醒时间设置为截止前1小时\n\n"
            f"任务标题：{context.user_data['task_title']}\n"
            f"任务描述：{context.user_data['task_description']}\n"
            f"任务周期：{context.user_data['task_period']}\n"
            f"截止时间：{datetime.fromtimestamp(deadline, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}\n"
            f"提醒时间：{datetime.fromtimestamp(remind_time, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}\n"
            f"员工：{len(context.user_data['selected_employees'])}人\n\n"
            f"确认发布？",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("确认发布", callback_data='task_confirm_yes')],
                [InlineKeyboardButton("取消", callback_data='task_confirm_no')]
            ])
        )
    else:
        context.user_data['task_remind_enabled'] = 0
        context.user_data['task_remind_time'] = 0

        deadline = context.user_data.get('task_deadline')

        await query.edit_message_text(
            f"任务标题：{context.user_data['task_title']}\n"
            f"任务描述：{context.user_data['task_description']}\n"
            f"任务周期：{context.user_data['task_period']}\n"
            f"截止时间：{datetime.fromtimestamp(deadline, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}\n"
            f"提醒：关闭\n"
            f"员工：{len(context.user_data['selected_employees'])}人\n\n"
            f"确认发布？",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("确认发布", callback_data='task_confirm_yes')],
                [InlineKeyboardButton("取消", callback_data='task_confirm_no')]
            ])
        )
    return TASK_CONFIRM


async def task_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == 'task_confirm_no':
        await query.edit_message_text("✅ 任务发布已取消")
        return ConversationHandler.END

    title = context.user_data['task_title']
    description = context.user_data['task_description']
    period_type = context.user_data['task_period']
    deadline = context.user_data['task_deadline']
    remind_time = context.user_data.get('task_remind_time', 0)
    remind_enabled = context.user_data.get('task_remind_enabled', 0)
    selected_employees = context.user_data['selected_employees']

    task_id = add_task(title, description, period_type, deadline, remind_time, remind_enabled, update.effective_user.id)

    if task_id:
        operators = list_operators()
        op_dict = {op_id: op_info.get('first_name', f"员工{op_id}") for op_id, op_info in operators.items()}

        for emp_id in selected_employees:
            emp_name = op_dict.get(emp_id, f"员工{emp_id}")
            assign_task(task_id, emp_id, emp_name)

        await query.edit_message_text(f"✅ 任务发布成功！任务ID：{task_id}")

        await notify_task_assignment(context.bot, task_id, title, description, deadline)
    else:
        await query.edit_message_text("❌ 任务发布失败")

    return ConversationHandler.END


async def notify_task_assignment(bot, task_id, title, description, deadline):
    assignments = get_task_assignments(task_id)

    for assignment in assignments:
        if assignment['notified'] == 0:
            try:
                deadline_str = datetime.fromtimestamp(deadline, timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

                await bot.send_message(
                    chat_id=assignment['employee_id'],
                    text=f"📋 **新任务通知**\n\n"
                         f"任务标题：{safe_escape_markdown(title)}\n"
                         f"任务描述：{safe_escape_markdown(description)}\n"
                         f"截止时间：{deadline_str}\n\n"
                         f"请按时完成任务！",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("查看任务", callback_data=f'employee_view_task_{task_id}_{assignment["id"]}')]
                    ])
                )

                mark_task_notified(assignment['id'])
            except Exception as e:
                print(f"通知员工 {assignment['employee_id']} 失败: {e}")


async def task_list(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    tasks = get_tasks()

    if not tasks:
        keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')]]
        await query.edit_message_text(
            "📋 **任务管理**\n\n"
            "暂无任务",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    keyboard = []
    for task in tasks:
        status_emoji = "✅" if task['status'] == 'completed' else "⏳"
        deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%m-%d %H:%M')
        keyboard.append([InlineKeyboardButton(
            f"{status_emoji} {task['title']} ({deadline_str})",
            callback_data=f'employee_view_task_detail_{task["id"]}'
        )])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📋 **任务管理**\n\n"
        "请选择要查看的任务：",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def view_task_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split('_')[-1])
    task = get_task_by_id(task_id)

    if not task:
        await query.edit_message_text("❌ 任务不存在")
        return

    assignments = get_task_assignments(task_id)

    deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    created_at_str = datetime.fromtimestamp(task['created_at'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

    status_text = "已完成" if task['status'] == 'completed' else "进行中"
    remind_text = f"⏰ {datetime.fromtimestamp(task['remind_time'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}" if task['remind_enabled'] else "关闭"

    employee_list = ""
    for a in assignments:
        status_text = '✅ 已完成' if a['status'] == 'completed' else '⏳ 进行中'
        employee_list += f"• {safe_escape_markdown(a['employee_name'])} - {status_text}\n"
        if a['status'] == 'completed' and a['completion_detail']:
            completed_at_str = datetime.fromtimestamp(a['completed_at'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
            employee_list += f"  └─ 完成详情：{safe_escape_markdown(a['completion_detail'])}\n  └─ 完成时间：{completed_at_str}\n"

    keyboard = [
        [InlineKeyboardButton("删除任务", callback_data=f'employee_delete_task_{task_id}')],
        [InlineKeyboardButton("⬅️ 返回", callback_data='employee_task_list')]
    ]

    await query.edit_message_text(
        f"📋 **任务详情**\n\n"
        f"标题：{safe_escape_markdown(task['title'])}\n"
        f"描述：{safe_escape_markdown(task['description'])}\n"
        f"周期：{safe_escape_markdown(task['period_type'])}\n"
        f"截止时间：{deadline_str}\n"
        f"提醒：{remind_text}\n"
        f"状态：{status_text}\n"
        f"创建时间：{created_at_str}\n\n"
        f"分配员工：\n{employee_list}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def delete_task_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split('_')[-1])

    if delete_task(task_id):
        await query.edit_message_text("✅ 任务删除成功")
    else:
        await query.edit_message_text("❌ 任务删除失败")

    await task_list(update, context)


async def view_employee_task(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    task_id = int(parts[-2])
    assignment_id = int(parts[-1])

    task = get_task_by_id(task_id)

    if not task:
        await query.edit_message_text("❌ 任务不存在")
        return

    assignments = get_task_assignments(task_id)
    my_assignment = next((a for a in assignments if a['id'] == assignment_id), None)

    deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

    keyboard = []
    if my_assignment:
        if my_assignment['status'] == 'pending':
            keyboard.append([InlineKeyboardButton("提交任务", callback_data=f'employee_complete_task_{assignment_id}')])
        elif my_assignment['status'] == 'pending_review':
            keyboard.append([InlineKeyboardButton("⏳ 等待审核", callback_data=f'employee_wait_review_{assignment_id}')])
            keyboard.append([InlineKeyboardButton("✏️ 修改任务", callback_data=f'employee_modify_task_{assignment_id}')])
        elif my_assignment['status'] == 'completed':
            keyboard.append([InlineKeyboardButton("✏️ 修改任务", callback_data=f'employee_modify_task_{assignment_id}')])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='employee_my_tasks')])

    status_text = "未提交"
    if my_assignment:
        if my_assignment['status'] == 'completed':
            status_text = "已完成"
        elif my_assignment['status'] == 'pending_review':
            status_text = "待审核"

    await query.edit_message_text(
        f"📋 **任务详情**\n\n"
        f"标题：{task['title']}\n"
        f"描述：{task['description']}\n"
        f"截止时间：{deadline_str}\n"
        f"状态：{status_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def wait_review_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    await query.answer("⏳ 任务正在等待管理员审核，请耐心等待")


async def complete_task(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    assignment_id = int(query.data.split('_')[-1])
    context.user_data['complete_assignment_id'] = assignment_id

    await query.edit_message_text(
        "请输入任务完成详情：",
        parse_mode='Markdown'
    )
    return COMPLETE_DETAIL


async def complete_detail(update: Update, context: CallbackContext):
    detail = update.message.text
    assignment_id = context.user_data.get('complete_assignment_id')
    employee_id = update.effective_user.id

    if complete_task_assignment(assignment_id, detail):
        await update.message.reply_text(
            "✅ 任务完成成功！",
            parse_mode='Markdown'
        )

        await notify_admin_task_completed(context.bot, assignment_id, employee_id, detail)
    else:
        await update.message.reply_text(
            "❌ 任务完成失败",
            parse_mode='Markdown'
        )

    return ConversationHandler.END


async def modify_task(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    assignment_id = int(query.data.split('_')[-1])
    context.user_data['modify_assignment_id'] = assignment_id

    await query.edit_message_text(
        "请输入修改后的任务完成详情：",
        parse_mode='Markdown'
    )
    return MODIFY_DETAIL


async def modify_detail(update: Update, context: CallbackContext):
    detail = update.message.text
    assignment_id = context.user_data.get('modify_assignment_id')
    employee_id = update.effective_user.id

    if update_task_assignment_detail(assignment_id, detail):
        await update.message.reply_text(
            "✅ 任务修改成功！已提交管理员审核",
            parse_mode='Markdown'
        )

        await notify_admin_task_completed(context.bot, assignment_id, employee_id, detail, is_modify=True)
    else:
        await update.message.reply_text(
            "❌ 任务修改失败",
            parse_mode='Markdown'
        )

    return ConversationHandler.END


async def notify_admin_task_completed(bot, assignment_id, employee_id, detail, is_modify=False):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            SELECT ta.*, t.title, t.description, t.deadline
            FROM task_assignments ta
            JOIN tasks t ON ta.task_id = t.id
            WHERE ta.id = ?
        """, (assignment_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return

        task_info = dict(row)
        employee_name = task_info.get('employee_name', f"员工{employee_id}")

        deadline_str = datetime.fromtimestamp(task_info['deadline'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

        now = int(time.time())
        is_overdue = now > task_info['deadline']

        if is_modify:
            notification_title = "🔄 **任务修改通知**"
            overdue_text = "\n⚠️ 此任务已超时" if is_overdue else ""
        else:
            notification_title = "🎉 **任务完成通知**"
            overdue_text = "\n⚠️ 此任务已超时提交" if is_overdue else ""

        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"{notification_title}\n\n"
                 f"员工：{employee_name}\n"
                 f"任务标题：{task_info['title']}\n"
                 f"任务描述：{task_info['description']}\n"
                 f"截止时间：{deadline_str}{overdue_text}\n\n"
                 f"✅ **完成详情**：\n{detail}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"通知管理员任务完成失败: {e}")


async def set_salary_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    operators = list_operators()
    if not operators:
        keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')]]
        await query.edit_message_text(
            "💰 **设置底薪**\n\n"
            "暂无正式操作员",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    salaries = {s['employee_id']: s['monthly_base'] for s in get_all_employee_salaries()}

    keyboard = []
    for op_id, op_info in operators.items():
        user_id = op_id
        name = op_info.get('first_name', f"员工{user_id}")
        salary = salaries.get(user_id, 0)
        salary_text = f"当前: {salary} USDT" if salary > 0 else "未设置"
        keyboard.append([InlineKeyboardButton(f"{name} ({salary_text})", callback_data=f'employee_set_salary_{user_id}')])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "💰 **设置底薪**\n\n"
        "请选择要设置底薪的员工：",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def set_salary_amount(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    employee_id = int(query.data.split('_')[-1])
    context.user_data['set_salary_employee_id'] = employee_id

    operators = list_operators()
    emp_name = next((op_info.get('first_name', f"员工{op_id}") for op_id, op_info in operators.items() if op_id == employee_id), f"员工{employee_id}")

    await query.edit_message_text(
        f"请输入 {emp_name} 的月底薪（USDT）：",
        parse_mode='Markdown'
    )
    return SET_SALARY_AMOUNT


async def save_salary(update: Update, context: CallbackContext):
    try:
        amount = float(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ 请输入有效的数字")
        return SET_SALARY_AMOUNT

    employee_id = context.user_data.get('set_salary_employee_id')

    if set_employee_base_salary(employee_id, amount, update.effective_user.id):
        await update.message.reply_text(f"✅ 底薪设置成功：{amount} USDT")
    else:
        await update.message.reply_text("❌ 底薪设置失败")

    return ConversationHandler.END


async def incentive_settings_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    operators = list_operators()
    if not operators:
        keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')]]
        await query.edit_message_text(
            "🏆 **激励奖开关**\n\n"
            "暂无正式操作员",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    settings = {s['employee_id']: s['incentive_enabled'] for s in get_all_employee_incentive_settings()}

    keyboard = []
    for op_id, op_info in operators.items():
        user_id = op_id
        name = op_info.get('first_name', f"员工{user_id}")
        enabled = settings.get(user_id, 1)
        status = "开启" if enabled else "关闭"
        keyboard.append([InlineKeyboardButton(f"{name} - {status}", callback_data=f'employee_toggle_incentive_{user_id}_{1-enabled}')])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🏆 **激励奖开关**\n\n"
        "点击员工名称切换激励奖状态：",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def toggle_incentive(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    employee_id = int(parts[-2])
    enabled = int(parts[-1])

    if set_employee_incentive(employee_id, enabled, update.effective_user.id):
        operators = list_operators()
        emp_name = next((op_info.get('first_name', f"员工{op_id}") for op_id, op_info in operators.items() if op_id == employee_id), f"员工{employee_id}")
        status = "开启" if enabled else "关闭"
        await query.edit_message_text(f"✅ {emp_name} 的激励奖已{status}")
    else:
        await query.edit_message_text("❌ 设置失败")

    await incentive_settings_menu(update, context)


async def statistics_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    stats = get_task_completion_stats()
    operators = list_operators()
    op_dict = {op_id: op_info.get('first_name', f"员工{op_id}") for op_id, op_info in operators.items()}

    now = datetime.now(timezone(timedelta(hours=8)))
    current_month = now.strftime('%Y-%m')

    employee_stats_text = ""
    if operators:
        employee_stats_text = "\n".join([
            f"• {op_dict[op_id]}: {get_employee_task_summary(op_id)['completed']}/{get_employee_task_summary(op_id)['total']} ({get_employee_task_summary(op_id)['completion_rate']}%)"
            for op_id in operators.keys()
        ])
    else:
        employee_stats_text = "暂无正式操作员"

    keyboard = [
        [InlineKeyboardButton("员工任务进度", callback_data='employee_task_progress')],
        [InlineKeyboardButton("员工底薪一览", callback_data='employee_salary_list')],
        [InlineKeyboardButton("⬅️ 返回", callback_data='employee_menu')]
    ]

    await query.edit_message_text(
        f"📊 **统计报表**\n\n"
        f"📅 统计周期：{current_month}\n\n"
        f"📈 **整体完成情况**\n"
        f"总任务数：{stats['total_tasks']}\n"
        f"已完成：{stats['completed_tasks']}\n"
        f"进行中：{stats['total_tasks'] - stats['completed_tasks']}\n"
        f"完成率：{stats['completion_rate']}%\n\n"
        f"👤 **员工完成情况**\n{employee_stats_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def task_progress(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    operators = list_operators()
    if not operators:
        keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='employee_statistics')]]
        await query.edit_message_text(
            "📊 **员工任务进度**\n\n"
            "暂无正式操作员",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    keyboard = []
    for op_id, op_info in operators.items():
        user_id = op_id
        name = op_info.get('first_name', f"员工{user_id}")
        summary = get_employee_task_summary(user_id)
        keyboard.append([InlineKeyboardButton(
            f"{name}: {summary['completed']}/{summary['total']} ({summary['completion_rate']}%)",
            callback_data=f'employee_progress_detail_{user_id}'
        )])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='employee_statistics')])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📊 **员工任务进度**\n\n"
        "请选择员工查看详情：",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def progress_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    employee_id = int(query.data.split('_')[-1])

    operators = list_operators()
    emp_name = next((op_info.get('first_name', f"员工{op_id}") for op_id, op_info in operators.items() if op_id == employee_id), f"员工{employee_id}")

    summary = get_employee_task_summary(employee_id)
    tasks = get_employee_tasks(employee_id)

    task_list = "\n".join([
        f"{'✅' if t['assignment_status'] == 'completed' else '⏳'} {safe_escape_markdown(t['title'])} - "
        f"{datetime.fromtimestamp(t['deadline'], timezone(timedelta(hours=8))).strftime('%m-%d')}"
        for t in tasks
    ]) if tasks else "暂无任务"

    keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='employee_task_progress')]]

    await query.edit_message_text(
        f"📊 **{safe_escape_markdown(emp_name)} 的任务进度**\n\n"
        f"总任务：{summary['total']}\n"
        f"已完成：{summary['completed']}\n"
        f"进行中：{summary['pending']}\n"
        f"已超时：{summary['overdue']}\n"
        f"完成率：{summary['completion_rate']}%\n\n"
        f"任务列表：\n{task_list}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def salary_list(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    salaries = get_all_employee_salaries()
    operators = list_operators()

    op_dict = {op_id: op_info.get('first_name', f"员工{op_id}") for op_id, op_info in operators.items()}

    salary_list_text = "\n".join([
        f"• {op_dict[s['employee_id']]}: {s['monthly_base']} USDT"
        for s in salaries if s['monthly_base'] > 0 and s['employee_id'] in op_dict
    ]) if salaries else "暂无底薪设置"

    if salary_list_text == "" and salaries:
        salary_list_text = "暂无在正式操作员列表中的员工底薪设置"

    keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data='employee_statistics')]]

    await query.edit_message_text(
        f"💰 **员工底薪一览**\n\n{salary_list_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def check_task_reminders(context: CallbackContext):
    reminders = get_tasks_needing_reminder()

    for reminder in reminders:
        try:
            deadline_str = datetime.fromtimestamp(reminder['deadline'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

            await context.bot.send_message(
                chat_id=reminder['employee_id'],
                text=f"⏰ **任务提醒**\n\n"
                     f"任务标题：{reminder['title']}\n"
                     f"截止时间：{deadline_str}\n\n"
                     f"请尽快完成任务！",
                parse_mode='Markdown'
            )

            mark_task_notified(reminder['id'])
        except Exception as e:
            print(f"发送提醒失败: {e}")


async def check_overdue_tasks(context: CallbackContext):
    overdue_tasks = get_overdue_tasks()

    for task in overdue_tasks:
        try:
            handle_overdue_task(task['id'])

            deadline_str = datetime.fromtimestamp(task['deadline'], timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"⚠️ **任务超时通知**\n\n"
                     f"员工：{task['employee_name']}\n"
                     f"任务标题：{task['title']}\n"
                     f"截止时间：{deadline_str}\n\n"
                     f"此任务已超时，默认完成度设为0%，等待审核",
                parse_mode='Markdown'
            )

            await context.bot.send_message(
                chat_id=task['employee_id'],
                text=f"⏰ **任务超时提醒**\n\n"
                     f"任务标题：{task['title']}\n"
                     f"截止时间：{deadline_str}\n\n"
                     f"此任务已超时，如需修改请点击「修改任务」按钮重新提交，等待管理员审核",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"处理超时任务失败: {e}")


def register_employee_handlers(application):
    publish_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_publish_task, pattern='^employee_publish_task$')],
        states={
            TASK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_title)],
            TASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_description)],
            TASK_PERIOD: [CallbackQueryHandler(task_period, pattern='^task_period_'), CallbackQueryHandler(task_period, pattern='^task_cancel$')],
            TASK_EMPLOYEES: [CallbackQueryHandler(task_employees, pattern='^task_employee_'), CallbackQueryHandler(task_employees, pattern='^task_cancel$')],
            TASK_REMIND: [CallbackQueryHandler(task_remind, pattern='^task_remind_'), CallbackQueryHandler(task_remind, pattern='^task_cancel$')],
            TASK_CONFIRM: [CallbackQueryHandler(task_confirm, pattern='^task_confirm_')],
        },
        fallbacks=[CallbackQueryHandler(employee_menu, pattern='^employee_menu$'), CommandHandler('cancel', employee_cancel)],
        allow_reentry=True
    )

    complete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(complete_task, pattern='^employee_complete_task_')],
        states={
            COMPLETE_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, complete_detail)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    modify_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(modify_task, pattern='^employee_modify_task_')],
        states={
            MODIFY_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, modify_detail)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    salary_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_salary_amount, pattern='^employee_set_salary_[0-9]+$')],
        states={
            SET_SALARY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_salary)],
        },
        fallbacks=[CallbackQueryHandler(set_salary_menu, pattern='^employee_set_salary$')],
        allow_reentry=True
    )

    application.add_handler(publish_conv, group=-1)
    application.add_handler(complete_conv, group=-1)
    application.add_handler(modify_conv, group=-1)
    application.add_handler(salary_conv, group=-1)

    application.add_handler(CallbackQueryHandler(employee_menu, pattern='^employee_menu$'), group=-1)
    application.add_handler(CallbackQueryHandler(pending_review_menu, pattern='^employee_pending_review$'), group=-1)
    application.add_handler(CallbackQueryHandler(review_task_detail, pattern='^employee_review_task_'), group=-1)
    application.add_handler(CallbackQueryHandler(confirm_task, pattern='^employee_confirm_task_'), group=-1)
    application.add_handler(CallbackQueryHandler(my_tasks, pattern='^employee_my_tasks$'), group=-1)
    application.add_handler(CallbackQueryHandler(view_my_task_detail, pattern='^employee_view_my_task_'), group=-1)
    application.add_handler(CallbackQueryHandler(task_list, pattern='^employee_task_list$'), group=-1)
    application.add_handler(CallbackQueryHandler(view_task_detail, pattern='^employee_view_task_detail_'), group=-1)
    application.add_handler(CallbackQueryHandler(delete_task_handler, pattern='^employee_delete_task_'), group=-1)
    application.add_handler(CallbackQueryHandler(view_employee_task, pattern='^employee_view_task_'), group=-1)
    application.add_handler(CallbackQueryHandler(wait_review_handler, pattern='^employee_wait_review_'), group=-1)
    application.add_handler(CallbackQueryHandler(set_salary_menu, pattern='^employee_set_salary$'), group=-1)
    application.add_handler(CallbackQueryHandler(incentive_settings_menu, pattern='^employee_incentive_settings$'), group=-1)
    application.add_handler(CallbackQueryHandler(toggle_incentive, pattern='^employee_toggle_incentive_'), group=-1)
    application.add_handler(CallbackQueryHandler(statistics_menu, pattern='^employee_statistics$'), group=-1)
    application.add_handler(CallbackQueryHandler(task_progress, pattern='^employee_task_progress$'), group=-1)
    application.add_handler(CallbackQueryHandler(progress_detail, pattern='^employee_progress_detail_'), group=-1)
    application.add_handler(CallbackQueryHandler(salary_list, pattern='^employee_salary_list$'), group=-1)
