import logging
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, ConversationHandler, 
    ContextTypes, filters, CommandHandler
)
from auth import is_authorized
from db import get_all_groups_from_db, delete_group_from_db

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 状态定义 ---
(
    BC_SELECT_GROUPS,
    BC_INPUT_MESSAGE,
    BC_CONFIRM_SEND
) = range(3)

# --- 核心逻辑：同步与清理 ---
async def sync_and_clean_groups(context: ContextTypes.DEFAULT_TYPE):
    """
    异步版本：验证群组有效性并清理无效群组
    """
    # 注意：这里需要异步获取数据库会话吗？如果你的 db.py 是同步的 sqlite3，
    # 在 async 函数中直接调用同步 IO 操作（sqlite3）会阻塞事件循环。
    # 但对于轻量级操作通常可以接受。如果追求完美，需要使用 aiosqlite 或 run_in_executor。
    # 这里为了简化，保持同步 DB 调用，但将 bot API 调用改为 await。

    from db import get_all_groups_from_db, delete_group_from_db # 确保在函数内或顶部导入

    db_groups = get_all_groups_from_db()
    valid_groups = []

    logger.info(f"开始同步群组，数据库记录数：{len(db_groups)}")

    for g in db_groups:
        gid = g['id']
        try:
            # 【修改点 2】必须加上 await
            chat = await context.bot.get_chat(gid)

            # 更新群名（防止群名变更）
            if chat.title != g['title']:
                g['title'] = chat.title
                # 如果需要持久化更新名字，这里可以调用 db 更新函数

            valid_groups.append(g)
        except Exception as e:
            # 获取失败，说明机器人不在群里了
            logger.warning(f"检测到已退出群组，正在删除：{gid} ({g['title']}) - Error: {e}")
            delete_group_from_db(gid)

    logger.info(f"同步完成。有效群组：{len(valid_groups)}")
    return valid_groups

