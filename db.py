# db.py

import sqlite3
import os
import time
import re

DB_PATH = "bot.db"
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_PATH)

COUNTRY_KEYWORDS = {
    # ========== 亚洲 ==========
    '中国': ['中国', 'china', 'cn', '🇨🇳', 'zhongguo'],
    '台湾': ['台湾', 'taiwan', 'tw', '🇹🇼', 'taiwan china'],
    '香港': ['香港', 'hong kong', 'hk', '🇭🇰', 'hongkong'],
    '澳门': ['澳门', 'macau', 'mo', '🇲🇴', 'macao'],
    '日本': ['日本', 'japan', 'jp', '🇯🇵', 'japon'],
    '韩国': ['韩国', 'korea', 'kr', '🇰🇷', 'south korea', 'republic of korea'],
    '朝鲜': ['朝鲜', 'north korea', 'kp', '🇰🇵', 'democratic people republic of korea'],
    '蒙古': ['蒙古', 'mongolia', 'mn', '🇲🇳'],
    '印度': ['印度', 'india', 'in', '🇮🇳', 'bharat'],
    '巴基斯坦': ['巴基斯坦', 'pakistan', 'pk', '🇵🇰'],
    '孟加拉国': ['孟加拉国', 'bangladesh', 'bd', '🇧🇩'],
    '尼泊尔': ['尼泊尔', 'nepal', 'np', '🇳🇵'],
    '不丹': ['不丹', 'bhutan', 'bt', '🇧🇹'],
    '斯里兰卡': ['斯里兰卡', 'sri lanka', 'lk', '🇱🇰'],
    '马尔代夫': ['马尔代夫', 'maldives', 'mv', '🇲🇻'],
    '泰国': ['泰国', 'thailand', 'th', '🇹🇭', 'siamese'],
    '越南': ['越南', 'vietnam', 'vn', '🇻🇳'],
    '老挝': ['老挝', 'laos', 'la', '🇱🇦'],
    '柬埔寨': ['柬埔寨', 'cambodia', 'kh', '🇰🇭'],
    '缅甸': ['缅甸', 'myanmar', 'mm', '🇲🇲', 'burma'],
    '马来西亚': ['马来西亚', 'malaysia', 'my', '🇲🇾'],
    '新加坡': ['新加坡', 'singapore', 'sg', '🇸🇬'],
    '印度尼西亚': ['印度尼西亚', 'indonesia', 'id', '🇮🇩'],
    '菲律宾': ['菲律宾', 'philippines', 'ph', '🇵🇭'],
    '东帝汶': ['东帝汶', 'timor leste', 'tl', '🇹🇱'],
    '文莱': ['文莱', 'brunei', 'bn', '🇧🇳'],
    '阿富汗': ['阿富汗', 'afghanistan', 'af', '🇦🇫'],
    '伊朗': ['伊朗', 'iran', 'ir', '🇮🇷', 'persia'],
    '伊拉克': ['伊拉克', 'iraq', 'iq', '🇮🇶'],
    '科威特': ['科威特', 'kuwait', 'kw', '🇰🇼'],
    '沙特阿拉伯': ['沙特', 'saudi', 'saudi arabia', 'sa', '🇸🇦'],
    '也门': ['也门', 'yemen', 'ye', '🇾🇪'],
    '阿曼': ['阿曼', 'oman', 'om', '🇴🇲'],
    '阿联酋': ['阿联酋', 'uae', 'united arab emirates', 'ae', '🇦🇪'],
    '卡塔尔': ['卡塔尔', 'qatar', 'qa', '🇶🇦'],
    '巴林': ['巴林', 'bahrain', 'bh', '🇧🇭'],
    '约旦': ['约旦', 'jordan', 'jo', '🇯🇴'],
    '黎巴嫩': ['黎巴嫩', 'lebanon', 'lb', '🇱🇧'],
    '叙利亚': ['叙利亚', 'syria', 'sy', '🇸🇾'],
    '塞浦路斯': ['塞浦路斯', 'cyprus', 'cy', '🇨🇾'],
    '以色列': ['以色列', 'israel', 'il', '🇮🇱'],
    '巴勒斯坦': ['巴勒斯坦', 'palestine', 'ps', '🇵🇸'],
    '土耳其': ['土耳其', 'turkey', 'tr', '🇹🇷'],
    '阿塞拜疆': ['阿塞拜疆', 'azerbaijan', 'az', '🇦🇿'],
    '格鲁吉亚': ['格鲁吉亚', 'georgia', 'ge', '🇬🇪'],
    '亚美尼亚': ['亚美尼亚', 'armenia', 'am', '🇦🇲'],
    '哈萨克斯坦': ['哈萨克斯坦', 'kazakhstan', 'kz', '🇰🇿'],
    '吉尔吉斯斯坦': ['吉尔吉斯斯坦', 'kyrgyzstan', 'kg', '🇰🇬'],
    '塔吉克斯坦': ['塔吉克斯坦', 'tajikistan', 'tj', '🇹🇯'],
    '乌兹别克斯坦': ['乌兹别克斯坦', 'uzbekistan', 'uz', '🇺🇿'],
    '土库曼斯坦': ['土库曼斯坦', 'turkmenistan', 'tm', '🇹🇲'],

    # ========== 欧洲 ==========
    '英国': ['英国', 'uk', 'united kingdom', 'england', 'britain', 'gb', '🇬🇧'],
    '法国': ['法国', 'france', 'fr', '🇫🇷'],
    '德国': ['德国', 'germany', 'de', '🇩🇪'],
    '意大利': ['意大利', 'italy', 'it', '🇮🇹'],
    '西班牙': ['西班牙', 'spain', 'es', '🇪🇸'],
    '葡萄牙': ['葡萄牙', 'portugal', 'pt', '🇵🇹'],
    '荷兰': ['荷兰', 'netherlands', 'nl', '🇳🇱', 'holland'],
    '比利时': ['比利时', 'belgium', 'be', '🇧🇪'],
    '卢森堡': ['卢森堡', 'luxembourg', 'lu', '🇱🇺'],
    '瑞士': ['瑞士', 'switzerland', 'ch', '🇨🇭'],
    '奥地利': ['奥地利', 'austria', 'at', '🇦🇹'],
    '列支敦士登': ['列支敦士登', 'liechtenstein', 'li', '🇱🇮'],
    '波兰': ['波兰', 'poland', 'pl', '🇵🇱'],
    '捷克': ['捷克', 'czech', 'cz', '🇨🇿', 'czech republic'],
    '斯洛伐克': ['斯洛伐克', 'slovakia', 'sk', '🇸🇰'],
    '匈牙利': ['匈牙利', 'hungary', 'hu', '🇭🇺'],
    '罗马尼亚': ['罗马尼亚', 'romania', 'ro', '🇷🇴'],
    '保加利亚': ['保加利亚', 'bulgaria', 'bg', '🇧🇬'],
    '塞尔维亚': ['塞尔维亚', 'serbia', 'rs', '🇷🇸'],
    '克罗地亚': ['克罗地亚', 'croatia', 'hr', '🇭🇷'],
    '斯洛文尼亚': ['斯洛文尼亚', 'slovenia', 'si', '🇸🇮'],
    '波黑': ['波黑', 'bosnia', 'ba', '🇧🇦', 'bosnia and herzegovina'],
    '黑山': ['黑山', 'montenegro', 'me', '🇲🇪'],
    '北马其顿': ['北马其顿', 'north macedonia', 'mk', '🇲🇰'],
    '阿尔巴尼亚': ['阿尔巴尼亚', 'albania', 'al', '🇦🇱'],
    '希腊': ['希腊', 'greece', 'gr', '🇬🇷'],
    '爱尔兰': ['爱尔兰', 'ireland', 'ie', '🇮🇪'],
    '丹麦': ['丹麦', 'denmark', 'dk', '🇩🇰'],
    '瑞典': ['瑞典', 'sweden', 'se', '🇸🇪'],
    '挪威': ['挪威', 'norway', 'no', '🇳🇴'],
    '芬兰': ['芬兰', 'finland', 'fi', '🇫🇮'],
    '冰岛': ['冰岛', 'iceland', 'is', '🇮🇸'],
    '俄罗斯': ['俄罗斯', 'russia', 'ru', '🇷🇺'],
    '爱沙尼亚': ['爱沙尼亚', 'estonia', 'ee', '🇪🇪'],
    '拉脱维亚': ['拉脱维亚', 'latvia', 'lv', '🇱🇻'],
    '立陶宛': ['立陶宛', 'lithuania', 'lt', '🇱🇹'],
    '白俄罗斯': ['白俄罗斯', 'belarus', 'by', '🇧🇾'],
    '摩尔多瓦': ['摩尔多瓦', 'moldova', 'md', '🇲🇩'],
    '乌克兰': ['乌克兰', 'ukraine', 'ua', '🇺🇦'],
    '摩纳哥': ['摩纳哥', 'monaco', 'mc', '🇲🇨'],
    '安道尔': ['安道尔', 'andorra', 'ad', '🇦🇩'],
    '圣马力诺': ['圣马力诺', 'san marino', 'sm', '🇸🇲'],
    '梵蒂冈': ['梵蒂冈', 'vatican', 'va', '🇻🇦'],
    '马耳他': ['马耳他', 'malta', 'mt', '🇲🇹'],
    '直布罗陀': ['直布罗陀', 'gibraltar', 'gi', '🇬🇮'],
    '马恩岛': ['马恩岛', 'isle of man', 'im', '🇮🇲'],
    '泽西岛': ['泽西岛', 'jersey', 'je', '🇯🇪'],
    '根西岛': ['根西岛', 'guernsey', 'gg', '🇬🇬'],
    '法罗群岛': ['法罗群岛', 'faroe islands', 'fo', '🇫🇴'],
    '奥兰群岛': ['奥兰群岛', 'aland islands', 'ax', '🇦🇽'],
    '斯瓦尔巴群岛': ['斯瓦尔巴', 'svalbard', 'sj', '🇸🇯'],

    # ========== 北美洲 ==========
    '美国': ['美国', 'usa', 'us', 'america', 'united states', '🇺🇸'],
    '加拿大': ['加拿大', 'canada', 'ca', '🇨🇦'],
    '墨西哥': ['墨西哥', 'mexico', 'mx', '🇲🇽'],
    '古巴': ['古巴', 'cuba', 'cu', '🇨🇺'],
    '牙买加': ['牙买加', 'jamaica', 'jm', '🇯🇲'],
    '海地': ['海地', 'haiti', 'ht', '🇭🇹'],
    '多米尼加': ['多米尼加', 'dominican', 'do', '🇩🇴'],
    '波多黎各': ['波多黎各', 'puerto rico', 'pr', '🇵🇷'],
    '巴哈马': ['巴哈马', 'bahamas', 'bs', '🇧🇸'],
    '特立尼达和多巴哥': ['特立尼达', 'trinidad', 'tt', '🇹🇹'],
    '巴巴多斯': ['巴巴多斯', 'barbados', 'bb', '🇧🇧'],
    '圣卢西亚': ['圣卢西亚', 'saint lucia', 'lc', '🇱🇨'],
    '格林纳达': ['格林纳达', 'grenada', 'gd', '🇬🇩'],
    '安提瓜和巴布达': ['安提瓜', 'antigua', 'ag', '🇦🇬'],
    '圣基茨和尼维斯': ['圣基茨', 'saint kitts', 'kn', '🇰🇳'],
    '伯利兹': ['伯利兹', 'belize', 'bz', '🇧🇿'],
    '哥斯达黎加': ['哥斯达黎加', 'costa rica', 'cr', '🇨🇷'],
    '萨尔瓦多': ['萨尔瓦多', 'el salvador', 'sv', '🇸🇻'],
    '危地马拉': ['危地马拉', 'guatemala', 'gt', '🇬🇹'],
    '洪都拉斯': ['洪都拉斯', 'honduras', 'hn', '🇭🇳'],
    '尼加拉瓜': ['尼加拉瓜', 'nicaragua', 'ni', '🇳🇮'],
    '巴拿马': ['巴拿马', 'panama', 'pa', '🇵🇦'],

    # ========== 南美洲 ==========
    '巴西': ['巴西', 'brazil', 'br', '🇧🇷'],
    '阿根廷': ['阿根廷', 'argentina', 'ar', '🇦🇷'],
    '乌拉圭': ['乌拉圭', 'uruguay', 'uy', '🇺🇾'],
    '巴拉圭': ['巴拉圭', 'paraguay', 'py', '🇵🇾'],
    '玻利维亚': ['玻利维亚', 'bolivia', 'bo', '🇧🇴'],
    '智利': ['智利', 'chile', 'cl', '🇨🇱'],
    '秘鲁': ['秘鲁', 'peru', 'pe', '🇵🇪'],
    '哥伦比亚': ['哥伦比亚', 'colombia', 'co', '🇨🇴'],
    '委内瑞拉': ['委内瑞拉', 'venezuela', 've', '🇻🇪'],
    '厄瓜多尔': ['厄瓜多尔', 'ecuador', 'ec', '🇪🇨'],
    '圭亚那': ['圭亚那', 'guyana', 'gy', '🇬🇾'],
    '苏里南': ['苏里南', 'suriname', 'sr', '🇸🇷'],
    '法属圭亚那': ['法属圭亚那', 'french guiana', 'gf', '🇬🇫'],

    # ========== 非洲 ==========
    '南非': ['南非', 'south africa', 'za', '🇿🇦'],
    '埃及': ['埃及', 'egypt', 'eg', '🇪🇬'],
    '摩洛哥': ['摩洛哥', 'morocco', 'ma', '🇲🇦'],
    '阿尔及利亚': ['阿尔及利亚', 'algeria', 'dz', '🇩🇿'],
    '突尼斯': ['突尼斯', 'tunisia', 'tn', '🇹🇳'],
    '利比亚': ['利比亚', 'libya', 'ly', '🇱🇾'],
    '苏丹': ['苏丹', 'sudan', 'sd', '🇸🇩'],
    '埃塞俄比亚': ['埃塞俄比亚', 'ethiopia', 'et', '🇪🇹'],
    '肯尼亚': ['肯尼亚', 'kenya', 'ke', '🇰🇪'],
    '坦桑尼亚': ['坦桑尼亚', 'tanzania', 'tz', '🇹🇿'],
    '乌干达': ['乌干达', 'uganda', 'ug', '🇺🇬'],
    '卢旺达': ['卢旺达', 'rwanda', 'rw', '🇷🇼'],
    '布隆迪': ['布隆迪', 'burundi', 'bi', '🇧🇮'],
    '索马里': ['索马里', 'somalia', 'so', '🇸🇴'],
    '吉布提': ['吉布提', 'djibouti', 'dj', '🇩🇯'],
    '厄立特里亚': ['厄立特里亚', 'eritrea', 'er', '🇪🇷'],
    '南苏丹': ['南苏丹', 'south sudan', 'ss', '🇸🇸'],
    '刚果金': ['刚果金', 'congo', 'cd', '🇨🇩', 'drc'],
    '刚果布': ['刚果布', 'congo brazzaville', 'cg', '🇨🇬'],
    '加蓬': ['加蓬', 'gabon', 'ga', '🇬🇦'],
    '赤道几内亚': ['赤道几内亚', 'equatorial guinea', 'gq', '🇬🇶'],
    '喀麦隆': ['喀麦隆', 'cameroon', 'cm', '🇨🇲'],
    '尼日利亚': ['尼日利亚', 'nigeria', 'ng', '🇳🇬'],
    '加纳': ['加纳', 'ghana', 'gh', '🇬🇭'],
    '科特迪瓦': ['科特迪瓦', 'ivory coast', 'ci', '🇨🇮'],
    '塞内加尔': ['塞内加尔', 'senegal', 'sn', '🇸🇳'],
    '几内亚': ['几内亚', 'guinea', 'gn', '🇬🇳'],
    '几内亚比绍': ['几内亚比绍', 'guinea bissau', 'gw', '🇬🇼'],
    '马里': ['马里', 'mali', 'ml', '🇲🇱'],
    '布基纳法索': ['布基纳法索', 'burkina faso', 'bf', '🇧🇫'],
    '尼日尔': ['尼日尔', 'niger', 'ne', '🇳🇪'],
    '乍得': ['乍得', 'chad', 'td', '🇹🇩'],
    '中非': ['中非', 'central african', 'cf', '🇨🇫'],
    '安哥拉': ['安哥拉', 'angola', 'ao', '🇦🇴'],
    '纳米比亚': ['纳米比亚', 'namibia', 'na', '🇳🇦'],
    '博茨瓦纳': ['博茨瓦纳', 'botswana', 'bw', '🇧🇼'],
    '赞比亚': ['赞比亚', 'zambia', 'zm', '🇿🇲'],
    '津巴布韦': ['津巴布韦', 'zimbabwe', 'zw', '🇿🇼'],
    '莫桑比克': ['莫桑比克', 'mozambique', 'mz', '🇲🇿'],
    '马拉维': ['马拉维', 'malawi', 'mw', '🇲🇼'],
    '马达加斯加': ['马达加斯加', 'madagascar', 'mg', '🇲🇬'],
    '毛里求斯': ['毛里求斯', 'mauritius', 'mu', '🇲🇺'],
    '塞舌尔': ['塞舌尔', 'seychelles', 'sc', '🇸🇨'],
    '科摩罗': ['科摩罗', 'comoros', 'km', '🇰🇲'],
    '毛里塔尼亚': ['毛里塔尼亚', 'mauritania', 'mr', '🇲🇷'],
    '西撒哈拉': ['西撒哈拉', 'western sahara', 'eh', '🇪🇭'],
    '冈比亚': ['冈比亚', 'gambia', 'gm', '🇬🇲'],
    '塞拉利昂': ['塞拉利昂', 'sierra leone', 'sl', '🇸🇱'],
    '利比里亚': ['利比里亚', 'liberia', 'lr', '🇱🇷'],
    '贝宁': ['贝宁', 'benin', 'bj', '🇧🇯'],
    '多哥': ['多哥', 'togo', 'tg', '🇹🇬'],

    # ========== 大洋洲 ==========
    '澳大利亚': ['澳大利亚', 'australia', 'au', '🇦🇺'],
    '新西兰': ['新西兰', 'new zealand', 'nz', '🇳🇿'],
    '斐济': ['斐济', 'fiji', 'fj', '🇫🇯'],
    '巴布亚新几内亚': ['巴布亚新几内亚', 'papua new guinea', 'pg', '🇵🇬'],
    '所罗门群岛': ['所罗门群岛', 'solomon islands', 'sb', '🇸🇧'],
    '瓦努阿图': ['瓦努阿图', 'vanuatu', 'vu', '🇻🇺'],
    '新喀里多尼亚': ['新喀里多尼亚', 'new caledonia', 'nc', '🇳🇨'],
    '萨摩亚': ['萨摩亚', 'samoa', 'ws', '🇼🇸'],
    '汤加': ['汤加', 'tonga', 'to', '🇹🇴'],
    '密克罗尼西亚': ['密克罗尼西亚', 'micronesia', 'fm', '🇫🇲'],
    '马绍尔群岛': ['马绍尔群岛', 'marshall islands', 'mh', '🇲🇭'],
    '帕劳': ['帕劳', 'palau', 'pw', '🇵🇼'],
    '瑙鲁': ['瑙鲁', 'nauru', 'nr', '🇳🇷'],
    '基里巴斯': ['基里巴斯', 'kiribati', 'ki', '🇰🇮'],
    '图瓦卢': ['图瓦卢', 'tuvalu', 'tv', '🇹🇻'],
}

