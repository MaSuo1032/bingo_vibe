"""選號、對獎、統計與回測邏輯（不依賴 Streamlit，可直接單元測試）。"""
import random
from collections import Counter
from math import comb
from typing import Callable, Dict, List, Optional, Tuple

ALL_NUMBERS = range(1, 81)
DRAW_SIZE = 20
TICKET_PRICE = 25

# 台彩 BINGO BINGO 標準獎金表 (每注 25 元，單位：元)。
# 實際對獎優先使用 API 回傳的每期官方獎金 (會反映限時加碼)，僅在缺資料時才退回此表。
# 每個星數內的鍵順序與 API `starDetails` 陣列順序一致，parse_prize_table 依賴此順序。
STANDARD_PRIZE_TABLE: Dict[int, Dict[int, int]] = {
    10: {10: 5000000, 9: 250000, 8: 25000, 7: 2500, 6: 250, 5: 25, 0: 25},
    9: {9: 1000000, 8: 100000, 7: 3000, 6: 500, 5: 100, 4: 25, 0: 25},
    8: {8: 500000, 7: 20000, 6: 1000, 5: 200, 4: 25, 0: 25},
    7: {7: 80000, 6: 3000, 5: 300, 4: 50, 3: 25},
    6: {6: 25000, 5: 1000, 4: 200, 3: 25},
    5: {5: 7500, 4: 500, 3: 50},
    4: {4: 1000, 3: 100, 2: 25},
    3: {3: 500, 2: 50},
    2: {2: 75, 1: 25},
    1: {1: 50},
}

PrizeTable = Dict[int, Dict[int, int]]


def parse_prize_table(star_details) -> Optional[PrizeTable]:
    """把 API 的 starDetails (40 筆 {winners, dividend}) 轉成 {星數: {對中數: 獎金}}；格式不符回傳 None。"""
    slots = [(star, match) for star, row in STANDARD_PRIZE_TABLE.items() for match in row]
    if not isinstance(star_details, list) or len(star_details) != len(slots):
        return None
    table: PrizeTable = {}
    for (star, match), detail in zip(slots, star_details):
        dividend = detail.get("dividend") if isinstance(detail, dict) else None
        if not isinstance(dividend, int) or dividend < 0:
            return None
        table.setdefault(star, {})[match] = dividend
    return table


def calculate_prize(star_count: int, matched_count: int, multiplier: int = 1,
                    prize_table: Optional[PrizeTable] = None) -> int:
    table = prize_table or STANDARD_PRIZE_TABLE
    return table.get(star_count, {}).get(matched_count, 0) * multiplier


def settle(picks: List[int], star: int, multiplier: int, draw: Dict) -> Tuple[List[int], int]:
    """回傳 (對中號碼, 獎金)，使用該期的官方獎金表。"""
    matched = sorted(set(picks) & set(draw["numbers"]))
    return matched, calculate_prize(star, len(matched), multiplier, draw.get("prize_table"))


def theoretical_rtp(star: int, prize_table: Optional[PrizeTable] = None) -> float:
    """理論回報率：每投注 1 元平均拿回多少 (超幾何分布)。"""
    table = prize_table or STANDARD_PRIZE_TABLE
    total = comb(80, star)
    expected = sum(comb(DRAW_SIZE, k) * comb(80 - DRAW_SIZE, star - k) / total * prize
                   for k, prize in table.get(star, {}).items())
    return expected / TICKET_PRICE


# ---------- 統計 ----------
def get_frequencies(history: List[Dict]) -> Counter:
    return Counter(num for draw in history for num in draw["numbers"])


def missing_counts(history: List[Dict]) -> Dict[int, int]:
    """每個號碼距今幾期未開 (history 由新到舊)；從未開出則為 len(history)。"""
    result = {}
    for num in ALL_NUMBERS:
        result[num] = next((idx for idx, draw in enumerate(history) if num in draw["numbers"]), len(history))
    return result


def hot_but_dormant(history: List[Dict], top_n: int = 20) -> List[Tuple[int, int]]:
    """出現次數前 top_n 名的號碼，依未開期數由多到少排序。"""
    missing = missing_counts(history)
    top_hot = [num for num, _ in get_frequencies(history).most_common(top_n)]
    return sorted(((num, missing[num]) for num in top_hot), key=lambda x: x[1], reverse=True)


def associated_numbers(history: List[Dict], target: int) -> Counter:
    """與 target 同期開出的其他號碼次數 (拖牌)。"""
    return Counter(n for draw in history if target in draw["numbers"] for n in draw["numbers"] if n != target)


# ---------- 選號策略 ----------
def _random_picks(star: int, rng=random) -> List[int]:
    return sorted(rng.sample(ALL_NUMBERS, star))


def _sample_or_fill(pool: List[int], star: int, rng=random) -> List[int]:
    """從 pool 抽 star 個；pool 不足時用其餘號碼隨機補滿。"""
    pool = list(dict.fromkeys(pool))
    if len(pool) >= star:
        return sorted(rng.sample(pool, star))
    rest = [n for n in ALL_NUMBERS if n not in pool]
    return sorted(pool + rng.sample(rest, star - len(pool)))


def _ranked_by_frequency(history: List[Dict]) -> List[int]:
    nums = [n for n, _ in get_frequencies(history).most_common()]
    return nums + [n for n in ALL_NUMBERS if n not in nums]


def gen_random(history: List[Dict], star: int, rng=random) -> List[int]:
    return _random_picks(star, rng)


