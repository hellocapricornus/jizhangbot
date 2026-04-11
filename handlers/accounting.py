# accounting.py - 完整的记账功能（带备注分组和国旗显示）

import re
import time
import sqlite3
import logging
import aiohttp
import math
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from auth import is_authorized

# 配置日志
logger = logging.getLogger(__name__)

# 常量配置
MAX_DISPLAY_RECORDS = 8  # 账单显示的最大记录数
DB_TIMEOUT = 10  # 数据库连接超时（秒）

# USDT 合约地址（可根据需要添加更多）
USDT_CONTRACTS = {
    'TRC20': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',  # TRC20 USDT
    'ERC20': '0xdAC17F958D2ee523a2206206994597C13D831ec7'  # ERC20 USDT
}

# API 配置
TRONGRID_API = "https://api.trongrid.io"
ETHERSCAN_API = "https://api.etherscan.io/api"
ETHERSCAN_API_KEY = "MVYZTUF89KQ117USY6WH8CT2M6W7TK3PUD"  # 需要去 https://etherscan.io 注册获取

# 设置北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))

def beijing_time(timestamp: int) -> datetime:
    """将时间戳转换为北京时间"""
    return datetime.fromtimestamp(timestamp, tz=BEIJING_TZ)

def get_today_beijing() -> str:
    """获取今天的北京时间日期字符串"""
    return beijing_time(int(time.time())).strftime('%Y-%m-%d')


# 国家代码和名称映射（带国旗）
COUNTRY_FLAGS = {
    # 中文名称
    '中国': '🇨🇳', '美国': '🇺🇸', '日本': '🇯🇵', '韩国': '🇰🇷',
    '英国': '🇬🇧', '法国': '🇫🇷', '德国': '🇩🇪', '意大利': '🇮🇹',
    '西班牙': '🇪🇸', '葡萄牙': '🇵🇹', '荷兰': '🇳🇱', '瑞士': '🇨🇭',
    '瑞典': '🇸🇪', '挪威': '🇳🇴', '丹麦': '🇩🇰', '芬兰': '🇫🇮',
    '俄罗斯': '🇷🇺', '澳大利亚': '🇦🇺', '新西兰': '🇳🇿', '加拿大': '🇨🇦',
    '巴西': '🇧🇷', '阿根廷': '🇦🇷', '墨西哥': '🇲🇽', '印度': '🇮🇳',
    '泰国': '🇹🇭', '越南': '🇻🇳', '新加坡': '🇸🇬', '马来西亚': '🇲🇾',
    '印度尼西亚': '🇮🇩', '菲律宾': '🇵🇭', '土耳其': '🇹🇷', '阿联酋': '🇦🇪',
    '沙特': '🇸🇦', '南非': '🇿🇦', '埃及': '🇪🇬', '希腊': '🇬🇷',
    '爱尔兰': '🇮🇪', '波兰': '🇵🇱', '捷克': '🇨🇿', '奥地利': '🇦🇹',
    '比利时': '🇧🇪', '匈牙利': '🇭🇺',
    '尼日利亚': '🇳🇬', '乌克兰': '🇺🇦', '波兰': '🇵🇱', '捷克': '🇨🇿',
    '斯洛伐克': '🇸🇰', '匈牙利': '🇭🇺', '罗马尼亚': '🇷🇴', '保加利亚': '🇧🇬',
    '塞尔维亚': '🇷🇸', '克罗地亚': '🇭🇷', '斯洛文尼亚': '🇸🇮', '爱沙尼亚': '🇪🇪',
    '拉脱维亚': '🇱🇻', '立陶宛': '🇱🇹', '白俄罗斯': '🇧🇾', '摩尔多瓦': '🇲🇩',
    '格鲁吉亚': '🇬🇪', '亚美尼亚': '🇦🇲', '阿塞拜疆': '🇦🇿', '哈萨克斯坦': '🇰🇿',
    '乌兹别克斯坦': '🇺🇿', '土库曼斯坦': '🇹🇲', '吉尔吉斯斯坦': '🇰🇬', '塔吉克斯坦': '🇹🇯',
    '蒙古': '🇲🇳', '朝鲜': '🇰🇵', '柬埔寨': '🇰🇭', '老挝': '🇱🇦',
    '缅甸': '🇲🇲', '斯里兰卡': '🇱🇰', '巴基斯坦': '🇵🇰', '孟加拉国': '🇧🇩',
    '尼泊尔': '🇳🇵', '不丹': '🇧🇹', '马尔代夫': '🇲🇻', '伊朗': '🇮🇷',
    '伊拉克': '🇮🇶', '科威特': '🇰🇼', '卡塔尔': '🇶🇦', '巴林': '🇧🇭',
    '阿曼': '🇴🇲', '也门': '🇾🇪', '约旦': '🇯🇴', '黎巴嫩': '🇱🇧',
    '叙利亚': '🇸🇾', '以色列': '🇮🇱', '巴勒斯坦': '🇵🇸', '塞浦路斯': '🇨🇾',
    '阿尔及利亚': '🇩🇿', '摩洛哥': '🇲🇦', '突尼斯': '🇹🇳', '利比亚': '🇱🇾',
    '苏丹': '🇸🇩', '埃塞俄比亚': '🇪🇹', '肯尼亚': '🇰🇪', '坦桑尼亚': '🇹🇿',
    '乌干达': '🇺🇬', '卢旺达': '🇷🇼', '刚果': '🇨🇩', '安哥拉': '🇦🇴',
    '纳米比亚': '🇳🇦', '博茨瓦纳': '🇧🇼', '赞比亚': '🇿🇲', '津巴布韦': '🇿🇼',
    '莫桑比克': '🇲🇿', '马达加斯加': '🇲🇬', '毛里求斯': '🇲🇺', '塞舌尔': '🇸🇨',
    '加纳': '🇬🇭', '科特迪瓦': '🇨🇮', '喀麦隆': '🇨🇲', '塞内加尔': '🇸🇳',
    '马里': '🇲🇱', '布基纳法索': '🇧🇫', '尼日尔': '🇳🇪', '乍得': '🇹🇩',
    '中非': '🇨🇫', '加蓬': '🇬🇦', '赤道几内亚': '🇬🇶', '吉布提': '🇩🇯',
    '索马里': '🇸🇴', '厄立特里亚': '🇪🇷', '毛里塔尼亚': '🇲🇷', '冈比亚': '🇬🇲',
    '几内亚': '🇬🇳', '几内亚比绍': '🇬🇼', '塞拉利昂': '🇸🇱', '利比里亚': '🇱🇷',
    '冰岛': '🇮🇸', '马耳他': '🇲🇹', '卢森堡': '🇱🇺', '摩纳哥': '🇲🇨',
    '列支敦士登': '🇱🇮', '安道尔': '🇦🇩', '圣马力诺': '🇸🇲', '梵蒂冈': '🇻🇦',
    '古巴': '🇨🇺', '牙买加': '🇯🇲', '海地': '🇭🇹', '多米尼加': '🇩🇴',
    '波多黎各': '🇵🇷', '巴哈马': '🇧🇸', '特立尼达和多巴哥': '🇹🇹', '巴巴多斯': '🇧🇧',
    '圣卢西亚': '🇱🇨', '格林纳达': '🇬🇩', '安提瓜和巴布达': '🇦🇬', '圣基茨和尼维斯': '🇰🇳',
    '哥伦比亚': '🇨🇴', '委内瑞拉': '🇻🇪', '厄瓜多尔': '🇪🇨', '秘鲁': '🇵🇪',
    '玻利维亚': '🇧🇴', '巴拉圭': '🇵🇾', '乌拉圭': '🇺🇾', '圭亚那': '🇬🇾',
    '苏里南': '🇸🇷', '法属圭亚那': '🇬🇫', '斐济': '🇫🇯', '巴布亚新几内亚': '🇵🇬',
    '所罗门群岛': '🇸🇧', '瓦努阿图': '🇻🇺', '萨摩亚': '🇼🇸', '汤加': '🇹🇴',
    '密克罗尼西亚': '🇫🇲', '马绍尔群岛': '🇲🇭', '帕劳': '🇵🇼', '瑙鲁': '🇳🇷',
    '图瓦卢': '🇹🇻', '基里巴斯': '🇰🇮',

    # 英文名称
    'china': '🇨🇳', 'usa': '🇺🇸', 'japan': '🇯🇵', 'korea': '🇰🇷',
    'uk': '🇬🇧', 'france': '🇫🇷', 'germany': '🇩🇪', 'italy': '🇮🇹',
    'spain': '🇪🇸', 'portugal': '🇵🇹', 'netherlands': '🇳🇱', 'switzerland': '🇨🇭',
    'sweden': '🇸🇪', 'norway': '🇳🇴', 'denmark': '🇩🇰', 'finland': '🇫🇮',
    'russia': '🇷🇺', 'australia': '🇦🇺', 'new zealand': '🇳🇿', 'canada': '🇨🇦',
    'brazil': '🇧🇷', 'argentina': '🇦🇷', 'mexico': '🇲🇽', 'india': '🇮🇳',
    'thailand': '🇹🇭', 'vietnam': '🇻🇳', 'singapore': '🇸🇬', 'malaysia': '🇲🇾',
    'indonesia': '🇮🇩', 'philippines': '🇵🇭', 'turkey': '🇹🇷', 'uae': '🇦🇪',
    'saudi': '🇸🇦', 'south africa': '🇿🇦', 'egypt': '🇪🇬', 'greece': '🇬🇷',
    'ireland': '🇮🇪', 'poland': '🇵🇱', 'czech': '🇨🇿', 'austria': '🇦🇹',
    'belgium': '🇧🇪', 'hungary': '🇭🇺',
    'nigeria': '🇳🇬', 'ukraine': '🇺🇦', 'poland': '🇵🇱', 'czech': '🇨🇿',
    'slovakia': '🇸🇰', 'hungary': '🇭🇺', 'romania': '🇷🇴', 'bulgaria': '🇧🇬',
    'serbia': '🇷🇸', 'croatia': '🇭🇷', 'slovenia': '🇸🇮', 'estonia': '🇪🇪',
    'latvia': '🇱🇻', 'lithuania': '🇱🇹', 'belarus': '🇧🇾', 'moldova': '🇲🇩',
    'georgia': '🇬🇪', 'armenia': '🇦🇲', 'azerbaijan': '🇦🇿', 'kazakhstan': '🇰🇿',
    'uzbekistan': '🇺🇿', 'turkmenistan': '🇹🇲', 'kyrgyzstan': '🇰🇬', 'tajikistan': '🇹🇯',
    'mongolia': '🇲🇳', 'cambodia': '🇰🇭', 'laos': '🇱🇦', 'myanmar': '🇲🇲',
    'sri lanka': '🇱🇰', 'pakistan': '🇵🇰', 'bangladesh': '🇧🇩', 'nepal': '🇳🇵',
    'bhutan': '🇧🇹', 'maldives': '🇲🇻', 'iran': '🇮🇷', 'iraq': '🇮🇶',
    'kuwait': '🇰🇼', 'qatar': '🇶🇦', 'bahrain': '🇧🇭', 'oman': '🇴🇲',
    'yemen': '🇾🇪', 'jordan': '🇯🇴', 'lebanon': '🇱🇧', 'syria': '🇸🇾',
    'israel': '🇮🇱', 'palestine': '🇵🇸', 'cyprus': '🇨🇾', 'algeria': '🇩🇿',
    'morocco': '🇲🇦', 'tunisia': '🇹🇳', 'libya': '🇱🇾', 'sudan': '🇸🇩',
    'ethiopia': '🇪🇹', 'kenya': '🇰🇪', 'tanzania': '🇹🇿', 'uganda': '🇺🇬',
    'rwanda': '🇷🇼', 'congo': '🇨🇩', 'angola': '🇦🇴', 'namibia': '🇳🇦',
    'botswana': '🇧🇼', 'zambia': '🇿🇲', 'zimbabwe': '🇿🇼', 'mozambique': '🇲🇿',
    'madagascar': '🇲🇬', 'mauritius': '🇲🇺', 'seychelles': '🇸🇨', 'ghana': '🇬🇭',
    'ivory coast': '🇨🇮', 'cameroon': '🇨🇲', 'senegal': '🇸🇳', 'mali': '🇲🇱',
    'burkina faso': '🇧🇫', 'niger': '🇳🇪', 'chad': '🇹🇩', 'central african': '🇨🇫',
    'gabon': '🇬🇦', 'equatorial guinea': '🇬🇶', 'djibouti': '🇩🇯', 'somalia': '🇸🇴',
    'eritrea': '🇪🇷', 'mauritania': '🇲🇷', 'gambia': '🇬🇲', 'guinea': '🇬🇳',
    'guinea-bissau': '🇬🇼', 'sierra leone': '🇸🇱', 'liberia': '🇱🇷', 'iceland': '🇮🇸',
    'malta': '🇲🇹', 'luxembourg': '🇱🇺', 'monaco': '🇲🇨', 'liechtenstein': '🇱🇮',
    'andorra': '🇦🇩', 'san marino': '🇸🇲', 'vatican': '🇻🇦', 'cuba': '🇨🇺',
    'jamaica': '🇯🇲', 'haiti': '🇭🇹', 'dominican': '🇩🇴', 'puerto rico': '🇵🇷',
    'bahamas': '🇧🇸', 'trinidad': '🇹🇹', 'barbados': '🇧🇧', 'saint lucia': '🇱🇨',
    'grenada': '🇬🇩', 'antigua': '🇦🇬', 'colombia': '🇨🇴', 'venezuela': '🇻🇪',
    'ecuador': '🇪🇨', 'peru': '🇵🇪', 'bolivia': '🇧🇴', 'paraguay': '🇵🇾',
    'uruguay': '🇺🇾', 'guyana': '🇬🇾', 'suriname': '🇸🇷', 'fiji': '🇫🇯',
    'papua new guinea': '🇵🇬', 'solomon islands': '🇸🇧', 'vanuatu': '🇻🇺',
    'samoa': '🇼🇸', 'tonga': '🇹🇴', 'micronesia': '🇫🇲', 'marshall islands': '🇲🇭',
    'palau': '🇵🇼', 'nauru': '🇳🇷', 'tuvalu': '🇹🇻', 'kiribati': '🇰🇮',

    # 常用缩写
    'cn': '🇨🇳', 'us': '🇺🇸', 'jp': '🇯🇵', 'kr': '🇰🇷',
    'gb': '🇬🇧', 'fr': '🇫🇷', 'de': '🇩🇪', 'it': '🇮🇹',
    'es': '🇪🇸', 'pt': '🇵🇹', 'nl': '🇳🇱', 'ch': '🇨🇭',
    'se': '🇸🇪', 'no': '🇳🇴', 'dk': '🇩🇰', 'fi': '🇫🇮',
    'ru': '🇷🇺', 'au': '🇦🇺', 'nz': '🇳🇿', 'ca': '🇨🇦',
    'br': '🇧🇷', 'ar': '🇦🇷', 'mx': '🇲🇽', 'in': '🇮🇳',
    'th': '🇹🇭', 'vn': '🇻🇳', 'sg': '🇸🇬', 'my': '🇲🇾',
    'id': '🇮🇩', 'ph': '🇵🇭', 'tr': '🇹🇷', 'ae': '🇦🇪',
    'sa': '🇸🇦', 'za': '🇿🇦', 'eg': '🇪🇬', 'gr': '🇬🇷',
    'ie': '🇮🇪', 'pl': '🇵🇱', 'cz': '🇨🇿', 'at': '🇦🇹',
    'be': '🇧🇪', 'hu': '🇭🇺',
    'ng': '🇳🇬', 'ua': '🇺🇦', 'pl': '🇵🇱', 'cz': '🇨🇿',
    'sk': '🇸🇰', 'hu': '🇭🇺', 'ro': '🇷🇴', 'bg': '🇧🇬',
    'rs': '🇷🇸', 'hr': '🇭🇷', 'si': '🇸🇮', 'ee': '🇪🇪',
    'lv': '🇱🇻', 'lt': '🇱🇹', 'by': '🇧🇾', 'md': '🇲🇩',
    'ge': '🇬🇪', 'am': '🇦🇲', 'az': '🇦🇿', 'kz': '🇰🇿',
    'uz': '🇺🇿', 'tm': '🇹🇲', 'kg': '🇰🇬', 'tj': '🇹🇯',
    'mn': '🇲🇳', 'kh': '🇰🇭', 'la': '🇱🇦', 'mm': '🇲🇲',
    'lk': '🇱🇰', 'pk': '🇵🇰', 'bd': '🇧🇩', 'np': '🇳🇵',
    'bt': '🇧🇹', 'mv': '🇲🇻', 'ir': '🇮🇷', 'iq': '🇮🇶',
    'kw': '🇰🇼', 'qa': '🇶🇦', 'bh': '🇧🇭', 'om': '🇴🇲',
    'ye': '🇾🇪', 'jo': '🇯🇴', 'lb': '🇱🇧', 'sy': '🇸🇾',
    'il': '🇮🇱', 'ps': '🇵🇸', 'cy': '🇨🇾', 'dz': '🇩🇿',
    'ma': '🇲🇦', 'tn': '🇹🇳', 'ly': '🇱🇾', 'sd': '🇸🇩',
    'et': '🇪🇹', 'ke': '🇰🇪', 'tz': '🇹🇿', 'ug': '🇺🇬',
    'rw': '🇷🇼', 'cd': '🇨🇩', 'ao': '🇦🇴', 'na': '🇳🇦',
    'bw': '🇧🇼', 'zm': '🇿🇲', 'zw': '🇿🇼', 'mz': '🇲🇿',
    'mg': '🇲🇬', 'mu': '🇲🇺', 'sc': '🇸🇨', 'gh': '🇬🇭',
    'ci': '🇨🇮', 'cm': '🇨🇲', 'sn': '🇸🇳', 'ml': '🇲🇱',
    'bf': '🇧🇫', 'ne': '🇳🇪', 'td': '🇹🇩', 'cf': '🇨🇫',
    'ga': '🇬🇦', 'gq': '🇬🇶', 'dj': '🇩🇯', 'so': '🇸🇴',
    'er': '🇪🇷', 'mr': '🇲🇷', 'gm': '🇬🇲', 'gn': '🇬🇳',
    'gw': '🇬🇼', 'sl': '🇸🇱', 'lr': '🇱🇷', 'is': '🇮🇸',
    'mt': '🇲🇹', 'lu': '🇱🇺', 'mc': '🇲🇨', 'li': '🇱🇮',
    'ad': '🇦🇩', 'sm': '🇸🇲', 'va': '🇻🇦', 'cu': '🇨🇺',
    'jm': '🇯🇲', 'ht': '🇭🇹', 'do': '🇩🇴', 'pr': '🇵🇷',
    'bs': '🇧🇸', 'tt': '🇹🇹', 'bb': '🇧🇧', 'lc': '🇱🇨',
    'gd': '🇬🇩', 'ag': '🇦🇬', 'co': '🇨🇴', 've': '🇻🇪',
    'ec': '🇪🇨', 'pe': '🇵🇪', 'bo': '🇧🇴', 'py': '🇵🇾',
    'uy': '🇺🇾', 'gy': '🇬🇾', 'sr': '🇸🇷', 'fj': '🇫🇯',
    'pg': '🇵🇬', 'sb': '🇸🇧', 'vu': '🇻🇺', 'ws': '🇼🇸',
    'to': '🇹🇴', 'fm': '🇫🇲', 'mh': '🇲🇭', 'pw': '🇵🇼',
    'nr': '🇳🇷', 'tv': '🇹🇻', 'ki': '🇰🇮',
}