def detect_country_from_group_name(group_name: str) -> str:
    """从群组名称中检测国家，返回国家名称，没有匹配返回 None"""
    if not group_name:
        return None

    group_name_lower = group_name.lower()

    for country, keywords in COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in group_name_lower:
                return country

    return None

def ensure_country_category(country_name: str) -> bool:
    """确保国家的分类存在，不存在则自动创建"""
    categories = get_all_categories()
    category_names = [cat['name'] for cat in categories]

    if country_name not in category_names:
        return add_category(country_name, f"自动创建的{country_name}分类")

    return True

def get_db_connection():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 创建 operators 表
    c.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            user_id TEXT PRIMARY KEY,
            name TEXT
        )
    """)

    # 创建 groups 表
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            last_seen INTEGER DEFAULT 0,
            category TEXT DEFAULT '未分类'
        )
    """)

    # 创建分类表
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            created_at INTEGER DEFAULT 0,
            description TEXT
        )
    """)

    # 🔥 创建群组记账配置表（添加 per_transaction_fee 字段）
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

    # 初始化默认分类
    now = int(time.time())
    default_categories = ['未分类']
    for cat in default_categories:
        c.execute("INSERT OR IGNORE INTO group_categories (category_name, created_at) VALUES (?, ?)", (cat, now))

    # 数据库迁移：为现有群组添加 category 字段
    try:
        c.execute("SELECT category FROM groups LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE groups ADD COLUMN category TEXT DEFAULT '未分类'")
        print("✅ 已为 groups 表添加 category 字段")

    # 🔥 数据库迁移：为已存在的 group_accounting_config 表添加 per_transaction_fee 字段
    try:
        c.execute("SELECT per_transaction_fee FROM group_accounting_config LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE group_accounting_config ADD COLUMN per_transaction_fee REAL DEFAULT 0.0")
        print("✅ 已为 group_accounting_config 表添加 per_transaction_fee 字段")

    # ========== 新增：监控地址表 ==========
    c.execute("""
        CREATE TABLE IF NOT EXISTS monitored_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            chain_type TEXT NOT NULL,
            added_by INTEGER NOT NULL,
            added_at INTEGER NOT NULL,
            last_check INTEGER DEFAULT 0,
            last_tx_id TEXT,
            note TEXT DEFAULT ''
        )
    """)
    
    # 迁移：删除旧的唯一约束（如果存在）
    try:
        c.execute("DROP INDEX IF EXISTS sqlite_autoindex_monitored_addresses_1")
        print("✅ 已移除 monitored_addresses 的唯一约束")
    except:
        pass

    # ========== 新增：自动迁移 note 字段 ==========
    try:
        c.execute("SELECT note FROM monitored_addresses LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE monitored_addresses ADD COLUMN note TEXT DEFAULT ''")
        print("✅ 已为 monitored_addresses 表添加 note 字段")

    # 数据库迁移：为 groups 表添加 joined_at 字段
    try:
        c.execute("SELECT joined_at FROM groups LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE groups ADD COLUMN joined_at INTEGER DEFAULT 0")
        print("✅ 已为 groups 表添加 joined_at 字段")

    # 新增：交易记录表
    c.execute("""
        CREATE TABLE IF NOT EXISTS address_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            tx_id TEXT NOT NULL,
            from_addr TEXT,
            to_addr TEXT,
            amount REAL,
            timestamp INTEGER NOT NULL,
            notified INTEGER DEFAULT 0
        )
    """)

    # 🔥 新增：记账记录表（确保存在）
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
            rate REAL DEFAULT 0,
            created_at INTEGER NOT NULL,
            date TEXT NOT NULL
        )
    """)

    # 🔥 新增：群组用户表
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

    # 🔥 新增：历史会话表
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

    # 创建索引
    c.execute("CREATE INDEX IF NOT EXISTS idx_records_group_id ON accounting_records(group_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_records_session_id ON accounting_records(session_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_records_date ON accounting_records(date)")

    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成: {DB_PATH}")