def gen_smart(history: List[Dict], star: int, mode: str = "hot", rng=random) -> List[int]:
    if not history:
        return _random_picks(star, rng)
    ranked = _ranked_by_frequency(history)
    if mode == "hot":
        pool = ranked[:max(15, star)]
    elif mode == "cold":
        pool = ranked[::-1][:max(15, star)]
    elif mode == "mid":
        pool = ranked[20:60]
    else:
        raise ValueError(f"未知模式: {mode}")
    return _sample_or_fill(pool, star, rng)


def gen_drag(history: List[Dict], star: int, rng=random) -> List[int]:
    if len(history) < 2:
        return _random_picks(star, rng)
    last_draw = set(history[0]["numbers"])
    associated = [n for draw in history[1:51] if last_draw & set(draw["numbers"])
                  for n in draw["numbers"] if n not in last_draw]
    if not associated:
        return _random_picks(star, rng)
    top_drag = [num for num, _ in Counter(associated).most_common(max(15, star))]
    return _sample_or_fill(top_drag, star, rng)


def gen_dormant_drag(history: List[Dict], star: int, rng=random) -> List[int]:
    dormant = hot_but_dormant(history)
    if not dormant:
        return _random_picks(star, rng)
    top_dormant = dormant[0][0]
    pool = [top_dormant] + [num for num, _ in associated_numbers(history, top_dormant).most_common()]
    pool = list(dict.fromkeys(pool))[:star]
    return _sample_or_fill(pool, star, rng)


def gen_repeat(history: List[Dict], star: int, rng=random) -> List[int]:
    if not history:
        return _random_picks(star, rng)
    return _sample_or_fill(history[0]["numbers"], star, rng)


def gen_tail(history: List[Dict], star: int, rng=random) -> List[int]:
    tails = rng.sample(range(10), 2)
    return _sample_or_fill([n for n in ALL_NUMBERS if n % 10 in tails], star, rng)


EXTREME_POOLS = {
    "odd": [n for n in ALL_NUMBERS if n % 2],
    "even": [n for n in ALL_NUMBERS if not n % 2],
    "big": list(range(41, 81)),
    "small": list(range(1, 41)),
}


def gen_extreme(history: List[Dict], star: int, mode: str, rng=random) -> List[int]:
    return sorted(rng.sample(EXTREME_POOLS[mode], star))


def fill_remaining_rand(picks: List[int], star: int, rng=random) -> List[int]:
    picks = list(picks)[:star]
    rest = [n for n in ALL_NUMBERS if n not in picks]
    return sorted(picks + rng.sample(rest, star - len(picks)))


def fill_remaining_hot(picks: List[int], star: int, history: List[Dict], rng=random) -> List[int]:
    picks = list(picks)[:star]
    needed = star - len(picks)
    if needed <= 0:
        return sorted(picks)
    available_hot = [n for n in _ranked_by_frequency(history) if n not in picks]
    pool = available_hot[:max(needed + 5, 10)]
    return sorted(picks + rng.sample(pool, needed))


# 策略註冊表：key -> (按鈕名稱, 產生函式(history, star, rng))
STRATEGIES: Dict[str, Tuple[str, Callable[..., List[int]]]] = {
    "random": ("🎲 機選", gen_random),
    "hot": ("🔥 熱門特徵", lambda h, s, rng=random: gen_smart(h, s, "hot", rng)),
    "cold": ("❄️ 冷門特徵", lambda h, s, rng=random: gen_smart(h, s, "cold", rng)),
    "mid": ("☯️ 溫態避險", lambda h, s, rng=random: gen_smart(h, s, "mid", rng)),
    "drag": ("🧲 上期拖牌", gen_drag),
    "dormant_drag": ("🕵️‍♂️ 潛伏+拖牌", gen_dormant_drag),
    "rep": ("🔁 上期重號", gen_repeat),
    "tail": ("🎯 同尾數", gen_tail),
    "odd": ("🔴 全單數", lambda h, s, rng=random: gen_extreme(h, s, "odd", rng)),
    "even": ("🔵 全雙數", lambda h, s, rng=random: gen_extreme(h, s, "even", rng)),
    "big": ("📈 全大區(41-80)", lambda h, s, rng=random: gen_extreme(h, s, "big", rng)),
    "small": ("📉 全小區(1-40)", lambda h, s, rng=random: gen_extreme(h, s, "small", rng)),
}


def generate(strategy: str, history: List[Dict], star: int, rng=random) -> List[int]:
    return STRATEGIES[strategy][1](history, star, rng)


# ---------- 回測 ----------
def backtest(history: List[Dict], star: int, n_tests: int = 200, window: int = 203,
             seed: int = 0) -> List[Dict]:
    """對每個策略：用第 i 期「之前」的 window 期資料選號，與第 i 期開獎結果對獎。history 由新到舊。"""
    n_tests = max(0, min(n_tests, len(history) - window))
    results = []
    for key, (label, _) in STRATEGIES.items():
        rng = random.Random(f"{seed}-{key}")
        cost = prize_total = hits = 0
        for i in range(n_tests):
            picks = generate(key, history[i + 1:i + 1 + window], star, rng)
            _, prize = settle(picks, star, 1, history[i])
            cost += TICKET_PRICE
            prize_total += prize
            hits += prize > 0
        results.append({
            "strategy": key, "label": label, "bets": n_tests, "cost": cost, "prize": prize_total,
            "rtp": prize_total / cost if cost else 0.0, "hit_rate": hits / n_tests if n_tests else 0.0,
        })
    return results
