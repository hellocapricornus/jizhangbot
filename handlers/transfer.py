# handlers/transfer.py
import aiohttp
import asyncio
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from auth import is_authorized
from logger import bot_logger as logger
from handlers.menu import get_main_menu  # ✅ 添加缺失的导入

# --- 配置 ---
TRON_GRID_API = "https://api.trongrid.io"
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# --- 状态常量（改为整数）---
TRANSFER_QUERY_WAIT_ADDR = 1   # ✅ 改为整数
TRANSFER_ANALYSIS_WAIT_ADDR = 2

# --- 辅助函数 ---
async def get_trc20_transfers(address: str, limit: int = 200) -> list:
    """获取指定地址的 TRC20 转账记录"""
    url = f"{TRON_GRID_API}/v1/accounts/{address}/transactions/trc20"
    params = {
        "limit": limit,
        "contract_address": USDT_CONTRACT
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", [])
                logger.warning(f"TronGrid API 返回状态码: {resp.status}")
                return []
    except asyncio.TimeoutError:
        logger.error(f"请求超时: {address}")
        return []
    except Exception as e:
        logger.error(f"API 错误: {e}")
        return []


def get_trc20_transfers_sync(address: str, limit: int = 200) -> list:
    """同步版本，供非异步环境使用"""
    import requests
    url = f"{TRON_GRID_API}/v1/accounts/{address}/transactions/trc20"
    params = {
        "limit": limit,
        "contract_address": USDT_CONTRACT
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", [])
        return []
    except Exception as e:
        logger.error(f"API Error: {e}")
        return []


def extract_counterparties(transfers, my_address):
    """从交易列表中提取所有交易对手地址"""
    counterparties = set()
    for tx in transfers:
        from_addr = tx.get("from")
        to_addr = tx.get("to")
        if from_addr and from_addr != my_address:
            counterparties.add(from_addr)
        if to_addr and to_addr != my_address:
            counterparties.add(to_addr)
    return counterparties


# --- 功能 1: 转账查询 ---
async def start_transfer_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始转账查询"""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id, require_full_access=True):
        await query.message.reply_text("❌ 无权限使用此功能")
        return ConversationHandler.END

    # 清除旧数据
    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)
    context.user_data["active_module"] = "transfer"

    await query.message.reply_text(
        "🔍 **转账查询**\n\n请输入两个 USDT 地址，中间用空格隔开：\n"
        "例如：`Txxxx... Tyyyy...`\n\n"
        "💡 提示：输入 /cancel 可取消操作",
        parse_mode="Markdown"
    )
    return TRANSFER_QUERY_WAIT_ADDR


async def process_transfer_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理转账查询输入"""
    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text("❌ 格式错误，请输入两个地址，用空格隔开。")
        return TRANSFER_QUERY_WAIT_ADDR

    addr_a, addr_b = parts[0], parts[1]

    # 校验地址格式
    tron_pattern = re.compile(r'^T[0-9A-Za-z]{33}$')
    if not (tron_pattern.match(addr_a) and tron_pattern.match(addr_b)):
        await update.message.reply_text("❌ 地址格式不正确 (Tron 地址以 T 开头，长度 34)。")
        return TRANSFER_QUERY_WAIT_ADDR

    await update.message.reply_text("⏳ 正在查询链上数据，请稍候...")

    # 获取交易记录
    history_a = await get_trc20_transfers(addr_a, limit=200)
    history_b = await get_trc20_transfers(addr_b, limit=200)

    matches = []
    for tx in history_a:
        if tx.get("to") == addr_b or tx.get("from") == addr_b:
            matches.append(tx)

    # 去重
    seen_tx_ids = set()
    unique_matches = []
    for tx in matches:
        tx_id = tx.get("txID")
        if tx_id not in seen_tx_ids:
            seen_tx_ids.add(tx_id)
            unique_matches.append(tx)

    if not unique_matches:
        for tx in history_b:
            if tx.get("to") == addr_a or tx.get("from") == addr_a:
                tx_id = tx.get("txID")
                if tx_id not in seen_tx_ids:
                    unique_matches.append(tx)

    if not unique_matches:
        await update.message.reply_text("📭 未找到直接转账记录。")
        context.user_data.pop("active_module", None)
        return ConversationHandler.END

    # 保存结果并显示
    context.user_data["transfer_results"] = unique_matches
    context.user_data["current_page"] = 0
    context.user_data["query_type"] = "direct"
    context.user_data["active_module"] = "transfer"

    # ✅ 修复：直接调用发送函数，传入 update 和 context
    await send_transfer_page(update, context, 0)

    return ConversationHandler.END


# --- 功能 2: 转账分析 ---
async def start_transfer_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """开始转账分析"""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id, require_full_access=True):
        await query.message.reply_text("❌ 无权限使用此功能")
        return ConversationHandler.END

    # 清除旧数据
    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)
    context.user_data["active_module"] = "transfer"

    await query.message.reply_text(
        "🕵️ **转账分析**\n\n将分析是否有第三方地址与这两个地址都产生过交易。\n"
        "请输入两个 USDT 地址，中间用空格隔开：\n"
        "例如：`Txxxx... Tyyyy...`\n"
        "💡 提示：输入 /cancel 可取消操作",
        parse_mode="Markdown"
    )
    return TRANSFER_ANALYSIS_WAIT_ADDR


