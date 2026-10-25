import time
from collections import Counter
from typing import Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

from bingo import logic, ui
from bingo.logic import TICKET_PRICE
from bingo.scraper import BingoScraper, now_tw, today_tw_str
from bingo.storage import StorageError, StorageManager, UserAuth


# ==========================================
# 共用輔助
# ==========================================
def timestamp_now() -> str:
    return now_tw().strftime("%m/%d %H:%M:%S")


def find_draw(issue: str, draw_index: Dict[str, Dict], history_data: List[Dict]) -> Optional[Dict]:
    """先從已載入的近 3 天資料找，找不到再跨日查詢；連線失敗回傳 None，下次刷新再試。"""
    if issue in draw_index: return draw_index[issue]
    try: res = BingoScraper.fetch_range(issue, 1, history_data)
    except requests.exceptions.RequestException: return None
    return res[0] if res else None


def save_current_bets():
    try:
        StorageManager.save_bets(st.session_state.current_user, st.session_state.bet_history)
    except StorageError as e:
        st.error(f"🚨 {e}"); st.stop()


def new_bet(bet_type: str, issue: int, star: int, multiplier: int, picks: List[int]) -> Dict:
    return {
        "type": bet_type,
        "issue": str(issue),
        "star": star,
        "multiplier": multiplier,
        "cost": TICKET_PRICE * multiplier,
        "prize": 0,
        "picks": list(picks),
        "status": "waiting",
        "timestamp": timestamp_now(),
    }


@st.cache_data(show_spinner=False, max_entries=20)
def run_backtest(history: List[Dict], star: int, n_tests: int) -> List[Dict]:
    return logic.backtest(history, star, n_tests=n_tests)


# ==========================================
# 側欄：帳號
# ==========================================
def sidebar_account() -> bool:
    """回傳是否已成功登入；成功時 session_state.current_user / bet_history 已就緒。"""
    with st.sidebar:
        st.title("👤 玩家帳戶系統")
        input_user = st.text_input("請輸入您的專屬暱稱：", value="預設玩家", help="輸入不同暱稱即可切換帳號，歷史紀錄完全獨立！").strip()
        password = st.text_input("🔑 密碼", type="password", help="已設定密碼的暱稱必須輸入正確密碼才能存取。")
        if not input_user:
            st.warning("請輸入暱稱。")
            return False

        try:
            has_password = UserAuth.has_password(input_user)
            if st.session_state.get("current_user") != input_user:
                if not UserAuth.verify(input_user, password):
                    st.error("🔒 密碼錯誤。" if password else "🔒 此暱稱已設定密碼，請輸入密碼。")
                    return False
                loaded_bets = StorageManager.load_bets(input_user)
                st.session_state.current_user = input_user
                st.session_state.bet_history = loaded_bets
                st.session_state.cart = []
                st.session_state.user_picks = []
                st.session_state.import_picks = []
        except StorageError as e:
            st.error(f"🚨 {e}")
            return False

        st.success(f"目前登入身份：**{st.session_state.current_user}**")
        if not has_password:
            st.warning("⚠️ 此暱稱尚未設定密碼，任何人輸入相同暱稱都能查看或清除紀錄。")
            if st.button("🔒 用上方輸入的密碼鎖定此暱稱", width="stretch"):
                try:
                    UserAuth.set_password(input_user, password)
                    st.success("✅ 已設定密碼，之後登入此暱稱需輸入密碼。")
                except (ValueError, StorageError) as e:
                    st.error(f"⚠️ {e}")
        st.divider()
        st.caption("💾 紀錄儲存於伺服器端檔案。若主機重新部署 (例如 Streamlit Cloud 重啟) 而未設定持久化儲存，紀錄可能遺失。")
    return True


