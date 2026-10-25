"""台彩 BINGO BINGO 開獎資料抓取與快取。"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests
import streamlit as st

from bingo.logic import parse_prize_table

TW_TZ = timezone(timedelta(hours=8))
API_URL = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult"
DRAWS_PER_DAY = 203  # 07:05 ~ 23:55 每 5 分鐘一期


def now_tw() -> datetime:
    return datetime.now(TW_TZ)


def today_tw_str() -> str:
    return now_tw().strftime("%Y-%m-%d")


class BingoScraper:
    @staticmethod
    def _extract_time(item: dict, fallback_date: str) -> str:
        keys_to_try = ["drawDate", "openDate", "drawTime", "openTime", "listDate", "Opendate", "DrawDate", "date", "time"]
        for k in keys_to_try:
            val = item.get(k)
            if val and isinstance(val, str):
                if "0001-01-01" in val: continue
                if "T" in val and len(val) >= 16: return val[:16].replace("T", " ")
                elif len(val) >= 5 and ":" in val: return f"{fallback_date} {val[:5]}"

        for val in item.values():
            if isinstance(val, str):
                if "0001-01-01" in val: continue
                if "T" in val and len(val) >= 16 and val[13] == ":": return val[:16].replace("T", " ")
                elif len(val) >= 5 and val[2] == ":" and val[:2].isdigit(): return f"{fallback_date} {val[:5]}"
        return f"{fallback_date} 未知"

    @staticmethod
    def fetch_by_date(date_str: str) -> List[Dict]:
        # 過去日期的開獎結果不會再變動，可長時間快取；今天(含未來)仍在開獎，只快取 30 秒
        if date_str < today_tw_str(): return BingoScraper._fetch_past_date(date_str)
        return BingoScraper._fetch_recent_date(date_str)

    @staticmethod
    @st.cache_data(ttl=86400, show_spinner=False, max_entries=500)
    def _fetch_past_date(date_str: str) -> List[Dict]:
        return BingoScraper._request_by_date(date_str)

    @staticmethod
    @st.cache_data(ttl=30, show_spinner=False)
    def _fetch_recent_date(date_str: str) -> List[Dict]:
        return BingoScraper._request_by_date(date_str)

    @staticmethod
    def _request_by_date(date_str: str) -> List[Dict]:
        params = {"openDate": date_str, "pageNum": 1, "pageSize": 250}
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = requests.get(API_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("rtCode") != 0 or "content" not in data: return []

        valid_items = [item for item in data["content"]["bingoQueryResult"] if item.get("bigShowOrder") and item.get("bullEyeTop") != "－"]
        if not valid_items: return []

        anchor_issue, anchor_time = None, None
        for item in valid_items:
            t = BingoScraper._extract_time(item, date_str)
            if "未知" not in t:
                try:
                    anchor_issue = int(item["drawTerm"])
                    anchor_time = datetime.strptime(t, "%Y-%m-%d %H:%M")
                    break
                except Exception: pass

        if anchor_issue is None:
            anchor_issue = min(int(item["drawTerm"]) for item in valid_items)
            anchor_time = datetime.strptime(f"{date_str} 07:05", "%Y-%m-%d %H:%M")

        history_draws = []
        for item in valid_items:
            issue_str = str(item["drawTerm"])
            extracted_time = BingoScraper._extract_time(item, date_str)

            if "未知" in extracted_time:
                try:
                    issue_diff = int(issue_str) - anchor_issue
                    extracted_time = (anchor_time + timedelta(minutes=5 * issue_diff)).strftime("%Y-%m-%d %H:%M")
                except Exception: pass

            history_draws.append({
                "issue": issue_str,
                "time": extracted_time,
                "date": date_str,
                "numbers": sorted([int(n) for n in item["bigShowOrder"]]),
                "super_num": int(item["bullEyeTop"]),
                # 該期官方獎金 (含加碼)；格式不符時為 None，對獎時退回標準獎金表
                "prize_table": parse_prize_table(item.get("starDetails")),
            })
        return sorted(history_draws, key=lambda d: int(d["issue"]), reverse=True)

    @staticmethod
    def fetch_range(start_issue: str, count: int, history_data: List[Dict]) -> List[Dict]:
        start_issue_int = int(start_issue)
        start_date_str = None
        for item in history_data:
            if item["issue"] == start_issue:
                start_date_str = item.get("date")
                break

        if not start_date_str and history_data:
            try:
                latest_issue_int = int(history_data[0]["issue"])
                latest_date_str = history_data[0].get("date", today_tw_str())
                latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d")
                diff = latest_issue_int - start_issue_int
                if diff > 0:
                    start_date_str = (latest_date - timedelta(days=diff // DRAWS_PER_DAY)).strftime("%Y-%m-%d")
                else:
                    start_date_str = latest_date_str
            except Exception: pass

        if not start_date_str: start_date_str = today_tw_str()
        try: start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError: start_date = now_tw()

        days_to_fetch = (count // DRAWS_PER_DAY) + 3
        fetch_start = start_date - timedelta(days=1)

        all_draws = []
        for i in range(days_to_fetch):
            all_draws.extend(BingoScraper.fetch_by_date((fetch_start + timedelta(days=i)).strftime("%Y-%m-%d")))

        issue_dict = {item["issue"]: item for item in all_draws}
        return [issue_dict[str(start_issue_int + i)] for i in range(count) if str(start_issue_int + i) in issue_dict]

    @staticmethod
    @st.cache_data(ttl=30, show_spinner=False)
    def fetch_data() -> Tuple[List[Dict], str]:
        now = now_tw()
        history_draws = []
        try:
            for i in range(3):
                history_draws.extend(BingoScraper.fetch_by_date((now - timedelta(days=i)).strftime("%Y-%m-%d")))
            if not history_draws: raise ValueError("近期皆無開獎資料。")
            history_draws.sort(key=lambda d: int(d["issue"]), reverse=True)
            return history_draws, f"{(now - timedelta(days=2)).strftime('%m/%d')} ~ {now.strftime('%m/%d')}"
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"API 連線異常: {e}")
