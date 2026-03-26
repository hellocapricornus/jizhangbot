# main.py - 修复重复导入和添加缺失的导入

import asyncio
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
# 合并重复的导入
from handlers.group_manager import (
    group_manager_menu, show_stats, list_categories, 
    add_category_start, delete_category_start, 
    delete_category_confirm, set_group_category_start,
    select_group_for_category, set_group_category,
    handle_text_input
)
from handlers.menu import get_main_menu

# 按钮路由处理器
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    print(f"[DEBUG] button_router 收到: {query.data}")

    # ========== 先处理广播按钮 ==========
    if query.data == "broadcast":
        print(f"[DEBUG] 触发广播功能")
        from handlers.broadcast import start_broadcast
        await start_broadcast(update, context)
        return

    # ========== 处理群组管理菜单 ==========
    if query.data == "group_manager":
        await group_manager_menu(update, context)
        return

    # ========== 处理群组管理的子菜单 ==========
    if query.data == "gm_stats":
        await show_stats(update, context)
        return

    if query.data == "gm_list_cats":
        await list_categories(update, context)
        return

    if query.data == "gm_add_cat":
        await add_category_start(update, context)
        return

    if query.data == "gm_del_cat":
        await delete_category_start(update, context)
        return

    if query.data.startswith("del_cat_"):
        await delete_category_confirm(update, context)
        return

    if query.data == "gm_set_cat":
        await set_group_category_start(update, context)
        return

    if query.data.startswith("sel_group_"):
        await select_group_for_category(update, context)
        return

    if query.data.startswith("set_cat_"):
        await set_group_category(update, context)
        return

    if query.data == "refresh_group_list":
        from handlers.group_manager import show_group_list_page
        await show_group_list_page(update, context)
        return

    if query.data == "group_page_prev" or query.data == "group_page_next":
        from handlers.group_manager import handle_group_pagination
        await handle_group_pagination(update, context)
        return

    if query.data == "filter_uncategorized" or query.data == "filter_categorized":
        from handlers.group_manager import handle_group_pagination
        await handle_group_pagination(update, context)
        return

    # ========== 处理返回主菜单 ==========
    if query.data == "main_menu":
        await query.message.edit_text(
            "请选择功能：",
            reply_markup=get_main_menu()
        )
        return

    # 在 button_router 函数中，添加记账模块的按钮处理
    # ========== 处理记账模块按钮 ==========
    if query.data == "acct_current":
        from handlers.accounting import handle_current_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "当前账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_current_bill(update, context)
        return

    if query.data == "acct_today":
        from handlers.accounting import handle_today_stats
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "今日总"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_today_stats(update, context)
        return

    if query.data == "acct_total":
        from handlers.accounting import handle_total_stats
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "总"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_total_stats(update, context)
        return

    if query.data == "acct_query":
        from handlers.accounting import handle_query_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "查询账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_query_bill(update, context)
        return

    if query.data == "acct_clear":
        from handlers.accounting import handle_clear_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "清理账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_clear_bill(update, context)
        return

    if query.data == "acct_clear_all":
        from handlers.accounting import handle_clear_all_bill
        class FakeMessage:
            def __init__(self, chat_id, user_id):
                self.chat = type('obj', (object,), {'id': chat_id, 'type': 'group'})()
                self.from_user = type('obj', (object,), {'id': user_id})()
                self.text = "清理总账单"
        fake_msg = FakeMessage(query.message.chat.id, query.from_user.id)
        update.message = fake_msg
        await handle_clear_all_bill(update, context)
        return

    if query.data == "acct_help":
        from handlers.accounting import handle
        await handle(update, context)
        return

    # ========== 处理记账模块的日期选择和确认按钮 ==========
    if query.data.startswith("acct_date_"):
        from handlers.accounting import handle_date_selection
        await handle_date_selection(update, context)
        return

    if query.data == "acct_cancel":
        await query.message.edit_text("✅ 已取消查询")
        return

    # ========== 处理清理账单确认按钮 ==========
    if query.data == "clear_current_confirm":
        from handlers.accounting import handle_clear_current_confirm
        await handle_clear_current_confirm(update, context)
        return

    if query.data == "clear_current_cancel":
        from handlers.accounting import handle_clear_current_cancel
        await handle_clear_current_cancel(update, context)
        return

    if query.data == "clear_all_confirm":
        from handlers.accounting import handle_clear_all_confirm
        await handle_clear_all_confirm(update, context)
        return

    if query.data == "clear_all_cancel":
        from handlers.accounting import handle_clear_all_cancel
        await handle_clear_all_cancel(update, context)
        return

    # ========== 权限检查 ==========
    if not is_authorized(user_id):
        await query.message.reply_text("❌ 管理人/操作员才能使用，如需使用请联系 @ChinaEdward")
        return

    data = query.data

    if data in ["func_broadcast", "broadcast", "bc_start_real"]:
        return None

    if data == "operator":
        context.user_data["active_module"] = "operator"
        await operator.handle(update, context)
        return

    if data.startswith("op_"):
        context.user_data["active_module"] = "operator"
        await operator.handle_buttons(update, context)
        return

    if data == "usdt":
        context.user_data["active_module"] = "usdt"
        await usdt.handle(update, context)
        return

    if data == "transfer":
        await transfer.show_transfer_menu(update, context)
        return

    if data == "accounting":
        context.user_data["active_module"] = "accounting"
        await accounting.handle(update, context)
        return

    print(f"Unhandled callback data: {data}")