# ==========================================
# Tab 1: 開獎紀錄
# ==========================================
def render_draws(history_data: List[Dict], target_date: str):
    st.subheader(f"📝 近期開獎紀錄 (共載入 {len(history_data)} 期 | 涵蓋 {target_date})")
    with st.container(height=650):
        for draw in history_data[:200]:
            with st.container(border=True):
                c1, c2 = st.columns([1, 4])
                c1.markdown(f"**第 `{draw['issue']}` 期**<br><span class='time-tag'>🕒 {draw['time']}</span>", unsafe_allow_html=True)
                c2.markdown(ui.render_balls(draw['numbers'], "normal") + ui.render_balls(draw['super_num'], "super"), unsafe_allow_html=True)


# ==========================================
# Tab 2: 今日走勢 (純統計描述)
# ==========================================
def render_analysis(history_data: List[Dict]):
    st.subheader("📊 今日開獎統計")
    st.caption("以下皆為已開出結果的統計描述。每期開獎彼此獨立，過去的冷熱、遺漏或拖牌不會影響下一期的機率。")
    today_str = today_tw_str()
    today_data = [d for d in history_data if d.get("date") == today_str]

    if not today_data and history_data:
        latest_date_str = history_data[0]["date"]
        today_data = [d for d in history_data if d.get("date") == latest_date_str]
        st.info(f"💡 今日 ({today_str}) 尚未有開獎資料，以下顯示最新開獎日 ({latest_date_str}) 的統計。")

    st.markdown(f"**📍 本日已開出：** `{len(today_data)}` 期")
    if not today_data: return

    counter = logic.get_frequencies(today_data)
    missing = logic.missing_counts(today_data)

    st.markdown("### 🏆 今日出現次數排行 (Top 15)")
    full_counts = {i: counter.get(i, 0) for i in logic.ALL_NUMBERS}
    sorted_hot = sorted(full_counts.items(), key=lambda x: (-x[1], x[0]))[:15]
    sorted_cold = sorted(full_counts.items(), key=lambda x: (x[1], x[0]))[:15]

    for col, title, icon, rows in zip(st.columns(2), ["##### 🔥 最常出現 15 名", "##### ❄️ 最少出現 15 名"], ["🔥", "❄️"], [sorted_hot, sorted_cold]):
        with col:
            st.markdown(title)
            df = pd.DataFrame(rows, columns=["號碼", "出現次數"])
            df["號碼"] = df["號碼"].apply(lambda x, icon=icon: f"{icon} {x:02d}")
            df.index = range(1, len(df) + 1)
            st.dataframe(df, width="stretch")

    st.divider()
    st.markdown("### 🕵️‍♂️ 今日熱門號的遺漏期數")
    st.markdown("今日出現次數前 20 名的號碼中，距離上次開出最久的 5 個。")
    for col, (dormant_num, miss_cnt) in zip(st.columns(5), logic.hot_but_dormant(today_data)[:5]):
        with col:
            st.metric(label=f"🔥熱號 {dormant_num:02d}", value=f"{miss_cnt} 期", delta="未開出", delta_color="off")

    st.divider()
    st.markdown("### 🌡️ 號碼區間分佈")
    zones = {f"{i*10+1:02d}-{i*10+10:02d}": 0 for i in range(8)}
    for num, cnt in counter.items():
        zone_idx = (num - 1) // 10
        zones[f"{zone_idx*10+1:02d}-{zone_idx*10+10:02d}"] += cnt
    st.bar_chart(pd.DataFrame(list(zones.items()), columns=["區間", "開出總次數"]).set_index("區間"), color="#FF4B2B")
    st.caption(f"💡 今日開出最多的區間為 **「{max(zones, key=zones.get)}」**；各區間理論上應各占約 12.5%。")
    st.divider()

    st.markdown("### 🎯 今日最常開出號碼 & 同期開出號碼")
    for hot_num, count in counter.most_common(5):
        assoc_str = '、 '.join([f"「{n:02d}」({c}次)" for n, c in logic.associated_numbers(today_data, hot_num).most_common(3)])
        st.info(f"👑 **{hot_num:02d}** (開出 {count} 次)\n\n ➡️ **最常同期開出：** {assoc_str}")
    st.divider()

    st.markdown("### 🥶 最大遺漏期數")
    st.markdown("今日最久沒開出的號碼。")
    for col, (miss_num, miss_cnt) in zip(st.columns(5), sorted(missing.items(), key=lambda x: x[1], reverse=True)[:5]):
        with col: st.metric(label=f"❄️號碼 {miss_num:02d}", value=f"{miss_cnt} 期", delta="未開出", delta_color="off")
    st.divider()

    st.markdown("### 📈 大小單雙 & 超級獎號")
    total_balls = len(today_data) * logic.DRAW_SIZE
    bigs = sum(1 for draw in today_data for n in draw['numbers'] if n >= 41)
    odds = sum(1 for draw in today_data for n in draw['numbers'] if n % 2 != 0)
    repeats = [len(set(today_data[i]['numbers']) & set(today_data[i+1]['numbers'])) for i in range(len(today_data) - 1)]
    avg_repeat = sum(repeats) / len(repeats) if repeats else 0

    super_nums = [draw['super_num'] for draw in today_data]
    super_big = sum(1 for n in super_nums if n >= 41)
    super_odd = sum(1 for n in super_nums if n % 2 != 0)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("**📉 整體大小/單雙**")
        st.write(f"大區: {bigs/total_balls:.1%} | 小區: {(total_balls-bigs)/total_balls:.1%}")
        st.write(f"單數: {odds/total_balls:.1%} | 雙數: {(total_balls-odds)/total_balls:.1%}")
        st.metric("平均與上期重複", f"{avg_repeat:.1f} 顆", help="理論期望值為 5 顆 (20 × 20/80)")
    with col_b:
        st.markdown("**🌟 超級獎號**")
        st.write(f"大區: {super_big} 次 | 小區: {len(super_nums) - super_big} 次")
        st.write(f"單數: {super_odd} 次 | 雙數: {len(super_nums) - super_odd} 次")
    with col_c:
        st.markdown("**🎯 尾數排行**")
        for rank, (tail_num, t_count) in enumerate(Counter(n % 10 for draw in today_data for n in draw['numbers']).most_common(3)):
            st.write(f"🏆 第 {rank+1} 名：**{tail_num} 尾** (開 {t_count} 次)")


