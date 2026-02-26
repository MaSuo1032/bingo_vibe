import streamlit as st
import requests
import urllib3
import pandas as pd
from collections import Counter
import random
import time
from typing import List, Dict, Tuple
from datetime import datetime, timedelta, timezone
from scipy.stats import chisquare # 📌 導入卡方檢定套件

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 資料層 (Model)
# ==========================================
class BingoScraper:
    @staticmethod
    def _fetch_by_date(date_str: str) -> List[Dict[str, any]]:
        api_url = f"https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult?openDate={date_str}&pageNum=1&pageSize=200"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json"
        }
        
        response = requests.get(api_url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        
        if data.get("rtCode") != 0 or "content" not in data:
            raise ValueError("API 格式變更或查無資料")
            
        results = data["content"]["bingoQueryResult"]
        history_draws = []
        
        for item in results:
            if not item.get("bigShowOrder") or item.get("bullEyeTop") == "－":
                continue
            history_draws.append({
                "issue": str(item["drawTerm"]),
                "numbers": sorted([int(n) for n in item["bigShowOrder"]]),
                "super_num": int(item["bullEyeTop"])
            })
        return history_draws

    @staticmethod
    @st.cache_data(ttl=120, show_spinner=False)
    def fetch_data() -> Tuple[List[Dict[str, any]], bool, str]:
        tw_tz = timezone(timedelta(hours=8))
        now_time = datetime.now(tw_tz)
        today_str = now_time.strftime("%Y-%m-%d")
        
        try:
            history_draws = BingoScraper._fetch_by_date(today_str)
            is_fallback = False
            target_date = today_str
            
            if not history_draws:
                yesterday_str = (now_time - timedelta(days=1)).strftime("%Y-%m-%d")
                history_draws = BingoScraper._fetch_by_date(yesterday_str)
                is_fallback = True
                target_date = yesterday_str
                
                if not history_draws:
                    raise ValueError(f"今天與昨天皆無開獎資料，請稍後再試。")
                    
            return history_draws, is_fallback, target_date
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"API 連線異常: {e}")

# ==========================================
# 2. 邏輯層 (Controller)
# ==========================================
class BingoGameLogic:
    @staticmethod
    def get_number_frequencies(history_data: List[Dict]) -> Counter:
        all_numbers = [num for draw in history_data for num in draw['numbers']]
        return Counter(all_numbers)

    # ... (保留原有的 generate_smart_pick, generate_repeat_pick 等快選邏輯) ...
    @staticmethod
    def generate_smart_pick(history_data: List[Dict], star_count: int, mode: str = "hot") -> List[int]:
        if not history_data: return sorted(random.sample(range(1, 81), star_count))
        counter = BingoGameLogic.get_number_frequencies(history_data)
        sorted_nums = [item[0] for item in counter.most_common()]
        if mode == "cold":
            sorted_nums.reverse()
            never_appeared = list(set(range(1, 81)) - set(sorted_nums))
            sorted_nums = never_appeared + sorted_nums
        pool_size = max(15, star_count) 
        return sorted(random.sample(sorted_nums[:pool_size], star_count))

    @staticmethod
    def generate_repeat_pick(history_data: List[Dict], star_count: int) -> List[int]:
        if not history_data: return sorted(random.sample(range(1, 81), star_count))
        last_draw = history_data[0]['numbers']
        return sorted(random.sample(last_draw, min(star_count, len(last_draw))))

    @staticmethod
    def generate_same_tail_pick(star_count: int) -> List[int]:
        tails = random.sample(range(10), 2)
        pool = [n for n in range(1, 81) if (n % 10) in tails]
        if len(pool) < star_count: pool = range(1, 81) 
        return sorted(random.sample(pool, star_count))

    @staticmethod
    def generate_odd_even_pick(star_count: int, is_odd: bool) -> List[int]:
        pool = [n for n in range(1, 81) if (n % 2 != 0) == is_odd]
        return sorted(random.sample(pool, star_count))

    @staticmethod
    def generate_big_small_pick(star_count: int, is_big: bool) -> List[int]:
        pool = range(41, 81) if is_big else range(1, 41)
        return sorted(random.sample(pool, star_count))

    @staticmethod
    def fill_remaining_picks(current_picks: List[int], star_count: int) -> List[int]:
        current_picks = current_picks[:star_count]
        needed = star_count - len(current_picks)
        if needed <= 0: return sorted(current_picks)
        remaining_pool = list(set(range(1, 81)) - set(current_picks))
        new_picks = random.sample(remaining_pool, needed)
        return sorted(current_picks + new_picks)

    @staticmethod
    def draw_random_numbers() -> Tuple[List[int], int]:
        latest_draw = random.sample(range(1, 81), 20)
        super_num = random.choice(latest_draw)
        return sorted(latest_draw), super_num

    # 📌 新增：卡方檢定邏輯
    @staticmethod
    def run_chi_square_test(history_data: List[Dict]) -> Tuple[float, float, List[int], float]:
        total_draws = len(history_data)
        # BINGO 每次抽 20 顆球，共 80 顆，所以每顆球每次被抽中的機率是 1/4
        # N 期下來的期望值 (Expected Value)
        expected_freq = total_draws * (20 / 80)
        
        counter = BingoGameLogic.get_number_frequencies(history_data)
        
        # 建立 1~80 的觀察值陣列 (Observed)
        observed_freqs = [counter.get(i, 0) for i in range(1, 81)]
        expected_freqs = [expected_freq] * 80
        
        # 執行卡方檢定
        chi2_stat, p_value = chisquare(f_obs=observed_freqs, f_exp=expected_freqs)
        
        return chi2_stat, p_value, observed_freqs, expected_freq

