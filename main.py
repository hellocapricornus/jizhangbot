# main.py - 添加调试信息的完整版本
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
    ChatMemberHandler
)
from config import BOT_TOKEN
from auth import is_authorized, init_operators_from_db
from db import init_db, save_group, delete_group_from_db, DB_PATH
from handlers.start import start
from handlers import operator, usdt, accounting, broadcast, transfer
from handlers.git_update import get_git_handlers

# 按钮路由处理器
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # 先处理记账模块的日期选择
    if query.data.startswith("acct_date_"):
        from handlers.accounting import handle_date_selection
        await handle_date_selection(update, context)
        return

    # 处理清空确认
    if query.data == "acct_clear_confirm" or query.data == "acct_clear_cancel":
        from handlers.accounting import handle_clear_confirm, handle_clear_cancel
        if query.data == "acct_clear_confirm":
            await handle_clear_confirm(update, context)
        else:
            await handle_clear_cancel(update, context)
        return

    # 处理清空所有账单确认（新增）
    if query.data == "clear_all_confirm" or query.data == "clear_all_cancel":
        from handlers.accounting import handle_clear_all_confirm, handle_clear_all_cancel
        if query.data == "clear_all_confirm":
            await handle_clear_all_confirm(update, context)
        else:
            await handle_clear_all_cancel(update, context)
        return

    if not is_authorized(user_id):
        await query.message.reply_text("❌ 需联系管理人才能使用")
        return ConversationHandler.END

    data = query.data

    if data == "func_broadcast" or data == "broadcast" or data == "bc_start_real":
        print("⏩ [Router] 跳过广播按钮，交给 Broadcast ConversationHandler 处理...")
        return None

    if data == "operator": 
        context.user_data["active_module"] = "operator"
        await operator.handle(update, context)
        return ConversationHandler.END

    if data.startswith("op_"):
        context.user_data["active_module"] = "operator"
        await operator.handle_buttons(update, context)
        return ConversationHandler.END

    if data == "usdt":
        context.user_data["active_module"] = "usdt"
        await usdt.handle(update, context)
        return ConversationHandler.END

    if data == "transfer":
        await transfer.show_transfer_menu(update, context)
        return ConversationHandler.END

    if data == "accounting":
        context.user_data["active_module"] = "accounting"
        await accounting.handle(update, context)
        return ConversationHandler.END

    print(f"Unhandled callback data: {data}")
    return ConversationHandler.END

# 输入路由处理器（仅处理私聊）
async def input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊的文本输入（用于USDT、操作员管理等模块）"""
    chat = update.effective_chat
    print(f"[DEBUG] input_router 收到消息，聊天类型: {chat.type}")

    # 只在私聊中处理输入路由
    if chat.type != 'private':
        return

    module = context.user_data.get("active_module")
    print(f"[DEBUG] 当前模块: {module}")

    if module == "operator":
        await operator.handle_input(update, context)
    elif module == "usdt":
        await usdt.handle_input(update, context)
    elif module == "accounting":
        # 记账模块在私聊中不需要输入处理
        pass

# 自动保存群组信息（作为备份）
# 修改 auto_save_group 函数
async def auto_save_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type in ['group', 'supergroup']:
        chat_id = str(update.effective_chat.id)
        title = update.effective_chat.title

        # 检查机器人是否还在群组中
        try:
            # 尝试获取机器人自己的成员信息
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ['member', 'administrator']:
                # 机器人不在群组中，不保存
                print(f"[DEBUG] 机器人不在群组 {title} ({chat_id}) 中，跳过保存")
                return
        except Exception as e:
            # 如果获取失败，说明可能已离开
            print(f"[DEBUG] 无法获取群组 {chat_id} 的成员状态: {e}")
            return

        print(f"[DEBUG] auto_save_group: 保存群组 {title} ({chat_id})")
        save_group(chat_id, title)

# 监听机器人加入/离开群组的事件
# 修改 on_bot_join_or_leave 函数
async def on_bot_join_or_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    专门处理机器人自己的成员状态变化。
    """
    my_chat_member = update.my_chat_member
    chat = my_chat_member.chat
    new_status = my_chat_member.new_chat_member.status

    chat_id = str(chat.id)
    title = chat.title

    if new_status in ['member', 'administrator']:
        print(f"🎉 [系统事件] 机器人加入群组：{title} ({chat_id})")
        save_group(chat_id, title)
        print(f"✅ [系统事件] 群组已自动存入数据库。")

    elif new_status in ['left', 'kicked', 'banned']:
        print(f"👋 [系统事件] 机器人离开/被踢出群组：{chat_id}")
        delete_group_from_db(chat_id)
        print(f"✅ [系统事件] 群组已从数据库删除。")

        # 等待一下，让 auto_save_group 不会重新保存
        await asyncio.sleep(1)