# ==========================================
# Tab 3: 虛擬下注 & 實體匯入
# ==========================================
TOOLBOX_BUTTONS = ["hot", "cold", "mid", "fill_rand", "drag", "dormant_drag", "tail", "fill_hot",
                   "odd", "even", "big", "small", "random", "rep"]
FILL_LABELS = {"fill_rand": "💡 隨機補滿", "fill_hot": "🧠 熱門補滿"}
BATCH_STRATEGIES = ["random", "hot", "mid", "drag", "dormant_drag"]


def render_virtual_betting(history_data: List[Dict], latest_issue: int):
    next_issue = latest_issue + 1
    st.info(f"💡 目前虛擬下注的目標起算期數為：**第 `{next_issue}` 期**")

    def apply_strat(strat):
        sc = st.session_state.star_input
        if strat == "fill_rand": st.session_state.user_picks = logic.fill_remaining_rand(st.session_state.user_picks, sc)
        elif strat == "fill_hot": st.session_state.user_picks = logic.fill_remaining_hot(st.session_state.user_picks, sc, history_data)
        else: st.session_state.user_picks = logic.generate(strat, history_data, sc)

    def on_star_change():
        sc = st.session_state.star_input
        if len(st.session_state.user_picks) > sc: st.session_state.user_picks = st.session_state.user_picks[:sc]

    def add_single_to_cart():
        sc = st.session_state.star_input
        picks = st.session_state.user_picks
        if len(picks) == sc:
            st.session_state.cart.append({"star": sc, "picks": sorted(picks)})
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
        with c2: st.multiselect("✍️ 手動選號 (或點擊下方工具自動產生)", logic.ALL_NUMBERS, max_selections=star_count, key="user_picks")

        st.markdown("##### 🧰 選號工具箱 (點擊自動套用)")
        st.caption("這些工具只是不同的選號方式，每種組合的中獎機率完全相同。想看實際差異可到「🧪 策略回測」。")
        for start in range(0, len(TOOLBOX_BUTTONS), 4):
            for col, key in zip(st.columns(4), TOOLBOX_BUTTONS[start:start + 4]):
                label = FILL_LABELS.get(key) or logic.STRATEGIES[key][0]
                help_text = "鎖定今日熱門號中最久未開的號碼，搭配與它最常同期開出的號碼" if key == "dormant_drag" else None
                col.button(label, on_click=apply_strat, args=(key,), width="stretch", help=help_text, key=f"tool_{key}")

        st.button("➕ 將上方號碼加入待結帳區", on_click=add_single_to_cart, width="stretch", type="secondary")
        if st.session_state.cart_warning: st.warning("⚠️ 請選滿號碼再加入！")

        st.divider()
        st.markdown(f"##### 🚀 一鍵批次產生 (直接產生 `{batch_count}` 組加入購物車)")
        for col, key in zip(st.columns(len(BATCH_STRATEGIES)), BATCH_STRATEGIES):
            if col.button(logic.STRATEGIES[key][0], width="stretch", key=f"batch_{key}"):
                st.session_state.cart.extend({"star": star_count, "picks": logic.generate(key, history_data, star_count)} for _ in range(batch_count))
                st.rerun()

    if not st.session_state.cart: return
    st.markdown("### 🛒 待下注購物車")
    for i, item in enumerate(st.session_state.cart):
        with st.container(border=True):
            cart_c1, cart_c2 = st.columns([10, 1])
            cart_c1.markdown(f"**{item['star']} 星** | " + ui.render_balls(item['picks'], "user"), unsafe_allow_html=True)
            if cart_c2.button("❌", key=f"del_cart_{i}"):
                st.session_state.cart.pop(i)
                st.rerun()

    cart_total_cost = len(st.session_state.cart) * TICKET_PRICE * multiplier * multi_draw
    st.info(f"🧾 本次結帳總計: **{len(st.session_state.cart)}** 組選號 x **{multiplier}** 倍 x **{multi_draw}** 期 = 扣除本金 **NT$ {cart_total_cost:,}**")

    col_submit, col_clear = st.columns([3, 1])
    if col_submit.button("📝 確認送出虛擬注單", type="primary", width="stretch"):
        for item in st.session_state.cart:
            for i in range(multi_draw):
                st.session_state.bet_history.insert(0, new_bet("virtual", next_issue + i, item['star'], multiplier, item['picks']))
        save_current_bets()
        st.session_state.cart.clear()
        st.success("✅ 虛擬下注成功！資料已寫入「我的投注紀錄」。")
        time.sleep(1.5)
        st.rerun()
    if col_clear.button("🗑️ 清空購物車", width="stretch"):
        st.session_state.cart.clear(); st.rerun()


