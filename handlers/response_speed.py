# handlers/response_speed.py

import asyncio
import re
import time
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, CommandHandler, CallbackContext, filters
from auth import list_operators, safe_escape_markdown, OWNER_ID
from db import (
    add_response_record, get_all_employee_response_stats, get_employee_response_stats,
    set_employee_work_time, get_employee_work_time, is_in_work_time,
    get_response_rating_config, update_response_rating_config, cleanup_old_response_records,
    get_months_with_response_records, get_response_rating_for_seconds,
    init_response_tables,
    get_effective_online_status, is_effectively_online, is_scheduled_work_time,
    get_employee_weekly_rest, set_employee_weekly_rest,
    get_employee_temp_schedules, set_employee_temp_schedule, delete_employee_temp_schedule
)
from logger import bot_logger as logger

RESPONSE_MAIN = 1
RESPONSE_MONTH_SELECT = 2
RESPONSE_EMPLOYEE_DETAIL = 3
RESPONSE_WORK_TIME_MENU = 4
RESPONSE_WORK_TIME_SET = 5
RESPONSE_RATING_CONFIG = 6
RESPONSE_RATING_EDIT = 7
RESPONSE_EMP_SCHEDULE = 8
RESPONSE_WEEKLY_REST = 9
RESPONSE_TEMP_SCHEDULE = 10
RESPONSE_TEMP_SCHEDULE_ADD = 11

WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

pending_customer_messages = {}

# ========== 结束语词典：客户发送这些消息时不计入响应统计 ==========
CLOSING_WORDS = {
    '到', '好的', '收到', '谢谢', '嗯', '行', 'ok', '了解', '明白', '1',
    '好的谢谢', '好的收到', '收到谢谢', '嗯嗯', '行吧', '好的呢',
}
CLOSING_EMOJIS = {'👍', '👌', '🙏', '😊', '✅', '😄', '😁', '🆗', '💯'}

# ========== 机器人触发指令模式：触发机器人回复的消息不计入响应统计 ==========
BOT_TRIGGER_PATTERNS = [
    r'^[+-]\d',                                                           # 记账：+100 或 -100
    r'^下发',                                                              # 下发100u
    r'^设置(手续费|汇率|单笔费用)',                                        # 设置命令
    r'^(今日总|总|当前账单|查询账单|导出账单|清理账单|清空账单|清理总账单|清空总账单|清空所有账单|移除上一笔|删除上一笔|撤销账单|结束账单)$',  # 账单命令
    r'^(查看配置|查看设置)$',                                              # 查看配置
    r'^(添加操作人|删除操作人)',                                           # 操作人管理
    r'^发送.+规则$',                                                       # 规则查询
    r'^T[1-9A-HJ-NP-Za-km-z]{33}$',                                      # TRC20地址查询
    r'^0x[0-9a-fA-F]{40}$',                                              # ERC20地址查询
]
BOT_TRIGGER_REGEXES = [re.compile(p) for p in BOT_TRIGGER_PATTERNS]

# 计算器表达式匹配：包含数字和运算符的表达式
CALC_PATTERN = re.compile(r'^[\d.+\-*/%() ^]+$')


# ========== 客户 @ 员工离线自动回复 ==========
OFFLINE_REPLY_COOLDOWN = 300  # 同一群组同一员工 5 分钟内不重复提醒
offline_reply_cache = {}  # {(chat_id, employee_id): last_reply_ts}