# ==========================================
# 3. 視覺層 (View)
# ==========================================
class BingoUI:
    @staticmethod
    def setup_page():
        st.set_page_config(page_title="BINGO BINGO 專業版", page_icon="🎰", layout="wide")
        st.markdown("""
        <style>
            .ball-container { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }
            .ball { width: 42px; height: 42px; line-height: 42px; border-radius: 50%; text-align: center; font-weight: 900; font-size: 18px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); }
            .ball-normal { background-color: #FFD700; color: #333; }
            .ball-super { background-color: #FF3B30; color: #FFF; }
            .ball-user { background-color: #007AFF; color: #FFF; }
            .ball-match { background-color: #34C759; color: #FFF; }
            .stTabs [data-baseweb="tab-list"] { justify-content: center; }
        </style>
        """, unsafe_allow_html=True)

    @staticmethod
    def render_balls(numbers: list | int, ball_type: str = "normal") -> str:
        if isinstance(numbers, int): numbers = [numbers]
        html = "<div class='ball-container'>"
        for n in sorted(numbers): html += f"<div class='ball ball-{ball_type}'>{n:02d}</div>"
        html += "</div>"
        return html

# ==========================================
# 4. 主程式 (Main Application)
# ==========================================
def main():
    BingoUI.setup_page()

    if 'sim_result' not in st.session_state: st.session_state.sim_result = None
    if 'user_picks' not in st.session_state: st.session_state.user_picks = []
    if 'toast_shown' not in st.session_state: st.session_state.toast_shown = False

    st.title("🎰 BINGO BINGO 專業模擬器")
    st.markdown("---")

    try:
        with st.spinner("🔄 正在與台灣彩券 API 同步最新資料..."):
            history_data, is_fallback, target_date = BingoScraper.fetch_data()
            if is_fallback:
                st.info(f"💡 今日尚未開獎，目前系統顯示昨日 ({target_date}) 的開獎數據。")
                if not st.session_state.toast_shown:
                    st.toast(f"已自動為您切換至昨日 ({target_date}) 數據。", icon="🔄")
                    st.session_state.toast_shown = True
    except Exception as e:
        st.error("🚨 **資料同步失敗！系統已啟動保護機制並停止運作。**")
        st.error(f"**錯誤細節：** {e}")
        st.stop()

    # 📌 新增 tab4
    tab1, tab2, tab3, tab4 = st.tabs(["📊 開獎紀錄", "🔥 冷熱門分析", "🎲 模擬投注區", "🕵️‍♂️ 系統異常偵測"])

    with tab1:
        st.subheader(f"📝 最新開獎紀錄 ({target_date})")
        with st.container(height=650):
            for draw in history_data[:200]:
                with st.container(border=True):
                    col1, col2 = st.columns([1, 4])
                    col1.markdown(f"**第 `{draw['issue']}` 期**")
                    col2.markdown(BingoUI.render_balls(draw['numbers'], "normal") + BingoUI.render_balls(draw['super_num'], "super"), unsafe_allow_html=True)

    with tab2:
        st.subheader(f"📈 號碼出現頻率分析 (共統計 {target_date} 的 {len(history_data)} 期)")
        counter = BingoGameLogic.get_number_frequencies(history_data)
        df_freq = pd.DataFrame(counter.items(), columns=["號碼", "出現次數"]).sort_values(by="出現次數", ascending=False)
        df_freq["號碼"] = df_freq["號碼"].apply(lambda x: f"{x:02d}")
        
        col_chart, col_rank = st.columns([3, 1])
        col_chart.bar_chart(df_freq.set_index("號碼"), color="#FFD700")
        
        with col_rank:
            st.write("**🔥 前 5 大熱門**")
            for _, row in df_freq.head(5).iterrows(): st.markdown(f"`{row['號碼']}` (共 {row['出現次數']} 次)")
            st.write("**❄️ 前 5 大冷門**")
            for _, row in df_freq.tail(5).iterrows(): st.markdown(f"`{row['號碼']}` (共 {row['出現次數']} 次)")

    with tab3:
        st.subheader("🎯 互動式模擬投注")
        def apply_strategy(strategy, *args):
            sc = st.session_state.star_input
            if strategy == "hot": st.session_state.user_picks = BingoGameLogic.generate_smart_pick(history_data, sc, "hot")
            elif strategy == "cold": st.session_state.user_picks = BingoGameLogic.generate_smart_pick(history_data, sc, "cold")
            elif strategy == "repeat": st.session_state.user_picks = BingoGameLogic.generate_repeat_pick(history_data, sc)
            elif strategy == "tail": st.session_state.user_picks = BingoGameLogic.generate_same_tail_pick(sc)
            elif strategy == "odd_even": st.session_state.user_picks = BingoGameLogic.generate_odd_even_pick(sc, args[0])
            elif strategy == "big_small": st.session_state.user_picks = BingoGameLogic.generate_big_small_pick(sc, args[0])
            elif strategy == "fill": st.session_state.user_picks = BingoGameLogic.fill_remaining_picks(st.session_state.user_picks, sc)

        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1: star_count = st.number_input("📌 選擇玩法 (幾星)", 1, 10, 5, key="star_input")
            with c2:
                st.session_state.user_picks = st.session_state.user_picks[:star_count]
                st.multiselect(f"✍️ 請挑選 {star_count} 個號碼", options=range(1, 81), max_selections=star_count, key="user_picks")
            
            st.divider()
            st.markdown("##### ⚡ 進階快選策略面板")
            r1c1, r1c2, r1c3, r1c4 = st.columns(4)
            r1c1.button("🔥 熱門快選", on_click=apply_strategy, args=("hot",), use_container_width=True)
            r1c2.button("❄️ 冷門快選", on_click=apply_strategy, args=("cold",), use_container_width=True)
            r1c3.button("🔁 抓連莊號", on_click=apply_strategy, args=("repeat",), use_container_width=True)
            r1c4.button("🎯 同尾數快選", on_click=apply_strategy, args=("tail",), use_container_width=True)
            
            r2c1, r2c2, r2c3, r2c4 = st.columns(4)
            r2c1.button("單 🔴 全單數", on_click=apply_strategy, args=("odd_even", True), use_container_width=True)
            r2c2.button("雙 🔵 全雙數", on_click=apply_strategy, args=("odd_even", False), use_container_width=True)
            r2c3.button("大 📈 全大區", on_click=apply_strategy, args=("big_small", True), use_container_width=True)
            r2c4.button("小 📉 全小區", on_click=apply_strategy, args=("big_small", False), use_container_width=True)
            st.button("💡 保留已選號碼，剩下隨機補滿", on_click=apply_strategy, args=("fill",), use_container_width=True, type="secondary")

        if st.button("🚀 立即開獎", type="primary", use_container_width=True):
            if len(st.session_state.user_picks) != star_count:
                st.warning(f"⚠️ 請選滿 {star_count} 個號碼再進行開獎！")
            else:
                with st.spinner("🎲 獎號開出中..."):
                    time.sleep(1)
                    draw_nums, super_num = BingoGameLogic.draw_random_numbers()
                    st.session_state.sim_result = {"draw": draw_nums, "super": super_num, "user": st.session_state.user_picks, "matched": list(set(st.session_state.user_picks) & set(draw_nums))}

        if st.session_state.sim_result:
            res = st.session_state.sim_result
            st.markdown("### 🏆 開獎結果")
            with st.container(border=True):
                r1, r2 = st.columns(2)
                with r1:
                    st.write("**本期開獎號碼**")
                    st.markdown(BingoUI.render_balls(res['draw'], "normal"), unsafe_allow_html=True)
                    st.markdown(BingoUI.render_balls(res['super'], "super"), unsafe_allow_html=True)
                with r2:
                    st.write("**你的投注號碼**")
                    st.markdown(BingoUI.render_balls(res['user'], "user"), unsafe_allow_html=True)
                    st.write("**對中號碼**")
                    if res['matched']:
                        st.markdown(BingoUI.render_balls(res['matched'], "match"), unsafe_allow_html=True)
                        st.success(f"🎉 恭喜！總共對中 **{len(res['matched'])}** 個號碼！")
                    else: st.error("💨 很可惜，這次沒有對中任何號碼。")

    # 📌 新增：系統異常偵測儀表板
    with tab4:
        st.subheader("🕵️‍♂️ 開獎機率異常偵測 (卡方檢定)")
        st.markdown("透過歷史開獎數據，運用統計學中的 **卡方檢定 (Chi-Square Test)** 來驗證台彩系統是否符合「完全隨機分佈」。")
        
        # 跑統計檢定
        chi2_stat, p_value, observed, expected = BingoGameLogic.run_chi_square_test(history_data)
        
        # 建立數學原理解釋區塊
        with st.expander("📝 查看數學檢定原理與公式"):
            st.markdown(f"""
            - **虛無假說 ($H_0$)**：開獎號碼呈現均勻的隨機分佈（系統無作弊）。
            - **對立假說 ($H_1$)**：開獎號碼不符合均勻隨機分佈（疑似受到人為操控或演算法干預）。
            - **統計期數 ($N$)**：{len(history_data)} 期
            - **期望值 ($E_i$)**：每一期會抽出 20 顆球，因此每顆球每期的中獎機率為 $\\frac{{20}}{{80}} = 0.25$。在 $N$ 期中，每個號碼理論上應該出現 $N \\times 0.25 = {expected:.1f}$ 次。
            - **卡方統計量**：
              $$ \\chi^2 = \\sum_{{i=1}}^{{80}} \\frac{{(O_i - E_i)^2}}{{E_i}} $$
            """)

        col_metric1, col_metric2, col_metric3 = st.columns(3)
        col_metric1.metric("卡方統計量 (Chi-Square)", f"{chi2_stat:.2f}")
        col_metric2.metric("P 值 (P-Value)", f"{p_value:.4f}")
        col_metric3.metric("樣本期數", f"{len(history_data)} 期")
        
        st.divider()
        st.markdown("#### ⚖️ 檢定結論判讀")
        
        # P-Value 解讀邏輯
        if p_value < 0.05:
            st.error(f"⚠️ **拒絕虛無假說 (P-Value < 0.05)**\n\n根據統計結果，目前開獎號碼的冷熱分佈過於極端，出現了統計學上的顯著異常。這代表這台機器的開獎結果 **很不隨機**！")
            st.markdown("💡 **防禦策略啟動**：建議前往「模擬投注區」，使用 **「❄️ 冷門快選」** 來對抗極端分佈。")
        else:
            st.success(f"✅ **不拒絕虛無假說 (P-Value >= 0.05)**\n\n目前的 p 值為 {p_value:.4f}，落在正常的隨機波動範圍內。這意味著目前的開獎分佈合乎統計學的隨機性，未見明顯的演算法控盤跡象。")
            
        st.markdown("#### 📊 實際觀察值 vs 理論期望值 分佈圖")
        df_chi = pd.DataFrame({
            "號碼": [f"{i:02d}" for i in range(1, 81)],
            "實際開出次數 (Observed)": observed,
            "理論期望次數 (Expected)": [expected] * 80
        }).set_index("號碼")
        
        # 繪製折線圖來對比理論與實際
        st.line_chart(df_chi, color=["#FF3B30", "#007AFF"])

if __name__ == "__main__":
    main()