# --- 状态 1: 选择群组 ---

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """入口：权限校验 -> 同步群组 -> 显示列表"""
    query = update.callback_query
    user_id = query.from_user.id

    if not is_authorized(user_id):
        await query.answer("❌ 无权限", show_alert=True)
        await query.message.reply_text("❌ 此功能仅限管理员或授权操作员使用。")
        return ConversationHandler.END

    await query.answer("正在检测群组状态...")

    # 【修改点 4】调用时必须 await
    groups = await sync_and_clean_groups(context)

    if not groups:
        # ... (保持不变) ...
        await query.message.reply_text("⚠️ **未找到任何有效群组**...") # 简化显示
        return ConversationHandler.END

    context.user_data["bc_all_groups"] = groups
    context.user_data["bc_selected_ids"] = []

    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def show_group_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """渲染简化的群组选择界面"""
    groups = context.user_data.get("bc_all_groups", [])
    selected_ids = context.user_data.get("bc_selected_ids", [])

    total_count = len(groups)
    selected_count = len(selected_ids)

    text = f"📢 **群发任务设置**\n\n"
    text += f"📊 在线群组：**{total_count}** 个\n"
    text += f"✅ 已勾选：**{selected_count}** 个\n\n"
    text += "👇 **点击群名勾选/取消** (支持多选)："

    keyboard = []

    # 限制显示数量以防消息过长，如果超过 50 个建议强制分页，这里暂按全量显示（Telegram 限制约 100 个按钮）
    # 如果群太多，可以加一个简单的分页逻辑，这里为了简化先展示前 40 个，并提示
    display_limit = 40
    display_groups = groups[:display_limit]

    if len(groups) > display_limit:
        text += f"\n_(仅显示前 {display_limit} 个，建议使用'全选'功能)_ "

    for g in display_groups:
        gid = g["id"]
        title = g["title"]
        is_selected = gid in selected_ids
        icon = "✅" if is_selected else "⬜"
        # 截断长标题
        safe_title = (title[:25] + "...") if len(title) > 25 else title
        keyboard.append([
            InlineKeyboardButton(f"{icon} {safe_title}", callback_data=f"bc_toggle_{gid}")
        ])

    # --- 核心需求：底部按钮 ---
    # 1. 全选/清空辅助
    nav_row = [
        InlineKeyboardButton("✅ 全选", callback_data="bc_select_all"),
        InlineKeyboardButton("🚫 清空", callback_data="bc_deselect_all")
    ]

    # 2. 发送模式按钮
    send_row = [
        InlineKeyboardButton("🚀 全部发送", callback_data="bc_send_all"),
        InlineKeyboardButton("📤 发送选中", callback_data="bc_send_selected")
    ]

    keyboard.append(nav_row)
    keyboard.append(send_row)
    keyboard.append([InlineKeyboardButton("❌ 取消", callback_data="bc_cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"编辑消息失败：{e}")

async def bc_toggle_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """切换单个群组"""
    query = update.callback_query
    await query.answer()
    gid = query.data.replace("bc_toggle_", "")
    selected = context.user_data.get("bc_selected_ids", [])

    if gid in selected:
        selected.remove(gid)
    else:
        selected.append(gid)

    context.user_data["bc_selected_ids"] = selected
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_select_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全选"""
    query = update.callback_query
    await query.answer("已全选")
    groups = context.user_data.get("bc_all_groups", [])
    context.user_data["bc_selected_ids"] = [g["id"] for g in groups]
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_deselect_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空"""
    query = update.callback_query
    await query.answer("已清空")
    context.user_data["bc_selected_ids"] = []
    await show_group_selection(update, context)
    return BC_SELECT_GROUPS

async def bc_prepare_send(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    """
    准备发送
    mode: 'all' -> 忽略勾选，发所有
    mode: 'selected' -> 只发勾选的
    """
    query = update.callback_query
    await query.answer()

    all_groups = context.user_data.get("bc_all_groups", [])
    current_selected = context.user_data.get("bc_selected_ids", [])

    target_ids = []
    mode_text = ""

    if mode == "all":
        target_ids = [g["id"] for g in all_groups]
        mode_text = "✅ 模式：**全部群组** (无视勾选)"
    else:
        if not current_selected:
            await query.message.reply_text("⚠️ 您未勾选任何群组！\n请先勾选或直接点击'全部发送'。")
            return BC_SELECT_GROUPS
        target_ids = current_selected
        mode_text = "✅ 模式：**仅选中群组**"

    # 临时存储目标 ID
    context.user_data["bc_temp_target_ids"] = target_ids

    await query.message.reply_text(
        f"📝 **确认发送配置**\n\n"
        f"{mode_text}\n"
        f"🎯 目标数量：**{len(target_ids)}** 个\n\n"
        f"👉 **请输入要发送的消息内容：**\n"
        f"(支持 Markdown，输入 /cancel 取消)",
        parse_mode="Markdown"
    )
    return BC_INPUT_MESSAGE

async def bc_send_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await bc_prepare_send(update, context, "all")

async def bc_send_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await bc_prepare_send(update, context, "selected")

# --- 状态 2: 输入消息 ---

async def receive_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "/cancel":
        await update.message.reply_text("❌ 已取消。")
        return end_conversation(update, context)

    context.user_data["bc_message_content"] = text
    count = len(context.user_data.get("bc_temp_target_ids", []))

    keyboard = [
        [InlineKeyboardButton("🚀 确认发送", callback_data="bc_exec_confirm")],
        [InlineKeyboardButton("✏️ 重新输入", callback_data="bc_reinput")]
    ]

    preview = text[:60] + "..." if len(text) > 60 else text

    await update.message.reply_text(
        f"📋 **发送预览**\n\n"
        f"{preview}\n\n"
        f"目标数：{count}\n"
        f"⏱️ 策略：随机间隔 1-3 秒",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BC_CONFIRM_SEND

async def bc_reinput(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("👉 **请重新输入消息内容：**")
    return BC_INPUT_MESSAGE

# --- 状态 3: 执行发送 (带进度和延迟) ---

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("任务启动...")

    target_ids = context.user_data.get("bc_temp_target_ids", [])
    message_text = context.user_data.get("bc_message_content", "")

    if not target_ids or not message_text:
        await query.message.reply_text("❌ 数据异常，请重新开始。")
        return end_conversation(update, context)

    # 发送进度条
    progress_msg = await query.message.reply_text(
        f"🚀 **群发进行中...**\n"
        f"进度：0 / {len(target_ids)}\n"
        f"✅ 成功：0 | ❌ 失败：0"
    )

    success = 0
    failed = 0
    total = len(target_ids)

    for i, gid in enumerate(target_ids):
        # 【核心需求】随机间隔 1-3 秒
        delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)

        try:
            await context.bot.send_message(
                chat_id=gid, 
                text=message_text, 
                parse_mode="Markdown"
            )
            success += 1
        except Exception as e:
            logger.error(f"发送失败 {gid}: {e}")
            failed += 1

        # 每 3 条或最后一条更新进度，避免频繁编辑导致限流
        if (i + 1) % 3 == 0 or i == total - 1:
            try:
                await progress_msg.edit_text(
                    f"🚀 **群发进行中...**\n"
                    f"进度：{i+1} / {total}\n"
                    f"✅ 成功：{success} | ❌ 失败：{failed}"
                )
            except:
                pass

    result_text = (
        f"🎉 **任务完成!**\n\n"
        f"总计：{total}\n"
        f"✅ 成功：{success}\n"
        f"❌ 失败：{failed}\n\n"
        f"失败原因通常是机器人已被移出该群。"
    )

    try:
        await progress_msg.edit_text(result_text)
    except:
        await query.message.reply_text(result_text)

    return end_conversation(update, context)

# --- 辅助函数 ---

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("已取消")
    await query.message.reply_text("❌ 操作已取消。")
    return end_conversation(update, context)

def end_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys = ["bc_all_groups", "bc_selected_ids", "bc_message_content", "bc_temp_target_ids"]
    for k in keys:
        context.user_data.pop(k, None)
    return ConversationHandler.END

# --- 注册处理器 ---

def get_handlers():
    return [
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(start_broadcast, pattern="^(func_broadcast|broadcast|bc_start_real)$")
            ],
            states={
                BC_SELECT_GROUPS: [
                    CallbackQueryHandler(bc_toggle_group, pattern="^bc_toggle_"),
                    CallbackQueryHandler(bc_select_all, pattern="^bc_select_all$"),
                    CallbackQueryHandler(bc_deselect_all, pattern="^bc_deselect_all$"),
                    CallbackQueryHandler(bc_send_all, pattern="^bc_send_all$"),
                    CallbackQueryHandler(bc_send_selected, pattern="^bc_send_selected$"),
                    CallbackQueryHandler(cancel_action, pattern="^bc_cancel$"),
                ],
                BC_INPUT_MESSAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message_input),
                    CommandHandler("cancel", cancel_action),
                ],
                BC_CONFIRM_SEND: [
                    CallbackQueryHandler(execute_broadcast, pattern="^bc_exec_confirm$"),
                    CallbackQueryHandler(bc_reinput, pattern="^bc_reinput$"),
                    CallbackQueryHandler(cancel_action, pattern="^bc_cancel$"),
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel_action)],
            per_message=False,
        )
    ]