def render_import(latest_issue: int):
    st.markdown("#### 📥 將手邊的實體彩券匯入系統代管")
    st.write("把彩券上的資訊輸入進來，系統會自動在後台持續幫你對獎，再也不怕漏看！")

    def on_import_star_change():
        sc = st.session_state.import_star
        if len(st.session_state.import_picks) > sc:
            st.session_state.import_picks = st.session_state.import_picks[:sc]

    def submit_import():
        issue = st.session_state.import_issue.strip()
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

        for i in range(draws):
            st.session_state.bet_history.insert(0, new_bet("real", int(issue) + i, star, multi, picks))
        try:
            StorageManager.save_bets(st.session_state.current_user, st.session_state.bet_history)
        except StorageError as e:
            st.session_state.import_msg = ("error", f"🚨 {e}")
            return
        st.session_state.import_picks = []
        st.session_state.import_msg = ("success", f"✅ 成功匯入 {draws} 期實體彩券！請至「我的投注紀錄」查看對獎結果。")

    with st.container(border=True):
        col_i1, col_i2, col_i3 = st.columns(3)
        with col_i1: st.text_input("📌 彩券起始期號", value=str(latest_issue), key="import_issue")
        with col_i2: st.number_input("🔁 連續期數", 1, 500, 1, key="import_draws")
        with col_i3: st.number_input("💰 投注倍數", 1, 100, 1, key="import_multi")

        col_i4, col_i5 = st.columns([1, 4])
        with col_i4: st.number_input("⭐ 玩法 (星數)", 1, 10, 5, key="import_star", on_change=on_import_star_change)
        with col_i5: st.multiselect("✍️ 彩券上的號碼", logic.ALL_NUMBERS, max_selections=st.session_state.get('import_star', 5), key="import_picks")

    st.button("📥 立即匯入這張彩券", type="primary", width="stretch", on_click=submit_import)

    if st.session_state.import_msg:
        msg_type, msg_text = st.session_state.import_msg
        if msg_type == "error": st.error(msg_text)
        else: st.success(msg_text)
        st.session_state.import_msg = None


