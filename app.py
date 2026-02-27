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
from scipy.stats import chisquare

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 資料層 (Model) - 📌 加入錨點時鐘同步技術
# ==========================================
class BingoScraper:
    @staticmethod
    def _extract_time(item: dict, fallback_date: str) -> str:
        """攔截殭屍時間，並暴力萃取正確時間格式"""
        keys_to_try = ["drawDate", "openDate", "drawTime", "openTime", "listDate", "Opendate", "DrawDate", "date", "time"]
        for k in keys_to_try:
            val = item.get(k)
            if val and isinstance(val, str):
                if "0001-01-01" in val: continue # 📌 攔截 C# 的預設空值
                if "T" in val and len(val) >= 16:
                    return val[:16].replace("T", " ")
                elif len(val) >= 5 and ":" in val:
                    return f"{fallback_date} {val[:5]}"
        
        for val in item.values():
            if isinstance(val, str):
                if "0001-01-01" in val: continue
                if "T" in val and len(val) >= 16 and val[13] == ":":
                    return val[:16].replace("T", " ")
                elif len(val) >= 5 and val[2] == ":" and val[:2].isdigit():
                    return f"{fallback_date} {val[:5]}"
                    
        return f"{fallback_date} 未知"

    @staticmethod
    def _fetch_by_date(date_str: str) -> List[Dict[str, any]]:
        api_url = f"https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult?openDate={date_str}&pageNum=1&pageSize=250"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = requests.get(api_url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        
        if data.get("rtCode") != 0 or "content" not in data:
            return []
            
        valid_items = [item for item in data["content"]["bingoQueryResult"] if item.get("bigShowOrder") and item.get("bullEyeTop") != "－"]
        if not valid_items: return []
        
        # 📌 尋找「時間正常」的錨點期數
        anchor_issue = None
        anchor_time = None
        for item in valid_items:
            t = BingoScraper._extract_time(item, date_str)
            if "未知" not in t:
                try:
                    anchor_issue = int(item["drawTerm"])
                    anchor_time = datetime.strptime(t, "%Y-%m-%d %H:%M")
                    break
                except Exception: pass
        
        # 如果整天都壞掉，以當天最小期數為 07:05 為基準
        if anchor_issue is None:
            anchor_issue = min(int(item["drawTerm"]) for item in valid_items)
            anchor_time = datetime.strptime(f"{date_str} 07:05", "%Y-%m-%d %H:%M")

        history_draws = []
        for item in valid_items:
            issue_str = str(item["drawTerm"])
            extracted_time = BingoScraper._extract_time(item, date_str)
            
            # 📌 啟動時鐘同步：用 5 分鐘法則換算出正確時間
            if "未知" in extracted_time:
                try:
                    issue_diff = int(issue_str) - anchor_issue
                    extracted_time = (anchor_time + timedelta(minutes=5 * issue_diff)).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass

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
                    days_ago = diff // 203 
                    start_date_str = (latest_date - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                else:
                    start_date_str = latest_date_str
            except Exception: pass

        if not start_date_str:
            start_date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError:
            start_date = datetime.now(timezone(timedelta(hours=8)))
            
        days_to_fetch = (count // 203) + 3
        fetch_start = start_date - timedelta(days=1)
        
        all_draws = []
        for i in range(days_to_fetch):
            d_str = (fetch_start + timedelta(days=i)).strftime("%Y-%m-%d")
            all_draws.extend(BingoScraper._fetch_by_date(d_str))
            
        issue_dict = {item["issue"]: item for item in all_draws}
        results = []
        for i in range(count):
            iss = str(start_issue_int + i)
            if iss in issue_dict:
                results.append(issue_dict[iss])
                
        return results

    @staticmethod
    @st.cache_data(ttl=30, show_spinner=False)
    def fetch_data() -> Tuple[List[Dict], str]:
        tw_tz = timezone(timedelta(hours=8))
        now = datetime.now(tw_tz)
        history_draws = []
        try:
            for i in range(3):
                target_date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                history_draws.extend(BingoScraper._fetch_by_date(target_date))
                
            if not history_draws: raise ValueError("近期皆無開獎資料，請稍後再試。")
            start_date, end_date = (now - timedelta(days=2)).strftime("%m/%d"), now.strftime("%m/%d")
            return history_draws, f"{start_date} ~ {end_date}"
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"API 連線異常: {e}")

# ==========================================
# 2. 儲存層 (Storage)
# ==========================================
class StorageManager:
    FILE_PATH = "bingo_bets_history.json"
    @staticmethod
    def load_bets() -> List[Dict]:
        if os.path.exists(StorageManager.FILE_PATH):
            try:
                with open(StorageManager.FILE_PATH, "r", encoding="utf-8") as f: return json.load(f)
            except Exception: return []
        return []
    @staticmethod
    def save_bets(bets: List[Dict]):
        with open(StorageManager.FILE_PATH, "w", encoding="utf-8") as f: json.dump(bets, f, ensure_ascii=False, indent=4)

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
        5: {5: 15000, 4: 600, 3: 50},
        4: {4: 2000, 3: 150, 2: 25},
        3: {3: 1000, 2: 50},
        2: {2: 150, 1: 25},
        1: {1: 100}
    }
    
    @staticmethod
    def calculate_prize(star_count: int, matched_count: int, multiplier: int = 1) -> int:
        return BingoGameLogic.PRIZE_TABLE.get(star_count, {}).get(matched_count, 0) * multiplier

    @staticmethod
    def get_frequencies(history: List[Dict]) -> Counter: return Counter([num for draw in history for num in draw['numbers']])

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
    def fill_remaining(picks: List[int], star: int) -> List[int]:
        picks = picks[:star]
        if len(picks) >= star: return sorted(picks)
        return sorted(picks + random.sample(list(set(range(1, 81)) - set(picks)), star - len(picks)))

    @staticmethod
    def run_chi2(history: List[Dict]) -> Tuple[float, float, List[int], float]:
        exp_freq = len(history) * (20 / 80)
        obs_freqs = [BingoGameLogic.get_frequencies(history).get(i, 0) for i in range(1, 81)]
        chi2, p = chisquare(f_obs=obs_freqs, f_exp=[exp_freq] * 80)
        return chi2, p, obs_freqs, exp_freq

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

    if 'bet_history' not in st.session_state: st.session_state.bet_history = StorageManager.load_bets()
    if 'user_picks' not in st.session_state: st.session_state.user_picks = []
    if 'cart' not in st.session_state: st.session_state.cart = []
    if 'cart_warning' not in st.session_state: st.session_state.cart_warning = False

    st.title("🎰 BINGO BINGO 真實對獎與包牌系統 (🎉 限時加碼版)")
    st.markdown("<div class='bonus-tag'>🔥 系統已全面套用 2026 台彩最新「1~6 星」限時加碼賠率！</div>", unsafe_allow_html=True)

    try:
        history_data, target_date = BingoScraper.fetch_data()
        latest_issue = int(history_data[0]['issue'])
    except Exception as e:
        st.error(f"🚨 系統連線失敗: {e}"); st.stop()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 開獎紀錄", "🔥 號碼分析", "🎫 購物車下注", "📋 我的投注紀錄", "🕵️‍♂️ 異常偵測", "🎯 實體彩券對獎"
    ])

    with tab1:
        st.subheader(f"📝 近期開獎紀錄 (共載入 {len(history_data)} 期 | {target_date})")
        with st.container(height=650):
            for draw in history_data:
                with st.container(border=True):
                    c1, c2 = st.columns([1, 4])
                    c1.markdown(f"**第 `{draw['issue']}` 期**<br><span class='time-tag'>🕒 {draw['time']}</span>", unsafe_allow_html=True)
                    c2.markdown(BingoUI.render_balls(draw['numbers'], "normal") + BingoUI.render_balls(draw['super_num'], "super"), unsafe_allow_html=True)

    with tab2:
        st.subheader(f"📈 頻率分析 ({len(history_data)} 期龐大樣本)")
        df = pd.DataFrame(BingoGameLogic.get_frequencies(history_data).items(), columns=["Num", "Count"]).sort_values("Count", ascending=False)
        df["Num"] = df["Num"].apply(lambda x: f"{x:02d}")
        
        c1, c2 = st.columns([3, 1])
        c1.bar_chart(df.set_index("Num"), color="#FFD700")
        with c2:
            st.write("**🔥 前 5 熱門**")
            for _, r in df.head(5).iterrows(): st.markdown(f"`{r['Num']}` ({r['Count']}次)")
            st.write("**❄️ 前 5 冷門**")
            for _, r in df.tail(5).iterrows(): st.markdown(f"`{r['Num']}` ({r['Count']}次)")

    with tab3:
        next_issue = latest_issue + 1
        st.subheader(f"🎫 下注看盤區 (目標起算期數: `{next_issue}`)")
        st.info("💡 **提示：** 本期熱門玩法「3 星」與「6 星」獎金皆已翻倍！利用下方倍數可嘗試網路瘋傳的『三星4倍』策略。")
        
        def apply_strat(strat, *args):
            sc = st.session_state.star_input
            if strat == "hot": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "hot")
            elif strat == "cold": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "cold")
            elif strat == "mid": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "mid")
            elif strat == "rep": st.session_state.user_picks = BingoGameLogic.gen_repeat(history_data, sc)
            elif strat == "tail": st.session_state.user_picks = BingoGameLogic.gen_tail(sc)
            elif strat in ["odd", "even", "big", "small"]: st.session_state.user_picks = BingoGameLogic.gen_extreme(sc, strat)
            elif strat == "fill": st.session_state.user_picks = BingoGameLogic.fill_remaining(st.session_state.user_picks, sc)

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
            with c2: st.multiselect("✍️ 手動選號 (或套用策略)", range(1, 81), max_selections=star_count, key="user_picks")
            
            st.markdown("##### ⚡ 單組選號策略")
            r1c1, r1c2, r1c3, r1c4 = st.columns(4)
            r1c1.button("🔥 熱門特徵", on_click=apply_strat, args=("hot",), use_container_width=True)
            r1c2.button("❄️ 冷門特徵", on_click=apply_strat, args=("cold",), use_container_width=True)
            r1c3.button("☯️ 溫態 (非冷非熱)", on_click=apply_strat, args=("mid",), use_container_width=True)
            r1c4.button("💡 保留已選，隨機補滿", on_click=apply_strat, args=("fill",), use_container_width=True)
            
            st.button("➕ 將上方號碼加入待結帳區", on_click=add_single_to_cart, use_container_width=True)
            if st.session_state.cart_warning: st.warning("⚠️ 請選滿號碼再加入！")

            st.divider()
            st.markdown(f"##### 🚀 一鍵批次包牌 (直接產生 `{batch_count}` 組)")
            b1, b2, b3, b4 = st.columns(4)
            if b1.button(f"🎲 機選 {batch_count} 組", use_container_width=True):
                for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": sorted(random.sample(range(1, 81), star_count))})
                st.rerun()
            if b2.button(f"🔥 熱門 {batch_count} 組", use_container_width=True):
                for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": BingoGameLogic.gen_smart(history_data, star_count, "hot")})
                st.rerun()
            if b3.button(f"☯️ 溫態 {batch_count} 組", use_container_width=True):
                for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": BingoGameLogic.gen_smart(history_data, star_count, "mid")})
                st.rerun()
            if b4.button(f"🔁 連莊 {batch_count} 組", use_container_width=True):
                for _ in range(batch_count): st.session_state.cart.append({"star": star_count, "picks": BingoGameLogic.gen_repeat(history_data, star_count)})
                st.rerun()

        if st.session_state.cart:
            st.markdown("### 🛒 待下注購物車")
            for i, item in enumerate(st.session_state.cart):
                with st.container(border=True):
                    cart_c1, cart_c2 = st.columns([10, 1])
                    cart_c1.markdown(f"**{item['star']} 星** | " + BingoUI.render_balls(item['picks'], "user"), unsafe_allow_html=True)
                    if cart_c2.button("❌", key=f"del_{i}"):
                        st.session_state.cart.pop(i)
                        st.rerun()
            
            cart_total_cost = len(st.session_state.cart) * 25 * multiplier * multi_draw
            st.info(f"🧾 本次結帳總計: **{len(st.session_state.cart)}** 組選號 x **{multiplier}** 倍 x **{multi_draw}** 期 = 扣除本金 **NT$ {cart_total_cost:,}**")

            col_submit, col_clear = st.columns([3, 1])
            if col_submit.button("📝 確認送出所有注單", type="primary", use_container_width=True):
                for item in st.session_state.cart:
                    for i in range(multi_draw):
                        st.session_state.bet_history.insert(0, {
                            "issue": str(next_issue + i),
                            "star": item['star'],
                            "multiplier": multiplier,
                            "cost": 25 * multiplier,
                            "prize": 0,
                            "picks": item['picks'].copy(),
                            "status": "waiting",
                            "timestamp": datetime.now().strftime("%m/%d %H:%M:%S")
                        })
                StorageManager.save_bets(st.session_state.bet_history)
                st.session_state.cart.clear()
                st.success("✅ 成功下注！資料已永久儲存，請至「我的投注紀錄」追蹤開獎狀態。")
                time.sleep(1.5)
                st.rerun()
            if col_clear.button("🗑️ 清空購物車", use_container_width=True):
                st.session_state.cart.clear(); st.rerun()

    with tab4:
        is_updated = False
        for bet in st.session_state.bet_history:
            if bet["status"] == "waiting":
                draw_result = next((item for item in history_data if item["issue"] == bet["issue"]), None)
                if draw_result:
                    bet["status"] = "matched"
                    matched_nums = list(set(bet['picks']) & set(draw_result['numbers']))
                    bet["matched_nums"] = matched_nums
                    bet["prize"] = BingoGameLogic.calculate_prize(bet["star"], len(matched_nums), bet["multiplier"])
                    bet["draw_time"] = draw_result["time"]
                    is_updated = True
        if is_updated: StorageManager.save_bets(st.session_state.bet_history)

        st.markdown("### 💰 帳戶財務總覽 (加碼期間)")
        total_cost = sum(b['cost'] for b in st.session_state.bet_history)
        total_prize = sum(b['prize'] for b in st.session_state.bet_history if b['status'] == 'matched')
        net_profit = total_prize - total_cost
        
        col_f1, col_f2, col_f3 = st.columns(3)
        col_f1.metric("總投入本金", f"NT$ {total_cost:,}")
        col_f2.metric("累積派彩金額", f"NT$ {total_prize:,}")
        col_f3.metric("總淨利 (損益)", f"NT$ {net_profit:,}", delta=int(net_profit))
        st.divider()
        
        c_title, c_btn1, c_btn2 = st.columns([2, 1, 1])
        c_title.markdown("### 📋 投注明細清單")
        if c_btn1.button("🔄 刷新開獎資料", use_container_width=True): st.cache_data.clear(); st.rerun()
        if c_btn2.button("🗑️ 清空所有歷史注單", type="secondary", use_container_width=True):
            st.session_state.bet_history = []
            StorageManager.save_bets([]) 
            st.rerun()

        if not st.session_state.bet_history: st.info("目前沒有注單，趁加碼期間快去下注吧！")
        else:
            summary_data = []
            for bet in st.session_state.bet_history:
                summary_data.append({
                    "下注時間": bet.get("timestamp", "-"),
                    "目標期數": bet["issue"],
                    "玩法": f"{bet['star']} 星",
                    "倍數": f"{bet['multiplier']} 倍",
                    "成本": f"${bet['cost']}",
                    "狀態": "⏳ 等待中" if bet["status"] == "waiting" else "✅ 已開獎",
                    "中獎金額": f"${bet['prize']}" if bet["status"] == "matched" else "-"
                })
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)
            
            st.markdown("#### 🔍 詳細對獎紀錄")
            for i, bet in enumerate(st.session_state.bet_history):
                time_str = f" | 🕒 {bet.get('draw_time', '未知')}" if bet['status'] == 'matched' else ""
                
                is_win = bet.get("prize", 0) > 0
                exp_title = f"{'🎉' if is_win else '💨'} 第 {bet['issue']} 期 | {bet['star']}星 | 成本 ${bet['cost']} | 狀態: {'⏳ 等待開獎' if bet['status'] == 'waiting' else '✅ 已開獎'}{time_str}"
                
                with st.expander(exp_title, expanded=is_win):
                    st.write("**你的選號：**")
                    st.markdown(BingoUI.render_balls(bet['picks'], "user"), unsafe_allow_html=True)
                    
                    if bet["status"] == "matched":
                        matched = bet.get("matched_nums", [])
                        draw_result = next((item for item in history_data if item["issue"] == bet["issue"]), None)
                        st.write("**本期開獎：**")
                        if draw_result: st.markdown(BingoUI.render_balls(draw_result['numbers'], "normal"), unsafe_allow_html=True)
                        
                        if bet["prize"] > 0:
                            if matched: st.success(f"🎉 對中 {len(matched)} 個號碼，贏得加碼獎金 **NT$ {bet['prize']:,}**")
                            else: st.success(f"🎉 觸發「全倒」規則 (0顆)，拿回安慰獎 **NT$ {bet['prize']:,}**")
                        else:
                            st.error(f"💨 對中 {len(matched)} 顆，未達派彩標準。")
                    
                    if st.button("🗑️ 刪除此單筆紀錄", key=f"del_hist_{i}"):
                        st.session_state.bet_history.pop(i)
                        StorageManager.save_bets(st.session_state.bet_history) 
                        st.rerun()

    with tab5:
        st.subheader("🕵️‍♂️ 開獎機率異常偵測 (卡方檢定)")
        chi2, p, obs, exp = BingoGameLogic.run_chi2(history_data)
        c1, c2, c3 = st.columns(3)
        c1.metric("卡方統計量", f"{chi2:.2f}"); c2.metric("P-Value", f"{p:.4f}"); c3.metric("樣本數", f"{len(history_data)}")
        if p < 0.05: st.error("⚠️ **P < 0.05：出現統計學顯著異常，開獎分佈不均勻！**")
        else: st.success("✅ **P >= 0.05：目前開獎分佈符合機率學的正常波動。**")
        df_c = pd.DataFrame({"號碼": [f"{i:02d}" for i in range(1, 81)], "實際": obs, "期望": [exp]*80}).set_index("號碼")
        st.line_chart(df_c, color=["#FF3B30", "#007AFF"])

    with tab6:
        st.subheader("🎯 實體彩券手動兌獎小幫手 (支援加碼賠率結算)")
        st.markdown("可自動反查購買時間對應的期號。支援一次對獎 **高達 500 期**，系統會自動套用加碼活動的高額賠率！")

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