# ========== 监控地址相关操作 ==========

def get_monitored_addresses(user_id: int = None):
    """获取监控地址，如果指定 user_id 则只返回该用户添加的地址"""
    conn = get_db_connection()
    c = conn.cursor()

    if user_id is not None:
        c.execute("SELECT id, address, chain_type, added_by, added_at, last_check, note FROM monitored_addresses WHERE added_by = ? ORDER BY added_at DESC", (user_id,))
    else:
        c.execute("SELECT id, address, chain_type, added_by, added_at, last_check, note FROM monitored_addresses ORDER BY added_at DESC")

    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "address": r[1], "chain_type": r[2], "added_by": r[3], "added_at": r[4], "last_check": r[5], "note": r[6] or ""} for r in rows]


def add_monitored_address(address: str, chain_type: str, added_by: int, note: str = ""):
    """添加监控地址（支持备注）
    - 不同用户可以添加同一个地址
    - 同一用户不能重复添加同一个地址
    """
    conn = get_db_connection()
    c = conn.cursor()
    try:
        # 检查该用户是否已经添加过这个地址
        c.execute("SELECT id FROM monitored_addresses WHERE address = ? AND added_by = ?", (address, added_by))
        if c.fetchone():
            print(f"用户 {added_by} 已添加过地址 {address}")
            return False

        # 允许不同用户添加
        c.execute("""
            INSERT INTO monitored_addresses (address, chain_type, added_by, added_at, last_check, note)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (address, chain_type, added_by, int(time.time()), note))
        conn.commit()
        return True
    except Exception as e:
        print(f"添加监控地址失败: {e}")
        return False
    finally:
        conn.close()


def remove_monitored_address(address_id: int):
    """删除监控地址"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM monitored_addresses WHERE id = ?", (address_id,))
    conn.commit()
    conn.close()
    return True