def render_betting(history_data: List[Dict], latest_issue: int):
    st.subheader("🎫 下注與實體彩券管理中樞")
    bet_mode = st.radio("請選擇操作模式：", ["🎮 虛擬模擬下注 (測試策略)", "🧾 匯入已購買的實體彩券 (系統代管對獎)"], horizontal=True)
    st.divider()
    if bet_mode == "🎮 虛擬模擬下注 (測試策略)": render_virtual_betting(history_data, latest_issue)
    else: render_import(latest_issue)


# ==========================================
# Tab 4: 我的投注紀錄
# ==========================================
def settle_pending_bets(history_data: List[Dict], draw_index: Dict[str, Dict], latest_issue: int):
    """對獎尚未開獎的注單；舊版用寫死加碼賠率結算過的注單，也會用該期官方獎金重新核算一次。"""
    is_updated = False
    for bet in st.session_state.bet_history:
        waiting = bet["status"] == "waiting" and int(bet["issue"]) <= latest_issue  # 期號大於最新期 → 一定還沒開
        legacy = bet["status"] == "matched" and "prize_source" not in bet
        if not (waiting or legacy): continue
        draw_result = find_draw(bet["issue"], draw_index, history_data)
        if not draw_result: continue
        matched, prize = logic.settle(bet["picks"], bet["star"], bet["multiplier"], draw_result)
        bet.update({
            "status": "matched", "matched_nums": matched, "prize": prize, "draw_time": draw_result["time"],
            "prize_source": "official" if draw_result.get("prize_table") else "standard",
        })
        is_updated = True
    if is_updated: save_current_bets()


