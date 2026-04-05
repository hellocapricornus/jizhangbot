import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime

USDT_CONTRACT_ADDR = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
PAGE_SIZE = 5

# 点击 USDT 按钮 → 提示输入地址
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # 设置模块标识（关键！）
    context.user_data["active_module"] = "usdt"

    # 设置独立 session 存储用户查询状态
    context.user_data["usdt_session"] = {
        "waiting_for_address": True
    }

    await query.message.reply_text("💰 请输入 TRON TRC20 地址（T 开头）：")

# 输入地址处理
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.user_data.get("usdt_session")
    if not session or not session.get("waiting_for_address"):
        return  # 不属于 USDT 模块输入

    address = update.message.text.strip()
    await update.message.reply_text("🔍 查询中，请稍等…")

    try:
        trx, usdt, txs = await query_tron(address)
        context.user_data["usdt_session"]["data"] = {
            "address": address,
            "trx": trx,
            "usdt": usdt,
            "transactions": txs,
            "page": 0
        }
        context.user_data["usdt_session"]["waiting_for_address"] = False

        if trx == 0 and usdt == 0 and len(txs) == 0:
            await update.message.reply_text(
                f"📊 地址：<code>{address}</code>\n❌ 该地址无余额或未激活",
                parse_mode="HTML"
            )
            # 无余额时也要清除状态
            context.user_data.pop("active_module", None)
            context.user_data.pop("usdt_session", None)
        else:
            await send_trx_usdt_page(update, context)

    except Exception as e:
        print("❗ USDT 查询异常:", e)
        await update.message.reply_text("❌ 查询失败，请稍后再试")
        context.user_data.pop("active_module", None)
        context.user_data.pop("usdt_session", None)

# 查询 TronGrid API
async def query_tron(address: str):
    async with aiohttp.ClientSession() as session:
        # 查询余额
        url_balance = f"https://api.trongrid.io/v1/accounts/{address}"
        async with session.get(url_balance) as resp:
            data = await resp.json()

        trx = 0
        usdt = 0
        if data.get("data"):
            trx = int(data["data"][0].get("balance", 0)) / 1_000_000
            trc20 = data["data"][0].get("trc20", [])
            for t in trc20:
                if USDT_CONTRACT_ADDR in t:
                    usdt = int(t[USDT_CONTRACT_ADDR]) / 1_000_000
                    break

        # 查询最近 50 条 USDT TRC20 交易
        url_tx = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=50&contract_address={USDT_CONTRACT_ADDR}"
        async with session.get(url_tx) as resp:
            tx_data = await resp.json()

        txs = []
        for tx in tx_data.get("data", []):
            from_addr = tx.get("from", "")
            to_addr = tx.get("to", "")
            amount = int(tx.get("value", 0)) / 1_000_000
            ts = tx.get("block_timestamp", 0)
            dt = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else "未知时间"
            direction = "收" if to_addr == address else "支"
            txs.append(f"{dt}\n{direction} | {amount} USDT | <code>{from_addr}</code> → <code>{to_addr}</code>")

        return trx, usdt, txs

# 分页显示
async def send_trx_usdt_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.user_data.get("usdt_session")
    if not session or "data" not in session:
        await update.message.reply_text("❌ 未查询数据")
        return

    data = session["data"]
    page = data["page"]
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_tx = data["transactions"][start:end]

    text = f"📊 地址：<code>{data['address']}</code>\n💠 TRX余额：{data['trx']}\n💰 USDT余额：{data['usdt']}\n\n📜 最近交易（第 {page+1} 页）：\n"
    text += "\n\n".join(page_tx) if page_tx else "暂无交易记录"

    buttons = []
    if start > 0:
        buttons.append(InlineKeyboardButton("⬅ 上一页", callback_data="usdt_prev"))
    if end < len(data["transactions"]):
        buttons.append(InlineKeyboardButton("➡ 下一页", callback_data="usdt_next"))

    # 添加完成按钮
    buttons.append(InlineKeyboardButton("✅ 完成", callback_data="usdt_done"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

# 分页按钮
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    session = context.user_data.get("usdt_session")

    # ✅ 添加完成按钮处理
    if query.data == "usdt_done":
        context.user_data.pop("active_module", None)
        context.user_data.pop("usdt_session", None)
        from handlers.menu import get_main_menu
        await query.message.edit_text(
            "✅ 查询完成\n\n请选择功能：",
            reply_markup=get_main_menu()
        )
        return
    
    if not session or "data" not in session:
        await query.message.reply_text("❌ 未查询数据")
        return

    data = session["data"]
    if query.data == "usdt_prev":
        data["page"] = max(data["page"] - 1, 0)
    elif query.data == "usdt_next":
        data["page"] = min(data["page"] + 1, (len(data["transactions"]) - 1) // PAGE_SIZE)

    await send_trx_usdt_page(update, context)

# 添加一个函数来处理分页完成后的清理
async def usdt_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """USDT 查询完成，清除状态"""
    query = update.callback_query
    await query.answer()

    context.user_data.pop("active_module", None)
    context.user_data.pop("usdt_session", None)

    from handlers.menu import get_main_menu
    await query.message.reply_text(
        "✅ 查询完成\n\n请选择功能：",
        reply_markup=get_main_menu()
    )
