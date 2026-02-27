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
# 1. 資料層 (Model)
# ==========================================
class BingoScraper:
    @staticmethod
    def _parse_draw_time(date_str: str) -> str:
        """解析 API 回傳的時間戳記並格式化"""
        try:
            return date_str[:16].replace("T", " ")
        except Exception:
            return date_str

    @staticmethod
    def _fetch_by_date(date_str: str) -> List[Dict[str, any]]:
        api_url = f"https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult?openDate={date_str}&pageNum=1&pageSize=200"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = requests.get(api_url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        
        if data.get("rtCode") != 0 or "content" not in data:
            return []
            
        history_draws = []
        for item in data["content"]["bingoQueryResult"]:
            if not item.get("bigShowOrder") or item.get("bullEyeTop") == "－":
                continue
            history_draws.append({
                "issue": str(item["drawTerm"]),
                "time": BingoScraper._parse_draw_time(item.get("drawDate", "")), # 📌 新增時間戳記
                "numbers": sorted([int(n) for n in item["bigShowOrder"]]),
                "super_num": int(item["bullEyeTop"])
            })
        return history_draws

    @staticmethod
    def fetch_single_issue(issue_num: str) -> Dict[str, any]:
        """📌 新增：突破限制，向台彩伺服器單獨查詢任意指定的「歷史期號」"""
        api_url = f"https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult?drawTerm={issue_num}"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        try:
            response = requests.get(api_url, headers=headers, timeout=5, verify=False)
            if response.status_code == 200:
                data = response.json()
                if data.get("content") and data["content"].get("bingoQueryResult"):
                    for item in data["content"]["bingoQueryResult"]:
                        if str(item.get("drawTerm")) == issue_num and item.get("bigShowOrder"):
                            return {
                                "issue": str(item["drawTerm"]),
                                "time": BingoScraper._parse_draw_time(item.get("drawDate", "")),
                                "numbers": sorted([int(n) for n in item["bigShowOrder"]]),
                                "super_num": int(item["bullEyeTop"])
                            }
        except Exception:
            pass
        return None

    @staticmethod
    @st.cache_data(ttl=30, show_spinner=False)
    def fetch_data() -> Tuple[List[Dict], str]:
        tw_tz = timezone(timedelta(hours=8))
        now = datetime.now(tw_tz)
        history_draws = []
        
        try:
            # 📌 修改：一口氣抓取最近 3 天的開獎資料 (確保資料量大於 400~600 期)
            for i in range(3):
                target_date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
                history_draws.extend(BingoScraper._fetch_by_date(target_date))
                
            if not history_draws:
                raise ValueError("近期皆無開獎資料，請稍後再試。")
                
            start_date = (now - timedelta(days=2)).strftime("%m/%d")
            end_date = now.strftime("%m/%d")
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
                with open(StorageManager.FILE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    @staticmethod
    def save_bets(bets: List[Dict]):
        with open(StorageManager.FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(bets, f, ensure_ascii=False, indent=4)

# ==========================================
# 3. 邏輯層 (Controller)
# ==========================================
class BingoGameLogic:
    PRIZE_TABLE = {
        10: {10: 5000000, 9: 250000, 8: 25000, 7: 2500, 6: 250, 5: 25, 0: 25},
        9: {9: 1000000, 8: 100000, 7: 3000, 6: 500, 5: 100, 4: 25, 0: 25},
        8: {8: 500000, 7: 20000, 6: 1000, 5: 200, 4: 25, 0: 25},
        7: {7: 80000, 6: 3000, 5: 300, 4: 50, 3: 25},
        6: {6: 25000, 5: 1000, 4: 200, 3: 25},
        5: {5: 7500, 4: 500, 3: 50},
        4: {4: 1000, 3: 100, 2: 25},
        3: {3: 500, 2: 50},
        2: {2: 75, 1: 25},
        1: {1: 50}
    }

    @staticmethod
    def calculate_prize(star_count: int, matched_count: int, multiplier: int = 1) -> int:
        base_prize = BingoGameLogic.PRIZE_TABLE.get(star_count, {}).get(matched_count, 0)
        return base_prize * multiplier

    @staticmethod
    def get_frequencies(history: List[Dict]) -> Counter:
        return Counter([num for draw in history for num in draw['numbers']])

    @staticmethod
    def gen_smart(history: List[Dict], star: int, mode="hot") -> List[int]:
        if not history: return sorted(random.sample(range(1, 81), star))
        freq = BingoGameLogic.get_frequencies(history)
        nums = [i[0] for i in freq.most_common()]
        all_ranked = nums + list(set(range(1, 81)) - set(nums))
        if mode == "hot": pool = all_ranked[:max(15, star)]
        elif mode == "cold": pool = all_ranked[::-1][:max(15, star)]
        elif mode == "mid": 
            pool = all_ranked[20:60]
            if len(pool) < star: pool = all_ranked 
        return sorted(random.sample(pool, star))

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
# 4. 視覺層 (View)
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
            div[data-testid="stMetricValue"] { font-size: 2rem; }
            .time-tag { color: #666; font-size: 0.9em; margin-left: 10px; background: #eee; padding: 2px 8px; border-radius: 12px; }
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

    st.title("🎰 BINGO BINGO 真實對獎與包牌系統")

    try:
        history_data, target_date = BingoScraper.fetch_data()
        latest_issue = int(history_data[0]['issue'])
    except Exception as e:
        st.error(f"🚨 系統連線失敗: {e}"); st.stop()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 開獎紀錄", "🔥 號碼分析", "🎫 購物車下注", "📋 我的投注紀錄", "🕵️‍♂️ 異常偵測", "🎯 實體彩券兌獎"
    ])

    with tab1:
        st.subheader(f"📝 近期開獎紀錄 (共載入 {len(history_data)} 期 | {target_date})")
        with st.container(height=650):
            for draw in history_data:
                with st.container(border=True):
                    c1, c2 = st.columns([1, 4])
                    # 📌 UI 更新：在期號旁加入精準的時間戳記
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

    # ==========================
    # 🎫 Tab 3: 下注與購物車區
    # ==========================
    with tab3:
        next_issue = latest_issue + 1
        st.subheader(f"🎫 下注看盤區 (目標起算期數: `{next_issue}`)")
        
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
                st.session_state.cart.clear()
                st.rerun()

    # ==========================
    # 📋 Tab 4: 獨立的投注紀錄與財務頁面
    # ==========================
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
                    bet["draw_time"] = draw_result["time"] # 儲存對中的時間
                    is_updated = True
        
        if is_updated:
            StorageManager.save_bets(st.session_state.bet_history)

        st.markdown("### 💰 帳戶財務總覽")
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
        if c_btn1.button("🔄 刷新開獎資料", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
            
        if c_btn2.button("🗑️ 清空所有歷史注單", type="secondary", use_container_width=True):
            st.session_state.bet_history = []
            StorageManager.save_bets([]) 
            st.rerun()

        if not st.session_state.bet_history:
            st.info("目前沒有注單，快去下注吧！")
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
                # 顯示時加入時間戳記
                time_str = f" | 開獎時間: {bet.get('draw_time', '未知')}" if bet['status'] == 'matched' else ""
                with st.expander(f"第 {bet['issue']} 期 | {bet['star']}星 | 成本 ${bet['cost']} | 狀態: {'⏳ 等待開獎' if bet['status'] == 'waiting' else '✅ 已開獎'}{time_str}"):
                    st.write("**你的選號：**")
                    st.markdown(BingoUI.render_balls(bet['picks'], "user"), unsafe_allow_html=True)
                    
                    if bet["status"] == "matched":
                        matched = bet.get("matched_nums", [])
                        draw_result = next((item for item in history_data if item["issue"] == bet["issue"]), None)
                        
                        st.write("**本期開獎：**")
                        if draw_result:
                            st.markdown(BingoUI.render_balls(draw_result['numbers'], "normal"), unsafe_allow_html=True)
                        
                        if bet["prize"] > 0:
                            if matched: st.success(f"🎉 對中 {len(matched)} 個號碼，贏得獎金 **NT$ {bet['prize']:,}**")
                            else: st.success(f"🎉 觸發「全倒」規則 (0顆)，拿回安慰獎 **NT$ {bet['prize']:,}**")
                        else:
                            st.error(f"💨 對中 {len(matched)} 顆，未達派彩標準。")
                    
                    if st.button("🗑️ 刪除此單筆紀錄", key=f"del_hist_{i}"):
                        st.session_state.bet_history.pop(i)
                        StorageManager.save_bets(st.session_state.bet_history) 
                        st.rerun()

    # ==========================
    # 🕵️‍♂️ Tab 5: 異常偵測
    # ==========================
    with tab5:
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

    # ==========================
    # 🎯 Tab 6: 實體彩券動態兌獎區 (📌 大幅強化)
    # ==========================
    with tab6:
        st.subheader("🎯 實體彩券手動兌獎小幫手 (支援任意期號)")
        st.markdown("輸入您手邊彩券的資訊，若查詢歷史超過 3 天，系統將自動向台彩伺服器**調閱任意指定期數**！")

        def on_check_star_change():
            if len(st.session_state.chk_picks) > st.session_state.chk_star:
                st.session_state.chk_picks = st.session_state.chk_picks[:st.session_state.chk_star]

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            with c1: check_issue = st.text_input("📌 起始期號", value=str(latest_issue), key="chk_issue")
            with c2: check_draws = st.number_input("🔁 連續期數", 1, 50, 1, key="chk_draws")
            with c3: check_star = st.number_input("⭐ 玩法 (星數)", 1, 10, 5, key="chk_star", on_change=on_check_star_change)
            with c4: check_multi = st.number_input("💰 投注倍數", 1, 50, 1, key="chk_multi")

            if 'chk_picks' not in st.session_state: st.session_state.chk_picks = []
            st.multiselect("✍️ 請輸入彩券上的投注號碼", range(1, 81), max_selections=check_star, key="chk_picks")

        if st.button("🔍 結算本張彩券", type="primary", use_container_width=True):
            if not check_issue.isdigit():
                st.warning("⚠️ 起始期號請輸入純數字！")
            elif len(st.session_state.chk_picks) != check_star:
                st.warning(f"⚠️ 號碼未選滿！您設定為 {check_star} 星，目前僅輸入 {len(st.session_state.chk_picks)} 個號碼。")
            else:
                start_issue = int(check_issue)
                total_cost = 25 * check_multi * check_draws
                total_win = 0
                
                st.divider()
                st.markdown(f"### 🧾 兌獎結果總覽 (成本: NT$ {total_cost:,})")
                
                with st.spinner("📡 正在比對歷史資料庫並向台彩伺服器查詢..."):
                    for i in range(check_draws):
                        target_issue = str(start_issue + i)
                        
                        # 📌 終極穿透查詢邏輯：先找快取，找不到就直接去打台彩 API
                        draw_data = next((item for item in history_data if item["issue"] == target_issue), None)
                        if not draw_data:
                            draw_data = BingoScraper.fetch_single_issue(target_issue)
                        
                        with st.expander(f"第 {target_issue} 期 對獎明細", expanded=True):
                            if draw_data:
                                matched = list(set(st.session_state.chk_picks) & set(draw_data['numbers']))
                                prize = BingoGameLogic.calculate_prize(check_star, len(matched), check_multi)
                                total_win += prize
                                
                                # 顯示動態抓回來的時間戳記
                                st.write(f"**本期開獎號碼：** <span class='time-tag'>🕒 開獎時間: {draw_data['time']}</span>", unsafe_allow_html=True)
                                st.markdown(BingoUI.render_balls(draw_data['numbers'], "normal") + BingoUI.render_balls(draw_data['super_num'], "super"), unsafe_allow_html=True)
                                
                                st.write("**您的號碼：**")
                                st.markdown(BingoUI.render_balls(st.session_state.chk_picks, "user"), unsafe_allow_html=True)
                                
                                if prize > 0:
                                    st.success(f"🎉 狂賀！對中 {len(matched)} 顆，獲得獎金 **NT$ {prize:,}**！")
                                    if matched: st.markdown(BingoUI.render_balls(matched, "match"), unsafe_allow_html=True)
                                else:
                                    st.error(f"💨 對中 {len(matched)} 顆，未中獎。")
                            else:
                                st.warning(f"⏳ 查無第 {target_issue} 期開獎資料 (可能尚未開出，或台彩伺服器已移除該期紀錄)。")
                
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