async def process_transfer_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理转账分析输入"""
    text = update.message.text.strip()
    parts = text.split()

    if len(parts) != 2:
        await update.message.reply_text("❌ 格式错误，请输入两个地址，用空格隔开。")
        return TRANSFER_ANALYSIS_WAIT_ADDR

    addr_a, addr_b = parts[0], parts[1]

    tron_pattern = re.compile(r'^T[0-9A-Za-z]{33}$')
    if not (tron_pattern.match(addr_a) and tron_pattern.match(addr_b)):
        await update.message.reply_text("❌ 地址格式不正确。")
        return TRANSFER_ANALYSIS_WAIT_ADDR

    await update.message.reply_text("⏳ 正在深度分析链上关系，这可能需要一点时间...")

    # 获取交易记录
    history_a = await get_trc20_transfers(addr_a, limit=200)
    history_b = await get_trc20_transfers(addr_b, limit=200)

    set_a = extract_counterparties(history_a, addr_a)
    set_b = extract_counterparties(history_b, addr_b)

    common_parties = list(set_a.intersection(set_b))
    common_parties = [p for p in common_parties if p != addr_a and p != addr_b]

    if not common_parties:
        await update.message.reply_text("📭 未发现共同交易对手。")
        context.user_data.pop("active_module", None)
        return ConversationHandler.END

    # 保存结果并显示
    context.user_data["transfer_results"] = common_parties
    context.user_data["current_page"] = 0
    context.user_data["query_type"] = "analysis"
    context.user_data["active_module"] = "transfer"

    await send_transfer_page(update, context, 0)

    return ConversationHandler.END


# --- 发送分页结果 ---
async def send_transfer_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page_num: int):
    """发送转账结果分页"""
    results = context.user_data.get("transfer_results", [])
    query_type = context.user_data.get("query_type")

    if not results:
        await update.message.reply_text("📭 没有数据")
        return

    page_size = 5
    total_pages = (len(results) + page_size - 1) // page_size
    start_idx = page_num * page_size
    end_idx = min(start_idx + page_size, len(results))
    current_items = results[start_idx:end_idx]

    text = ""
    keyboard = []

    if query_type == "direct":
        text = f"🔗 **直接转账记录** (第 {page_num+1}/{total_pages} 页)\n\n"

        for i, tx in enumerate(current_items, start=start_idx):
            raw_amount = tx.get("value") or tx.get("amount")
            try:
                if raw_amount is None:
                    amount_float = 0.0
                else:
                    amount_float = float(str(raw_amount)) / 1_000_000.0
            except (ValueError, TypeError) as e:
                logger.error(f"转换金额失败: {e}")
                amount_float = 0.0

            amount_str = f"{amount_float:.2f}" if amount_float >= 0.01 else f"{amount_float:.6f}"

            from_addr = tx.get("from", "Unknown")
            to_addr = tx.get("to", "Unknown")
            from_short = f"{from_addr[:6]}...{from_addr[-6:]}" if len(from_addr) >= 12 else from_addr
            to_short = f"{to_addr[:6]}...{to_addr[-6:]}" if len(to_addr) >= 12 else to_addr

            text += f"{i+1}. 💰 **{amount_str} USDT**\n"
            text += f"   🟢 {from_short} ➡️ 🔴 {to_short}\n"

            timestamp = tx.get("block_timestamp", 0)
            if timestamp:
                dt = datetime.fromtimestamp(timestamp / 1000)
                text += f"   ⏰ {dt.strftime('%Y-%m-%d %H:%M:%S')}\n"

            tx_id = tx.get("txID", "")
            if tx_id:
                text += f"   🔗 [查看详情](https://tronscan.org/#/transaction/{tx_id})\n"
            text += "\n"

    elif query_type == "analysis":
        text = f"🕸️ **共同交易对手地址** (第 {page_num+1}/{total_pages} 页)\n\n"
        text += "以下地址同时与您查询的两个地址有过交易：\n\n"
        for i, addr in enumerate(current_items, start=start_idx):
            short_addr = f"{addr[:8]}...{addr[-6:]}"
            text += f"{i+1}. `{addr}`\n   ({short_addr})\n\n"
            keyboard.append([InlineKeyboardButton(f"📋 复制地址 {i+1}", callback_data=f"copy_addr_{addr}")])

    # 分页按钮
    nav_buttons = []
    if page_num > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"trans_page_{page_num-1}"))
    if page_num < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"trans_page_{page_num+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("◀️ 返回主菜单", callback_data="transfer_back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    # ✅ 修复：正确处理两种调用方式
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=reply_markup,
            disable_web_page_preview=True
        )


# --- 处理分页点击 ---
async def handle_transfer_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理分页按钮"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("trans_page_"):
        page_num = int(data.split("_")[2])
        # ✅ 修复：传入 query 作为 update
        await send_transfer_page(update, context, page_num)
    elif data.startswith("copy_addr_"):
        addr = data.replace("copy_addr_", "")
        await query.message.reply_text(f"📋 已获取地址，长按复制：\n<code>{addr}</code>", parse_mode="HTML")
        context.user_data.pop("transfer_results", None)
        context.user_data.pop("current_page", None)
        context.user_data.pop("query_type", None)
        context.user_data.pop("active_module", None)


# --- 返回主菜单 ---
async def transfer_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """返回主菜单并清除互转查询状态"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # 清除所有互转查询相关的状态
    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)
    context.user_data.pop("active_module", None)

    await query.message.edit_text(
        "✅ 已退出互转查询\n\n请选择功能：",
        reply_markup=get_main_menu(user_id)
    )
    return ConversationHandler.END


