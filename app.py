import streamlit as st
import requests
import urllib3
import pandas as pd
from collections import Counter
import random
import time
from typing import List, Dict, Tuple
from datetime import datetime, timedelta, timezone
from scipy.stats import chisquare

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 資料層
# ==========================================
class BingoScraper:
    @staticmethod
    def _fetch_by_date(date_str: str) -> List[Dict[str, any]]:
        api_url = f"https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult?openDate={date_str}&pageNum=1&pageSize=200"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = requests.get(api_url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        
        if data.get("rtCode") != 0 or "content" not in data:
            raise ValueError("API 格式變更或查無資料")
            
        history_draws = []
        for item in data["content"]["bingoQueryResult"]:
            if not item.get("bigShowOrder") or item.get("bullEyeTop") == "－":
                continue
            history_draws.append({
                "issue": str(item["drawTerm"]),
                "numbers": sorted([int(n) for n in item["bigShowOrder"]]),
                "super_num": int(item["bullEyeTop"])
            })
        return history_draws

    @staticmethod
    @st.cache_data(ttl=30, show_spinner=False) # 縮短快取時間，方便頻繁對獎
    def fetch_data() -> Tuple[List[Dict], str]:
        tw_tz = timezone(timedelta(hours=8))
        now = datetime.now(tw_tz)
        today, yesterday = now.strftime("%Y-%m-%d"), (now - timedelta(days=1)).strftime("%Y-%m-%d")
        
        try:
            today_data = BingoScraper._fetch_by_date(today)
            if len(today_data) < 200:
                yesterday_data = BingoScraper._fetch_by_date(yesterday)
                return (today_data + yesterday_data)[:200], f"{yesterday} ~ {today}"
            return today_data[:200], today
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"API 連線異常: {e}")

# ==========================================
# 邏輯層
# ==========================================
class BingoGameLogic:
    @staticmethod
    def get_frequencies(history: List[Dict]) -> Counter:
        return Counter([num for draw in history for num in draw['numbers']])

    @staticmethod
    def gen_smart(history: List[Dict], star: int, mode="hot") -> List[int]:
        if not history: return sorted(random.sample(range(1, 81), star))
        nums = [i[0] for i in BingoGameLogic.get_frequencies(history).most_common()]
        if mode == "cold":
            nums = list(set(range(1, 81)) - set(nums)) + nums[::-1]
        return sorted(random.sample(nums[:max(15, star)], star))

    @staticmethod
    def gen_repeat(history: List[Dict], star: int) -> List[int]:
        if not history: return sorted(random.sample(range(1, 81), star))
        last = history[0]['numbers']
        return sorted(random.sample(last, min(star, len(last))))

    @staticmethod
    def gen_tail(star: int) -> List[int]:
        tails = random.sample(range(10), 2)
        pool = [n for n in range(1, 81) if (n % 10) in tails]
        if len(pool) < star: pool = range(1, 81) 
        return sorted(random.sample(pool, star))

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
        pool = list(set(range(1, 81)) - set(picks))
        return sorted(picks + random.sample(pool, star - len(picks)))

    @staticmethod
    def run_chi2(history: List[Dict]) -> Tuple[float, float, List[int], float]:
        exp_freq = len(history) * (20 / 80)
        obs_freqs = [BingoGameLogic.get_frequencies(history).get(i, 0) for i in range(1, 81)]
        chi2, p = chisquare(f_obs=obs_freqs, f_exp=[exp_freq] * 80)
        return chi2, p, obs_freqs, exp_freq

# ==========================================
# 視覺層
# ==========================================
class BingoUI:
    @staticmethod
    def setup():
        st.set_page_config(page_title="BINGO 專業看盤", page_icon="🎰", layout="wide")
        st.markdown("""
        <style>
            .ball-container { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
            .ball { width: 42px; height: 42px; line-height: 42px; border-radius: 50%; text-align: center; font-weight: 900; font-size: 18px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); }
            .ball-normal { background-color: #FFD700; color: #333; }
            .ball-super { background-color: #FF3B30; color: #FFF; }
            .ball-user { background-color: #007AFF; color: #FFF; }
            .ball-match { background-color: #34C759; color: #FFF; }
            .stTabs [data-baseweb="tab-list"] { justify-content: center; }
        </style>
        """, unsafe_allow_html=True)

    @staticmethod
    def render_balls(nums: list | int, btype: str = "normal") -> str:
        nums = [nums] if isinstance(nums, int) else sorted(nums)
        html = "<div class='ball-container'>"
        for n in nums: html += f"<div class='ball ball-{btype}'>{n:02d}</div>"
        return html + "</div>"