def render_records(history_data: List[Dict], draw_index: Dict[str, Dict], latest_issue: int):
    settle_pending_bets(history_data, draw_index, latest_issue)
    bets = st.session_state.bet_history

    st.markdown(f"### 💰 【{st.session_state.current_user}】專屬帳戶總覽")
    for label, is_real in [("🧾 實體彩券", True), ("🎮 虛擬測試", False)]:
        group = [b for b in bets if (b.get('type') == 'real') == is_real]
        cost = sum(b['cost'] for b in group)
        prize = sum(b['prize'] for b in group if b['status'] == 'matched')
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{label}總成本", f"NT$ {cost:,}")
        c2.metric(f"{label}累積中獎", f"NT$ {prize:,}")
        c3.metric(f"{label}淨損益", f"NT$ {prize - cost:,}", delta=int(prize - cost))
    st.caption("派彩金額依台彩官方公布之各期獎金計算 (自動反映限時加碼活動)。")

    st.divider()
    c_title, c_btn1, c_btn2 = st.columns([2, 1, 1])
    c_title.markdown("### 📋 歷史明細清單")
    if c_btn1.button("🔄 刷新最新開獎", width="stretch"): st.cache_data.clear(); st.rerun()
    if c_btn2.button("🗑️ 清空此帳號所有紀錄", type="secondary", width="stretch"):
        st.session_state.bet_history = []
        save_current_bets()
        st.rerun()

    if not bets:
        st.info("目前沒有注單。")
        return

    summary_data = [{
        "類型": "🧾 實體" if bet.get("type") == "real" else "🎮 虛擬",
        "目標期數": bet["issue"],
        "玩法": f"{bet['star']} 星",
        "倍數": f"{bet['multiplier']} 倍",
        "成本": f"${bet['cost']}",
        "狀態": "⏳ 等待中" if bet["status"] == "waiting" else "✅ 已開獎",
        "中獎金額": f"${bet['prize']}" if bet["status"] == "matched" else "-",
    } for bet in bets]
    st.dataframe(pd.DataFrame(summary_data), width="stretch", hide_index=True)

    st.markdown("#### 🔍 詳細對獎紀錄 (中獎會自動展開)")
    for i, bet in enumerate(bets):
        time_str = f" | 🕒 {bet.get('draw_time', '未知')}" if bet['status'] == 'matched' else ""
        type_icon = "🧾 實體" if bet.get("type") == "real" else "🎮 虛擬"
        is_win = bet.get("prize", 0) > 0
        exp_title = f"{'🎉' if is_win else '💨'} [{type_icon}] 第 {bet['issue']} 期 | {bet['star']}星 | 成本 ${bet['cost']} | 狀態: {'⏳ 等待開獎' if bet['status'] == 'waiting' else '✅ 已開獎'}{time_str}"

        with st.expander(exp_title, expanded=is_win):
            st.write("**你的選號：**")
            st.markdown(ui.render_balls(bet['picks'], "user"), unsafe_allow_html=True)

            if bet["status"] == "matched":
                matched = bet.get("matched_nums", [])
                draw_result = find_draw(bet["issue"], draw_index, history_data)
                if draw_result:
                    st.write("**本期開獎：**")
                    st.markdown(ui.render_balls(draw_result['numbers'], "normal"), unsafe_allow_html=True)

                if bet["prize"] > 0:
                    if matched: st.success(f"🎉 對中 {len(matched)} 個號碼，贏得獎金 **NT$ {bet['prize']:,}**")
                    else: st.success(f"🎉 觸發「全倒」規則 (0顆)，拿回 **NT$ {bet['prize']:,}**")
                else:
                    st.error(f"💨 對中 {len(matched)} 顆，未達派彩標準。")

            if st.button("🗑️ 刪除此單筆紀錄", key=f"del_hist_{i}"):
                st.session_state.bet_history.pop(i)
                save_current_bets()
                st.rerun()


