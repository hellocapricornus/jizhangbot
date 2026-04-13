import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict
import os

class GoogleSheetsReader:
    """Google Sheets 点位数据读取器（使用现代认证）"""

    def __init__(self, credentials_file: str, spreadsheet_id: str, worksheet_name: str = "点位"):
        self.credentials_file = credentials_file
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name
        self.client = None
        self.sheet = None
        self._cached_points = None
        self._connect()

    def _connect(self):
        """连接 Google Sheets"""
        try:
            if not os.path.exists(self.credentials_file):
                print(f"❌ 凭证文件不存在: {self.credentials_file}")
                return

            scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
            creds = Credentials.from_service_account_file(
                self.credentials_file, 
                scopes=scope
            )
            self.client = gspread.authorize(creds)
            spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            self.sheet = spreadsheet.worksheet(self.worksheet_name)
            print("✅ Google Sheets 连接成功")
        except Exception as e:
            print(f"❌ Google Sheets 连接失败: {e}")

    def get_all_points(self) -> List[Dict]:
        """获取所有点位数据"""
        if self._cached_points is not None:
            return self._cached_points

        if not self.sheet:
            return []

        try:
            records = self.sheet.get_all_records()
            points = []

            for row in records:
                point = {
                    "公群": self._safe_str(row.get("公群", "")),
                    "昵称": self._safe_str(row.get("昵称", "")),
                    "用户ID": self._safe_str(row.get("用户ID", "")),
                    "合作方": self._safe_str(row.get("合作方", "")),
                    "国家": self._safe_str(row.get("国家", "")),
                    "进算拖算": self._safe_str(row.get("进算拖算", "")),
                    "料性": self._safe_str(row.get("料性", "")),
                    "卡/钱包": self._safe_str(row.get("卡/钱包", "")),
                    "费率": self._parse_number(row.get("费率", 0)),
                    "汇率": self._parse_number(row.get("汇率", 0)),
                    "日期": self._safe_str(row.get("日期", "")),
                    "备注": self._safe_str(row.get("备注", "")),
                    "业务员": self._safe_str(row.get("业务员", "")),
                    "参考价": self._safe_str(row.get("参考价", ""))
                }

                if point["费率"] > 0 and point["汇率"] > 0 and point["国家"]:
                    points.append(point)

            self._cached_points = points
            print(f"✅ 加载了 {len(points)} 条点位数据")
            return points
        except Exception as e:
            print(f"读取表格失败: {e}")
            return []

    def _safe_str(self, value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _parse_number(self, value) -> float:
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return float(value)

        str_value = str(value).strip()
        str_value = str_value.replace("%", "").replace(",", "")

        if '/' in str_value:
            try:
                parts = str_value.split('/')
                return float(parts[0]) / float(parts[1])
            except:
                pass

        try:
            return float(str_value)
        except:
            return 0

    def filter_by_country(self, points: List[Dict], country: str) -> List[Dict]:
        """按国家筛选"""
        if not country:
            return points
        country_lower = country.lower()
        return [p for p in points if country_lower in p["国家"].lower()]

    def calculate_ratio(self, point_a: Dict, point_b: Dict) -> float:
        """计算 A 相对于 B 的性价比系数"""
        rate_a = point_a["汇率"]
        rate_b = point_b["汇率"]
        fee_a = point_a["费率"]
        fee_b = point_b["费率"]

        if rate_b == 0:
            return 999

        return (rate_a / rate_b) + (fee_a - fee_b) / 100

    def find_cheapest(self, country: str = None, limit: int = 5) -> Dict:
        """找出最便宜的点位"""
        points = self.get_all_points()

        if country:
            points = self.filter_by_country(points, country)

        if not points:
            return {
                "success": False,
                "error": f"未找到{country or '任何'}国家的点位数据",
                "points": []
            }

        for point in points:
            point["_index"] = point["汇率"] + point["费率"]

        sorted_points = sorted(points, key=lambda x: x["_index"])
        cheapest = sorted_points[0]

        ranking = []
        for i, point in enumerate(sorted_points[:limit], 1):
            if point == cheapest:
                ratio = 1.0
                is_cheapest = True
            else:
                ratio = self.calculate_ratio(point, cheapest)
                is_cheapest = False

            ranking.append({
                "rank": i,
                "公群": point.get("公群", ""),
                "昵称": point.get("昵称", ""),
                "国家": point.get("国家", ""),
                "费率": point.get("费率", 0),
                "汇率": point.get("汇率", 0),
                "合作方": point.get("合作方", ""),
                "料性": point.get("料性", ""),
                "卡/钱包": point.get("卡/钱包", ""),
                "进算拖算": point.get("进算拖算", ""),
                "备注": point.get("备注", ""),
                "业务员": point.get("业务员", ""),
                "日期": point.get("日期", ""),
                "是否最便宜": is_cheapest
            })

        comparisons = []
        for point in sorted_points[1:5]:
            ratio = self.calculate_ratio(point, cheapest)
            cheaper_or_expensive = "便宜" if ratio < 1 else "贵"
            comparisons.append({
                "name": point["昵称"],
                "group": point["公群"],
                "ratio": round(ratio, 4),
                "比较结果": f"{cheaper_or_expensive} {abs(1-ratio)*100:.1f}%"
            })

        return {
            "success": True,
            "country": country or "全部",
            "total_count": len(points),
            "cheapest": ranking[0] if ranking else None,
            "ranking": ranking,
            "comparisons": comparisons
        }

    def refresh_cache(self):
        """强制刷新缓存，重新从 Google Sheets 读取数据"""
        self._cached_points = None
        print("🔄 定时刷新：正在重新加载 Google Sheets 数据...")
        points = self.get_all_points()
        print(f"✅ 定时刷新完成，加载了 {len(points)} 条点位数据")
        return points


_sheets_reader = None

def init_google_sheets(credentials_file: str, spreadsheet_id: str):
    """初始化 Google Sheets"""
    global _sheets_reader
    if not credentials_file or not spreadsheet_id:
        print("⚠️ Google Sheets 配置不完整，跳过初始化")
        return False

    try:
        _sheets_reader = GoogleSheetsReader(credentials_file, spreadsheet_id)
        return True
    except Exception as e:
        print(f"Google Sheets 初始化失败: {e}")
        return False

def get_sheets_reader():
    return _sheets_reader