def update_address_last_check(address: str, last_check: int):
    """更新地址最后检查时间"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE monitored_addresses SET last_check = ? WHERE address = ?", (last_check, address))
    conn.commit()
    conn.close()


def add_transaction_record(address: str, tx_id: str, from_addr: str, to_addr: str, amount: float, timestamp: int):
    """添加交易记录"""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO address_transactions (address, tx_id, from_addr, to_addr, amount, timestamp, notified)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (address, tx_id, from_addr, to_addr, amount, timestamp))
        conn.commit()
        return True
    except Exception as e:
        print(f"添加交易记录失败: {e}")
        return False
    finally:
        conn.close()


def is_tx_notified(tx_id: str) -> bool:
    """检查交易是否已通知"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT notified FROM address_transactions WHERE tx_id = ?", (tx_id,))
    row = c.fetchone()
    conn.close()
    return row is not None and row[0] == 1


def mark_tx_notified(tx_id: str):
    """标记交易为已通知"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE address_transactions SET notified = 1 WHERE tx_id = ?", (tx_id,))
    conn.commit()
    conn.close()


# ========== 原有函数保持不变 ==========

# db.py - 修复 save_group 函数

def save_group(group_id: str, title: str, category: str = None):
    """保存或更新群组信息（支持自动分类）"""
    import time
    conn = get_db_connection()
    c = conn.cursor()

    try:
        # 先获取现有的 joined_at
        c.execute("SELECT category, joined_at FROM groups WHERE group_id = ?", (group_id,))
        row = c.fetchone()

        if row:
            existing_category = row[0]
            joined_at = row[1] if row[1] else 0
        else:
            existing_category = None
            joined_at = 0

        # 确定分类
        if category is None:
            final_category = existing_category if existing_category else '未分类'
        else:
            final_category = category

        # 如果是新群组（没有 joined_at），设置当前时间
        if joined_at == 0:
            joined_at = int(time.time())

        # 如果分类是"未分类"，尝试自动识别
        if final_category == '未分类':
            country = detect_country_from_group_name(title)
            if country:
                if ensure_country_category(country):
                    final_category = country
                    print(f"✅ 自动分类：群组「{title}」已归类到「{country}」")

        c.execute("""
            INSERT OR REPLACE INTO groups (group_id, title, last_seen, category, joined_at)
            VALUES (?, ?, ?, ?, ?)
        """, (group_id, title, int(time.time()), final_category, joined_at))

        conn.commit()
        print(f"💾 [DB] 群组 {title} (分类: {final_category}) 已保存。")

    except Exception as e:
        print(f"❌ [DB Error] 保存群组失败: {e}")
        conn.rollback()
    finally:
        conn.close()

# db.py - 添加修复函数

def fix_joined_at():
    """修复现有群组的 joined_at 字段"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT group_id, last_seen FROM groups WHERE joined_at = 0 OR joined_at IS NULL")
    rows = c.fetchall()

    count = 0
    for row in rows:
        group_id = row[0]
        last_seen = row[1] if row[1] else int(time.time())
        c.execute("UPDATE groups SET joined_at = ? WHERE group_id = ?", (last_seen, group_id))
        count += 1

    conn.commit()
    conn.close()
    print(f"✅ 已修复 {count} 个群组的 joined_at")