# ==========================================
# Tab 5: 單次實體對獎
# ==========================================
def render_quick_check(history_data: List[Dict], latest_issue: int):
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
            q_date = st.date_input("1. 選擇購買日期", value=now_tw())
        with col_q2:
            try: day_data = BingoScraper.fetch_by_date(q_date.strftime("%Y-%m-%d"))
            except requests.exceptions.RequestException as e:
                day_data = []
                st.error(f"🚨 開獎資料連線失敗: {e}")
            if day_data:
                opts = {f"🕒 {d['time'][11:16]} (第 {d['issue']} 期)": d['issue'] for d in sorted(day_data, key=lambda x: int(x['issue']))}
                sel_lbl = st.selectbox("2. 選擇購買/起始時間", list(opts.keys()))
                check_issue_value = opts[sel_lbl]
            else:
                st.warning("⚠️ 查無該日開獎資料")
    else:
        with col_q1: check_issue_value = st.text_input("📌 手動輸入起始期號", value=str(latest_issue)).strip()

    st.divider()

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1: check_draws = st.number_input("🔁 連續期數 (最高支援 500 期)", 1, 500, 1)
        with c2: check_star = st.number_input("⭐ 玩法 (星數)", 1, 10, 5, key="chk_star", on_change=on_chk_star_change)
        with c3: check_multi = st.number_input("💰 投注倍數", 1, 100, 1)

        if 'chk_picks' not in st.session_state: st.session_state.chk_picks = []
        st.multiselect("✍️ 請輸入彩券上的投注號碼", logic.ALL_NUMBERS, max_selections=check_star, key="chk_picks")

    if not st.button("🔍 一鍵結算本張彩券", type="primary", width="stretch"): return
    if not check_issue_value.isdigit(): st.warning("⚠️ 起始期號不正確！"); return
    if len(st.session_state.chk_picks) != check_star: st.warning(f"⚠️ 號碼未選滿 {check_star} 顆！"); return

    total_cost = TICKET_PRICE * check_multi * check_draws
    total_win = 0

    st.divider()
    st.markdown(f"### 🧾 兌獎結果總覽 (成本: NT$ {total_cost:,})")

    with st.spinner(f"📡 正在為您跨日調閱連續 {check_draws} 期的開獎資料，請稍候..."):
        try: range_data = BingoScraper.fetch_range(check_issue_value, check_draws, history_data)
        except requests.exceptions.RequestException as e:
            st.error(f"🚨 開獎資料連線失敗，請稍後再試: {e}"); return

    if not range_data:
        st.error("❌ 查無該起始期號的資料！請確認日期或期號是否正確。")
        return

    for draw_data in range_data:
        matched, prize = logic.settle(st.session_state.chk_picks, check_star, check_multi, draw_data)
        total_win += prize

        if prize > 0:
            exp_title = f"🎉 第 {draw_data['issue']} 期 | 中獎 NT$ {prize:,} | 🕒 {draw_data['time']}"
        else:
            exp_title = f"💨 第 {draw_data['issue']} 期 | 未中獎 | 🕒 {draw_data['time']}"

        with st.expander(exp_title, expanded=prize > 0 or check_draws <= 5):
            st.markdown("**開獎號碼：**<br>" + ui.render_balls(draw_data['numbers'], "normal") + ui.render_balls(draw_data['super_num'], "super"), unsafe_allow_html=True)
            st.markdown("**您的號碼：**<br>" + ui.render_balls(st.session_state.chk_picks, "user"), unsafe_allow_html=True)
            if prize > 0:
                st.success(f"🎉 對中 {len(matched)} 顆，獲得獎金 **NT$ {prize:,}**！")
                if matched: st.markdown(ui.render_balls(matched, "match"), unsafe_allow_html=True)
            else:
                st.error(f"💨 對中 {len(matched)} 顆，未中獎。")

    if len(range_data) < check_draws:
        st.info(f"⏳ 溫馨提示：您選擇對獎 {check_draws} 期，但目前僅開出 {len(range_data)} 期，剩餘期數請稍後再查。")

    st.divider()
    st.markdown(f"#### 💰 總計獲得獎金: **NT$ {total_win:,}**")
    if total_win > total_cost:
        st.balloons()
        st.success(f"🎊 恭喜！本張彩券淨賺 **NT$ {total_win - total_cost:,}**")
    elif total_win > 0:
        st.info(f"💵 本張彩券回本 **NT$ {total_win:,}**，總計淨損 **NT$ {total_cost - total_win:,}**")
    else:
        st.error(f"💸 本張彩券未中獎，淨損 **NT$ {total_cost:,}**")