def get_category_with_flag(category: str) -> str:
    """获取带国旗的类别名称"""
    if not category:
        return category

    category_lower = category.lower().strip()

    # 直接匹配
    if category_lower in COUNTRY_FLAGS:
        return f"{COUNTRY_FLAGS[category_lower]} {category}"

    # 尝试匹配部分（如"德国柏林" -> "德国"）
    for country, flag in COUNTRY_FLAGS.items():
        if country in category_lower or category_lower in country:
            return f"{flag} {category}"

    # 没有匹配到，返回原名称
    return category

def safe_escape_markdown(text: str) -> str:
    """转义 Markdown 特殊字符，防止报错"""
    if not text:
        return text
    # 需要转义的字符：_ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

class Calculator:
    """安全计算器类"""

    # 允许的数学函数
    MATH_FUNCTIONS = {
        'sqrt': math.sqrt,
        'sin': math.sin,
        'cos': math.cos,
        'tan': math.tan,
        'asin': math.asin,
        'acos': math.acos,
        'atan': math.atan,
        'log': math.log,
        'log10': math.log10,
        'exp': math.exp,
        'abs': abs,
        'round': round,
        'floor': math.floor,
        'ceil': math.ceil,
        'pi': math.pi,
        'e': math.e,
    }

    @staticmethod
    def safe_eval(expr: str):
        """安全计算表达式"""
        try:
            # 预处理：替换 ^ 为 **
            expr = expr.replace('^', '**')

            # 创建安全的命名空间
            safe_dict = Calculator.MATH_FUNCTIONS.copy()
            safe_dict['__builtins__'] = {}

            # 计算
            result = eval(expr, {"__builtins__": {}}, safe_dict)

            return float(result)
        except:
            return None

    @staticmethod
    def format_result(result: float) -> str:
        """格式化结果"""
        if result.is_integer():
            return str(int(result))
        else:
            # 保留适当的小数位数
            s = f"{result:.6f}".rstrip('0').rstrip('.')
            return s


# 🔥 添加上标转换函数
def superscript_number(n) -> str:
    """将数字转换为上标形式，支持整数、小数和负数"""
    superscripts = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '.': '·',   # 小数点用中点代替
        '-': '⁻'    # 负号用上标负号
    }

    s = str(n)
    result = []
    for c in s:
        if c in superscripts:
            result.append(superscripts[c])
        else:
            result.append(c)
    return ''.join(result)


def format_fee_info(fee_rate: float, exchange_rate: float) -> str:
    """格式化手续费和汇率显示，如 ⁵/7.2 或 ¹¹/7.2"""
    # 处理整数：5.0 显示为 5，不显示 .0
    if fee_rate == int(fee_rate):
        fee_display = int(fee_rate)
    else:
        fee_display = fee_rate

    fee_sup = superscript_number(fee_display)
    return f"{fee_sup}/{exchange_rate:.2f}"


# 状态定义
ACCOUNTING_DATE_SELECT = 1
ACCOUNTING_CONFIRM_CLEAR = 2
ACCOUNTING_CONFIRM_CLEAR_ALL = 3