# ==========================================
# 主程式
# ==========================================
def main():
    BingoUI.setup()

    # 狀態管理
    if 'bet_history' not in st.session_state: st.session_state.bet_history = []
    if 'user_picks' not in st.session_state: st.session_state.user_picks = []

    st.title("🎰 BINGO BINGO 專業看盤與對獎系統")

    try:
        history_data, target_date = BingoScraper.fetch_data()
        latest_issue = int(history_data[0]['issue'])
    except Exception as e:
        st.error(f"🚨 系統連線失敗: {e}"); st.stop()

    tab1, tab2, tab3, tab4 = st.tabs(["📊 開獎紀錄", "🔥 冷熱門分析", "🎫 真實對獎區", "🕵️‍♂️ 異常偵測"])

    # 1. 歷史紀錄
    with tab1:
        st.subheader(f"📝 最新 200 期紀錄 (最新期數: {latest_issue})")
        with st.container(height=650):
            for draw in history_data:
                with st.container(border=True):
                    c1, c2 = st.columns([1, 4])
                    c1.markdown(f"**第 `{draw['issue']}` 期**")
                    c2.markdown(BingoUI.render_balls(draw['numbers'], "normal") + BingoUI.render_balls(draw['super_num'], "super"), unsafe_allow_html=True)

    # 2. 分析
    with tab2:
        st.subheader(f"📈 頻率分析 ({len(history_data)} 期樣本)")
        df = pd.DataFrame(BingoGameLogic.get_frequencies(history_data).items(), columns=["Num", "Count"]).sort_values("Count", ascending=False)
        df["Num"] = df["Num"].apply(lambda x: f"{x:02d}")
        
        c1, c2 = st.columns([3, 1])
        c1.bar_chart(df.set_index("Num"), color="#FFD700")
        with c2:
            st.write("**🔥 前 5 熱門**")
            for _, r in df.head(5).iterrows(): st.markdown(f"`{r['Num']}` ({r['Count']}次)")
            st.write("**❄️ 前 5 冷門**")
            for _, r in df.tail(5).iterrows(): st.markdown(f"`{r['Num']}` ({r['Count']}次)")

    # 3. 真實對獎區
    with tab3:
        # 計算下一期期數
        next_issue = latest_issue + 1
        st.subheader(f"🎫 下注下一期 (第 `{next_issue}` 期)")
        
        def apply_strat(strat, *args):
            sc = st.session_state.star_input
            if strat == "hot": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "hot")
            elif strat == "cold": st.session_state.user_picks = BingoGameLogic.gen_smart(history_data, sc, "cold")
            elif strat == "rep": st.session_state.user_picks = BingoGameLogic.gen_repeat(history_data, sc)
            elif strat == "tail": st.session_state.user_picks = BingoGameLogic.gen_tail(sc)
            elif strat in ["odd", "even", "big", "small"]: st.session_state.user_picks = BingoGameLogic.gen_extreme(sc, strat)
            elif strat == "fill": st.session_state.user_picks = BingoGameLogic.fill_remaining(st.session_state.user_picks, sc)

        with st.container(border=True):
            c1, c2 = st.columns([1, 3])
            with c1: star_count = st.number_input("📌 玩法 (幾星)", 1, 10, 5, key="star_input")
            with c2:
                st.session_state.user_picks = st.session_state.user_picks[:star_count]
                st.multiselect("✍️ 選號", range(1, 81), max_selections=star_count, key="user_picks")
            
            st.markdown("##### ⚡ 快選策略")
            r1c1, r1c2, r1c3, r1c4 = st.columns(4)
            r1c1.button("🔥 熱門", on_click=apply_strat, args=("hot",), use_container_width=True)
            r1c2.button("❄️ 冷門", on_click=apply_strat, args=("cold",), use_container_width=True)
            r1c3.button("🔁 連莊", on_click=apply_strat, args=("rep",), use_container_width=True)
            r1c4.button("🎯 同尾", on_click=apply_strat, args=("tail",), use_container_width=True)
            
            r2c1, r2c2, r2c3, r2c4 = st.columns(4)
            r2c1.button("單", on_click=apply_strat, args=("odd",), use_container_width=True)
            r2c2.button("雙", on_click=apply_strat, args=("even",), use_container_width=True)
            r2c3.button("大(41-80)", on_click=apply_strat, args=("big",), use_container_width=True)
            r2c4.button("小(1-40)", on_click=apply_strat, args=("small",), use_container_width=True)
            st.button("💡 保留已選，隨機補滿", on_click=apply_strat, args=("fill",), use_container_width=True)

        if st.button("📝 確認虛擬下注", type="primary", use_container_width=True):
            if len(st.session_state.user_picks) != star_count:
                st.warning("⚠️ 請選滿號碼再下注！")
            else:
                st.session_state.bet_history.insert(0, {
                    "issue": str(next_issue),
                    "picks": st.session_state.user_picks.copy(),
                    "status": "waiting" # waiting, matched
                })
                st.success(f"✅ 成功下注第 {next_issue} 期！請等待台彩開獎後重新整理網頁對獎。")

        # 對獎與注單顯示區
        st.divider()
        c_title, c_btn = st.columns([3, 1])
        c_title.markdown("### 📋 我的虛擬注單與對獎紀錄")
        if c_btn.button("🔄 刷新開獎資料並對獎", use_container_width=True):
            st.cache_data.clear() # 清除快取強制重抓資料
            st.rerun()

        if not st.session_state.bet_history:
            st.info("目前沒有注單。")
        else:
            for bet in st.session_state.bet_history:
                with st.container(border=True):
                    # 在歷史紀錄中尋找這期的開獎結果
                    draw_result = next((item for item in history_data if item["issue"] == bet["issue"]), None)
                    
                    st.write(f"**📌 第 `{bet['issue']}` 期**")
                    st.write("**你的選號：**")
                    st.markdown(BingoUI.render_balls(bet['picks'], "user"), unsafe_allow_html=True)
                    
                    if draw_result:
                        if bet["status"] == "waiting": bet["status"] = "matched"
                        matched = list(set(bet['picks']) & set(draw_result['numbers']))
                        
                        st.write("**本期開獎：**")
                        st.markdown(BingoUI.render_balls(draw_result['numbers'], "normal") + BingoUI.render_balls(draw_result['super_num'], "super"), unsafe_allow_html=True)
                        st.write("**對中號碼：**")
                        if matched:
                            st.markdown(BingoUI.render_balls(matched, "match"), unsafe_allow_html=True)
                            st.success(f"🎉 對中 {len(matched)} 個號碼！")
                        else:
                            st.error("💨 沒中半個。")
                    else:
                        st.warning("⏳ 尚未開獎，請稍候刷新...")

    # 4. 異常偵測
    with tab4:
        st.subheader("🕵️‍♂️ 開獎機率異常偵測 (卡方檢定)")
        chi2, p, obs, exp = BingoGameLogic.run_chi2(history_data)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("卡方統計量", f"{chi2:.2f}")
        c2.metric("P-Value", f"{p:.4f}")
        c3.metric("樣本數", f"{len(history_data)}")
        
        if p < 0.05: st.error("⚠️ **P < 0.05：出現統計學顯著異常，開獎分佈不均勻！**")
        else: st.success("✅ **P >= 0.05：目前開獎分佈符合機率學的正常波動。**")
            
        df_c = pd.DataFrame({"號碼": [f"{i:02d}" for i in range(1, 81)], "實際": obs, "期望": [exp]*80}).set_index("號碼")
        st.line_chart(df_c, color=["#FF3B30", "#007AFF"])

if __name__ == "__main__":
    main()