# ==========================================
# Tab 6: 策略回測
# ==========================================
def render_backtest(history_data: List[Dict]):
    st.subheader("🧪 策略回測：這些選號法真的有用嗎？")
    st.markdown(
        "對最近的每一期，只用**該期之前**的 203 期 (約一天) 資料，以各種工具箱策略選號並與實際開獎對獎，"
        "每期每策略買 1 注。若某個策略真的有預測力，它的回報率應該**穩定地**高於機選。"
    )
    window = 203
    max_tests = len(history_data) - window
    if max_tests < 20:
        st.info("目前載入的歷史資料不足，無法回測。")
        return

    c1, c2 = st.columns(2)
    star = c1.number_input("⭐ 回測星數", 1, 10, 5, key="bt_star")
    n_tests = c2.slider("📆 回測期數", 20, min(max_tests, 400), min(200, max_tests), step=10, key="bt_n")

    prize_table = history_data[0].get("prize_table")
    rtp = logic.theoretical_rtp(star, prize_table)
    st.metric(f"{star} 星理論回報率 (依最新一期獎金)", f"{rtp:.1%}", help="每投注 1 元，長期平均可拿回的金額；不論怎麼選號都一樣。")

    if not st.button("▶️ 開始回測", type="primary", width="stretch"): return
    with st.spinner("回測中..."):
        results = run_backtest(history_data, star, n_tests)

    df = pd.DataFrame([{
        "策略": r["label"], "注數": r["bets"], "成本": r["cost"], "獎金": r["prize"],
        "回報率": f"{r['rtp']:.1%}", "中獎率": f"{r['hit_rate']:.1%}",
    } for r in sorted(results, key=lambda r: -r["rtp"])])
    st.dataframe(df, width="stretch", hide_index=True)
    st.caption(
        f"回測僅 {n_tests} 注，結果受少數大獎影響很大：重新選不同期數或星數，排名通常會大幅變動。"
        f"長期而言所有策略的回報率都會收斂到理論值 {rtp:.1%}。"
    )


# ==========================================
# 主程式
# ==========================================
def main():
    ui.setup()
    if not sidebar_account():
        st.info("👈 請在左側輸入暱稱 (以及密碼，如有設定) 以開始使用。")
        st.stop()

    if 'cart_warning' not in st.session_state: st.session_state.cart_warning = False
    if 'import_msg' not in st.session_state: st.session_state.import_msg = None

    st.title("🎰 BINGO BINGO 對獎與統計系統")
    st.markdown("<div class='info-tag'>💡 派彩依台彩官方公布之各期獎金計算，自動反映限時加碼活動</div>", unsafe_allow_html=True)

    try:
        history_data, target_date = BingoScraper.fetch_data()
        latest_issue = int(history_data[0]['issue'])
    except Exception as e:
        st.error(f"🚨 系統連線失敗: {e}"); st.stop()
    draw_index = {d["issue"]: d for d in history_data}

    rtps = [logic.theoretical_rtp(s, history_data[0].get("prize_table")) for s in range(1, 11)]
    st.caption(
        f"⚠️ 每期開獎都是獨立的隨機事件，本工具的統計與選號策略都無法提高中獎機率。"
        f"依目前獎金，各玩法理論回報率約 {min(rtps):.0%}～{max(rtps):.0%} (每投注 100 元長期平均拿回的金額)。"
        f"請量力而為，未滿 18 歲不得購買彩券。"
    )

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 開獎紀錄", "🔥 今日開獎統計", "🎫 虛擬下注 & 實體匯入", "📋 我的投注紀錄", "🎯 單次實體對獎", "🧪 策略回測"
    ])
    with tab1: render_draws(history_data, target_date)
    with tab2: render_analysis(history_data)
    with tab3: render_betting(history_data, latest_issue)
    with tab4: render_records(history_data, draw_index, latest_issue)
    with tab5: render_quick_check(history_data, latest_issue)
    with tab6: render_backtest(history_data)


if __name__ == "__main__":
    main()