def main():
    # 初始化数据库和操作员
    init_db()
    init_operators_from_db()

    # 导入记账模块并初始化
    from handlers.accounting import init_accounting, get_conversation_handler, handle_group_message
    init_accounting(DB_PATH)

    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()

    # 1. 启动命令
    app.add_handler(CommandHandler("start", start))

    # 2. 添加 Git 更新命令（管理员专用）
    for handler in get_git_handlers():
        app.add_handler(handler)

    # 2. Transfer 对话处理器
    transfer_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(transfer.start_transfer_query, pattern="^trans_direct$"),
            CallbackQueryHandler(transfer.start_transfer_analysis, pattern="^trans_analysis$"),
            CallbackQueryHandler(transfer.handle_transfer_pagination, pattern="^trans_page_|^copy_addr_"),
        ],
        states={
            transfer.TRANSFER_QUERY_WAIT_ADDR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, transfer.process_transfer_query)
            ],
            transfer.TRANSFER_ANALYSIS_WAIT_ADDR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, transfer.process_transfer_analysis)
            ],
        },
        fallbacks=[CommandHandler("cancel", transfer.cancel_transfer)],
        per_message=False, 
    )
    app.add_handler(transfer_conv_handler)

    # 3. Broadcast 对话处理器
    for handler in broadcast.get_handlers():
        app.add_handler(handler)

    # 4. USDT 分页按钮
    app.add_handler(CallbackQueryHandler(usdt.handle_buttons, pattern="^usdt_"))

    # 5. 通用按钮路由
    app.add_handler(CallbackQueryHandler(button_router))

    # 6. 【重要】添加一个全局的消息处理器来调试
    async def debug_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """调试用的消息处理器，显示所有收到的消息"""
        if update.message and update.message.text:
            chat = update.effective_chat
            print(f"[DEBUG] 收到消息 - 聊天类型: {chat.type}, 聊天ID: {chat.id}, 文本: {update.message.text[:50]}")
        return None  # 返回None让其他handler继续处理

    # 添加调试处理器（最高优先级）
    app.add_handler(MessageHandler(filters.ALL, debug_message_handler), group=0)

    # 7. 【重要】群组消息处理器（处理记账指令和计算器）
    # 设置 group=1 优先级，确保在input_router之前执行
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ), group=1)

    # 8. 私聊文本输入路由（用于USDT、操作员管理等模块）
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        input_router
    ), group=1)

    # 9. 全局群组消息捕获（备份用，用于保存群组信息）
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND, 
        auto_save_group
    ), group=2)

    # 10. 注册机器人成员状态监听器
    app.add_handler(ChatMemberHandler(on_bot_join_or_leave, ChatMemberHandler.MY_CHAT_MEMBER))

    # 11. 添加记账对话处理器（处理日期选择和清空确认）
    #app.add_handler(get_conversation_handler())

    print("=" * 50)
    print("🤖 机器人启动成功...")
    print("=" * 50)
    print("已加载模块：")
    print("  ✅ Operator - 操作员管理")
    print("  ✅ USDT - USDT地址查询")
    print("  ✅ Accounting - 群组记账功能")
    print("  ✅ Broadcast - 群发消息")
    print("  ✅ Transfer - 转账查询和分析")
    print("=" * 50)
    print("📌 功能提示：")
    print("  • 机器人加入群组时会自动记录")
    print("  • 退出群组时会自动清理数据")
    print("  • 记账功能仅在群组中可用，支持以下指令：")
    print("    - +金额：添加入款")
    print("    - -金额：修正入款")
    print("    - 下发金额u：添加出款")
    print("    - 下发-金额u：修正出款")
    print("    - 设置手续费 数字：设置手续费率")
    print("    - 设置汇率 数字：设置汇率")
    print("    - 今日总：查看今日账单")
    print("    - 总：查看总计账单")
    print("    - 查询账单：按日期查询")
    print("    - 清理账单：清空所有记录")
    print("  • 计算器功能：群内发送如 100+200 即可计算")
    print("=" * 50)

    # 启动定时清理任务
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        import asyncio

        async def cleanup_wrapper():
            """包装清理函数为异步"""
            try:
                from handlers.accounting import accounting_manager
                accounting_manager.cleanup_expired_groups()
                print("✅ 定时清理任务执行完成")
            except Exception as e:
                print(f"❌ 清理任务执行失败: {e}")

        scheduler = AsyncIOScheduler()
        scheduler.add_job(cleanup_wrapper, 'interval', hours=24)
        scheduler.start()
        print("✅ 定时清理任务已启动（每天清理过期群组数据）")
    except ImportError:
        print("⚠️ 未安装 apscheduler，跳过定时清理任务")
    except Exception as e:
        print(f"⚠️ 启动定时清理任务失败: {e}")

    # 启动机器人
    app.run_polling()

if __name__ == "__main__":
    main()