# 输入路由处理器（仅处理私聊）
async def input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊的文本输入（用于USDT、操作员管理等模块）"""
    chat = update.effective_chat
    print(f"[DEBUG] input_router 收到消息，聊天类型: {chat.type}")

    # 只在私聊中处理输入路由
    if chat.type != 'private':
        return

    # 先检查是否有群组管理的状态
    user_id = update.effective_user.id
    from handlers.group_manager import user_states
    if user_id in user_states:
        print(f"[DEBUG] 检测到群组管理状态，交给 handle_text_input")
        from handlers.group_manager import handle_text_input
        await handle_text_input(update, context)
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
async def auto_save_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type in ['group', 'supergroup']:
        chat_id = str(update.effective_chat.id)
        title = update.effective_chat.title

        # 检查机器人是否还在群组中
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ['member', 'administrator']:
                print(f"[DEBUG] 机器人不在群组 {title} ({chat_id}) 中，跳过保存")
                return
        except Exception as e:
            print(f"[DEBUG] 无法获取群组 {chat_id} 的成员状态: {e}")
            return

        print(f"[DEBUG] auto_save_group: 保存群组 {title} ({chat_id})")

        # 获取现有群组的分类（如果有）
        from db import get_all_groups_from_db
        existing_groups = get_all_groups_from_db()
        existing = next((g for g in existing_groups if g['id'] == chat_id), None)
        category = existing['category'] if existing else '未分类'

        # 保存时保留原有分类
        save_group(chat_id, title, category)

# 监听机器人加入/离开群组的事件
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
        save_group(chat_id, title, '未分类')  # 新群组默认分类为"未分类"
        print(f"✅ [系统事件] 群组已自动存入数据库。")

    elif new_status in ['left', 'kicked', 'banned']:
        print(f"👋 [系统事件] 机器人离开/被踢出群组：{chat_id}")
        delete_group_from_db(chat_id)
        print(f"✅ [系统事件] 群组已从数据库删除。")

        # 等待一下，让 auto_save_group 不会重新保存
        await asyncio.sleep(1)

# main.py - 改进广播状态检测
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全局取消命令 - 智能判断当前状态"""
    user_id = update.effective_user.id
    print(f"[DEBUG] cancel_command 被调用, user_id: {user_id}")

    # 🔥 先检查是否在群组管理状态
    from handlers.group_manager import user_states, handle_cancel_in_group_manager
    print(f"[DEBUG] user_states: {user_states}")

    if user_id in user_states:
        print(f"[DEBUG] 检测到群组管理状态，调用 handle_cancel_in_group_manager")
        await handle_cancel_in_group_manager(update, context)
        return

    # 🔥 广播状态 - 不需要在这里处理，因为 ConversationHandler 的 fallback 会处理
    # 直接返回，让广播自己的 fallback 处理
    if context.user_data.get("in_broadcast", False):
        print(f"[DEBUG] 检测到广播状态，跳过处理（让广播的 ConversationHandler 处理）")
        return

    # 清理其他模块的状态
    context.user_data.clear()
    print(f"[DEBUG] 清理其他模块状态")

    await update.message.reply_text("❌ 已取消所有操作")

    # 返回主菜单
    from handlers.menu import get_main_menu
    await update.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu()
    )