# --- 取消操作 ---
async def cancel_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消互转查询"""
    user_id = update.effective_user.id
    context.user_data.pop("active_module", None)
    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)

    await update.message.reply_text("❌ 已取消互转查询")
    await update.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu(user_id)
    )
    return ConversationHandler.END


async def cancel_transfer_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从消息中取消互转查询"""
    user_id = update.effective_user.id
    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)
    context.user_data.pop("active_module", None)

    await update.message.reply_text("❌ 已取消互转查询")
    await update.message.reply_text(
        "请选择功能：",
        reply_markup=get_main_menu(user_id)
    )
    return ConversationHandler.END


# --- 主菜单入口 ---
async def show_transfer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示互转查询菜单"""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id, require_full_access=True):
        await query.answer("❌ 无权限", show_alert=True)
        return

    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)
    context.user_data["active_module"] = "transfer"

    keyboard = [
        [InlineKeyboardButton("🔍 转账查询 (直接记录)", callback_data="trans_direct")],
        [InlineKeyboardButton("🕸️ 转账分析 (共同对手)", callback_data="trans_analysis")],
        [InlineKeyboardButton("◀️ 返回主菜单", callback_data="transfer_back_to_main")]
    ]

    await query.message.reply_text(
        "💱 **互转查询功能**\n请选择操作：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# --- 键盘版入口 ---
async def show_transfer_menu_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """互转查询 - 键盘版"""
    from telegram import ReplyKeyboardMarkup, KeyboardButton

    user_id = update.effective_user.id

    if not is_authorized(user_id, require_full_access=True):
        await update.message.reply_text("❌ 管理人/操作员才能使用")
        return

    context.user_data.pop("transfer_results", None)
    context.user_data.pop("current_page", None)
    context.user_data.pop("query_type", None)
    context.user_data["active_module"] = "transfer"

    keyboard = [
        [KeyboardButton("🔍 转账查询"), KeyboardButton("🕸️ 转账分析")],
        [KeyboardButton("◀️ 返回主菜单")],
    ]

    await update.message.reply_text(
        "💱 **互转查询功能**\n请选择操作：",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )


# --- 导出 ---
__all__ = [
    'get_trc20_transfers',
    'get_trc20_transfers_sync',
    'extract_counterparties',
    'start_transfer_query',
    'process_transfer_query',
    'start_transfer_analysis',
    'process_transfer_analysis',
    'send_transfer_page',
    'handle_transfer_pagination',
    'cancel_transfer',
    'cancel_transfer_from_message',
    'show_transfer_menu',
    'show_transfer_menu_keyboard',
    'transfer_back_to_main',
    'TRANSFER_QUERY_WAIT_ADDR',
    'TRANSFER_ANALYSIS_WAIT_ADDR',
]