def get_mentioned_operator_ids(message) -> set:
    """从消息中提取被 @ 的操作员 ID（支持 @username 和无用户名用户的 text_mention）"""
    mentioned = set()
    operators = list_operators()

    def parse_entities(entities, text):
        if not entities or not text:
            return
        for entity in entities:
            if entity.type == 'mention':
                uname = text[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                for uid, info in operators.items():
                    if info.get('username') and info['username'].lower() == uname:
                        mentioned.add(uid)
            elif entity.type == 'text_mention' and getattr(entity, 'user', None):
                if entity.user.id in operators:
                    mentioned.add(entity.user.id)

    parse_entities(message.entities, message.text)
    parse_entities(message.caption_entities, message.caption)
    return mentioned


async def reply_offline_mentioned_employees(message):
    """客户 @ 了不在工作时间内的员工时，自动回复提示"""
    mentioned_ids = get_mentioned_operator_ids(message)
    if not mentioned_ids:
        return

    operators = list_operators()
    now_ts = int(time.time())
    offline_entries = []

    for emp_id in mentioned_ids:
        status_info = get_effective_online_status(emp_id)
        if status_info['online']:
            continue  # 在线（含打卡在线/排班在岗），不提醒
        cache_key = (message.chat_id, emp_id)
        if now_ts - offline_reply_cache.get(cache_key, 0) < OFFLINE_REPLY_COOLDOWN:
            continue  # 冷却期内不重复提醒
        offline_reply_cache[cache_key] = now_ts

        op_info = operators.get(emp_id) or {}
        name = op_info.get('first_name') or f"员工{emp_id}"
        work_time = get_employee_work_time(emp_id)
        offline_entries.append((name, status_info['status'], work_time))

    if not offline_entries:
        return

    lines = []
    for name, status, work_time in offline_entries:
        if status == 'away':
            lines.append(f"{name} 暂时离开，稍后回来会立即回复您，您可以先留言说明需求。")
        else:
            time_hint = f"（工作时间 {work_time['work_start']}-{work_time['work_end']}）" if work_time else ""
            lines.append(f"{name}{time_hint} 现在暂时不在线，会在工作时间尽快回复您，您可以先留言说明需求。")

    try:
        await message.reply_text("\n".join(lines))
    except Exception as e:
        logger.warning(f"发送员工离线提醒失败: {e}")


# ========== 全员离线时的通用提示 ==========
ALL_OFFLINE_REPLY_COOLDOWN = 600  # 同一群组 10 分钟内不重复提醒
all_offline_reply_cache = {}  # {chat_id: last_reply_ts}

ALL_OFFLINE_AFTER_HOURS_TEXT = (
    "您好，当前为非工作时间，客服人员暂时不在线。"
    "请您留言说明具体需求，我们会在工作时间尽快回复您，感谢您的理解。"
)
ALL_AWAY_TEXT = (
    "您好，客服人员当前暂时离开，稍后回来会尽快回复您，请先留言说明需求，谢谢。"
)


def _has_any_mention(message) -> bool:
    """消息中是否 @ 了任何用户（含机器人/外部人员）"""
    for entities in (message.entities, message.caption_entities):
        if entities and any(e.type in ('mention', 'text_mention') for e in entities):
            return True
    return False


async def reply_when_all_staff_offline(message):
    """客户未 @ 任何员工，但所有员工当前都不在线时，提示非工作时间/暂时离开"""
    if _has_any_mention(message):
        return  # @ 了任何人都不触发（@员工走针对性提醒，@机器人/外人不打扰）

    now_ts = int(time.time())
    if now_ts - all_offline_reply_cache.get(message.chat_id, 0) < ALL_OFFLINE_REPLY_COOLDOWN:
        return  # 冷却期内不重复提醒

    # 排除超级管理员（超管不参与考勤）
    operators = {uid: info for uid, info in list_operators().items() if uid != OWNER_ID}

    any_online = False
    any_away_in_shift = False
    candidate_count = 0

    for emp_id in operators:
        status_info = get_effective_online_status(emp_id)
        # 只纳入"设置了排班"或"今日手动打卡过"的员工，避免未排班者被误判为全天在岗
        has_schedule = get_employee_work_time(emp_id) is not None
        has_manual = status_info['source'] == 'manual'
        if not has_schedule and not has_manual:
            continue
        candidate_count += 1

        if status_info['online']:
            any_online = True
            break
        if status_info['status'] == 'away' and is_scheduled_work_time(emp_id):
            any_away_in_shift = True

    # 没有可判定的员工，或仍有员工在线 -> 不提示
    if candidate_count == 0 or any_online:
        return

    all_offline_reply_cache[message.chat_id] = now_ts

    text = ALL_AWAY_TEXT if any_away_in_shift else ALL_OFFLINE_AFTER_HOURS_TEXT
    logger.info(f"[全员离线提醒] 群{message.chat_id} 触发文案类型={'暂时离开' if any_away_in_shift else '非工作时间'}")

    try:
        await message.reply_text(text)
    except Exception as e:
        logger.warning(f"发送全员离线提醒失败: {e}")


def is_closing_message(text: str) -> bool:
    """判断是否为结束语消息"""
    if not text:
        return False
    text_stripped = text.strip().lower()
    if text_stripped in CLOSING_WORDS:
        return True
    # 检查纯表情消息
    if text_stripped in CLOSING_EMOJIS:
        return True
    return False


def is_bot_trigger_message(text: str) -> bool:
    """判断是否为触发机器人回复的消息"""
    if not text:
        return False
    text_stripped = text.strip()
    # 匹配机器人指令模式
    for regex in BOT_TRIGGER_REGEXES:
        if regex.search(text_stripped):
            return True
    # 匹配计算器表达式（必须包含运算符，排除纯数字）
    if CALC_PATTERN.match(text_stripped):
        has_operator = any(op in text_stripped for op in ['+', '-', '*', '/', '%', '^', '('])
        has_digit = any(c.isdigit() for c in text_stripped)
        if has_operator and has_digit:
            return True
    return False


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

    # 防御：服务消息等可能没有 from_user
    if not message.from_user:
        return

    chat_id = message.chat_id
    user_id = message.from_user.id
    message_time = int(message.date.timestamp())

    operators = list_operators()

    if user_id in operators:
        # 操作员分支：任何消息类型（文本/表情/Sticker/图片/文件）都算响应
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

                is_customer_in_work = is_effectively_online(user_id, customer_msg_time)
                is_responder_in_work = is_effectively_online(user_id, message_time)

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
        # 客户分支
        # 命令消息已被外层 filters.COMMAND 过滤，此处无需再检查

        # 客户 @ 了不在工作时间内的员工时，自动回复离线提醒
        await reply_offline_mentioned_employees(message)

        # 过滤结束语：客户发送结束语不计入响应统计
        if is_closing_message(message.text):
            return

        # 过滤机器人触发指令：触发机器人回复的消息不计入响应统计
        if is_bot_trigger_message(message.text):
            return

        # 客户未 @ 任何人，但所有员工都不在线时，提示非工作时间/暂时离开
        await reply_when_all_staff_offline(message)

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
        keyboard.append([InlineKeyboardButton("⏰ 员工排班管理", callback_data='response_work_time_menu')])
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
    """设置员工排班菜单（工作时间/休息日/临时调整）"""
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
            callback_data=f'response_emp_schedule_{emp_id}'
        )])

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data='response_speed_menu')])

    await query.edit_message_text(
        "⏰ **员工排班管理**\n\n"
        "点击员工管理其排班（工作时间/休息日/临时调整）：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RESPONSE_WORK_TIME_MENU


def _build_emp_schedule_text(emp_id: int) -> str:
    """构建员工排班详情文本"""
    operators = list_operators()
    op_info = operators.get(emp_id)
    name = op_info.get('first_name', f"员工{emp_id}") if op_info else f"员工{emp_id}"

    work_time = get_employee_work_time(emp_id)
    time_text = f"{work_time['work_start']}-{work_time['work_end']}" if work_time else "未设置"

    weekly_rest = get_employee_weekly_rest(emp_id)
    rest_text = "、".join(WEEKDAY_NAMES[d] for d in weekly_rest) if weekly_rest else "无"

    temp_list = get_employee_temp_schedules(emp_id, limit=10)
    if temp_list:
        temp_text = "\n".join(
            f"  {t['date']} {'休息' if t['type'] == 'rest' else '补班'}" for t in temp_list
        )
    else:
        temp_text = "  无"

    text = f"📋 **{safe_escape_markdown(name)} 的排班**\n\n"
    text += f"⏰ 工作时间：{time_text}\n"
    text += f"📅 每周休息日：{rest_text}\n"
    text += f"🗓 临时调整（近期）：\n{temp_text}\n"
    return text


async def response_emp_schedule(update: Update, context: CallbackContext):
    """员工排班详情菜单"""
    query = update.callback_query
    await query.answer()

    emp_id = int(query.data.split('_')[-1])
    context.user_data['response_schedule_emp_id'] = emp_id

    text = _build_emp_schedule_text(emp_id)

    keyboard = [
        [InlineKeyboardButton("⏰ 设置工作时间", callback_data=f'response_set_work_time_{emp_id}')],
        [InlineKeyboardButton("📅 设置每周休息日", callback_data=f'response_weekly_rest_{emp_id}')],
        [InlineKeyboardButton("🗓 临时休息/补班", callback_data=f'response_temp_schedule_{emp_id}')],
        [InlineKeyboardButton("⬅️ 返回", callback_data='response_work_time_menu')],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return RESPONSE_EMP_SCHEDULE


async def _render_weekly_rest(query, emp_id: int):
    """渲染每周休息日设置界面（不调用 query.answer）"""
    weekly_rest = get_employee_weekly_rest(emp_id)

    keyboard = []
    row = []
    for d in range(7):
        mark = "✅" if d in weekly_rest else "⬜"
        row.append(InlineKeyboardButton(
            f"{mark}{WEEKDAY_NAMES[d]}",
            callback_data=f'response_toggle_rest_{emp_id}_{d}'
        ))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🗑 清除全部休息日", callback_data=f'response_clear_rest_{emp_id}')])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f'response_emp_schedule_{emp_id}')])

    try:
        await query.edit_message_text(
            "📅 **设置每周休息日**\n\n"
            "点击切换休息/上班（✅=休息）：",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass  # 界面内容未变化（如清空已是空的休息日）


async def response_weekly_rest(update: Update, context: CallbackContext):
    """设置每周休息日菜单（点击切换）"""
    query = update.callback_query
    await query.answer()

    emp_id = int(query.data.split('_')[-1])
    context.user_data['response_schedule_emp_id'] = emp_id

    await _render_weekly_rest(query, emp_id)
    return RESPONSE_WEEKLY_REST


async def response_toggle_rest(update: Update, context: CallbackContext):
    """切换某天是否为休息日"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    emp_id = int(parts[-2])
    day = int(parts[-1])

    weekly_rest = get_employee_weekly_rest(emp_id)
    if day in weekly_rest:
        weekly_rest.remove(day)
    else:
        weekly_rest.append(day)
    set_employee_weekly_rest(emp_id, sorted(weekly_rest))

    await _render_weekly_rest(query, emp_id)
    return RESPONSE_WEEKLY_REST


async def response_clear_rest(update: Update, context: CallbackContext):
    """清除全部每周休息日"""
    query = update.callback_query
    await query.answer()

    emp_id = int(query.data.split('_')[-1])
    set_employee_weekly_rest(emp_id, [])

    await _render_weekly_rest(query, emp_id)
    return RESPONSE_WEEKLY_REST


async def _render_temp_schedule(query, emp_id: int):
    """渲染临时休息/补班管理界面（不调用 query.answer）"""
    temp_list = get_employee_temp_schedules(emp_id, limit=30)

    text = "🗓 **临时休息/补班管理**\n\n"
    if temp_list:
        for t in temp_list:
            type_text = "休息" if t['type'] == 'rest' else "补班"
            text += f"  {t['date']} {type_text}\n"
    else:
        text += "暂无临时调整\n"
    text += "\n点击下方按钮添加，或点击已有记录删除："

    keyboard = []
    for t in temp_list:
        type_text = "休息" if t['type'] == 'rest' else "补班"
        keyboard.append([InlineKeyboardButton(
            f"❌ {t['date']} {type_text}",
            callback_data=f'response_del_temp_{emp_id}_{t["date"]}'
        )])

    keyboard.append([
        InlineKeyboardButton("➕ 添加休息", callback_data=f'response_add_temp_rest_{emp_id}'),
        InlineKeyboardButton("➕ 添加补班", callback_data=f'response_add_temp_makeup_{emp_id}'),
    ])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=f'response_emp_schedule_{emp_id}')])

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass


async def response_temp_schedule(update: Update, context: CallbackContext):
    """临时休息/补班管理"""
    query = update.callback_query
    await query.answer()

    emp_id = int(query.data.split('_')[-1])
    context.user_data['response_schedule_emp_id'] = emp_id

    await _render_temp_schedule(query, emp_id)
    return RESPONSE_TEMP_SCHEDULE


async def response_add_temp_start(update: Update, context: CallbackContext):
    """开始添加临时休息/补班"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')
    # response_add_temp_rest_{emp_id} 或 response_add_temp_makeup_{emp_id}
    schedule_type = parts[-2]
    emp_id = int(parts[-1])

    context.user_data['response_schedule_emp_id'] = emp_id
    context.user_data['response_temp_type'] = schedule_type
    context.user_data['profile_input_state'] = True

    type_text = "休息" if schedule_type == 'rest' else "补班"
    await query.edit_message_text(
        f"🗓 **添加临时{type_text}**\n\n"
        f"请输入日期（格式：YYYY-MM-DD 或 MM-DD）\n"
        f"例如：2026-10-01 或 10-01\n\n"
        f"❌ 发送 /cancel 取消",
        parse_mode='Markdown'
    )
    return RESPONSE_TEMP_SCHEDULE_ADD


async def response_save_temp_schedule(update: Update, context: CallbackContext):
    """保存临时休息/补班"""
    text = update.message.text.strip()
    emp_id = context.user_data.get('response_schedule_emp_id')
    schedule_type = context.user_data.get('response_temp_type', 'rest')

    if text == '/cancel':
        context.user_data.pop('profile_input_state', None)
        await update.message.reply_text("✅ 已取消")
        return ConversationHandler.END

    now = datetime.now(timezone(timedelta(hours=8)))
    date_str = text
    try:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            datetime.strptime(text, '%Y-%m-%d')
        elif re.match(r'^\d{1,2}-\d{1,2}$', text):
            m, d = text.split('-')
            date_str = f"{now.year}-{int(m):02d}-{int(d):02d}"
            datetime.strptime(date_str, '%Y-%m-%d')
        else:
            raise ValueError("格式错误")
    except ValueError:
        await update.message.reply_text(
            "❌ 日期格式不正确，请重新输入（格式：YYYY-MM-DD 或 MM-DD）\n"
            "例如：2026-10-01 或 10-01"
        )
        return RESPONSE_TEMP_SCHEDULE_ADD

    if set_employee_temp_schedule(emp_id, date_str, schedule_type):
        type_text = "休息" if schedule_type == 'rest' else "补班"
        await update.message.reply_text(f"✅ 已设置 {date_str} 为{type_text}")
    else:
        await update.message.reply_text("❌ 设置失败")

    context.user_data['response_message_processed'] = True
    context.user_data.pop('profile_input_state', None)
    return ConversationHandler.END


async def response_del_temp_schedule(update: Update, context: CallbackContext):
    """删除临时休息/补班"""
    query = update.callback_query
    await query.answer()

    # response_del_temp_{emp_id}_{date}
    data = query.data[len('response_del_temp_'):]
    emp_id_str, date_str = data.split('_', 1)
    emp_id = int(emp_id_str)

    delete_employee_temp_schedule(emp_id, date_str)

    await _render_temp_schedule(query, emp_id)
    return RESPONSE_TEMP_SCHEDULE


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
                CallbackQueryHandler(response_emp_schedule, pattern='^response_emp_schedule_'),
            ],
            RESPONSE_EMP_SCHEDULE: [
                CallbackQueryHandler(response_set_work_time, pattern='^response_set_work_time_'),
                CallbackQueryHandler(response_weekly_rest, pattern='^response_weekly_rest_'),
                CallbackQueryHandler(response_temp_schedule, pattern='^response_temp_schedule_'),
                CallbackQueryHandler(response_work_time_menu, pattern='^response_work_time_menu$'),
            ],
            RESPONSE_WEEKLY_REST: [
                CallbackQueryHandler(response_toggle_rest, pattern='^response_toggle_rest_'),
                CallbackQueryHandler(response_clear_rest, pattern='^response_clear_rest_'),
                CallbackQueryHandler(response_emp_schedule, pattern='^response_emp_schedule_'),
            ],
            RESPONSE_TEMP_SCHEDULE: [
                CallbackQueryHandler(response_add_temp_start, pattern='^response_add_temp_'),
                CallbackQueryHandler(response_del_temp_schedule, pattern='^response_del_temp_'),
                CallbackQueryHandler(response_emp_schedule, pattern='^response_emp_schedule_'),
            ],
            RESPONSE_TEMP_SCHEDULE_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, response_save_temp_schedule),
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
        allow_reentry=True,
        block=False
    )

    application.add_handler(main_conv, group=-1)

    init_response_tables()
