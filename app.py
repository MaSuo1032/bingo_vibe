import streamlit as st
import requests
import urllib3
import pandas as pd
from collections import Counter
import random
import time
import json
import os
from typing import List, Dict, Tuple
from datetime import datetime, timedelta, timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 資料層 (Model)
# ==========================================
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
    def _fetch_by_date(date_str: str) -> List[Dict[str, any]]:
        api_url = f"https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult?openDate={date_str}&pageNum=1&pageSize=250"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = requests.get(api_url, headers=headers, timeout=10, verify=False)
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
                "super_num": int(item["bullEyeTop"])
            })
        return history_draws

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
                latest_date_str = history_data[0].get("date", datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"))
                latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d")
                diff = latest_issue_int - start_issue_int
                if diff > 0:
                    start_date_str = (latest_date - timedelta(days=diff // 203)).strftime("%Y-%m-%d")
                else:
                    start_date_str = latest_date_str
            except Exception: pass

        if not start_date_str: start_date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        try: start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError: start_date = datetime.now(timezone(timedelta(hours=8)))
            
        days_to_fetch = (count // 203) + 3
        fetch_start = start_date - timedelta(days=1)
        
        all_draws = []
        for i in range(days_to_fetch):
            all_draws.extend(BingoScraper._fetch_by_date((fetch_start + timedelta(days=i)).strftime("%Y-%m-%d")))
            
        issue_dict = {item["issue"]: item for item in all_draws}
        return [issue_dict[str(start_issue_int + i)] for i in range(count) if str(start_issue_int + i) in issue_dict]

    @staticmethod
    @st.cache_data(ttl=30, show_spinner=False)
    def fetch_data() -> Tuple[List[Dict], str]:
        now = datetime.now(timezone(timedelta(hours=8)))
        history_draws = []
        try:
            for i in range(3):
                history_draws.extend(BingoScraper._fetch_by_date((now - timedelta(days=i)).strftime("%Y-%m-%d")))
            if not history_draws: raise ValueError("近期皆無開獎資料。")
            return history_draws, f"{(now - timedelta(days=2)).strftime('%m/%d')} ~ {now.strftime('%m/%d')}"
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"API 連線異常: {e}")

# ==========================================
# 2. 儲存層 (Storage)
# ==========================================
class StorageManager:
    FILE_PATH = "bingo_bets_history.json"
    
    @staticmethod
    def load_all() -> Dict[str, List[Dict]]:
        if os.path.exists(StorageManager.FILE_PATH):
            try:
                with open(StorageManager.FILE_PATH, "r", encoding="utf-8") as f: 
                    return json.load(f)
            except Exception: 
                return {}
        return {}

    @staticmethod
    def load_bets(username: str) -> List[Dict]:
        all_data = StorageManager.load_all()
        return all_data.get(username, [])

    @staticmethod
    def save_bets(username: str, bets: List[Dict]):
        all_data = StorageManager.load_all()
        all_data[username] = bets
        with open(StorageManager.FILE_PATH, "w", encoding="utf-8") as f: 
            json.dump(all_data, f, ensure_ascii=False, indent=4)

# ==========================================
# 3. 邏輯層 (Controller)
# ==========================================
class BingoGameLogic:
    PRIZE_TABLE = {
        10: {10: 5000000, 9: 250000, 8: 25000, 7: 2500, 6: 250, 5: 25, 0: 25},
        9: {9: 1000000, 8: 100000, 7: 3000, 6: 500, 5: 100, 4: 25, 0: 25},
        8: {8: 500000, 7: 20000, 6: 1000, 5: 200, 4: 25, 0: 25},
        7: {7: 80000, 6: 3000, 5: 300, 4: 50, 3: 25},
        6: {6: 50000, 5: 1200, 4: 200, 3: 25}, 
        5: {5: 10000, 4: 600, 3: 50},          
        4: {4: 2000, 3: 150, 2: 25},           
        3: {3: 1000, 2: 50},                   
        2: {2: 150, 1: 25},                    
        1: {1: 75}                             
    }
    
    @staticmethod
    def calculate_prize(star_count: int, matched_count: int, multiplier: int = 1) -> int:
        return BingoGameLogic.PRIZE_TABLE.get(star_count, {}).get(matched_count, 0) * multiplier

    @staticmethod
    def get_frequencies(history: List[Dict]) -> Counter: 
        return Counter([num for draw in history for num in draw['numbers']])

    @staticmethod
    def gen_smart(history: List[Dict], star: int, mode="hot") -> List[int]:
        if not history: return sorted(random.sample(range(1, 81), star))
        nums = [i[0] for i in BingoGameLogic.get_frequencies(history).most_common()]
        all_ranked = nums + list(set(range(1, 81)) - set(nums))
        if mode == "hot": pool = all_ranked[:max(15, star)]
        elif mode == "cold": pool = all_ranked[::-1][:max(15, star)]
        elif mode == "mid": pool = all_ranked[20:60] if len(all_ranked[20:60]) >= star else all_ranked
        return sorted(random.sample(pool, star))

    @staticmethod
    def gen_drag(history: List[Dict], star: int) -> List[int]:
        if len(history) < 2: return sorted(random.sample(range(1, 81), star))
        last_draw = history[0]['numbers']
        associated_nums = []
        for draw in history[1:51]:
            shared = set(last_draw) & set(draw['numbers'])
            if shared:
                associated_nums.extend([n for n in draw['numbers'] if n not in last_draw])
        if not associated_nums: return sorted(random.sample(range(1, 81), star))
        
        counter = Counter(associated_nums)
        top_drag = [num for num, _ in counter.most_common(max(15, star))]
        return sorted(random.sample(top_drag, star))

    @staticmethod
    def gen_dormant_drag(history: List[Dict], star: int) -> List[int]:
        if not history: return sorted(random.sample(range(1, 81), star))
        
        counter = Counter([num for draw in history for num in draw['numbers']])
        top_20_hot = [num for num, _ in counter.most_common(20)]
        
        last_seen = {i: -1 for i in range(1, 81)}
        for current_idx, draw in enumerate(history):
            for num in draw['numbers']:
                if last_seen[num] == -1: last_seen[num] = current_idx
        missing_counts = {num: (idx if idx != -1 else len(history)) for num, idx in last_seen.items()}
        
        hot_but_dormant = sorted([(num, missing_counts[num]) for num in top_20_hot], key=lambda x: x[1], reverse=True)
        if not hot_but_dormant: return sorted(random.sample(range(1, 81), star))
        
        top_dormant_num = hot_but_dormant[0][0]
        
        associated_nums = []
        for draw in history:
            if top_dormant_num in draw['numbers']:
                associated_nums.extend([n for n in draw['numbers'] if n != top_dormant_num])
                
        drag_counter = Counter(associated_nums)
        top_drags = [num for num, _ in drag_counter.most_common()]
        
        pool = [top_dormant_num] + top_drags
        unique_pool = []
        for n in pool:
            if n not in unique_pool: unique_pool.append(n)
            
        if len(unique_pool) < star:
            remaining = list(set(range(1, 81)) - set(unique_pool))
            unique_pool.extend(random.sample(remaining, star - len(unique_pool)))
            
        return sorted(unique_pool[:star])

    @staticmethod
    def gen_repeat(history: List[Dict], star: int) -> List[int]:
        if not history: return sorted(random.sample(range(1, 81), star))
        return sorted(random.sample(history[0]['numbers'], min(star, len(history[0]['numbers']))))

    @staticmethod
    def gen_tail(star: int) -> List[int]:
        tails = random.sample(range(10), 2)
        pool = [n for n in range(1, 81) if (n % 10) in tails]
        return sorted(random.sample(pool if len(pool) >= star else range(1, 81), star))

    @staticmethod
    def gen_extreme(star: int, mode: str) -> List[int]:
        pool = []
        if mode == "odd": pool = [n for n in range(1, 81) if n % 2 != 0]
        elif mode == "even": pool = [n for n in range(1, 81) if n % 2 == 0]
        elif mode == "big": pool = range(41, 81)
        elif mode == "small": pool = range(1, 41)
        return sorted(random.sample(pool, star))

    @staticmethod
    def fill_remaining_rand(picks: List[int], star: int) -> List[int]:
        picks = picks[:star]
        if len(picks) >= star: return sorted(picks)
        return sorted(picks + random.sample(list(set(range(1, 81)) - set(picks)), star - len(picks)))

    @staticmethod
    def fill_remaining_hot(picks: List[int], star: int, history: List[Dict]) -> List[int]:
        picks = picks[:star]
        if len(picks) >= star: return sorted(picks)
        freq = BingoGameLogic.get_frequencies(history)
        hot_nums = [i[0] for i in freq.most_common()]
        available_hot = [n for n in hot_nums if n not in picks]
        needed = star - len(picks)
        pool_size = max(needed + 5, 10) 
        chosen = random.sample(available_hot[:pool_size], needed)
        return sorted(picks + chosen)

# ==========================================
# 4. 視覺層 (View)
# ==========================================
class BingoUI:
    @staticmethod
    def setup():
        st.set_page_config(page_title="BINGO 專業看盤加碼版", page_icon="🎰", layout="wide")
        st.markdown("""
        <style>
            .ball-container { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
            .ball { width: 42px; height: 42px; line-height: 42px; border-radius: 50%; text-align: center; font-weight: 900; font-size: 18px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); }
            .ball-normal { background-color: #FFD700; color: #333; }
            .ball-super { background-color: #FF3B30; color: #FFF; }
            .ball-user { background-color: #007AFF; color: #FFF; }
            .ball-match { background-color: #34C759; color: #FFF; }
            .stTabs [data-baseweb="tab-list"] { justify-content: center; }
            div[data-testid="stMetricValue"] { font-size: 2rem; }
            .time-tag { color: #666; font-size: 0.85em; margin-left: 10px; background: #eee; padding: 2px 8px; border-radius: 12px; }
            .bonus-tag { background: linear-gradient(90deg, #ff416c, #ff4b2b); color: white; padding: 4px 12px; border-radius: 15px; font-weight: bold; margin-bottom: 10px; display: inline-block; }
            .assoc-box { background-color: #f8f9fa; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 5px solid #007AFF;}
            .hot-miss-box { background-color: #fff3e0; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 5px solid #ff9800;}
            .type-tag-real { background-color: #34C759; color: white; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; }
            .type-tag-virtual { background-color: #007AFF; color: white; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; }
        </style>
        """, unsafe_allow_html=True)

    @staticmethod
    def render_balls(nums: list | int, btype: str = "normal") -> str:
        nums = [nums] if isinstance(nums, int) else sorted(nums)
        html = "<div class='ball-container'>"
        for n in nums: html += f"<div class='ball ball-{btype}'>{n:02d}</div>"
        return html + "</div>"

# ==========================================
# 5. 主程式 (Main Application)
# ==========================================
def main():
    BingoUI.setup()

    with st.sidebar:
        st.title("👤 玩家帳戶系統")
        input_user = st.text_input("請輸入您的專屬暱稱：", value="預設玩家", help="輸入不同暱稱即可切換帳號，歷史紀錄完全獨立！")
        
        if 'current_user' not in st.session_state or st.session_state.current_user != input_user:
            st.session_state.current_user = input_user
            st.session_state.bet_history = StorageManager.load_bets(input_user)
            st.session_state.cart = [] 
            st.session_state.user_picks = []
            st.session_state.import_picks = []
        
        st.success(f"目前登入身份：**{st.session_state.current_user}**")
        st.divider()
        st.markdown("💡 **操作提示**\n只要不清除瀏覽器快取或刪除後台檔案，您的紀錄將永久保存在此暱稱下。")

    if 'cart_warning' not in st.session_state: st.session_state.cart_warning = False
    if 'import_msg' not in st.session_state: st.session_state.import_msg = None

    st.title("🎰 BINGO BINGO 真實對獎與包牌系統")
    st.markdown("<div class='bonus-tag'>🔥 系統已全面套用 2026 台彩最新「1~6 星」限時加碼賠率！</div>", unsafe_allow_html=True)

    try:
        history_data, target_date = BingoScraper.fetch_data()
        latest_issue = int(history_data[0]['issue'])
    except Exception as e:
        st.error(f"🚨 系統連線失敗: {e}"); st.stop()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 開獎紀錄", "🔥 今日走勢與深度分析", "🎫 虛擬下注 & 實體匯入", "📋 我的投注紀錄", "🎯 單次實體對獎"
    ])

    with tab1:
        st.subheader(f"📝 近期開獎紀錄 (共載入 {len(history_data)} 期 | 涵蓋 {target_date})")
        with st.container(height=650):
            for draw in history_data[:200]:
                with st.container(border=True):
                    c1, c2 = st.columns([1, 4])
                    c1.markdown(f"**第 `{draw['issue']}` 期**<br><span class='time-tag'>🕒 {draw['time']}</span>", unsafe_allow_html=True)
                    c2.markdown(BingoUI.render_balls(draw['numbers'], "normal") + BingoUI.render_balls(draw['super_num'], "super"), unsafe_allow_html=True)

    with tab2:
        st.subheader("📊 今日專屬實戰盤勢分析")
        today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        today_data = [d for d in history_data if d["time"].startswith(today_str) or d.get("date") == today_str]
        
        if not today_data and history_data:
            latest_date_str = history_data[0].get("date", history_data[0]["time"][:10])
            today_data = [d for d in history_data if d["time"].startswith(latest_date_str) or d.get("date") == latest_date_str]
            st.info(f"💡 今日 ({today_str}) 尚未有開獎資料，以下顯示最新開獎日 ({latest_date_str}) 的盤勢分析。")

        st.markdown(f"**📍 本日已開出：** `{len(today_data)}` 期")
        
        if today_data:
            counter = BingoGameLogic.get_frequencies(today_data)
            
            st.markdown("### 🏆 今日極端冷熱門排行榜 (Top 15)")
            full_counts = {i: counter.get(i, 0) for i in range(1, 81)}
            sorted_hot = sorted(full_counts.items(), key=lambda x: (-x[1], x[0]))[:15]
            sorted_cold = sorted(full_counts.items(), key=lambda x: (x[1], x[0]))[:15]

            col_hot, col_cold = st.columns(2)
            with col_hot:
                st.markdown("##### 🔥 最常出現 15 名")
                df_hot = pd.DataFrame(sorted_hot, columns=["號碼", "出現次數"])
                df_hot["號碼"] = df_hot["號碼"].apply(lambda x: f"🔥 {x:02d}")
                df_hot.index = range(1, 16) 
                st.dataframe(df_hot, use_container_width=True)
            
            with col_cold:
                st.markdown("##### ❄️ 最少出現 15 名")
                df_cold = pd.DataFrame(sorted_cold, columns=["號碼", "出現次數"])
                df_cold["號碼"] = df_cold["號碼"].apply(lambda x: f"❄️ {x:02d}")
                df_cold.index = range(1, 16) 
                st.dataframe(df_cold, use_container_width=True)
            
            st.divider()

            st.markdown("### 🕵️‍♂️ 潛伏熱門號 (熱門號碼但近期未開)")
            st.markdown("這些號碼是今天的「常客榜首」，但剛好已經『休息』了一段時間沒開出，隨時可能反彈爆發！")
            
            last_seen = {i: -1 for i in range(1, 81)}
            for current_idx, draw in enumerate(today_data):
                for num in draw['numbers']:
                    if last_seen[num] == -1: last_seen[num] = current_idx
            missing_counts = {num: (idx if idx != -1 else len(today_data)) for num, idx in last_seen.items()}
            
            top_20_hot_nums = [num for num, _ in counter.most_common(20)]
            hot_but_dormant = sorted([(num, missing_counts[num]) for num in top_20_hot_nums], key=lambda x: x[1], reverse=True)[:5]
            
            col_d1, col_d2, col_d3, col_d4, col_d5 = st.columns(5)
            cols_d = [col_d1, col_d2, col_d3, col_d4, col_d5]
            for idx, (dormant_num, miss_cnt) in enumerate(hot_but_dormant):
                with cols_d[idx]: 
                    st.metric(label=f"🔥熱號 {dormant_num:02d}", value="潛伏", delta=f"{miss_cnt} 期未開", delta_color="inverse")

            st.divider()

            st.markdown("### 🌡️ 號碼區間熱度分佈")
            zones = {f"{i*10+1:02d}-{i*10+10:02d}": 0 for i in range(8)}
            for num, cnt in counter.items():
                zone_idx = (num - 1) // 10
                zones[f"{zone_idx*10+1:02d}-{zone_idx*10+10:02d}"] += cnt
            
            df_zones = pd.DataFrame(list(zones.items()), columns=["區間", "開出總次數"]).set_index("區間")
            st.bar_chart(df_zones, color="#FF4B2B")
            hottest_zone = max(zones, key=zones.get)
            st.caption(f"💡 目前最燙手的板塊為 **「{hottest_zone}」** 區間，喜歡包牌的玩家可鎖定此範圍。")
            st.divider()

            st.markdown("### 🎯 焦點霸主 & 共伴拖牌效應")
            top_hot_5 = counter.most_common(5)
            for hot_num, count in top_hot_5:
                associated_nums = []
                for draw in today_data:
                    if hot_num in draw['numbers']:
                        associated_nums.extend([n for n in draw['numbers'] if n != hot_num])
                assoc_top3 = Counter(associated_nums).most_common(3)
                assoc_str = '、 '.join([f"「{n:02d}」({c}次)" for n, c in assoc_top3])
                st.info(f"👑 **今日霸主 {hot_num:02d}** (開出 {count} 次)\n\n ➡️ 🎯 **常伴隨開出 (拖牌)：** {assoc_str}")
            
            st.divider()

            st.markdown("### 🥶 極端冷牌追蹤 (最大遺漏期數)")
            st.markdown("尋找已經非常久沒開出來的冷門號碼。")
            top_missing = sorted(missing_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            
            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
            cols_m = [col_m1, col_m2, col_m3, col_m4, col_m5]
            for idx, (miss_num, miss_cnt) in enumerate(top_missing):
                with cols_m[idx]: st.metric(label=f"❄️號碼 {miss_num:02d}", value="極冷", delta=f"{miss_cnt} 期未開", delta_color="inverse")
            st.divider()

            st.markdown("### 📈 進階特徵版路 & 超級獎號解析")
            total_balls = len(today_data) * 20
            bigs = sum(1 for draw in today_data for n in draw['numbers'] if n >= 41)
            smalls = total_balls - bigs
            odds = sum(1 for draw in today_data for n in draw['numbers'] if n % 2 != 0)
            evens = total_balls - odds
            
            repeats = []
            for i in range(len(today_data)-1):
                curr_set = set(today_data[i]['numbers'])
                prev_set = set(today_data[i+1]['numbers'])
                repeats.append(len(curr_set & prev_set))
            avg_repeat = sum(repeats) / len(repeats) if repeats else 0

            super_nums = [draw['super_num'] for draw in today_data]
            super_big = sum(1 for n in super_nums if n >= 41)
            super_small = len(super_nums) - super_big
            super_odd = sum(1 for n in super_nums if n % 2 != 0)
            super_even = len(super_nums) - super_odd

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.markdown("**📉 整體大小/單雙**")
                st.write(f"大區: {bigs/total_balls:.1%} | 小區: {smalls/total_balls:.1%}")
                st.write(f"單數: {odds/total_balls:.1%} | 雙數: {evens/total_balls:.1%}")
                st.metric("平均連莊數", f"{avg_repeat:.1f} 顆")

            with col_b:
                st.markdown("**🌟 超級獎號獨立特徵**")
                st.write(f"大區: {super_big} 次 | 小區: {super_small} 次")
                st.write(f"單數: {super_odd} 次 | 雙數: {super_even} 次")
                st.caption("玩超級獎號的玩家請留意此偏差走勢！")

            tails = [n % 10 for draw in today_data for n in draw['numbers']]
            top_tails = Counter(tails).most_common(3)
            with col_c:
                st.markdown("**🎯 最旺尾數排行**")
                for rank, (tail_num, t_count) in enumerate(top_tails):
                    st.write(f"🏆 第 {rank+1} 名：**{tail_num} 尾** (開 {t_count} 次)")

    with tab3:
        st.subheader("🎫 下注與實體彩券管理中樞")
        bet_mode = st.radio("請選擇操作模式：", ["🎮 虛擬模擬下注 (測試策略)", "🧾 匯入已購買的實體彩券 (系統代管對獎)"], horizontal=True)
        st.divider()

        if bet_mode == "🎮 虛擬模擬下注 (測試策略)":
            next_issue = latest_issue + 1
            st.info(f"💡 目前虛擬下注的目標起算期數為：**第 `{next_issue}` 期**")
            
            def apply_strat(strat, *args):
                sc = st.session_state.star_input
                if strat == "hot": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "hot")
                elif strat == "cold": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "cold")
                elif strat == "mid": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "mid")
                elif strat == "drag": st.session_state.user_picks = BingoGameLogic.gen_drag(history_data, sc)
                elif strat == "dormant_drag": st.session_state.user_picks = BingoGameLogic.gen_dormant_drag(history_data, sc)
                elif strat == "rep": st.session_state.user_picks = BingoGameLogic.gen_repeat(history_data, sc)
                elif strat == "tail": st.session_state.user_picks = BingoGameLogic.gen_tail(sc)
                elif strat in ["odd", "even", "big", "small"]: st.session_state.user_picks = BingoGameLogic.gen_extreme(sc, strat)
                elif strat == "fill_rand": st.session_state.user_picks = BingoGameLogic.fill_remaining_rand(st.session_state.user_picks, sc)
                elif strat == "fill_hot": st.session_state.user_picks = BingoGameLogic.fill_remaining_hot(st.session_state.user_picks, sc, history_data)

            def on_star_change():
                sc = st.session_state.star_input
                if len(st.session_state.user_picks) > sc: st.session_state.user_picks = st.session_state.user_picks[:sc]

            def add_single_to_cart():
                sc = st.session_state.star_input
                picks = st.session_state.user_picks
                if len(picks) == sc:
                    st.session_state.cart.append({"star": sc, "picks": picks.copy()})
                    st.session_state.user_picks = [] 
                    st.session_state.cart_warning = False
                else:
                    st.session_state.cart_warning = True

            with st.container(border=True):
                g1, g2, g3 = st.columns(3)
                multiplier = g1.number_input("💰 全局倍數", 1, 50, 1)
                multi_draw = g2.number_input("🔁 連續買幾期", 1, 50, 1)
                batch_count = g3.number_input("⚡ 批次產生組數", 1, 50, 1)
                st.divider()

                c1, c2 = st.columns([1, 4])
                with c1: star_count = st.number_input("📌 單筆星數", 1, 10, 5, key="star_input", on_change=on_star_change)
                with c2: st.multiselect("✍️ 手動選號 (或點擊下方策略全自動產生)", range(1, 81), max_selections=star_count, key="user_picks")
                
                st.markdown("##### 🧰 專業選號工具箱 (點擊自動套用)")
                row1_1, row1_2, row1_3, row1_4 = st.columns(4)
                row1_1.button("🔥 熱門特徵", on_click=apply_strat, args=("hot",), use_container_width=True)
                row1_2.button("❄️ 冷門特徵", on_click=apply_strat, args=("cold",), use_container_width=True)
                row1_3.button("☯️ 溫態避險", on_click=apply_strat, args=("mid",), use_container_width=True)
                row1_4.button("💡 隨機補滿", on_click=apply_strat, args=("fill_rand",), use_container_width=True)

                row2_1, row2_2, row2_3, row2_4 = st.columns(4)
                row2_1.button("🧲 上期拖牌", on_click=apply_strat, args=("drag",), use_container_width=True)
                row2_2.button("🕵️‍♂️ 潛伏+拖牌", on_click=apply_strat, args=("dormant_drag",), use_container_width=True, help="優先鎖定近期未開的熱門號，並搭配其專屬拖牌")
                row2_3.button("🎯 同尾數", on_click=apply_strat, args=("tail",), use_container_width=True)
                row2_4.button("🧠 熱門補滿", on_click=apply_strat, args=("fill_hot",), use_container_width=True)

                row3_1, row3_2, row3_3, row3_4 = st.columns(4)
                row3_1.button("🔴 全單數", on_click=apply_strat, args=("odd",), use_container_width=True)
                row3_2.button("🔵 全雙數", on_click=apply_strat, args=("even",), use_container_width=True)
                row3_3.button("📈 全大區(41-80)", on_click=apply_strat, args=("big",), use_container_width=True)
                row3_4.button("📉 全小區(1-40)", on_click=apply_strat, args=("small",), use_container_width=True)
                
                st.button("➕ 將上方號碼加入待結帳區", on_click=add_single_to_cart, use_container_width=True, type="secondary")
                if st.session_state.cart_warning: st.warning("⚠️ 請選滿號碼再加入！")

                st.divider()
                st.markdown(f"##### 🚀 一鍵批次包牌 (直接產生 `{batch_count}` 組加入購物車)")
                b1, b2, b3, b4, b5 = st.columns(5)
                if b1.button(f"🎲 機選", use_container_width=True):
                    for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": sorted(random.sample(range(1, 81), star_count))})
                    st.rerun()
                if b2.button(f"🔥 熱門", use_container_width=True):
                    for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": BingoGameLogic.gen_smart(history_data, star_count, "hot")})
                    st.rerun()
                if b3.button(f"☯️ 溫態", use_container_width=True):
                    for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": BingoGameLogic.gen_smart(history_data, star_count, "mid")})
                    st.rerun()
                if b4.button(f"🧲 拖牌", use_container_width=True):
                    for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": BingoGameLogic.gen_drag(history_data, star_count)})
                    st.rerun()
                if b5.button(f"🕵️‍♂️ 潛伏", use_container_width=True):
                    for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": BingoGameLogic.gen_dormant_drag(history_data, star_count)})
                    st.rerun()

            if st.session_state.cart:
                st.markdown("### 🛒 待下注購物車")
                for i, item in enumerate(st.session_state.cart):
                    with st.container(border=True):
                        cart_c1, cart_c2 = st.columns([10, 1])
                        cart_c1.markdown(f"**{item['star']} 星** | " + BingoUI.render_balls(item['picks'], "user"), unsafe_allow_html=True)
                        if cart_c2.button("❌", key=f"del_cart_{i}"):
                            st.session_state.cart.pop(i)
                            st.rerun()
                
                cart_total_cost = len(st.session_state.cart) * 25 * multiplier * multi_draw
                st.info(f"🧾 本次結帳總計: **{len(st.session_state.cart)}** 組選號 x **{multiplier}** 倍 x **{multi_draw}** 期 = 扣除本金 **NT$ {cart_total_cost:,}**")

                col_submit, col_clear = st.columns([3, 1])
                if col_submit.button("📝 確認送出虛擬注單", type="primary", use_container_width=True):
                    for item in st.session_state.cart:
                        for i in range(multi_draw):
                            st.session_state.bet_history.insert(0, {
                                "type": "virtual",
                                "issue": str(next_issue + i),
                                "star": item['star'],
                                "multiplier": multiplier,
                                "cost": 25 * multiplier,
                                "prize": 0,
                                "picks": item['picks'].copy(),
                                "status": "waiting",
                                "timestamp": datetime.now().strftime("%m/%d %H:%M:%S")
                            })
                    StorageManager.save_bets(st.session_state.current_user, st.session_state.bet_history)
                    st.session_state.cart.clear()
                    st.success("✅ 虛擬下注成功！資料已寫入「我的投注紀錄」。")
                    time.sleep(1.5)
                    st.rerun()
                if col_clear.button("🗑️ 清空購物車", use_container_width=True):
                    st.session_state.cart.clear(); st.rerun()

        else:
            st.markdown("#### 📥 將手邊的實體彩券匯入系統代管")
            st.write("把彩券上的資訊輸入進來，系統會自動在後台持續幫你對獎，再也不怕漏看！")
            
            def on_import_star_change():
                sc = st.session_state.import_star
                if len(st.session_state.import_picks) > sc: 
                    st.session_state.import_picks = st.session_state.import_picks[:sc]

            def submit_import():
                issue = st.session_state.import_issue
                draws = st.session_state.import_draws
                multi = st.session_state.import_multi
                star = st.session_state.import_star
                picks = st.session_state.import_picks
                
                if not issue.isdigit():
                    st.session_state.import_msg = ("error", "⚠️ 起始期號請輸入純數字！")
                    return
                if len(picks) != star:
                    st.session_state.import_msg = ("error", f"⚠️ 號碼未選滿！這張彩券是 {star} 星玩法，請選滿號碼。")
                    return
                    
                start_iss_int = int(issue)
                for i in range(draws):
                    st.session_state.bet_history.insert(0, {
                        "type": "real",
                        "issue": str(start_iss_int + i),
                        "star": star,
                        "multiplier": multi,
                        "cost": 25 * multi,
                        "prize": 0,
                        "picks": picks.copy(),
                        "status": "waiting",
                        "timestamp": datetime.now().strftime("%m/%d %H:%M:%S")
                    })
                StorageManager.save_bets(st.session_state.current_user, st.session_state.bet_history)
                st.session_state.import_picks = [] 
                st.session_state.import_msg = ("success", f"✅ 成功匯入 {draws} 期實體彩券！請至「我的投注紀錄」查看對獎結果。")

            with st.container(border=True):
                col_i1, col_i2, col_i3 = st.columns(3)
                st.text_input("📌 彩券起始期號", value=str(latest_issue), key="import_issue")
                st.number_input("🔁 連續期數", 1, 500, 1, key="import_draws")
                st.number_input("💰 投注倍數", 1, 100, 1, key="import_multi")

                col_i4, col_i5 = st.columns([1, 4])
                st.number_input("⭐ 玩法 (星數)", 1, 10, 5, key="import_star", on_change=on_import_star_change)
                st.multiselect("✍️ 彩券上的號碼", range(1, 81), max_selections=st.session_state.get('import_star', 5), key="import_picks")

            st.button("📥 立即匯入這張彩券", type="primary", use_container_width=True, on_click=submit_import)
            
            if st.session_state.import_msg:
                msg_type, msg_text = st.session_state.import_msg
                if msg_type == "error": st.error(msg_text)
                else: st.success(msg_text)
                st.session_state.import_msg = None

    # ==========================
    # 📋 Tab 4: 我的投注紀錄 (📌 完美替換 fetch_range 修復報錯)
    # ==========================
    with tab4:
        is_updated = False
        
        # 📌 自動核對尚未開獎的注單
        for bet in st.session_state.bet_history:
            if bet["status"] == "waiting":
                # 1. 先嘗試從目前已經載入的 3 天快取資料裡找
                draw_result = next((item for item in history_data if item["issue"] == bet["issue"]), None)
                
                # 2. 如果快取裡找不到，代表這張單可能是很多天前的，呼叫時空引擎單抓 1 期
                if not draw_result:
                    res = BingoScraper.fetch_range(bet["issue"], 1, history_data)
                    draw_result = res[0] if res else None
                    
                if draw_result:
                    bet["status"] = "matched"
                    matched_nums = list(set(bet['picks']) & set(draw_result['numbers']))
                    bet["matched_nums"] = matched_nums
                    bet["prize"] = BingoGameLogic.calculate_prize(bet["star"], len(matched_nums), bet["multiplier"])
                    bet["draw_time"] = draw_result["time"]
                    is_updated = True
                    
        if is_updated: StorageManager.save_bets(st.session_state.current_user, st.session_state.bet_history)

        st.markdown(f"### 💰 【{st.session_state.current_user}】專屬帳戶總覽")
        real_cost = sum(b['cost'] for b in st.session_state.bet_history if b.get('type') == 'real')
        real_prize = sum(b['prize'] for b in st.session_state.bet_history if b['status'] == 'matched' and b.get('type') == 'real')
        
        virt_cost = sum(b['cost'] for b in st.session_state.bet_history if b.get('type') != 'real')
        virt_prize = sum(b['prize'] for b in st.session_state.bet_history if b['status'] == 'matched' and b.get('type') != 'real')
        
        col_r1, col_r2, col_r3 = st.columns(3)
        col_r1.metric("🧾 實體彩券總成本", f"NT$ {real_cost:,}")
        col_r2.metric("🧾 實體累積中獎", f"NT$ {real_prize:,}")
        col_r3.metric("🧾 實體淨損益", f"NT$ {real_prize - real_cost:,}", delta=int(real_prize - real_cost))
        
        col_v1, col_v2, col_v3 = st.columns(3)
        col_v1.metric("🎮 虛擬測試總成本", f"NT$ {virt_cost:,}")
        col_v2.metric("🎮 虛擬累積中獎", f"NT$ {virt_prize:,}")
        col_v3.metric("🎮 虛擬淨損益", f"NT$ {virt_prize - virt_cost:,}", delta=int(virt_prize - virt_cost))
        
        st.divider()
        
        c_title, c_btn1, c_btn2 = st.columns([2, 1, 1])
        c_title.markdown("### 📋 歷史明細清單")
        if c_btn1.button("🔄 刷新最新開獎", use_container_width=True): st.cache_data.clear(); st.rerun()
        if c_btn2.button("🗑️ 清空此帳號所有紀錄", type="secondary", use_container_width=True):
            st.session_state.bet_history = []
            StorageManager.save_bets(st.session_state.current_user, []) 
            st.rerun()

        if not st.session_state.bet_history: st.info("目前沒有注單。")
        else:
            summary_data = []
            for bet in st.session_state.bet_history:
                b_type = "🧾 實體" if bet.get("type") == "real" else "🎮 虛擬"
                summary_data.append({
                    "類型": b_type,
                    "目標期數": bet["issue"],
                    "玩法": f"{bet['star']} 星",
                    "倍數": f"{bet['multiplier']} 倍",
                    "成本": f"${bet['cost']}",
                    "狀態": "⏳ 等待中" if bet["status"] == "waiting" else "✅ 已開獎",
                    "中獎金額": f"${bet['prize']}" if bet["status"] == "matched" else "-"
                })
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)
            
            st.markdown("#### 🔍 詳細對獎紀錄 (中獎會自動展開)")
            for i, bet in enumerate(st.session_state.bet_history):
                time_str = f" | 🕒 {bet.get('draw_time', '未知')}" if bet['status'] == 'matched' else ""
                type_icon = "🧾 實體" if bet.get("type") == "real" else "🎮 虛擬"
                
                is_win = bet.get("prize", 0) > 0
                exp_title = f"{'🎉' if is_win else '💨'} [{type_icon}] 第 {bet['issue']} 期 | {bet['star']}星 | 成本 ${bet['cost']} | 狀態: {'⏳ 等待開獎' if bet['status'] == 'waiting' else '✅ 已開獎'}{time_str}"
                
                with st.expander(exp_title, expanded=is_win):
                    st.write("**你的選號：**")
                    st.markdown(BingoUI.render_balls(bet['picks'], "user"), unsafe_allow_html=True)
                    
                    if bet["status"] == "matched":
                        matched = bet.get("matched_nums", [])
                        draw_result = next((item for item in history_data if item["issue"] == bet["issue"]), None)
                        
                        # 📌 同樣使用 fetch_range 取代舊函式，顯示開獎號碼球
                        if not draw_result: 
                            res = BingoScraper.fetch_range(bet["issue"], 1, history_data)
                            draw_result = res[0] if res else None
                            
                        if draw_result: 
                            st.write("**本期開獎：**")
                            st.markdown(BingoUI.render_balls(draw_result['numbers'], "normal"), unsafe_allow_html=True)
                        
                        if bet["prize"] > 0:
                            if matched: st.success(f"🎉 對中 {len(matched)} 個號碼，贏得獎金 **NT$ {bet['prize']:,}**")
                            else: st.success(f"🎉 觸發「全倒」規則 (0顆)，拿回安慰獎 **NT$ {bet['prize']:,}**")
                        else:
                            st.error(f"💨 對中 {len(matched)} 顆，未達派彩標準。")
                    
                    if st.button("🗑️ 刪除此單筆紀錄", key=f"del_hist_{i}"):
                        st.session_state.bet_history.pop(i)
                        StorageManager.save_bets(st.session_state.current_user, st.session_state.bet_history) 
                        st.rerun()

    # ==========================
    # 🎯 Tab 5: 單次實體對獎
    # ==========================
    with tab5:
        st.subheader("🎯 單次實體彩券速查工具")
        st.markdown("這區適合用來「快速對獎」，對完即焚。如果你想把彩券放著讓系統自動追蹤，請使用 **「🎫 虛擬下注 & 實體匯入」** 頁籤！")

        def on_chk_star_change():
            if len(st.session_state.chk_picks) > st.session_state.chk_star:
                st.session_state.chk_picks = st.session_state.chk_picks[:st.session_state.chk_star]

        query_mode = st.radio("🔍 尋找期號方式", ["📅 依彩券購買時間查詢 (推薦)", "🔢 直接輸入起始期號"], horizontal=True)
        check_issue_value = ""

        col_q1, col_q2 = st.columns(2)
        if query_mode == "📅 依彩券購買時間查詢 (推薦)":
            with col_q1:
                q_date = st.date_input("1. 選擇購買日期", value=datetime.now(timezone(timedelta(hours=8))))
            with col_q2:
                day_data = BingoScraper._fetch_by_date(q_date.strftime("%Y-%m-%d"))
                if day_data:
                    day_data_sorted = sorted(day_data, key=lambda x: int(x['issue']))
                    opts = {f"🕒 {d['time'][11:16]} (第 {d['issue']} 期)": d['issue'] for d in day_data_sorted}
                    sel_lbl = st.selectbox("2. 選擇購買/起始時間", list(opts.keys()))
                    check_issue_value = opts[sel_lbl]
                else:
                    st.warning("⚠️ 查無該日開獎資料")
        else:
            with col_q1: check_issue_value = st.text_input("📌 手動輸入起始期號", value=str(latest_issue))

        st.divider()

        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            with c1: check_draws = st.number_input("🔁 連續期數 (最高支援 500 期)", 1, 500, 1)
            with c2: check_star = st.number_input("⭐ 玩法 (星數)", 1, 10, 5, key="chk_star", on_change=on_chk_star_change)
            with c3: check_multi = st.number_input("💰 投注倍數", 1, 100, 1)

            if 'chk_picks' not in st.session_state: st.session_state.chk_picks = []
            st.multiselect("✍️ 請輸入彩券上的投注號碼", range(1, 81), max_selections=check_star, key="chk_picks")

        if st.button("🔍 一鍵結算本張彩券", type="primary", use_container_width=True):
            if not check_issue_value.isdigit(): st.warning("⚠️ 起始期號不正確！")
            elif len(st.session_state.chk_picks) != check_star: st.warning(f"⚠️ 號碼未選滿 {check_star} 顆！")
            else:
                total_cost = 25 * check_multi * check_draws
                total_win = 0
                
                st.divider()
                st.markdown(f"### 🧾 兌獎結果總覽 (成本: NT$ {total_cost:,})")
                
                with st.spinner(f"📡 正在為您跨日調閱連續 {check_draws} 期的巨量開獎資料，請稍候..."):
                    range_data = BingoScraper.fetch_range(check_issue_value, check_draws, history_data)
                
                if not range_data:
                    st.error("❌ 查無該起始期號的資料！請確認日期或期號是否正確。")
                else:
                    for draw_data in range_data:
                        target_issue = draw_data["issue"]
                        
                        matched = list(set(st.session_state.chk_picks) & set(draw_data['numbers']))
                        prize = BingoGameLogic.calculate_prize(check_star, len(matched), check_multi)
                        total_win += prize
                        
                        if prize > 0:
                            exp_title = f"🎉 第 {target_issue} 期 | 中獎 NT$ {prize:,} | 🕒 {draw_data['time']}"
                            should_expand = True
                        else:
                            exp_title = f"💨 第 {target_issue} 期 | 未中獎 | 🕒 {draw_data['time']}"
                            should_expand = (check_draws <= 5)
                        
                        with st.expander(exp_title, expanded=should_expand):
                            st.markdown("**開獎號碼：**<br>" + BingoUI.render_balls(draw_data['numbers'], "normal") + BingoUI.render_balls(draw_data['super_num'], "super"), unsafe_allow_html=True)
                            st.markdown("**您的號碼：**<br>" + BingoUI.render_balls(st.session_state.chk_picks, "user"), unsafe_allow_html=True)
                            
                            if prize > 0:
                                st.success(f"🎉 狂賀！對中 {len(matched)} 顆，獲得加碼獎金 **NT$ {prize:,}**！")
                                if matched: st.markdown(BingoUI.render_balls(matched, "match"), unsafe_allow_html=True)
                            else:
                                st.error(f"💨 對中 {len(matched)} 顆，未中獎。")
                    
                    if len(range_data) < check_draws:
                        st.info(f"⏳ 溫馨提示：您選擇對獎 {check_draws} 期，但目前僅開出 {len(range_data)} 期，剩餘期數請稍後再查。")
                    
                    st.divider()
                    st.markdown(f"#### 💰 總計獲得獎金: **NT$ {total_win:,}**")
                    
                    if total_win > total_cost:
                        st.balloons()
                        st.success(f"🎊 恭喜發財！本張彩券淨賺 **NT$ {total_win - total_cost:,}**")
                    elif total_win > 0:
                        st.info(f"💵 本張彩券回本 **NT$ {total_win:,}**，總計淨損 **NT$ {total_cost - total_win:,}**")
                    else:
                        st.error(f"💸 全軍覆沒，本張彩券淨損 **NT$ {total_cost:,}**")

if __name__ == "__main__":
    main()