# handlers/ai_client.py - 重构版

import aiohttp
import asyncio
import json
import re
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from config import (
    DEEPSEEK_API_KEY,
    SILICONFLOW_API_KEY,
    DASHSCOPE_API_KEY,
    ZHIPU_API_KEY
)

API_CONFIGS = [
    {
        "name": "DeepSeek",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "api_key": DEEPSEEK_API_KEY,
        "model": "deepseek-chat",
        "free_quota": 5000000
    },
    {
        "name": "SiliconFlow",
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_key": SILICONFLOW_API_KEY,
        "model": "Qwen/Qwen2-7B-Instruct",
        "free_quota": 20000000
    },
    {
        "name": "阿里云通义",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        "api_key": DASHSCOPE_API_KEY,
        "model": "qwen-turbo",
        "free_quota": 5000000
    },
    {
        "name": "智谱AI",
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key": ZHIPU_API_KEY,
        "model": "glm-4-flash",
        "free_quota": 5000000
    }
]

API_CONFIGS = [c for c in API_CONFIGS if c["api_key"]]

# 对话上下文缓存
CONVERSATION_CACHE = {}
CACHE_TIMEOUT = 300


class AIClient:
    """多 API 自动切换客户端 - 智能回答版"""

    def __init__(self, configs: List[Dict] = None):
        self.configs = configs or API_CONFIGS
        self.current_index = 0
        self.failed_keys = set()

    async def chat(self, prompt: str, system_prompt: str = "你是一个智能助手，回答问题要简洁、准确、友好。") -> str:
        """普通对话"""
        errors = []
        for config in self.configs:
            if not config.get("api_key"):
                continue
            if config["name"] in self.failed_keys:
                continue
            try:
                result = await self._call_api(config, prompt, system_prompt)
                return result
            except Exception as e:
                error_msg = str(e)
                errors.append(f"{config['name']}: {error_msg[:50]}")
                if "insufficient" in error_msg.lower() or "quota" in error_msg.lower() or "balance" in error_msg.lower():
                    self.failed_keys.add(config["name"])
                continue
        return f"❌ 所有 AI 服务暂时不可用，请稍后再试。\n错误: {', '.join(errors)}"

    async def chat_with_data(self, prompt: str, group_id: str = None, 
                              user_id: int = None,
                              system_prompt: str = None) -> str:
        """
        支持数据查询的对话 - 让 AI 读取数据库中的数据并分析回答
        """
        from handlers.data_provider import data_provider
        from auth import is_authorized

        if user_id is None:
            user_id = 0

        # ========== ✅ 添加权限检查 ==========
        # AI 对话功能仅限管理员和操作员（临时操作人不能使用）
        if not is_authorized(user_id, require_full_access=True):
            return "❌ AI 对话功能仅限管理员和操作员使用\n\n如需使用，请联系 @ChinaEdward 申请权限"
        # ===================================

        prompt_lower = prompt.lower()

        # 检测是否是帮助类问题
        help_keywords = ["你能做什么", "有什么功能", "怎么用", "帮助", "help", "功能列表", "提示词", "可以问什么"]
        if any(kw in prompt_lower for kw in help_keywords):
            return self._get_help_message()

        # 检测是否是导出请求（这些使用固定格式，更清晰）
        export_keywords = ["导出", "详细账单", "原始账单", "完整账单", "所有记录", "每一笔", "导出完整账单"]
        is_export = any(word in prompt for word in export_keywords)

        question_keywords = ["哪些", "多少", "几个", "什么", "哪个", "谁", "哪几个", "哪些群"]
        is_question = any(word in prompt for word in question_keywords)

        if is_export and not is_question:
            cached = CONVERSATION_CACHE.get(user_id)
            if cached:
                cache_age = time.time() - cached.get("timestamp", 0)
                if cache_age < CACHE_TIMEOUT:
                    last_intent = cached.get("last_intent")
                    last_data = cached.get("last_data")
                    if last_data:
                        print(f"[DEBUG] 使用缓存数据导出 (年龄: {cache_age:.0f}秒)")
                        return await self._export_raw_bill(prompt, last_data, last_intent)
                else:
                    CONVERSATION_CACHE.pop(user_id, None)
            return "📭 请先查询账单，然后再使用「导出」功能。\n\n例如：先问「测试5群今天收入」，然后说「导出详细账单」"

        # 识别意图
        intent = await self._identify_intent(prompt, user_id)

        print(f"[DEBUG] AI 意图识别结果: {intent}")
        print(f"[DEBUG] 用户ID: {user_id}")

        # 普通聊天直接调用 AI
        if intent.get("type") == "chat":
            return await self.chat(prompt)

        # 获取数据
        data = await self._fetch_data(intent, data_provider)

        if data.get("error"):
            if data.get("available_groups"):
                return f"❌ {data['error']}\n\n💡 {data['suggestion']}"
            return f"❌ {data['error']}"

        # 缓存数据
        CONVERSATION_CACHE[user_id] = {
            "last_intent": intent,
            "last_data": data,
            "timestamp": time.time()
        }
        print(f"[DEBUG] 已缓存用户 {user_id} 的查询数据")

        # 🔥 核心改动：让 AI 生成自然回答（保留导出提示）
        answer = await self._generate_natural_answer(prompt, intent, data)

        if self._should_suggest_export(data):
            answer += "\n\n💡 如需查看详细账单，请发送「导出完整账单」"

        return answer

    async def _identify_intent(self, prompt: str, user_id: int = 0) -> Dict:
        """
        识别用户意图 - 使用规则匹配
        """
        prompt_lower = prompt.lower()

        # ========== 先检测是否是普通聊天 ==========
        data_keywords = [
            "收入", "入款", "出款", "下发", "账单", "记账", "收支", "统计", "情况",
            "群组", "群", "分类", "操作员", "管理员", "监控地址", "地址", "USDT", "usdt",
            "待下发", "未下发", "pending",
            "活跃", "交易", "排行", "趋势", "时段", "大额", "汇总", "新加入"
        ]

        has_data_keyword = any(kw in prompt_lower for kw in data_keywords)

        chat_keywords = ["你好", "谢谢", "感谢", "怎么样", "如何", "什么", "为什么", "谁", "哪里", 
                         "天气", "新闻", "故事", "笑话", "聊天", "打招呼", "hello", "hi", "hey",
                         "今天天气", "明天天气", "温度", "下雨", "晴天", "阴天"]

        if not has_data_keyword or any(kw in prompt_lower for kw in chat_keywords):
            return {"type": "chat", "params": {}}

        # ========== 优先检测地址相关查询 ==========
        address_keywords = ["地址", "usdt", "USDT", "监控地址", "收支", "月度统计"]
        has_address_keyword = any(kw in prompt_lower for kw in address_keywords)

        # 提取地址备注名
        address_note = self._extract_address_note(prompt)

        if has_address_keyword or address_note:
            # 获取用户添加的监控地址
            from db import get_monitored_addresses
            addresses = get_monitored_addresses(user_id=user_id) if user_id else get_monitored_addresses()

            # 尝试匹配备注名
            matched_address = None
            matched_note = None

            for addr in addresses:
                note = addr.get('note', '')
                if note:
                    if address_note and (address_note in note or note in address_note):
                        matched_address = addr['address']
                        matched_note = note
                        break
                    if address_note and address_note == note:
                        matched_address = addr['address']
                        matched_note = note
                        break

            if matched_address:
                if "月度统计" in prompt_lower:
                    return {"type": "address_monthly_stats", "params": {"address": matched_address, "note": matched_note}}
                else:
                    date_range = self._extract_date_range(prompt)
                    return {"type": "address_stats", "params": {"address": matched_address, "date": date_range, "note": matched_note}}

            # 尝试直接提取地址
            address = self._extract_address(prompt)
            if address:
                if "月度统计" in prompt_lower:
                    return {"type": "address_monthly_stats", "params": {"address": address}}
                else:
                    date_range = self._extract_date_range(prompt)
                    return {"type": "address_stats", "params": {"address": address, "date": date_range}}

        # ========== 操作员查询 ==========
        if any(kw in prompt_lower for kw in ["操作员", "管理员", "授权用户"]):
            return {"type": "operators", "params": {}}

        # ========== 群组分类查询 ==========
        if any(kw in prompt_lower for kw in ["有哪些分类", "群组分类", "分类列表"]):
            return {"type": "group_categories", "params": {}}

        # ========== 新加入群组查询 ==========
        if "新加入" in prompt_lower or "新加群" in prompt_lower:
            date = self._extract_date(prompt)
            if date:
                return {"type": "joined_groups_by_date", "params": {"date": date}}
            elif "本周" in prompt_lower:
                return {"type": "joined_groups_weekly", "params": {}}
            elif "本月" in prompt_lower:
                return {"type": "joined_groups_monthly", "params": {}}
            elif "今天" in prompt_lower or "今日" in prompt_lower:
                return {"type": "joined_groups_today", "params": {}}
            elif "昨天" in prompt_lower or "昨日" in prompt_lower:
                return {"type": "joined_groups_yesterday", "params": {}}
            else:
                return {"type": "joined_groups_today", "params": {}}

        # ========== 群组活跃度排行 ==========
        if any(kw in prompt_lower for kw in ["活跃度排行", "活跃排行", "活跃群组排行"]):
            return {"type": "activity_ranking", "params": {}}

        # ========== 今日汇总查询（今天总入款和待下发）==========
        if ("汇总" in prompt_lower or "总入款" in prompt_lower) and ("今天" in prompt_lower or "今日" in prompt_lower):
            return {"type": "today_summary", "params": {}}

        # ========== 待下发查询 ==========
        if any(kw in prompt_lower for kw in ["未下发", "待下发", "pending", "待出款", "未出款", "还有多少"]):
            return {"type": "pending_groups", "params": {}}

        # ========== 今日有交易的群组 ==========
        if any(kw in prompt_lower for kw in ["有交易的群", "交易过的群", "活跃群组", "哪些群使用了记账", "哪些群使用记账", "哪些群用了记账", "哪些群组使用了记账"]):
            # 提取日期范围
            date_range = self._extract_date_range(prompt)
            return {"type": "active_groups", "params": {"date": date_range}}

        # ========== 今日交易最多的群组 ==========
        if any(kw in prompt_lower for kw in ["交易最多", "收入最多", "入款最多群", "top群"]):
            return {"type": "top_group", "params": {}}

        # ========== 用户排行 ==========
        if any(kw in prompt_lower for kw in ["入款最多的用户", "入款排行", "top用户", "最高入款"]):
            return {"type": "top_users", "params": {"limit": 10}}

        # ========== 今日使用记账的用户 ==========
        if any(kw in prompt_lower for kw in ["使用记账的用户", "记账用户", "活跃用户"]):
            return {"type": "active_users", "params": {}}

        # ========== 时段分布 ==========
        if any(kw in prompt_lower for kw in ["时段分布", "哪个时段", "小时分布"]):
            return {"type": "hourly_distribution", "params": {}}

        # ========== 分类入款占比 ==========
        if any(kw in prompt_lower for kw in ["分类占比", "入款占比", "各分类占比"]):
            return {"type": "category_percentage", "params": {}}

        # ========== 最近7天趋势 ==========
        if any(kw in prompt_lower for kw in ["最近7天", "7天趋势", "收入趋势", "走势"]):
            return {"type": "weekly_trend", "params": {}}

        # ========== 所有群组收入查询 ==========
        all_groups_keywords = ["所有群", "全部群", "每个群", "各个群", "所有群组", "全部群组", "各个群组"]
        if any(kw in prompt_lower for kw in all_groups_keywords):
            date = self._extract_date_range(prompt)
            return {"type": "today_all_income", "params": {"date": date}}

        # ========== 本月总收入 ==========
        if any(kw in prompt_lower for kw in ["本月总收入", "本月收入", "这个月收入"]):
            return {"type": "month_total", "params": {}}

        # ========== 大额交易 ==========
        if any(kw in prompt_lower for kw in ["大额交易", "大额", "大笔"]):
            return {"type": "large_transactions", "params": {"threshold": 5000}}

        # ========== 指定分类下的群组 ==========
        category_keywords = ["分类下的群组", "分类有哪些群", "分类下的群", "分类里的群", "分类下的群组有"]
        if any(kw in prompt_lower for kw in category_keywords):
            # 从数据库动态获取分类名称
            from db import get_all_categories
            categories = get_all_categories()
            category_names = [cat['name'] for cat in categories]

            for cat in category_names:
                if cat in prompt:
                    return {"type": "groups_by_category", "params": {"category": cat}}

            # 如果没有匹配到具体分类，返回所有分类列表
            if category_names:
                return {"type": "groups_by_category", "params": {"category": None, "available_categories": category_names}}
            return {"type": "groups_by_category", "params": {"category": None}}

        # ========== 所有分类及群组列表 ==========
        all_category_keywords = ["所有分类及群组", "每个分类下的群组", "分类群组列表", "所有分类群组", "全部分类及群组", "所有分类的群组"]
        if any(kw in prompt_lower for kw in all_category_keywords):
            return {"type": "all_groups_by_category", "params": {}}

        # ========== 收入对比分析 ==========
        if "对比" in prompt_lower:
            group_name = self._extract_group_name(prompt)
            period = self._extract_compare_period(prompt)
            if group_name:
                return {"type": "group_compare", "params": {"group_name": group_name, "period": period}}
            else:
                return {"type": "all_compare", "params": {"period": period}}

        # ========== 群组账单查询（放在最后，避免误匹配）==========
        skip_keywords = ["有交易的群", "活跃群组", "分类下的群组", "所有分类", "待下发", "汇总", "哪些群"]
        if "群" in prompt_lower and not has_address_keyword:
            should_skip = any(kw in prompt_lower for kw in skip_keywords)
            if not should_skip:
                group_name = self._extract_group_name(prompt)
                if group_name:
                    date_range = self._extract_date_range(prompt)
                    return {"type": "group_bill", "params": {"group_name": group_name, "date": date_range}}

        # ========== 记账情况查询 ==========
        if any(kw in prompt_lower for kw in ["记账情况", "记账记录"]):
            date_range = self._extract_date_range(prompt)
            return {"type": "today_all_income", "params": {"date": date_range}}

        return {"type": "chat", "params": {}}

    def _extract_address_note(self, prompt: str) -> str:
        """
        提取地址备注名
        支持格式：
        - "查看三角国际地址今天的收入" -> "三角国际地址"
        - "三角国际地址昨天收入" -> "三角国际地址"
        - "查询今天三角国际地址收入" -> "三角国际地址"
        """
        # 移除日期关键词
        date_keywords = ["今天", "昨天", "今日", "昨日", "本周", "上周", "本月", "上月", 
                         "收入", "查询", "查看", "分析", "统计", "月度统计", "收支"]
        clean_prompt = prompt
        for kw in date_keywords:
            clean_prompt = clean_prompt.replace(kw, "")

        # 移除"地址"后缀
        clean_prompt = clean_prompt.replace("地址", "")
        clean_prompt = clean_prompt.strip()

        if clean_prompt and len(clean_prompt) >= 2:
            return clean_prompt

        pattern = r'([\u4e00-\u9fa5a-zA-Z0-9]+)地址'
        match = re.search(pattern, prompt)
        if match:
            return match.group(1)

        return None

    def _should_suggest_export(self, data: Dict) -> bool:
        """判断是否应该提示用户可以导出详细账单"""
        if data.get("income_count", 0) > 5 or data.get("expense_count", 0) > 5:
            return True
        if data.get("recent_income") and len(data.get("recent_income", [])) > 5:
            return True
        if data.get("groups") and len(data.get("groups", [])) > 10:
            return True
        return False

    def _get_help_message(self) -> str:
        """获取帮助信息 - 优化版，满足所有提问需求"""
        return """🤖 **智能记账助手 - 功能说明**

💡 **直接输入问题即可，我会自动识别！**

📊 **记账**
  `xxx群今天收入` - 查看今日收入
  `xxx群昨天账单` - 查看昨日账单
  `xxx群本周收入` - 查看本周账单
  `xxx群本月账单` - 查看本月账单
  `xxx群4月5日账单` - 查看指定日期账单
  `xxx群4月3日到今天收入` - 查看日期范围

• **所有群组统计**
  `所有群今天收入` - 所有群今日收入
  `所有群昨天收入` - 所有群昨日收入
  `所有群本周收入` - 所有群本周收入
  `所有群本月收入` - 所有群本月收入

• **收入对比分析**
  `分析xxx群昨天和今天收入对比` - 群组对比
  `分析昨天和今天收入对比` - 全局对比
  `分析本周和上周收入对比` - 周对比
  `分析本月和上月收入对比` - 月对比

• **待下发查询**
  `是否有未下发`、`待下发USDT` - 查看待下发金额

• **导出详细账单**
  先查询账单，再说`导出详细账单` - 查看每笔交易明细

💰 **地址监控**（支持备注名）
  `查看XXX地址今天的收入` - 用备注名查询
  `XXX地址昨天收入` - 用备注名查询
  `查询今天XXX地址收入` - 用备注名查询
  `查看XXX地址月度统计` - 月度统计

• **通过地址查询**
  `查询今天Txxxx...地址收入` - 用完整地址查询
  `分析本周Txxxx...地址` - 周期统计

👥 **操作员管理**
• `操作员有哪些` - 查看操作员列表（含昵称、用户名、ID）

📁 **群组管理**
• `有哪些分类` - 查看所有群组分类
• `今天新加入了哪些群组` - 今日新群组
• `昨天新加入了哪些群组` - 昨日新群组
• `本周新加入了哪些群组` - 本周新群组（含每天详情）
• `本月新加入了哪些群组` - 本月新群组（含每天详情）
• `4月5日新加入了哪些群组` - 指定日期
• `群组活跃度排行` - 按交易笔数排行
• `今天哪些群使用了记账功能` - 今日活跃群组
• `今日交易最多的群组` - 收入最高群组
• `查询中国分类下的群组` - 按分类查群组
• `所有分类及群组列表` - 完整分类列表

📈 **数据分析**
• `今日入款最多的用户` - 用户排行
• `今日使用记账的用户` - 活跃用户
• `最近7天趋势` - 收入走势图
• `查询时段分布` - 各时段收入
• `各分类入款占比` - 分类统计
• `本月总收入` - 本月汇总
• `查询大额交易` - 大额提醒
• `今天总入款和待下发` - 今日汇总

💡 **提示**：模糊匹配 | 5分钟上下文记忆 | 先查询后导出"""

    def _extract_date(self, prompt: str) -> str:
        """提取日期，如 4月5日"""
        patterns = [
            r'(\d{1,2})月(\d{1,2})日',
            r'(\d{1,2})-(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, prompt)
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
                now = datetime.now()
                year = now.year
                if month > now.month:
                    year = now.year - 1
                return f"{year}-{month:02d}-{day:02d}"
        return None

    def _extract_date_range(self, prompt: str) -> str:
        """提取日期范围"""
        prompt_lower = prompt.lower()

        range_pattern = r'(\d{1,2})月(\d{1,2})日到今天'
        match = re.search(range_pattern, prompt)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            now = datetime.now()
            year = now.year
            if month > now.month:
                year = now.year - 1
            start_date = f"{year}-{month:02d}-{day:02d}"
            end_date = now.strftime('%Y-%m-%d')
            return f"{start_date}_to_{end_date}"

        date = self._extract_date(prompt)
        if date:
            return date

        if any(kw in prompt_lower for kw in ["今天", "今日"]):
            return "today"
        if any(kw in prompt_lower for kw in ["昨天", "昨日"]):
            return "yesterday"
        if "本周" in prompt_lower:
            return "week"
        if "本月" in prompt_lower:
            return "month"
        if "最近两天" in prompt_lower:
            return "last2days"

        return "today"

    def _extract_compare_period(self, prompt: str) -> str:
        """提取对比周期"""
        prompt_lower = prompt.lower()

        if "昨天和今天" in prompt_lower or "今日和昨日" in prompt_lower:
            return "today_vs_yesterday"
        if "本周和上周" in prompt_lower:
            return "week_vs_lastweek"
        if "本月和上一月" in prompt_lower or "本月和上月" in prompt_lower:
            return "month_vs_lastmonth"

        date = self._extract_date(prompt)
        if date:
            return f"date_{date}"

        return "today_vs_yesterday"

    def _extract_group_name(self, prompt: str) -> str:
        """提取群组名称"""
        date_keywords = ["今天", "昨天", "今日", "昨日", "本周", "上周", "本月", "上月", 
                         "收入", "账单", "情况", "统计", "查询", "分析", "对比"]
        clean_prompt = prompt
        for kw in date_keywords:
            clean_prompt = clean_prompt.replace(kw, "")

        pattern1 = r'([^\s]+)群(?:组)?'
        match = re.search(pattern1, clean_prompt)
        if match:
            name = match.group(1).strip()
            if name and len(name) >= 2:
                return name

        pattern2 = r'([A-Za-z0-9]+\s+[^\s]+/[^\s]+)'
        match = re.search(pattern2, clean_prompt)
        if match:
            return match.group(1).strip()

        pattern3 = r'([A-Za-z0-9]+[\u4e00-\u9fa5]*)'
        match = re.search(pattern3, clean_prompt)
        if match:
            name = match.group(1).strip()
            if any(c.isdigit() for c in name) and len(name) >= 3:
                return name

        pattern4 = r'([\u4e00-\u9fa5]{2,8})'
        match = re.search(pattern4, clean_prompt)
        if match:
            name = match.group(1).strip()
            if name not in ["收入", "入款", "出款", "下发", "账单", "记账"]:
                return name

        return None

    def _extract_category(self, prompt: str) -> str:
        """提取分类名称（从数据库动态获取）"""
        from db import get_all_categories

        # 获取所有已保存的分类名称
        categories = get_all_categories()
        category_names = [cat['name'] for cat in categories]

        # 按长度排序，优先匹配更长的分类名（避免短词误匹配）
        category_names.sort(key=len, reverse=True)

        for cat in category_names:
            if cat in prompt:
                return cat

        return None

    def _extract_address(self, prompt: str) -> str:
        """提取TRC20地址"""
        pattern = r'T[0-9A-Za-z]{33}'
        match = re.search(pattern, prompt)
        if match:
            return match.group()
        return None

    async def _fetch_data(self, intent: Dict, data_provider) -> Dict:
        """根据意图获取数据"""
        intent_type = intent.get("type", "unknown")
        params = intent.get("params", {})

        # 操作员
        if intent_type == "operators":
            return data_provider.get_operators()

        # 群组分类
        if intent_type == "group_categories":
            return data_provider.get_group_categories()

        # 新加入群组
        if intent_type == "joined_groups_today":
            return data_provider.get_today_joined_groups()
        if intent_type == "joined_groups_yesterday":
            return data_provider.get_yesterday_joined_groups()
        if intent_type == "joined_groups_weekly":
            return data_provider.get_weekly_joined_groups()
        if intent_type == "joined_groups_monthly":
            return data_provider.get_monthly_joined_groups()
        if intent_type == "joined_groups_by_date":
            return data_provider.get_joined_groups_by_date(params.get("date"))

        # 活跃度
        if intent_type == "activity_ranking":
            return data_provider.get_group_activity_ranking()
        if intent_type == "active_groups":
            date = params.get("date", "today")
            if date == "yesterday":
                return data_provider.get_yesterday_active_groups()
            elif date == "week":
                return data_provider.get_week_active_groups()
            elif date == "month":
                return data_provider.get_month_active_groups()
            else:
                return data_provider.get_today_active_groups()
        if intent_type == "top_group":
            return data_provider.get_today_top_group()

        # 用户相关
        if intent_type == "top_users":
            return data_provider.get_today_top_users(params.get("limit", 10))
        if intent_type == "active_users":
            return data_provider.get_today_active_users()

        # 数据分析
        if intent_type == "hourly_distribution":
            return data_provider.get_hourly_distribution()
        if intent_type == "category_percentage":
            return data_provider.get_category_income_percentage()
        if intent_type == "weekly_trend":
            return data_provider.get_weekly_trend()
        if intent_type == "month_total":
            return data_provider.get_month_total_income()
        if intent_type == "large_transactions":
            return data_provider.get_large_transactions(params.get("threshold", 5000))
        if intent_type == "pending_groups":
            return data_provider.get_pending_usdt_groups()
        if intent_type == "today_summary":
            return data_provider.get_today_summary()

        # 所有群组收入
        if intent_type == "today_all_income":
            date = params.get("date", "today")
            if date == "yesterday":
                result = data_provider.get_yesterday_all_income()
            elif date == "week":
                result = data_provider.get_week_all_income()
            elif date == "month":
                result = data_provider.get_month_all_income()
            else:
                result = data_provider.get_today_all_income()

            # 🔥 如果返回结果中有 summary，直接使用
            if result.get("summary"):
                return result
            return result

        # 待下发
        if intent_type == "pending_groups":
            result = data_provider.get_pending_usdt_groups()
            # 🔥 如果返回结果中有 summary，直接使用
            if result.get("summary"):
                return result
            return result

        # 群组账单
        if intent_type == "group_bill":
            group_name = params.get("group_name", "")
            date = params.get("date", "today")
            if not group_name:
                return {"error": "请指定群组名称"}
            if date == "today":
                return data_provider.get_group_today_bill(group_name)
            elif date == "yesterday":
                return data_provider.get_group_yesterday_bill(group_name)
            elif date == "week":
                return data_provider.get_group_week_bill(group_name)
            elif date == "month":
                return data_provider.get_group_month_bill(group_name)
            elif "_to_" in date:
                parts = date.split("_to_")
                return data_provider.get_group_bill_range(group_name, parts[0], parts[1])
            return data_provider.get_group_bill_by_date(group_name, date)

        # 对比分析
        if intent_type == "group_compare":
            return data_provider.get_group_compare(params.get("group_name", ""), params.get("period", "today_vs_yesterday"))
        if intent_type == "all_compare":
            return data_provider.get_all_compare(params.get("period", "today_vs_yesterday"))

        # 分类群组
        if intent_type == "groups_by_category":
            return data_provider.get_groups_by_category(params.get("category", ""))
        if intent_type == "all_groups_by_category":
            return data_provider.get_all_groups_by_category()

        # 地址统计
        if intent_type == "address_stats":
            address = params.get("address", "")
            note = params.get("note", "")
            date = params.get("date", "today")

            if not address and note:
                from db import get_monitored_addresses
                addresses = get_monitored_addresses()
                for addr in addresses:
                    if note in addr.get('note', '') or addr.get('note', '') in note:
                        address = addr['address']
                        break

            if not address:
                return {"error": f"未找到备注为「{note}」的监控地址" if note else "请指定地址"}

            return await data_provider.get_address_stats(address, date)

        if intent_type == "address_monthly_stats":
            address = params.get("address", "")
            note = params.get("note", "")

            if not address and note:
                from db import get_monitored_addresses
                addresses = get_monitored_addresses()
                for addr in addresses:
                    if note in addr.get('note', '') or addr.get('note', '') in note:
                        address = addr['address']
                        break

            if not address:
                return {"error": f"未找到备注为「{note}」的监控地址" if note else "请指定地址"}

            return await data_provider.get_address_monthly_stats(address)

        return {"error": "无法获取数据"}

    # ========== 🔥 核心改进：让 AI 真正智能回答 ==========

    async def _generate_natural_answer(self, question: str, intent: Dict, data: Dict) -> str:
        """
        让 AI 用自然语言生成回答
        除非数据已经包含了 summary（来自 data_provider 的固定格式）
        """
        # 如果数据已经有 summary（来自 data_provider 的固定格式），直接使用
        if data.get("summary"):
            return data["summary"]

        if data.get("error"):
            return f"❌ {data['error']}"
        if data.get("message"):
            return f"📭 {data['message']}"

        # 检查数据量，如果太大则截断
        data_summary = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        if len(data_summary) > 2500:
            # 对于大数据，智能截断关键信息
            data_summary = self._smart_truncate_data(data, data_summary)

        intent_type = intent.get("type", "unknown")

        # 根据意图类型定制 system prompt
        system_prompt = self._build_system_prompt(intent_type, data)

        user_prompt = f"""用户问题：{question}

查询到的数据：
{data_summary}

请根据以上数据，用自然、友好的语言回答用户的问题。

要求：
1. 直接回答，不要重复问题
2. 金额格式：数字+元 或 数字+USDT
3. 同时显示时用" = "连接
4. 不要说"人民币"、"折合"、"美元"
5. 根据数据特点灵活组织语言，可以适当使用emoji
6. 如果数据较多，可以分类总结
7. 不要输出JSON或代码块"""

        return await self.chat(user_prompt, system_prompt)

    def _smart_truncate_data(self, data: Dict, full_json: str) -> str:
        """智能截断数据，保留关键信息"""
        # 如果是群组列表，只保留前10个
        if "groups" in data and isinstance(data["groups"], list) and len(data["groups"]) > 10:
            data["groups"] = data["groups"][:10]
            data["_truncated"] = f"（共{len(data.get('groups_original', []))}个群组，仅显示前10个）"

        # 如果是交易记录，只保留前10条
        if "recent_income" in data and isinstance(data["recent_income"], list) and len(data["recent_income"]) > 10:
            data["recent_income"] = data["recent_income"][:10]
            data["_income_truncated"] = f"（共{len(data.get('income_count', 0))}笔，仅显示前10笔）"

        if "recent_expense" in data and isinstance(data["recent_expense"], list) and len(data["recent_expense"]) > 10:
            data["recent_expense"] = data["recent_expense"][:10]
            data["_expense_truncated"] = f"（共{len(data.get('expense_count', 0))}笔，仅显示前10笔）"

        # 如果是分类数据，保留所有（通常不大）

        truncated = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        if len(truncated) > 2500:
            truncated = truncated[:2500] + "...\n（数据过长已截断）"

        return truncated

    def _build_system_prompt(self, intent_type: str, data: Dict) -> str:
        """根据意图类型构建 system prompt - 强化金额规则"""
        base_rules = """你是智能记账助手，回答要自然、友好、简洁。

【重要】金额格式规则（必须严格遵守）：
1. 人民币金额：数字后面跟"元"，如：1000元
2. USDT金额：数字后面跟"USDT"，如：138 USDT
3. 【禁止】不要把元直接等于USDT！正确示例：1000元 ≈ 138 USDT（按实时汇率）
4. 【禁止】绝对不能说"502元 = 502 USDT"，这是错误的！除非汇率是1:1
5. 如果只有人民币就只显示元，只有USDT就只显示USDT
6. 不要说"人民币"、"折合"、"美元"
7. 不要说"根据提供的数据"、"数据显示"等套话

汇率参考：1 USDT ≈ 7.2元（具体根据实际数据）"""

        # 针对地址查询的特殊规则
        if intent_type == "address_stats":
            address_rules = """
【地址查询特别注意】：
- 余额是USDT单位，不是元！
- 格式示例：当前余额 502 USDT（不是502元）
- 收入/支出也是USDT单位
- 如果收入为0，就只说"今日无收入记录"
- 数据中的 received_usdt、sent_usdt、net_usdt、balance_usdt 字段，单位全部是【USDT】
- 请使用"USDT"作为单位，绝对不要使用"元"
- 正确示例：「收入 13094 USDT，支出 12642 USDT，净收入 452 USDT，余额 502 USDT」
- 错误示例：「收入 13094元」（这是错误的！）
- 不要编造汇率转换"""
            base_rules += "\n" + address_rules

        # 针对不同意图类型的特殊指导
        intent_guides = {
            "group_bill": "重点总结收入、支出、待下发金额。注意：收入是人民币元，待下发是USDT，不要混淆。",
            "address_stats": "地址统计中所有金额都是USDT单位。格式：收到X USDT，转出Y USDT，净收入Z USDT，当前余额W USDT。",
            "today_all_income": "列出收入较高的几个群组，金额是人民币元。",
            "pending_groups": "待下发金额是USDT单位。",
            "top_users": "列出前几名用户及其入款金额。",
            "weekly_trend": "分析收入趋势（上升/下降/平稳），指出最高和最低的一天。",
            "hourly_distribution": "指出哪个时段收入最多，哪个时段最少。",
            "category_percentage": "说明各分类占比，指出占比最大的分类。",
            "active_groups": "告诉用户今天有多少群组使用了记账，可以列举几个。",
            "operators": "简洁列出操作员信息。",
            "address_stats": "总结地址的收支情况，包括净收入和余额。",
            "group_compare": "重点说明增长或下降的幅度和金额。",
            "all_compare": "总结整体收入变化趋势。"
        }

        guide = intent_guides.get(intent_type, "根据数据准确回答用户问题。")

        return f"{base_rules}\n\n{guide}"

    # ========== 以下是导出功能（保留固定格式，更清晰）==========

    async def _export_raw_bill(self, question: str, data: Dict, intent: Dict) -> str:
        """导出原始账单 - 使用固定格式，更清晰"""
        intent_type = intent.get("type", "unknown")

        if intent_type == "group_bill":
            return self._format_group_bill_export(data)
        elif intent_type == "address_stats":
            return self._format_address_export(data)
        elif intent_type == "today_all_income":
            return self._format_all_income_export(data)
        else:
            # 其他类型也用AI生成，但提示是导出
            return await self._generate_natural_answer(question, intent, data)

    def _format_group_bill_export(self, data: Dict) -> str:
        """格式化群组账单导出 - 固定格式"""
        if data.get("error"):
            return f"❌ {data['error']}"
        if data.get("message"):
            return f"📭 {data['message']}"

        group_name = data.get("group_name", "未知群组")
        date = data.get("date", "未知日期")
        fee_rate = data.get("fee_rate", 0)
        exchange_rate = data.get("exchange_rate", 1)
        per_transaction_fee = data.get("per_transaction_fee", 0)

        result = f"📊 **{group_name} {date} 详细账单**\n\n"
        result += f"⚙️ 费率：{fee_rate}%\n"
        result += f"💱 汇率：1 USDT = {exchange_rate} 元\n"
        result += f"📝 单笔费用：{per_transaction_fee} 元\n\n"

        income_records = data.get("recent_income", [])
        if income_records:
            result += f"💰 **入款记录（{len(income_records)}笔）**\n"
            result += "```\n"
            result += f"{'时间':<8} {'金额(元)':<12} {'USDT':<10} {'用户':<15} {'分类'}\n"
            result += "-" * 55 + "\n"
            for r in income_records:
                time_str = r.get("time", "")
                amount_cny = r.get("amount_cny", 0)
                amount_usdt = r.get("amount_usdt", 0)
                user = r.get("user", "")[:12]
                category = r.get("category", "")
                result += f"{time_str:<8} {amount_cny:<12.2f} {amount_usdt:<10.2f} {user:<15} {category}\n"
            result += "```\n\n"

        expense_records = data.get("recent_expense", [])
        if expense_records:
            result += f"📤 **出款记录（{len(expense_records)}笔）**\n"
            result += "```\n"
            result += f"{'时间':<8} {'USDT':<10} {'用户':<15}\n"
            result += "-" * 35 + "\n"
            for r in expense_records:
                time_str = r.get("time", "")
                amount_usdt = r.get("amount_usdt", 0)
                user = r.get("user", "")[:12]
                result += f"{time_str:<8} {amount_usdt:<10.2f} {user:<15}\n"
            result += "```\n\n"

        categories = data.get("categories", {})
        if categories:
            result += f"📁 **入款分组统计**\n"
            for cat, cat_data in categories.items():
                result += f"  • {cat}：{cat_data.get('cny', 0):.2f}元 = {cat_data.get('usdt', 0):.2f} USDT（{cat_data.get('count', 0)}笔）\n"
            result += "\n"

        result += f"📊 **汇总**\n"
        result += f"  • 总入款：{data.get('income_cny', 0):.2f}元 = {data.get('income_usdt', 0):.2f} USDT（{data.get('income_count', 0)}笔）\n"
        result += f"  • 总出款：{data.get('expense_usdt', 0):.2f} USDT（{data.get('expense_count', 0)}笔）\n"
        result += f"  • 待下发：{data.get('pending_usdt', 0):.2f} USDT\n"

        return result

    def _format_address_export(self, data: Dict) -> str:
        """格式化地址导出 - 固定格式"""
        if data.get("error"):
            return f"❌ {data['error']}"

        address = data.get("address", "未知地址")
        note = data.get("note", "")
        period = data.get("period", "今日")

        result = f"💰 **监控地址收支详情**\n\n"
        result += f"📌 地址：`{address}`\n"
        if note:
            result += f"📝 备注：{note}\n"
        result += f"📅 周期：{period}\n\n"

        result += f"📊 **统计**\n"
        result += f"  • 收到：{data.get('received_usdt', 0):.2f} USDT\n"
        result += f"  • 转出：{data.get('sent_usdt', 0):.2f} USDT\n"
        result += f"  • 净收入：{data.get('net_usdt', 0):.2f} USDT\n"
        result += f"  • 当前余额：{data.get('balance_usdt', 0):.2f} USDT\n"
        result += f"  • 交易笔数：{data.get('transaction_count', 0)} 笔\n"

        return result

    def _format_all_income_export(self, data: Dict) -> str:
        """格式化所有群组收入导出 - 固定格式"""
        if data.get("error"):
            return f"❌ {data['error']}"

        date = data.get("date", "今日")
        groups = data.get("groups", [])
        total_income = data.get("total_income_usdt", 0)

        result = f"📊 **{date}所有群组收入明细**\n\n"
        result += f"💰 总收入：{total_income:.2f} USDT\n"
        result += f"📈 活跃群组：{len(groups)} 个\n\n"
        result += "📋 **详细列表**：\n"

        for g in groups:
            result += f"  • {g['name']}：{g['income_usdt']:.2f} USDT ({g['income_count']}笔)\n"

        return result

    async def _call_api(self, config: Dict, prompt: str, system_prompt: str) -> str:
        """调用 API"""
        name = config["name"]
        url = config["url"]
        api_key = config["api_key"]

        print(f"🤖 正在使用 {name} API...")

        headers = {"Content-Type": "application/json"}

        if name == "DeepSeek" or name == "SiliconFlow" or name == "智谱AI":
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "max_tokens": 2000,
                "temperature": 0.7
            }
        elif name == "阿里云通义":
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": config["model"],
                "input": {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ]
                },
                "parameters": {
                    "max_tokens": 2000,
                    "temperature": 0.7
                }
            }
        else:
            raise ValueError(f"未知的 API: {name}")

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"HTTP {resp.status}: {error_text[:100]}")
                data = await resp.json()
                if name == "DeepSeek" or name == "SiliconFlow" or name == "智谱AI":
                    return data["choices"][0]["message"]["content"]
                elif name == "阿里云通义":
                    return data["output"]["choices"][0]["message"]["content"]
                else:
                    return str(data)


ai_client = None

def get_ai_client() -> AIClient:
    global ai_client
    if ai_client is None:
        ai_client = AIClient()
    return ai_client