def main():
    # 初始化数据库和操作员
    init_db()
    init_operators_from_db()

    # 导入记账模块并初始化
    from handlers.accounting import init_accounting, get_conversation_handler, handle_group_message
    init_accounting(DB_PATH)

    # 创建应用
    app = Application.builder().token(BOT_TOKEN).build()

    # 🔥 0. 全局取消命令（最高优先级，放在最前面）
    app.add_handler(CommandHandler("cancel", cancel_command))

    # 🔥 添加 skip 命令处理器
    from handlers.group_manager import skip_command
    app.add_handler(CommandHandler("skip", skip_command))

    # 1. 启动命令
    app.add_handler(CommandHandler("start", start))

    # 2. 添加 Git 更新命令（管理员专用）
    for handler in get_git_handlers():
        app.add_handler(handler)

    # 3. Transfer 对话处理器
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

    # 4. Broadcast 对话处理器
    for handler in broadcast.get_handlers():
        app.add_handler(handler)

    # 5. USDT 分页按钮
    app.add_handler(CallbackQueryHandler(usdt.handle_buttons, pattern="^usdt_"))

    # 6. 通用按钮路由（放在最后，处理其他所有未被处理的消息）
    app.add_handler(CallbackQueryHandler(button_router))

    # 7. 调试处理器（降低优先级，避免干扰命令）
    async def debug_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """调试用的消息处理器，显示所有收到的消息"""
        # 🔥 跳过所有命令消息，避免干扰
        if update.message and update.message.text:
            if update.message.text.startswith('/'):
                return
            chat = update.effective_chat
            print(f"[DEBUG] 收到消息 - 聊天类型: {chat.type}, 聊天ID: {chat.id}, 文本: {update.message.text[:50]}")
        return None

    # 调试处理器放在低优先级
    app.add_handler(MessageHandler(filters.ALL, debug_message_handler), group=10)

    # 8. 群组消息处理器（处理记账指令和计算器）
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ), group=1)

    # 9. 私聊文本输入路由（用于USDT、操作员管理等模块）
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        input_router
    ), group=1)

    # 10. 全局群组消息捕获（备份用，用于保存群组信息）
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND, 
        auto_save_group
    ), group=2)

    app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    # 11. 注册机器人成员状态监听器
    app.add_handler(ChatMemberHandler(on_bot_join_or_leave, ChatMemberHandler.MY_CHAT_MEMBER))

    # ... 其余代码不变 ...

    print("=" * 50)
    print("🤖 机器人启动成功...")
    print("=" * 50)
    print("已加载模块：")
    print("  ✅ Operator - 操作员管理")
    print("  ✅ USDT - USDT地址查询")
    print("  ✅ Accounting - 群组记账功能")
    print("  ✅ Broadcast - 群发消息")
    print("  ✅ Transfer - 转账查询和分析")
    print("  ✅ Group Manager - 群组分类管理")
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
    print("  • 群组管理：可创建分类，按分类筛选群组进行群发")
    print("=" * 50)

    # 启动定时清理任务
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