class AccountingManager:
    """记账管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @contextmanager
    def _get_conn(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
        try:
            yield conn
        finally:
            conn.close()

    def init_tables(self):
        """初始化记账相关的表"""
        with self._get_conn() as conn:
            c = conn.cursor()

            # 群组配置表
            c.execute("""
                CREATE TABLE IF NOT EXISTS group_accounting_config (
                    group_id TEXT PRIMARY KEY,
                    fee_rate REAL DEFAULT 0.0,
                    exchange_rate REAL DEFAULT 1.0,
                    per_transaction_fee REAL DEFAULT 0.0,
                    session_id TEXT,
                    session_start_time INTEGER DEFAULT 0,
                    session_end_time INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    updated_at INTEGER DEFAULT 0
                )
            """)

            # 记账记录表（添加 category 字段）
            c.execute("""
                CREATE TABLE IF NOT EXISTS accounting_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    record_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    amount_usdt REAL NOT NULL,
                    description TEXT,
                    category TEXT DEFAULT '',
                    created_at INTEGER NOT NULL,
                    date TEXT NOT NULL
                )
            """)
            # ========== 数据库迁移 ==========
            # 1. 添加 category 字段
            try:
                c.execute("SELECT category FROM accounting_records LIMIT 1")
            except sqlite3.OperationalError:
                c.execute("ALTER TABLE accounting_records ADD COLUMN category TEXT DEFAULT ''")
                logger.info("✅ 已添加 category 字段到 accounting_records 表")

            # 2. 添加 rate 字段（放在这里！）
            try:
                c.execute("SELECT rate FROM accounting_records LIMIT 1")
            except sqlite3.OperationalError:
                c.execute("ALTER TABLE accounting_records ADD COLUMN rate REAL DEFAULT 0")
                logger.info("✅ 已添加 rate 字段到 accounting_records 表")

            # 3. 🔥 添加 fee_rate 字段（保存当时的手续费率）
            try:
                c.execute("SELECT fee_rate FROM accounting_records LIMIT 1")
            except sqlite3.OperationalError:
                c.execute("ALTER TABLE accounting_records ADD COLUMN fee_rate REAL DEFAULT 0")
                logger.info("✅ 已添加 fee_rate 字段到 accounting_records 表")

            # 2. 添加索引（如果不存在）
            c.execute("CREATE INDEX IF NOT EXISTS idx_records_group_id ON accounting_records(group_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_records_session_id ON accounting_records(session_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_records_date ON accounting_records(date)")

            logger.info("✅ 数据库表结构检查完成")

            # 已结束的会话表
            c.execute("""
                CREATE TABLE IF NOT EXISTS accounting_sessions (
                    session_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    fee_rate REAL DEFAULT 0.0,
                    exchange_rate REAL DEFAULT 1.0
                )
            """)

            # 添加用户追踪表
            c.execute("""
                CREATE TABLE IF NOT EXISTS group_users (
                    group_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    last_seen INTEGER NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                )
            """)

            conn.commit()

    def init_query_tables(self):
        """初始化地址查询记录表"""
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS address_queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    address TEXT NOT NULL,
                    chain_type TEXT NOT NULL,
                    query_time INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    balance REAL,
                    UNIQUE(group_id, address)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS address_query_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    query_time INTEGER NOT NULL,
                    balance REAL
                )
            """)
            conn.commit()
            logger.info("✅ 地址查询表初始化完成")

    def get_or_create_session(self, group_id: str) -> Dict:
        """获取或创建当前会话"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()

                c.execute("""
                    SELECT fee_rate, exchange_rate, per_transaction_fee, session_id, session_start_time, is_active
                    FROM group_accounting_config 
                    WHERE group_id = ? AND is_active = 1
                """, (group_id,))
                row = c.fetchone()

                if row:
                    return {
                        'session_id': row[3],
                        'fee_rate': row[0],
                        'exchange_rate': row[1],
                        'per_transaction_fee': row[2] if row[2] is not None else 0.0,
                        'start_time': row[4],
                        'is_active': True
                    }

                now = int(time.time())
                session_id = f"{group_id}_{now}"

                c.execute("DELETE FROM group_accounting_config WHERE group_id = ?", (group_id,))

                c.execute("""
                    INSERT INTO group_accounting_config 
                    (group_id, fee_rate, exchange_rate, per_transaction_fee, session_id, session_start_time, is_active, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (group_id, 0.0, 1.0, 0.0, session_id, now, now))

                conn.commit()

                return {
                    'session_id': session_id,
                    'fee_rate': 0.0,
                    'exchange_rate': 1.0,
                    'start_time': now,
                    'is_active': True
                }
        except Exception as e:
            logger.error(f"获取/创建会话失败: {e}")
            return {
                'session_id': f"{group_id}_{int(time.time())}",
                'fee_rate': 0.0,
                'exchange_rate': 1.0,
                'start_time': int(time.time()),
                'is_active': True
            }

    def end_session(self, group_id: str) -> Optional[Dict]:
        """结束当前会话，并按自然日分割账单"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                now = int(time.time())

                c.execute("""
                    SELECT session_id, fee_rate, exchange_rate, session_start_time
                    FROM group_accounting_config 
                    WHERE group_id = ? AND is_active = 1
                """, (group_id,))
                row = c.fetchone()

                if not row:
                    return None

                old_session_id, fee_rate, exchange_rate, start_time = row

                # 获取所有记录，按日期分组
                c.execute("""
                    SELECT date, COUNT(*), 
                           SUM(CASE WHEN record_type = 'income' THEN amount_usdt ELSE 0 END) as income_usdt,
                           SUM(CASE WHEN record_type = 'expense' THEN amount_usdt ELSE 0 END) as expense_usdt
                    FROM accounting_records
                    WHERE group_id = ? AND session_id = ?
                    GROUP BY date
                    ORDER BY date
                """, (group_id, old_session_id))
                date_groups = c.fetchall()

                # 如果没有记录，直接结束
                if not date_groups:
                    c.execute("""
                        UPDATE group_accounting_config 
                        SET is_active = 0, session_end_time = ?, updated_at = ?
                        WHERE group_id = ? AND is_active = 1
                    """, (now, now, group_id))
                    conn.commit()
                    return None

                # 为每个日期创建独立的会话记录
                for date_group in date_groups:
                    date_str = date_group[0]
                    income_usdt = date_group[2] or 0
                    expense_usdt = date_group[3] or 0

                    # 为该日期的记录创建新的 session_id
                    new_session_id = f"{old_session_id}_{date_str}"

                    # 获取该日期的开始和结束时间
                    c.execute("""
                        SELECT MIN(created_at), MAX(created_at)
                        FROM accounting_records
                        WHERE group_id = ? AND session_id = ? AND date = ?
                    """, (group_id, old_session_id, date_str))
                    time_range = c.fetchone()
                    day_start = time_range[0] or start_time
                    day_end = time_range[1] or now

                    # 插入该日期的会话记录
                    c.execute("""
                        INSERT INTO accounting_sessions 
                        (session_id, group_id, start_time, end_time, date, fee_rate, exchange_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (new_session_id, group_id, day_start, day_end, date_str, fee_rate, exchange_rate))

                # 更新原会话为已结束（但实际数据已按日期拆分）
                c.execute("""
                    UPDATE group_accounting_config 
                    SET is_active = 0, session_end_time = ?, updated_at = ?
                    WHERE group_id = ? AND is_active = 1
                """, (now, now, group_id))

                conn.commit()

                # 计算总的统计（所有日期的总和）
                total_income_usdt = sum(g[2] for g in date_groups)
                total_expense_usdt = sum(g[3] for g in date_groups)

                return {
                    'session_id': old_session_id,
                    'fee_rate': fee_rate,
                    'exchange_rate': exchange_rate,
                    'income_usdt': total_income_usdt,
                    'expense_usdt': total_expense_usdt
                }
        except Exception as e:
            logger.error(f"结束会话失败: {e}")
            return None

    def _get_records_by_condition(self, group_id: str, session_id: str = None, 
                                    date: str = None) -> List[Dict]:
        """通用记录查询方法（关联用户表获取昵称）"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()

                # 关联查询 group_users 表获取用户昵称
                query = """
                    SELECT r.record_type, r.amount, r.amount_usdt, r.description, r.created_at, 
                           r.username, r.category, r.user_id, u.first_name, r.rate, r.fee_rate
                    FROM accounting_records r
                    LEFT JOIN group_users u ON r.group_id = u.group_id AND r.user_id = u.user_id
                    WHERE r.group_id = ?
                """
                params = [group_id]

                # 第 451 行附近，需要修改
                if session_id:
                    query += " AND r.session_id = ?"  # 改为 r.session_id
                    params.append(session_id)
                if date:
                    query += " AND r.date = ?"  # 改为 r.date
                    params.append(date)

                query += " ORDER BY r.created_at ASC"
                c.execute(query, params)
                rows = c.fetchall()

                records = []
                for row in rows:
                    record = {
                        'type': row[0],
                        'amount': row[1],
                        'amount_usdt': row[2],
                        'description': row[3],
                        'created_at': row[4],
                        'username': row[5],
                        'category': row[6],
                        'user_id': row[7],
                        'rate': row[9] if len(row) > 9 else 0,
                        'fee_rate': row[10] if len(row) > 10 else 0,
                    }
                    # 设置显示名称（优先昵称，其次用户名，最后显示用户ID）
                    first_name = row[8] if len(row) > 8 else None
                    if first_name:
                        record['display_name'] = first_name
                    elif row[5]:
                        record['display_name'] = row[5]
                    else:
                        record['display_name'] = f"用户{row[7]}"
                    records.append(record)
                return records
        except Exception as e:
            logger.error(f"获取记录失败: {e}")
            return []

    def get_current_records(self, group_id: str) -> List[Dict]:
        """获取当前会话记录"""
        session = self.get_or_create_session(group_id)
        return self._get_records_by_condition(group_id, session_id=session['session_id'])

    def get_today_records(self, group_id: str) -> List[Dict]:
        """获取今日所有记录"""
        today = get_today_beijing()
        return self._get_records_by_condition(group_id, date=today)

    def get_total_records(self, group_id: str) -> List[Dict]:
        """获取所有记录"""
        return self._get_records_by_condition(group_id)

    def get_records_by_date(self, group_id: str, date_str: str) -> List[Dict]:
        """获取指定日期的所有记录"""
        return self._get_records_by_condition(group_id, date=date_str)

    def get_current_stats(self, group_id: str) -> Dict:
        """获取当前会话统计"""
        try:
            session = self.get_or_create_session(group_id)

            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                    FROM accounting_records
                    WHERE group_id = ? AND session_id = ?
                    GROUP BY record_type
                """, (group_id, session['session_id']))
                rows = c.fetchall()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            return {
                'fee_rate': session['fee_rate'],
                'exchange_rate': session['exchange_rate'],
                'per_transaction_fee': session.get('per_transaction_fee', 0),
                'income_total': income_total,
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            logger.error(f"获取当前统计失败: {e}")
            return {
                'fee_rate': 0,
                'exchange_rate': 1,
                'income_total': 0,
                'income_usdt': 0,
                'income_count': 0,
                'expense_total': 0,
                'expense_usdt': 0,
                'expense_count': 0,
                'pending_usdt': 0
            }

    def add_record(self, group_id: str, user_id: int, username: str, 
                   record_type: str, amount: float, description: str = "",
                   category: str = "", temp_rate: float = None) -> bool:
        """添加记账记录"""
        try:
            session = self.get_or_create_session(group_id)

            if record_type == 'income':
                # 使用临时汇率或当前汇率
                actual_rate = temp_rate if temp_rate is not None else session['exchange_rate']
                # 1. 先扣除手续费
                after_fee = amount * (1 - session['fee_rate'] / 100)
                # 2. 加上单笔费用
                per_fee = session.get('per_transaction_fee', 0)
                with_fee = after_fee + per_fee
                # 3. 除以汇率
                amount_usdt = with_fee / actual_rate

                # 🔥 保存当前手续费率到记录中
                current_fee_rate = session['fee_rate']

                # 调试日志
                logger.info(f"[记账计算] 金额: {amount}, 手续费率: {session['fee_rate']}%, "
                           f"单笔费用: {per_fee}, 汇率: {actual_rate}, 结果: {amount_usdt:.4f} USDT")
            else:
                amount_usdt = amount
                actual_rate = 0  # 出款不保存汇率
                current_fee_rate = 0

            now = int(time.time())
            date_str = beijing_time(now).strftime('%Y-%m-%d')

            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO accounting_records 
                    (group_id, session_id, user_id, username, record_type, amount, amount_usdt, 
                     description, category, rate, fee_rate, created_at, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (group_id, session['session_id'], user_id, username, record_type, amount, 
                      amount_usdt, description, category, actual_rate, current_fee_rate, now, date_str))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"添加记录失败: {e}")
            return False

    def set_fee_rate(self, group_id: str, rate: float) -> bool:
        """设置手续费率"""
        try:
            # 确保会话存在
            self.get_or_create_session(group_id)

            with self._get_conn() as conn:
                c = conn.cursor()
                now = int(time.time())
                c.execute("""
                    UPDATE group_accounting_config 
                    SET fee_rate = ?, updated_at = ?
                    WHERE group_id = ? AND is_active = 1
                """, (rate, now, group_id))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"设置费率失败: {e}")
            return False

    def set_exchange_rate(self, group_id: str, rate: float) -> bool:
        """设置汇率"""
        try:
            # 确保会话存在
            self.get_or_create_session(group_id)

            with self._get_conn() as conn:
                c = conn.cursor()
                now = int(time.time())
                c.execute("""
                    UPDATE group_accounting_config 
                    SET exchange_rate = ?, updated_at = ?
                    WHERE group_id = ? AND is_active = 1
                """, (rate, now, group_id))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"设置汇率失败: {e}")
            return False

    def set_per_transaction_fee(self, group_id: str, fee: float) -> bool:
        """设置单笔费用"""
        try:
            self.get_or_create_session(group_id)
            with self._get_conn() as conn:
                c = conn.cursor()
                now = int(time.time())
                c.execute("""
                    UPDATE group_accounting_config 
                    SET per_transaction_fee = ?, updated_at = ?
                    WHERE group_id = ? AND is_active = 1
                """, (fee, now, group_id))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"设置单笔费用失败: {e}")
            return False

    def get_today_stats(self, group_id: str) -> Dict:
        """获取今日统计"""
        today = get_today_beijing()

        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                    FROM accounting_records
                    WHERE group_id = ? AND date = ?
                    GROUP BY record_type
                """, (group_id, today))
                rows = c.fetchall()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            # 确保会话存在
            self.get_or_create_session(group_id)

            session = self.get_or_create_session(group_id)

            return {
                'fee_rate': session['fee_rate'],
                'exchange_rate': session['exchange_rate'],
                'per_transaction_fee': session.get('per_transaction_fee', 0),
                'income_total': income_total,
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            logger.error(f"获取今日统计失败: {e}")
            return self.get_current_stats(group_id)

    def get_total_stats(self, group_id: str) -> Dict:
        """获取总计统计"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                    FROM accounting_records
                    WHERE group_id = ?
                    GROUP BY record_type
                """, (group_id,))
                rows = c.fetchall()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            session = self.get_or_create_session(group_id)

            return {
                'fee_rate': session['fee_rate'],
                'exchange_rate': session['exchange_rate'],
                'per_transaction_fee': session.get('per_transaction_fee', 0),
                'income_total': income_total,
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            logger.error(f"获取总计统计失败: {e}")
            return self.get_current_stats(group_id)

    def get_sessions_by_date(self, group_id: str) -> List[Dict]:
        """获取按日期分组的历史会话"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT DISTINCT date
                    FROM accounting_sessions
                    WHERE group_id = ?
                    ORDER BY date DESC
                    LIMIT 30
                """, (group_id,))
                rows = c.fetchall()

            return [{'date': row[0]} for row in rows]
        except Exception as e:
            logger.error(f"获取历史日期失败: {e}")
            return []

    def get_stats_by_date(self, group_id: str, date_str: str) -> Dict:
        """获取指定日期的统计"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT record_type, SUM(amount), SUM(amount_usdt), COUNT(*)
                    FROM accounting_records
                    WHERE group_id = ? AND date = ?
                    GROUP BY record_type
                """, (group_id, date_str))
                rows = c.fetchall()

            income_total = 0
            income_usdt = 0
            income_count = 0
            expense_total = 0
            expense_usdt = 0
            expense_count = 0

            for row in rows:
                if row[0] == 'income':
                    income_total = row[1] or 0
                    income_usdt = row[2] or 0
                    income_count = row[3] or 0
                else:
                    expense_total = row[1] or 0
                    expense_usdt = row[2] or 0
                    expense_count = row[3] or 0

            return {
                'income_total': income_total,
                'income_usdt': income_usdt,
                'income_count': income_count,
                'expense_total': expense_total,
                'expense_usdt': expense_usdt,
                'expense_count': expense_count,
                'pending_usdt': income_usdt - expense_usdt
            }
        except Exception as e:
            logger.error(f"获取日期统计失败: {e}")
            return {
                'income_total': 0,
                'income_usdt': 0,
                'income_count': 0,
                'expense_total': 0,
                'expense_usdt': 0,
                'expense_count': 0,
                'pending_usdt': 0
            }

    def clear_current_session(self, group_id: str) -> bool:
        """清空当前会话"""
        try:
            session = self.get_or_create_session(group_id)
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM accounting_records WHERE group_id = ? AND session_id = ?", 
                          (group_id, session['session_id']))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"清空记录失败: {e}")
            return False

    def clear_all_records(self, group_id: str) -> bool:
        """清空群组的所有账单记录（包括当前会话和历史会话）"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM accounting_records WHERE group_id = ?", (group_id,))
                c.execute("DELETE FROM accounting_sessions WHERE group_id = ?", (group_id,))
                # 🔥 修改：同时重置费率、汇率、单笔费用
                c.execute("""
                    UPDATE group_accounting_config 
                    SET fee_rate = 0, exchange_rate = 1, per_transaction_fee = 0, updated_at = ?
                    WHERE group_id = ?
                """, (int(time.time()), group_id))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"清空所有记录失败: {e}")
            return False

    def update_user_info(self, group_id: str, user_id: int, username: str, 
                         first_name: str, last_name: str = "") -> Tuple[bool, str, str, str]:
        """
        更新或添加用户信息
        返回: (是否有变更, 旧显示名称, 新显示名称, 变更类型)
        """
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                now = int(time.time())

                c.execute("""
                    SELECT username, first_name, last_name
                    FROM group_users
                    WHERE group_id = ? AND user_id = ?
                """, (group_id, user_id))
                old = c.fetchone()

                old_display_name = None
                change_type = None

                if old:
                    old_username = old[0] or ""
                    old_first_name = old[1] or ""
                    if old_username:
                        old_display_name = f"{old_first_name} (@{old_username})"
                    else:
                        old_display_name = old_first_name

                if username:
                    new_display_name = f"{first_name} (@{username})"
                else:
                    new_display_name = first_name

                c.execute("""
                    INSERT OR REPLACE INTO group_users 
                    (group_id, user_id, username, first_name, last_name, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (group_id, user_id, username or "", first_name or "", last_name or "", now))

                conn.commit()

                if old:
                    old_username = old[0] or ""
                    old_first_name = old[1] or ""
                    if old_username != (username or "") and old_first_name != (first_name or ""):
                        change_type = "昵称和用户名"
                    elif old_username != (username or ""):
                        change_type = "用户名"
                    elif old_first_name != (first_name or ""):
                        change_type = "昵称"

                if change_type:
                    return True, old_display_name or first_name, new_display_name, change_type

                return False, "", "", ""
        except Exception as e:
            logger.error(f"更新用户信息失败: {e}")
            return False, "", "", ""

    def cleanup_expired_groups(self, days: int = 7):
        """清理过期群组数据（超过指定天数没有活动的群组）"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                # 计算过期时间戳
                expire_time = int(time.time()) - (days * 24 * 3600)

                # 获取过期群组
                c.execute("""
                    SELECT group_id FROM group_accounting_config 
                    WHERE updated_at < ? AND is_active = 0
                """, (expire_time,))
                expired_groups = c.fetchall()

                for group in expired_groups:
                    group_id = group[0]
                    # 删除相关记录
                    c.execute("DELETE FROM accounting_records WHERE group_id = ?", (group_id,))
                    c.execute("DELETE FROM accounting_sessions WHERE group_id = ?", (group_id,))
                    c.execute("DELETE FROM group_accounting_config WHERE group_id = ?", (group_id,))
                    c.execute("DELETE FROM group_users WHERE group_id = ?", (group_id,))

                conn.commit()
                logger.info(f"清理了 {len(expired_groups)} 个过期群组的数据")
                return len(expired_groups)
        except Exception as e:
            logger.error(f"清理过期群组失败: {e}")
            return 0

    def remove_last_record(self, group_id: str) -> Tuple[bool, Dict]:
        """移除当前会话中的最后一条记录
        返回: (是否成功, 被移除的记录信息)
        """
        try:
            session = self.get_or_create_session(group_id)

            with self._get_conn() as conn:
                c = conn.cursor()

                # 获取当前会话中的最后一条记录
                c.execute("""
                    SELECT id, record_type, amount, amount_usdt, description, category, rate, created_at, username, user_id
                    FROM accounting_records
                    WHERE group_id = ? AND session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                """, (group_id, session['session_id']))

                row = c.fetchone()

                if not row:
                    return False, {"error": "没有可以移除的记录"}

                # 保存记录信息用于返回
                removed_record = {
                    'id': row[0],
                    'type': row[1],
                    'amount': row[2],
                    'amount_usdt': row[3],
                    'description': row[4],
                    'category': row[5],
                    'rate': row[6],
                    'created_at': row[7],
                    'username': row[8],
                    'user_id': row[9]
                }

                # 删除记录
                c.execute("DELETE FROM accounting_records WHERE id = ?", (row[0],))
                conn.commit()

                return True, removed_record
        except Exception as e:
            logger.error(f"移除最后记录失败: {e}")
            return False, {"error": str(e)}

    # ========== USDT 地址查询相关方法 ==========

    def record_address_query(self, group_id: str, address: str, chain_type: str, 
                              user_id: int, username: str, balance: float):
        """记录地址查询次数"""
        try:
            now = int(time.time())
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO address_queries (group_id, address, chain_type, query_time, user_id, username, balance)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(group_id, address) DO UPDATE SET
                        query_time = excluded.query_time,
                        user_id = excluded.user_id,
                        username = excluded.username,
                        balance = excluded.balance
                """, (group_id, address, chain_type, now, user_id, username, balance))
                c.execute("""
                    INSERT INTO address_query_log (address, query_time, balance)
                    VALUES (?, ?, ?)
                """, (address, now, balance))
                conn.commit()
        except Exception as e:
            logger.error(f"记录地址查询失败: {e}")

    def get_address_stats(self, address: str) -> dict:
        """获取地址被查询的统计信息"""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM address_query_log WHERE address = ?", (address,))
                total_queries = c.fetchone()[0]
                c.execute("SELECT MIN(query_time) FROM address_query_log WHERE address = ?", (address,))
                first_query = c.fetchone()[0]
                c.execute("SELECT MAX(query_time) FROM address_query_log WHERE address = ?", (address,))
                last_query = c.fetchone()[0]
                return {
                    'total_queries': total_queries,
                    'first_query': first_query,
                    'last_query': last_query
                }
        except Exception as e:
            logger.error(f"获取地址统计失败: {e}")
            return {'total_queries': 0, 'first_query': None, 'last_query': None}


# 全局实例
accounting_manager = None

def init_accounting(db_path: str):
    """初始化记账模块"""
    global accounting_manager
    accounting_manager = AccountingManager(db_path)
    accounting_manager.init_tables()
    accounting_manager.init_query_tables()  # 新增

# ==================== USDT 地址查询函数 ====================

async def query_trc20_balance(address: str) -> dict:
    """查询 TRC20 USDT 余额"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{TRONGRID_API}/v1/accounts/{address}"
            async with session.get(url) as resp:
                data = await resp.json()

            if data.get('data') and len(data['data']) > 0:
                account = data['data'][0]
                trc20_tokens = account.get('trc20', [])
                for token in trc20_tokens:
                    if USDT_CONTRACTS['TRC20'] in token:
                        balance = int(token[USDT_CONTRACTS['TRC20']]) / 10**6
                        return {'balance': balance, 'success': True, 'chain': 'TRC20'}
            return {'balance': 0, 'success': True, 'chain': 'TRC20'}
    except Exception as e:
        logger.error(f"TRC20 查询失败: {e}")
        return {'balance': None, 'success': False, 'error': str(e)}

async def query_erc20_balance(address: str) -> dict:
    """查询 ERC20 USDT 余额"""
    try:
        params = {
            'module': 'account',
            'action': 'tokenbalance',
            'contractaddress': USDT_CONTRACTS['ERC20'],
            'address': address,
            'tag': 'latest',
            'apikey': ETHERSCAN_API_KEY
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(ETHERSCAN_API, params=params) as resp:
                data = await resp.json()

            if data.get('status') == '1':
                balance = int(data.get('result', 0)) / 10**6
                return {'balance': balance, 'success': True, 'chain': 'ERC20'}
            return {'balance': 0, 'success': True, 'chain': 'ERC20'}
    except Exception as e:
        logger.error(f"ERC20 查询失败: {e}")
        return {'balance': None, 'success': False, 'error': str(e)}

def is_valid_address(text: str) -> tuple:
    """检测文本中的 USDT 地址，返回 (是否匹配, 地址, 链类型)"""
    trc20_pattern = r'T[0-9A-Za-z]{33}'
    erc20_pattern = r'0x[0-9a-fA-F]{40}'

    trc20_match = re.search(trc20_pattern, text)
    if trc20_match:
        return True, trc20_match.group(), 'TRC20'

    erc20_match = re.search(erc20_pattern, text)
    if erc20_match:
        return True, erc20_match.group(), 'ERC20'

    return False, None, None


def _format_record_line(record: Dict) -> str:
    """格式化单条记录"""
    dt = beijing_time(record['created_at'])
    time_str = dt.strftime('%H:%M')
    amount = record['amount']
    amount_usdt = record['amount_usdt']
    rate = record.get('rate', 0)
    record_type = record.get('type', '')

    # 只有入款才显示汇率（不加粗）
    rate_info = ""
    if record_type == 'income' and rate > 0:
        if rate == int(rate):
            rate_info = f" /{int(rate)}"
        else:
            rate_info = f" /{rate:.2f}"

    display_name = record.get('display_name', '未知用户')
    user_id = record.get('user_id')

    if user_id:
        mention = f" [{display_name}](tg://user?id={user_id})"
    else:
        mention = f" {display_name}"

    if amount < 0:
        return f"`{time_str} {amount:.2f}{rate_info} = {amount_usdt:.2f} USDT`{mention}"
    else:
        return f"`{time_str} +{amount:.2f}{rate_info} = {amount_usdt:.2f} USDT`{mention}"

# --- 格式化账单函数 ---
def format_bill_message(stats: Dict, records: List[Dict], title: str = "当前账单") -> str:
    """格式化账单消息"""
    message = f"📊 **{title}**\n\n"

    # 分离入款和出款记录
    income_records = [r for r in records if r['type'] == 'income']
    expense_records = [r for r in records if r['type'] == 'expense']

    # ==================== 入款记录 ====================
    if income_records:
        # 按时间倒序排序
        income_records_sorted = sorted(income_records, key=lambda x: x['created_at'], reverse=True)

        # 按备注分组（排除"无备注"）
        categories = {}
        no_category_records = []  # 无备注的记录单独存放

        for r in income_records_sorted:
            category = r.get('category', '') or ''
            if category:
                if category not in categories:
                    categories[category] = []
                categories[category].append(r)
            else:
                no_category_records.append(r)

        total_income_count = len(income_records)
        message += f"📈 **入款 {total_income_count} 笔**\n"

        # 先显示无备注的记录（直接显示，不分组）
        if no_category_records:
            for r in no_category_records[:MAX_DISPLAY_RECORDS]:
                dt = beijing_time(r['created_at'])
                time_str = dt.strftime('%H:%M')
                amount = r['amount']
                amount_usdt = r['amount_usdt']

                # 🔥 使用新的格式：手续费上标 + 汇率
                fee_rate = r.get('fee_rate', 0)  # 而不是 stats.get('fee_rate', 0)
                rate = r.get('rate', 0)
                fee_info = format_fee_info(fee_rate, rate)
                
                operator = r.get('display_name', '未知用户')
                safe_operator = safe_escape_markdown(operator)
                user_id = r.get('user_id')

                if user_id:
                    mention = f" [{safe_operator}](tg://user?id={user_id})"
                else:
                    mention = f" {safe_operator}"

                amount_str = f"{amount:+.2f}"
                message += f"  {time_str} {amount_str} {fee_info} = {amount_usdt:.2f} USDT{mention}\n"

            if len(no_category_records) > MAX_DISPLAY_RECORDS:
                message += f"  `... 还有 {len(no_category_records) - MAX_DISPLAY_RECORDS} 条记录`\n"

        # 再显示有备注的分组
        for category, group_records in categories.items():
            group_sorted = sorted(group_records, key=lambda x: x['created_at'], reverse=True)

            # 显示分组标题
            display_category = get_category_with_flag(category)
            message += f"\n{display_category} ({len(group_records)} 笔)\n"

            # 显示该分组下的具体记录
            for r in group_sorted[:MAX_DISPLAY_RECORDS]:
                dt = beijing_time(r['created_at'])
                time_str = dt.strftime('%H:%M')
                amount = r['amount']
                amount_usdt = r['amount_usdt']

                # 🔥 使用新的格式：手续费上标 + 汇率
                fee_rate = r.get('fee_rate', 0)  # 而不是 stats.get('fee_rate', 0)
                rate = r.get('rate', 0)
                fee_info = format_fee_info(fee_rate, rate)
                
                operator = r.get('display_name', '未知用户')
                safe_operator = safe_escape_markdown(operator)
                user_id = r.get('user_id')

                if user_id:
                    mention = f" [{safe_operator}](tg://user?id={user_id})"
                else:
                    mention = f" {safe_operator}"

                amount_str = f"{amount:+.2f}"
                message += f"  {time_str} {amount_str} {fee_info} = {amount_usdt:.2f} USDT{mention}\n"

            # 显示该组小计
            group_total_cny = sum(r['amount'] for r in group_records)
            group_total_usdt = sum(r['amount_usdt'] for r in group_records)
            message += f"  小计：{group_total_cny:.2f} = {group_total_usdt:.2f} USDT\n"

            if len(group_records) > MAX_DISPLAY_RECORDS:
                message += f"  `... 还有 {len(group_records) - MAX_DISPLAY_RECORDS} 条记录`\n"

        message += "\n"
    else:
        message += "📈 **入款 0 笔**\n\n"

    # ==================== 出款记录 ====================
    if expense_records:
        expense_records_sorted = sorted(expense_records, key=lambda x: x['created_at'], reverse=True)
        display_expense = expense_records_sorted[:MAX_DISPLAY_RECORDS]
        total_expense_count = len(expense_records)

        message += f"📉 **出款 {total_expense_count} 笔**\n"
        if total_expense_count > MAX_DISPLAY_RECORDS:
            message += f" (显示最新{MAX_DISPLAY_RECORDS}条)\n"

        for r in display_expense:
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']
            amount_usdt = r['amount_usdt']
            operator = r.get('display_name', '未知用户')
            safe_operator = safe_escape_markdown(operator)
            user_id = r.get('user_id')

            if user_id:
                mention = f" [{safe_operator}](tg://user?id={user_id})"
            else:
                mention = f" {safe_operator}"

            amount_str = f"{amount:+.2f}"
            message += f"  {time_str} {amount_str} = {amount_usdt:.2f} USDT{mention}\n"

        if total_expense_count > MAX_DISPLAY_RECORDS:
            message += f"  `... 还有 {total_expense_count - MAX_DISPLAY_RECORDS} 条记录`\n"
        message += "\n"
    else:
        message += "📉 **出款 0 笔**\n\n"

    # ==================== 入款分组统计（只显示有备注的）====================
    if income_records:
        categories = {}
        for r in income_records:
            category = r.get('category', '') or ''
            if category:
                if category not in categories:
                    categories[category] = {'cny': 0, 'usdt': 0, 'count': 0}
                categories[category]['cny'] += r['amount']
                categories[category]['usdt'] += r['amount_usdt']
                categories[category]['count'] += 1

        if categories:
            message += f"📊 **入款分组统计**\n"
            for category, data in categories.items():
                display_category = get_category_with_flag(category)
                message += f"{display_category}：{data['cny']:.2f} = {data['usdt']:.2f} USDT ({data['count']}笔)\n"
            message += "\n"

    # ==================== 统计信息 ====================
    fee_rate = stats['fee_rate']
    exchange_rate = stats['exchange_rate']
    per_transaction_fee = stats.get('per_transaction_fee', 0)
    total_income_cny = stats['income_total']
    total_income_usdt = stats['income_usdt']
    total_expense_usdt = stats['expense_usdt']
    pending_usdt = total_income_usdt - total_expense_usdt

    message += f"💰 **费率**：{fee_rate}%\n"
    message += f"💱 **汇率**：{exchange_rate}\n"
    message += f"📝 **单笔费用**：{per_transaction_fee} 元\n\n"
    message += f"📊 **总入款**：{total_income_cny:.2f} = {total_income_usdt:.2f} USDT\n"
    message += f"📤 **已下发**：{total_expense_usdt:.2f} USDT\n"

    if title == "总计账单":
        message += f"📋 **总待出款**：{pending_usdt:.2f} USDT"
    else:
        message += f"⏳ **待下发**：{pending_usdt:.2f} USDT"

    return message


# --- 辅助函数 ---
def _is_authorized_in_group(update: Update) -> bool:
    """检查用户是否在群组中有权限"""
    user = update.effective_user
    chat = update.effective_chat
    if not user or chat.type not in ['group', 'supergroup']:
        return False
    return is_authorized(user.id)


# --- 指令处理函数 ---
async def handle_end_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """结束当前账单"""
    chat = update.effective_chat
    user = update.effective_user

    if not is_authorized(user.id):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)

    stats = accounting_manager.get_current_stats(group_id)
    records = accounting_manager.get_current_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text("📭 当前没有账单记录，无需结束")
        return

    final_bill = format_bill_message(stats, records, "结束账单")

    result = accounting_manager.end_session(group_id)

    if result:
        await update.message.reply_text(
            f"✅ **账单已结束并保存！**\n\n{final_bill}\n\n"
            f"💡 提示：费率已重置为0%，汇率已重置为1 = 1 USDT\n"
            f"可使用「设置手续费」和「设置汇率」重新配置",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ 结束账单失败")


async def handle_set_fee(update: Update, context: ContextTypes.DEFAULT_TYPE, rate: float):
    """设置手续费率"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    group_id = str(update.effective_chat.id)

    if accounting_manager.set_fee_rate(group_id, rate):
        # ✅ 只输出成功提示，不输出账单
        try:
            await update.message.reply_text(f"✅ 手续费率已设置为 {rate}%")
        except Exception as e:
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text(f"✅ 手续费率已设置为 {rate}%（网络问题无法确认，请稍后查看）")
            else:
                raise e
    else:
        try:
            await update.message.reply_text("❌ 设置失败，请稍后重试")
        except Exception as e:
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text("⚠️ 设置可能已失败，网络问题无法确认，请稍后重试")
            else:
                raise e


async def handle_set_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE, rate: float):
    """设置汇率"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    group_id = str(update.effective_chat.id)

    if accounting_manager.set_exchange_rate(group_id, rate):
        try:
            await update.message.reply_text(f"✅ 汇率已设置为 {rate}")
        except Exception as e:
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text(f"✅ 汇率已设置为 {rate}（网络问题无法确认，请稍后查看）")
            else:
                raise e
    else:
        try:
            await update.message.reply_text("❌ 设置失败，请稍后重试")
        except Exception as e:
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text("⚠️ 设置可能已失败，网络问题无法确认，请稍后重试")
            else:
                raise e

async def handle_set_per_transaction_fee(update: Update, context: ContextTypes.DEFAULT_TYPE, fee: float):
    """设置单笔费用"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    group_id = str(update.effective_chat.id)

    if accounting_manager.set_per_transaction_fee(group_id, fee):
        try:
            await update.message.reply_text(f"✅ 单笔费用已设置为 {fee} 元")
        except Exception as e:
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text(f"✅ 单笔费用已设置为 {fee} 元（网络问题无法确认，请稍后查看）")
            else:
                raise e
    else:
        try:
            await update.message.reply_text("❌ 设置失败，请稍后重试")
        except Exception as e:
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text("⚠️ 设置可能已失败，网络问题无法确认，请稍后重试")
            else:
                raise e


async def handle_add_income(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                            amount: float, is_correction: bool = False,
                            category: str = "", temp_rate: float = None):
    """添加入款记录（支持修正、备注和临时汇率）"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    chat = update.effective_chat
    user = update.effective_user
    group_id = str(chat.id)
    username = user.username or user.first_name or str(user.id)

    record_amount = -abs(amount) if is_correction else abs(amount)
    desc = "修正入款" if is_correction else "入款"

# 直接调用 add_record，传入 temp_rate
    if accounting_manager.add_record(group_id, user.id, username, 'income', 
                                      record_amount, desc, category, temp_rate):
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")

        prefix = f"✅ 已记录修正入款：-{abs(amount):.2f}" if is_correction else f"✅ 已记录入款：{amount:.2f}"
        if category:
            prefix += f" (分类：{category})"
        if temp_rate:
            prefix += f" (汇率：{temp_rate})"
        try:
            await update.message.reply_text(f"{prefix} \n\n{message}", parse_mode='Markdown')
        except Exception as e:
            # 发送消息失败（网络问题），但记账已成功
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text(f"{prefix}\n\n⚠️ ✅ 记账成功，网络问题无法显示账单，使用「当前账单」查看")
            else:
                raise e
    else:
        await update.message.reply_text("❌ 记录失败，请稍后重试")


async def handle_add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                             amount: float, is_correction: bool = False):
    """添加出款记录（支持修正）"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    chat = update.effective_chat
    user = update.effective_user
    group_id = str(chat.id)
    username = user.username or user.first_name or str(user.id)

    record_amount = -abs(amount) if is_correction else abs(amount)
    desc = "修正出款" if is_correction else "出款"

    if accounting_manager.add_record(group_id, user.id, username, 'expense', record_amount, desc):
        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")

        prefix = f"✅ 已记录修正出款：-{abs(amount):.2f} USDT" if is_correction else f"✅ 已记录出款：{amount:.2f} USDT"
        try:
            await update.message.reply_text(f"{prefix}\n\n{message}", parse_mode='Markdown')
        except Exception as e:
            error_msg = str(e)
            if "ConnectError" in error_msg or "Timeout" in error_msg:
                await update.message.reply_text(f"{prefix}\n\n⚠️ ✅ 记账成功，网络问题无法显示账单，使用「当前账单」查看")
            else:
                raise e
    else:
        await update.message.reply_text("❌ 记录失败，请稍后重试")


async def handle_total_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看总计账单"""
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    stats = accounting_manager.get_total_stats(group_id)
    records = accounting_manager.get_total_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text("📭 暂无账单记录")
        return

    message = format_bill_message(stats, records, "总计账单")
    await update.message.reply_text(message, parse_mode='Markdown')


async def handle_today_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看今日账单"""
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    stats = accounting_manager.get_today_stats(group_id)
    records = accounting_manager.get_today_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text("📭 今日暂无账单记录")
        return

    message = format_bill_message(stats, records, "今日账单")
    await update.message.reply_text(message, parse_mode='Markdown')


async def handle_current_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看当前账单"""
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    stats = accounting_manager.get_current_stats(group_id)
    records = accounting_manager.get_current_records(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text(
            "📭 当前账单为空\n\n"
            "💡 使用以下指令开始记账：\n"
            "  • +金额 - 添加入款\n"
            "  • +金额 备注 - 带分类的入款（如：+1000 德国）\n"
            "  • -金额 - 修正入款\n"
            "  • 下发金额u - 添加出款\n"
            "  • 下发-金额u - 修正出款\n"
            "  • 设置手续费 数字 - 设置手续费率\n"
            "  • 设置汇率 数字 - 设置汇率\n"
            "  • 结束账单 - 结束并保存当前账单"
        )
        return

    message = format_bill_message(stats, records, "当前账单")
    await update.message.reply_text(message, parse_mode='Markdown')


async def handle_query_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查询历史账单（按日期）"""
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ 此功能仅在群组中可用")
        return

    group_id = str(chat.id)
    dates = accounting_manager.get_sessions_by_date(group_id)

    if not dates:
        await update.message.reply_text("📭 暂无历史账单记录")
        return

    keyboard = []
    for date_info in dates[:10]:
        date_str = date_info['date']
        keyboard.append([InlineKeyboardButton(f"📅 {date_str}", callback_data=f"acct_date_{date_str}")])

    keyboard.append([InlineKeyboardButton("❌ 取消", callback_data="acct_cancel")])

    await update.message.reply_text(
        "📅 **请选择要查询的日期：**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ACCOUNTING_DATE_SELECT


async def handle_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理日期选择"""
    query = update.callback_query
    await query.answer()

    date_str = query.data.replace("acct_date_", "")
    group_id = str(query.message.chat.id)

    stats = accounting_manager.get_stats_by_date(group_id, date_str)
    records = accounting_manager.get_records_by_date(group_id, date_str)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await query.message.edit_text(f"📭 {date_str} 暂无账单记录")
        return ConversationHandler.END

    message = f"📅 **{date_str} 账单**\n\n"

    income_records = [r for r in records if r['type'] == 'income']
    expense_records = [r for r in records if r['type'] == 'expense']

    # 入款记录
    if income_records:
        income_records_sorted = sorted(income_records, key=lambda x: x['created_at'], reverse=True)
        display_income = income_records_sorted[:MAX_DISPLAY_RECORDS]
        total_income_count = len(income_records)

        message += f"📈 **入款 {total_income_count} 笔**"
        if total_income_count > MAX_DISPLAY_RECORDS:
            message += f" (显示最新{MAX_DISPLAY_RECORDS}条)"
        message += "\n"

        for r in display_income:
            dt = beijing_time(r['created_at'])
            time_str = dt.strftime('%H:%M')
            amount = r['amount']
            amount_usdt = r['amount_usdt']

            # ✅ 正确 - 使用记录中保存的费率
            fee_rate = r.get('fee_rate', 0)  # 从记录中获取
            rate = r.get('rate', 0)
            fee_info = format_fee_info(fee_rate, rate)

            display_name = r.get('display_name', '未知用户')
            user_id = r.get('user_id')

            if user_id:
                mention = f" [{display_name}](tg://user?id={user_id})"
            else:
                mention = f" {display_name}"

            amount_str = f"{amount:+.2f}"
            message += f"\n`{time_str} {amount_str} {fee_info} = {amount_usdt:.2f} USDT`{mention}"

        if total_income_count > MAX_DISPLAY_RECORDS:
            message += f"\n`... 还有 {total_income_count - MAX_DISPLAY_RECORDS} 条记录`"
        message += "\n\n"
    else:
        message += "📈 **入款 0 笔**\n\n"

    # 出款记录
    if expense_records:
        expense_records_sorted = sorted(expense_records, key=lambda x: x['created_at'], reverse=True)
        display_expense = expense_records_sorted[:MAX_DISPLAY_RECORDS]
        total_expense_count = len(expense_records)

        message += f"📉 **出款 {total_expense_count} 笔**"
        if total_expense_count > MAX_DISPLAY_RECORDS:
            message += f" (显示最新{MAX_DISPLAY_RECORDS}条)"
        message += "\n"

        for r in display_expense:
            # 使用 _format_record_line 统一格式化
            message += f"\n{_format_record_line(r)}"

        if total_expense_count > MAX_DISPLAY_RECORDS:
            message += f"\n`... 还有 {total_expense_count - MAX_DISPLAY_RECORDS} 条记录`"
        message += "\n\n"
    else:
        message += "📉 **出款 0 笔**\n\n"

    session = accounting_manager.get_or_create_session(group_id)
    fee_rate = session.get('fee_rate', 0)
    exchange_rate = session.get('exchange_rate', 1)
    per_transaction_fee = session.get('per_transaction_fee', 0)

    total_income_cny = stats['income_total']
    total_income_usdt = stats['income_usdt']
    total_expense_usdt = stats['expense_usdt']
    pending_usdt = stats['pending_usdt']

    message += f"💰 **当前费率**：{fee_rate}%\n"
    message += f"💱 **当前汇率**：{exchange_rate}\n"
    message += f"📝 **当前单笔费用**：{per_transaction_fee} 元\n\n"
    message += f"📊 **总入款**：{total_income_cny:.2f} = {total_income_usdt:.2f} USDT\n"
    message += f"📤 **已下发**：{total_expense_usdt:.2f} USDT\n"
    message += f"⏳ **待下发**：{pending_usdt:.2f} USDT"

    await query.message.edit_text(message, parse_mode='Markdown')
    return ConversationHandler.END


async def handle_clear_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空当前账单（弹出确认）"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    chat = update.effective_chat
    group_id = str(chat.id)

    stats = accounting_manager.get_current_stats(group_id)

    if stats['income_count'] == 0 and stats['expense_count'] == 0:
        await update.message.reply_text("📭 当前账单为空，无需清理")
        return

    keyboard = [
        [InlineKeyboardButton("✅ 确认清理", callback_data="clear_current_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="clear_current_cancel")]
    ]

    await update.message.reply_text(
        f"⚠️ **警告：此操作将清空当前账单！**\n\n"
        f"📊 当前账单统计：\n"
        f"  总入款：{stats['income_total']:.2f} = {stats['income_usdt']:.2f} USDT\n"
        f"  已下发：{stats['expense_usdt']:.2f} USDT\n"
        f"  记录总数：{stats['income_count'] + stats['expense_count']} 笔\n\n"
        f"⚠️ **注意：当前账单未结束，清理后所有数据将永久丢失！**\n\n"
        f"确认要继续吗？",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ACCOUNTING_CONFIRM_CLEAR


async def handle_clear_current_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认清空当前账单"""
    query = update.callback_query
    await query.answer()

    group_id = str(query.message.chat.id)

    if accounting_manager.clear_current_session(group_id):
        await query.message.edit_text("✅ 已清空当前账单")

        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")
        await query.message.reply_text(message, parse_mode='Markdown')
    else:
        await query.message.edit_text("❌ 清空失败，请稍后重试")

    return ConversationHandler.END


async def handle_clear_current_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消清空当前账单"""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("✅ 已取消清空操作")
    return ConversationHandler.END


async def handle_clear_all_bill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清空所有账单（包括历史记录）"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    chat = update.effective_chat
    group_id = str(chat.id)
    total_stats = accounting_manager.get_total_stats(group_id)

    if total_stats['income_count'] == 0 and total_stats['expense_count'] == 0:
        await update.message.reply_text("📭 暂无任何账单记录")
        return

    keyboard = [
        [InlineKeyboardButton("✅ 确认清空所有账单", callback_data="clear_all_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="clear_all_cancel")]
    ]

    await update.message.reply_text(
        f"⚠️ **警告：此操作将清空本群的所有账单记录！**\n\n"
        f"📊 当前统计：\n"
        f"  总入款：{total_stats['income_total']:.2f} = {total_stats['income_usdt']:.2f} USDT\n"
        f"  总下发：{total_stats['expense_usdt']:.2f} USDT\n"
        f"  记录总数：{total_stats['income_count'] + total_stats['expense_count']} 笔\n\n"
        f"确认要继续吗？此操作不可恢复！",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ACCOUNTING_CONFIRM_CLEAR_ALL


async def handle_clear_all_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认清空所有账单"""
    query = update.callback_query
    await query.answer()

    group_id = str(query.message.chat.id)

    if accounting_manager.clear_all_records(group_id):
        await query.message.edit_text("✅ 已清空本群所有账单记录（包括历史记录）")

        stats = accounting_manager.get_current_stats(group_id)
        records = accounting_manager.get_current_records(group_id)
        message = format_bill_message(stats, records, "当前账单")
        await query.message.reply_text(message, parse_mode='Markdown')
    else:
        await query.message.edit_text("❌ 清空失败，请稍后重试")

    return ConversationHandler.END


async def handle_clear_all_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消清空所有账单"""
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("✅ 已取消清空操作")
    return ConversationHandler.END

async def handle_remove_last_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """移除上一笔记账记录"""
    if not _is_authorized_in_group(update):
        await update.message.reply_text("❌ 此操作需要管理员权限")
        return

    chat = update.effective_chat
    group_id = str(chat.id)

    success, result = accounting_manager.remove_last_record(group_id)

    if not success:
        await update.message.reply_text(f"❌ {result.get('error', '移除失败')}")
        return

    # 构建移除记录的信息
    record = result
    record_type = "入款" if record['type'] == 'income' else "出款"

    if record['type'] == 'income':
        amount_info = f"{record['amount']:.2f} 元 = {record['amount_usdt']:.2f} USDT"
        if record.get('category'):
            amount_info += f" (分类：{record['category']})"
    else:
        amount_info = f"{record['amount_usdt']:.2f} USDT"

    # 时间格式化
    dt = beijing_time(record['created_at'])
    time_str = dt.strftime('%H:%M:%S')

    # 操作人
    operator = record.get('username') or f"用户{record.get('user_id', '未知')}"

    await update.message.reply_text(
        f"✅ 已移除上一笔记账\n\n"
        f"📝 记录信息：\n"
        f"  • 类型：{record_type}\n"
        f"  • 金额：{amount_info}\n"
        f"  • 时间：{time_str}\n"
        f"  • 操作人：{operator}\n\n"
        f"💡 使用「当前账单」查看最新账单"
    )

    # 可选：显示更新后的账单
    stats = accounting_manager.get_current_stats(group_id)
    records = accounting_manager.get_current_records(group_id)
    message = format_bill_message(stats, records, "当前账单")
    await update.message.reply_text(message, parse_mode='Markdown')

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理群组消息中的记账指令"""
    chat = update.effective_chat
    message = update.message

    if not message or chat.type not in ['group', 'supergroup']:
        return

    text = message.text.strip() if message.text else ""

    # ========== 1. 优先处理 USDT 地址查询（不需要权限） ==========
    is_addr, address, chain_type = is_valid_address(text)
    if is_addr:
        user = message.from_user
        group_id = str(chat.id)

        status_msg = await message.reply_text(f"🔍 正在查询 {chain_type} 地址余额，请稍候...")

        if chain_type == 'TRC20':
            result = await query_trc20_balance(address)
        else:
            result = await query_erc20_balance(address)

        if result.get('success'):
            balance = result['balance']

            if accounting_manager:
                accounting_manager.record_address_query(
                    group_id, address, chain_type, user.id,
                    user.username or user.first_name, balance
                )
                stats = accounting_manager.get_address_stats(address)

            first_time = datetime.fromtimestamp(stats['first_query']).strftime('%Y-%m-%d %H:%M') if stats['first_query'] else '首次'
            last_time = datetime.fromtimestamp(stats['last_query']).strftime('%Y-%m-%d %H:%M') if stats['last_query'] else '刚刚'

            reply = (
                f"💰 **USDT 地址查询结果**\n\n"
                f"📌 地址：`{address}`\n"
                f"⛓️ 网络：{chain_type}\n"
                f"💵 余额：**{balance:.2f} USDT**\n"
            )
            await status_msg.edit_text(reply, parse_mode='Markdown')
        else:
            error_msg = result.get('error', '查询失败，请稍后重试')
            await status_msg.edit_text(f"❌ 查询失败：{error_msg}")
        return

    # 追踪用户信息
    await handle_user_info_tracking(update, context)

    if not text:
        return

    # 处理计算器功能
    await handle_calculator(update, context)
    
    # 处理记账指令（需要权限）
    if not is_authorized(message.from_user.id):
        return

    # 设置手续费
    if text.startswith('设置手续费'):
        try:
            rate_str = text.replace('设置手续费', '').strip()
            if rate_str:
                rate = float(rate_str)
                await handle_set_fee(update, context, rate)
        except:
            await message.reply_text("❌ 格式错误：设置手续费 数字（如：设置手续费5）")
        return

    # 设置汇率
    elif text.startswith('设置汇率'):
        try:
            rate_str = text.replace('设置汇率', '').strip()
            if rate_str:
                rate = float(rate_str)
                await handle_set_exchange(update, context, rate)
        except:
            await message.reply_text("❌ 格式错误：设置汇率 数字（如：设置汇率7.2）")
        return

    # 设置单笔费用
    elif text.startswith('设置单笔费用'):
        try:
            fee_str = text.replace('设置单笔费用', '').strip()
            print(f"[DEBUG] 设置单笔费用 - 原始文本: '{text}'")
            print(f"[DEBUG] 设置单笔费用 - 提取的字符串: '{fee_str}'")

            if not fee_str:
                await message.reply_text("❌ 格式错误：设置单笔费用 数字（如：设置单笔费用10）")
                return

            fee = float(fee_str)
            print(f"[DEBUG] 设置单笔费用 - 转换后的数字: {fee}")

            await handle_set_per_transaction_fee(update, context, fee)
            # 成功提示已经在 handle_set_per_transaction_fee 中发送，这里不需要再发送

        except ValueError as e:
            print(f"[DEBUG] ValueError: {e}")
            await message.reply_text("❌ 金额格式错误，请输入数字（如：设置单笔费用10 或 设置单笔费用2）")
        except Exception as e:
            print(f"[DEBUG] 其他异常: {e}")
            await message.reply_text(f"❌ 设置失败：{str(e)[:50]}")
        return

    # 结束账单
    elif text == '结束账单':
        await handle_end_bill(update, context)
        return

    # 今日总
    elif text == '今日总':
        await handle_today_stats(update, context)
        return

    # 总
    elif text == '总':
        await handle_total_stats(update, context)
        return

    # 当前账单
    elif text == '当前账单':
        await handle_current_bill(update, context)
        return

    # 查询账单
    elif text == '查询账单':
        await handle_query_bill(update, context)
        return

    # 清理账单 / 清空账单
    elif text in ['清理账单', '清空账单']:
        await handle_clear_bill(update, context)
        return

    # 清理总账单（所有账单）
    elif text in ['清理总账单', '清空总账单', '清空所有账单']:
        await handle_clear_all_bill(update, context)
        return

    # 移除上一笔
    elif text == '移除上一笔' or text == '删除上一笔':
        await handle_remove_last_record(update, context)
        return

    # +xxx 添加入款（支持备注和临时汇率）
    elif text.startswith('+'):
        try:
            content = text[1:].strip()

            # 解析格式：+金额 或 +金额/汇率 或 +金额 备注 或 +金额/汇率 备注
            temp_rate = None
            category = ""
            amount_str = content

            # 检查是否包含 / 汇率
            if '/' in content:
                parts = content.split('/', 1)
                amount_str = parts[0].strip()
                rest = parts[1].strip()

                # 检查 / 后面是否有空格（如果有空格，则后面是备注）
                if ' ' in rest:
                    rate_part, category = rest.split(' ', 1)
                    try:
                        temp_rate = float(rate_part)
                    except ValueError:
                        category = rest
                        temp_rate = None
                else:
                    # 尝试解析为汇率
                    try:
                        temp_rate = float(rest)
                    except ValueError:
                        category = rest
                        temp_rate = None
            else:
                # 提取备注
                if ' ' in amount_str:
                    parts = amount_str.split(' ', 1)
                    amount_str = parts[0]
                    category = parts[1]

            if amount_str:
                amount = float(amount_str)
                await handle_add_income(update, context, amount, is_correction=False, 
                                       category=category, temp_rate=temp_rate)
            else:
                await message.reply_text("❌ 格式错误：+金额 或 +金额/汇率 或 +金额 备注（如：+1000 或 +1000/10 或 +1000 德国）")
        except ValueError:
            await message.reply_text("❌ 金额格式错误，请输入数字")
        except Exception as e:
            logger.error(f"解析入款失败: {e}")
            await message.reply_text("❌ 格式错误：+金额 或 +金额/汇率 或 +金额 备注（如：+1000 或 +1000/10 或 +1000 德国）")
            return

    # -xxx 修正入款（支持备注和临时汇率）
    elif text.startswith('-') and len(text) > 1:
        try:
            content = text[1:].strip()

            # 解析格式：-金额 或 -金额/汇率 或 -金额 备注 或 -金额/汇率 备注
            temp_rate = None
            category = ""
            amount_str = content

            # 检查是否包含 / 汇率
            if '/' in content:
                parts = content.split('/', 1)
                amount_str = parts[0].strip()
                rest = parts[1].strip()

                # 检查 / 后面是否有空格（如果有空格，则后面是备注）
                if ' ' in rest:
                    rate_part, category = rest.split(' ', 1)
                    try:
                        temp_rate = float(rate_part)
                    except ValueError:
                        category = rest
                        temp_rate = None
                else:
                    # 尝试解析为汇率
                    try:
                        temp_rate = float(rest)
                    except ValueError:
                        category = rest
                        temp_rate = None
            else:
                # 提取备注
                if ' ' in amount_str:
                    parts = amount_str.split(' ', 1)
                    amount_str = parts[0]
                    category = parts[1]

            if amount_str:
                amount = float(amount_str)
                await handle_add_income(update, context, amount, is_correction=True, 
                                       category=category, temp_rate=temp_rate)
            else:
                await message.reply_text("❌ 格式错误：-金额 或 -金额/汇率 或 -金额 备注（如：-500 或 -500/10 或 -500 德国）")
        except ValueError:
            await message.reply_text("❌ 金额格式错误，请输入数字")
        except Exception as e:
            logger.error(f"解析修正入款失败: {e}")
            await message.reply_text("❌ 格式错误：-金额 或 -金额/汇率 或 -金额 备注（如：-500 或 -500/10 或 -500 德国）")
            return

    # 下发 xxxu 添加出款（正数）
    elif text.startswith('下发') and 'u' in text and not text.startswith('下发-'):
        try:
            amount_str = text.replace('下发', '').replace('u', '').strip()
            if amount_str:
                amount = float(amount_str)
                await handle_add_expense(update, context, amount, is_correction=False)
            else:
                await message.reply_text("❌ 格式错误：下发金额u（如：下发100u）")
        except:
            await message.reply_text("❌ 格式错误：下发金额u（如：下发100u）")
            return

    # 下发- xxxu 修正出款（负数）
    elif text.startswith('下发-') and 'u' in text:
        try:
            amount_str = text.replace('下发-', '').replace('u', '').strip()
            if amount_str:
                amount = float(amount_str)
                await handle_add_expense(update, context, amount, is_correction=True)
            else:
                await message.reply_text("❌ 格式错误：下发-金额u（如：下发-50u）")
        except:
            await message.reply_text("❌ 格式错误：下发-金额u（如：下发-50u）")
            return

    # ========== 3. AI 对话（需要管理员或操作员权限） ==========
    bot_username = context.bot.username
    if f"@{bot_username}" in text:
        question = text.replace(f"@{bot_username}", "").strip()
        if question:
            # 权限检查
            if not is_authorized(message.from_user.id):
                try:
                    await context.bot.send_message(
                        chat_id=message.chat_id,
                        text="❌ AI 对话功能仅限管理员和操作员使用\n\n如需使用，请联系 @ChinaEdward 申请权限",
                        reply_to_message_id=message.message_id  # 引用原消息
                    )
                except Exception as e:
                    print(f"[ERROR] 发送权限提示失败: {e}")
                    # 如果失败，尝试简单回复
                    await message.reply_text("❌ 无权限使用 AI 对话")
                return

            # 有权限，继续处理
            thinking_msg = await message.reply_text("🤔 思考中...")
            from handlers.ai_client import get_ai_client
            ai_client = get_ai_client()
            
            # 使用工具调用版本
            reply = await ai_client.chat_with_data(
                prompt=question,
                group_id=str(chat.id),
                user_id=message.from_user.id
            )
            
            if len(reply) > 4000:
                reply = reply[:4000] + "...\n\n(回复过长已截断)"
            await thinking_msg.edit_text(reply)
        return

async def handle_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理计算器功能（只识别完整的计算表达式）"""
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return

    text = update.message.text.strip()

    # 🔥 排除记账命令
    exclude_prefixes = ['设置手续费', '设置汇率', '设置单笔费用', '结束账单', '今日总', '总', 
                        '当前账单', '查询账单', '清理账单', '清空账单', '清理总账单', 
                        '清空总账单', '清空所有账单', '下发', '+', '-']

    for prefix in exclude_prefixes:
        if text.startswith(prefix):
            return

    # 🔥 只识别完整的计算表达式
    # 规则：必须以数字或 ( 或函数名开头，以数字或 ) 结尾
    # 且必须包含运算符

    # 检查是否是有效的计算表达式
    def is_valid_expression(expr: str) -> bool:
        # 去除空格
        expr = expr.replace(' ', '')
        if not expr:
            return False

        # 必须以数字、小数点、(、函数名开头
        valid_starts = ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '(', '-', '+', 
                       'sqrt', 'sin', 'cos', 'tan', 'log', 'abs', 'round', 'floor', 'ceil', 'pi', 'e')
        if not any(expr.startswith(s) for s in valid_starts):
            return False

        # 必须以数字、) 结尾
        if not (expr[-1].isdigit() or expr[-1] == ')'):
            return False

        # 必须包含运算符（+ - * / % ^）
        operators = ['+', '-', '*', '/', '%', '^']
        has_operator = any(op in expr for op in operators)
        if not has_operator:
            return False

        return True

    if not is_valid_expression(text):
        return

    # 简单算式：如 100+200
    simple_pattern = r'^(-?\d+(?:\.\d+)?)\s*([+\-*/%])\s*(-?\d+(?:\.\d+)?)$'
    simple_match = re.match(simple_pattern, text)

    if simple_match:
        # 简单计算直接处理
        a, op, b = simple_match.groups()
        a_num = float(a)
        b_num = float(b)

        try:
            if op == '+':
                result = a_num + b_num
            elif op == '-':
                result = a_num - b_num
            elif op == '*':
                result = a_num * b_num
            elif op == '/':
                if b_num == 0:
                    await update.message.reply_text("❌ 除数不能为0")
                    return
                result = a_num / b_num
            elif op == '%':
                result = a_num % b_num
            else:
                return

            result_str = str(int(result)) if result.is_integer() else f"{result:.2f}"
            await update.message.reply_text(f"🧮 {a}{op}{b} = {result_str}")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ 计算错误：{str(e)[:50]}")
            return

    # 复杂计算
    result = Calculator.safe_eval(text)

    if result is not None:
        result_str = Calculator.format_result(result)
        await update.message.reply_text(f"🧮 {text} = {result_str}")
    else:
        await update.message.reply_text(
            "❌ 请输入完整计算格式\n"
            "支持的运算符：+ - * / % ^ ( )\n"
            "支持的函数：sqrt, sin, cos, tan, log, abs, round, floor, ceil\n"
            "支持的常数：pi, e\n"
        )


async def handle_user_info_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """追踪用户信息变更"""
    chat = update.effective_chat
    user = update.effective_user

    if not user or chat.type not in ['group', 'supergroup']:
        return

    group_id = str(chat.id)
    username = user.username
    first_name = user.first_name
    last_name = user.last_name or ""

    has_change, old_name, new_name, change_type = accounting_manager.update_user_info(
        group_id, user.id, username, first_name, last_name
    )

    if has_change:
        if change_type:
            await update.message.reply_text(
                f"🚨🚨 **用户信息变更提醒**\n\n"
                f"用户 {old_name}\n"
                f"已更新{change_type}为：\n"
                f"{new_name}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"🚨🚨 **用户信息变更提醒**\n\n"
                f"用户 {old_name} → {new_name}",
                parse_mode='Markdown'
            )

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新成员加入事件"""
    # 获取 chat_member 更新
    chat_member = update.chat_member

    if not chat_member:
        print("❌ 没有 chat_member 数据")
        return

    # 获取新旧状态
    old_status = chat_member.old_chat_member.status if chat_member.old_chat_member else None
    new_status = chat_member.new_chat_member.status if chat_member.new_chat_member else None

    print(f"[欢迎检测] 群组: {chat_member.chat.title}")
    print(f"[欢迎检测] 旧状态: {old_status}")
    print(f"[欢迎检测] 新状态: {new_status}")

    # 检测成员加入（从 left/kicked/restricted 变为 member）
    if new_status == 'member' and old_status in ['left', 'kicked', 'restricted']:
        print(f"✅ 检测到新成员加入！")

        user = chat_member.new_chat_member.user
        chat = chat_member.chat

        # 获取用户信息
        first_name = user.first_name or ""
        username = user.username

        # 构建欢迎语
        if username:
            welcome_text = f"{first_name} @{username}\n欢迎加入本群"
        else:
            welcome_text = f"{first_name}\n欢迎加入本群"

        # 发送欢迎消息
        try:
            await context.bot.send_message(chat_id=chat.id, text=welcome_text)
            print(f"✅ 欢迎消息已发送: {welcome_text}")
        except Exception as e:
            print(f"❌ 发送欢迎消息失败: {e}")

    # 检测成员离开（从 member 变为 left/kicked）
    elif old_status == 'member' and new_status in ['left', 'kicked']:
        print(f"👋 检测到成员离开")
        user = chat_member.new_chat_member.user
        print(f"离开的用户: {user.first_name}")

# ==================== 群组成员变化监听器（服务消息方式）====================

async def handle_group_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理群组的服务消息（成员加入/退出）
    这种方式更可靠，因为 Telegram 会在群组中发送服务消息
    """
    message = update.effective_message

    if not message:
        return

    chat = message.chat
    if chat.type not in ['group', 'supergroup']:
        return

    group_id = str(chat.id)

    # ========== 检测新成员加入 ==========
    if message.new_chat_members:
        for new_member in message.new_chat_members:
            # 跳过机器人自己
            if new_member.id == context.bot.id:
                logger.info(f"机器人加入群组 {chat.title}，跳过欢迎消息")
                continue

            user_name = new_member.full_name
            username = f"@{new_member.username}" if new_member.username else ""

            # 构建欢迎消息
            welcome_message = f"{user_name} {username}\n欢迎进入本群组"

            try:
                await message.reply_text(welcome_message)
                logger.info(f"✅ 已发送欢迎消息给 {user_name} (群组: {chat.title})")
            except Exception as e:
                logger.error(f"发送欢迎消息失败: {e}")

            # 更新用户信息到数据库
            try:
                if accounting_manager:
                    accounting_manager.update_user_info(
                        group_id,
                        new_member.id,
                        new_member.username or "",
                        new_member.first_name or "",
                        new_member.last_name or ""
                    )
            except Exception as e:
                logger.error(f"更新用户信息失败: {e}")

        return

    # ========== 检测成员退出 ==========
    if message.left_chat_member:
        left_member = message.left_chat_member

        # 跳过机器人自己
        if left_member.id == context.bot.id:
            logger.info(f"机器人退出群组 {chat.title}，跳过告别消息")
            return

        user_name = left_member.full_name
        username = f"@{left_member.username}" if left_member.username else ""

        # 构建退出消息
        leave_message = f"{user_name} {username}\n退出了本群组"

        try:
            await message.reply_text(leave_message)
            logger.info(f"✅ 已发送退出消息 (用户: {user_name}, 群组: {chat.title})")
        except Exception as e:
            logger.error(f"发送退出消息失败: {e}")

        return


def get_service_message_handler():
    """
    获取服务消息处理器，用于 main.py 中注册
    """
    from telegram.ext import MessageHandler, filters
    # 监听新成员加入和成员退出的事件
    return MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        handle_group_service_message
    )


def get_conversation_handler():
    """获取记账模块的对话处理器"""
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_date_selection, pattern="^acct_date_"),
            CallbackQueryHandler(handle_clear_current_confirm, pattern="^clear_current_confirm$"),
            CallbackQueryHandler(handle_clear_current_cancel, pattern="^clear_current_cancel$"),
            CallbackQueryHandler(handle_clear_all_confirm, pattern="^clear_all_confirm$"),
            CallbackQueryHandler(handle_clear_all_cancel, pattern="^clear_all_cancel$"),
        ],
        states={
            ACCOUNTING_DATE_SELECT: [
                CallbackQueryHandler(handle_date_selection, pattern="^acct_date_"),
                CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern="^acct_cancel$"),
            ],
            ACCOUNTING_CONFIRM_CLEAR: [
                CallbackQueryHandler(handle_clear_current_confirm, pattern="^clear_current_confirm$"),
                CallbackQueryHandler(handle_clear_current_cancel, pattern="^clear_current_cancel$"),
            ],
            ACCOUNTING_CONFIRM_CLEAR_ALL: [
                CallbackQueryHandler(handle_clear_all_confirm, pattern="^clear_all_confirm$"),
                CallbackQueryHandler(handle_clear_all_cancel, pattern="^clear_all_cancel$"),
            ],
        },
        fallbacks=[],
        per_message=False,
    )
    return conv_handler


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理记账菜单按钮点击"""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.message.reply_text("❌ 此功能仅限管理员或操作员使用")
        # 清除状态
        context.user_data.pop("active_module", None)
        return

    # 设置模块标识
    context.user_data["active_module"] = "accounting"

    message = (
        "📒 **记账功能说明**\n\n"
        "💰 **入款操作**：\n"
        "`+金额` - 添加一笔入款（如：+1000）\n"
        "`+金额/汇率` - 使用临时汇率入款（如：+1000/7.2）\n"
        "`+金额 备注` - 带分类入款（如：+1000 德国）\n"
        "`+金额/汇率 备注` - 带分类+临时汇率（如：+1000/7.2 德国）\n"
        "`-金额` - 修正入款（如：-500）\n"
        "`-金额/汇率` - 修正入款+临时汇率（如：-500/7.2）\n"
        "`-金额 备注` - 修正入款+分类（如：-500 德国）\n"
        "`-金额/汇率 备注` - 修正+分类+临时汇率（如：-500/7.2 德国）\n\n"
        "💸 **出款操作**：\n"
        "`下发金额u` - 添加出款（如：下发100u）\n"
        "`下发-金额u` - 修正出款（如：下发-50u）\n\n"
        "⚙️ **配置**：\n"
        "`设置手续费 数字` - 设置手续费率（如：设置手续费 5）\n"
        "`设置汇率 数字` - 设置汇率（如：设置汇率 7.2）\n"
        "`设置单笔费用 数字` - 设置单笔费用（如：设置单笔费用 2）\n\n"
        "📊 **查询**：\n"
        "`今日总` - 查看今日账单\n"
        "`总` - 查看总计账单\n"
        "`当前账单` - 查看当前会话账单\n"
        "`查询账单` - 按日期查询历史账单\n\n"
        "🗑️ **管理**：\n"
        "`结束账单` - 结束当前会话并保存\n"
        "`清理账单` - 清空当前会话记录\n"
        "`清理总账单` - 清空所有历史记录\n"
        "`移除上一笔` / `删除上一笔` - 撤销最后一笔记账\n\n"
        "🧮 **计算器**：\n"
        "`数字+数字`、`数字-数字`、`数字*数字`、`数字/数字`\n"
        "支持复杂表达式：`(100+200)*3`、`sqrt(100)`、`2^3` 等\n\n"
        "💡 **智能识别**：\n"
        "• 群内发送 USDT 地址自动查询余额\n"
        "• 分类备注自动识别国家并显示国旗\n"
        "• `@机器人 问题` - AI 智能问答\n\n"
        "⚠️ **权限说明**：\n"
        "• 记账、配置、AI问答、管理操作需要管理员或操作员权限\n"
        "• 地址查询、计算器所有人可用"
    )

    await query.message.reply_text(message, parse_mode='Markdown')
    context.user_data.pop("active_module", None)