def delete_group_from_db(group_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    conn.commit()
    count = c.execute("SELECT count(*) FROM groups").fetchone()[0]
    print(f"🗑️ [DB] 群组 {group_id} 已删除。剩余群组数：{count}")
    conn.close()

def get_all_groups_from_db(category: str = None):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if category:
        c.execute("SELECT group_id, title, last_seen, category, joined_at FROM groups WHERE category = ?", (category,))
    else:
        c.execute("SELECT group_id, title, last_seen, category, joined_at FROM groups")

    rows = c.fetchall()
    conn.close()

    # ✅ 处理 joined_at 为空的情况
    result = []
    for row in rows:
        joined_at = row["joined_at"]
        if joined_at is None or joined_at == 0:
            # 如果没有加入时间，用 last_seen 代替
            joined_at = row["last_seen"] if row["last_seen"] else 0

        result.append({
            "id": row["group_id"], 
            "title": row["title"], 
            "last_seen": row["last_seen"], 
            "category": row["category"], 
            "joined_at": joined_at
        })

    return result

def update_group_category(group_id: str, category: str):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE groups SET category = ? WHERE group_id = ?", (category, group_id))
        conn.commit()
        print(f"✅ 群组 {group_id} 分类已更新为: {category}")
        return True
    except Exception as e:
        print(f"❌ 更新分类失败: {e}")
        return False
    finally:
        conn.close()


def get_all_categories():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT category_name, description FROM group_categories ORDER BY category_id")
    rows = c.fetchall()
    conn.close()
    return [{"name": row[0], "description": row[1] or ""} for row in rows]


def add_category(category_name: str, description: str = ""):
    import time
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO group_categories (category_name, description, created_at) VALUES (?, ?, ?)",
                  (category_name, description, int(time.time())))
        conn.commit()
        print(f"✅ 已添加分类: {category_name}")
        return True
    except sqlite3.IntegrityError:
        print(f"❌ 分类已存在: {category_name}")
        return False
    finally:
        conn.close()


def delete_category(category_name: str):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE groups SET category = '未分类' WHERE category = ?", (category_name,))
        c.execute("DELETE FROM group_categories WHERE category_name = ?", (category_name,))
        conn.commit()
        print(f"✅ 已删除分类: {category_name}")
        return True
    except Exception as e:
        print(f"❌ 删除分类失败: {e}")
        return False
    finally:
        conn.close()


def get_groups_by_category():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT category, COUNT(*) as count 
        FROM groups 
        GROUP BY category 
        ORDER BY count DESC
    """)
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def update_group_category_if_needed(group_id: str, group_name: str):
    """
    根据群组名称自动更新群组分类
    如果群组名称包含国家关键词，则自动分类
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT category FROM groups WHERE group_id = ?", (group_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return False

    current_category = row[0]

    # 如果已经分类且不是"未分类"，则不再自动覆盖
    if current_category != '未分类':
        return False

    # 检测国家
    country = detect_country_from_group_name(group_name)

    if country:
        # 确保分类存在
        if ensure_country_category(country):
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE groups SET category = ? WHERE group_id = ?", (country, group_id))
            conn.commit()
            conn.close()
            print(f"✅ 自动分类：群组「{group_name}」已归类到「{country}」")
            return True

    return False
