import random

import pytest

from bingo import logic


def draw(numbers, prize_table=None):
    return {"issue": "1", "numbers": sorted(numbers), "super_num": numbers[0], "prize_table": prize_table}


def make_history(n, seed=0):
    rng = random.Random(seed)
    return [{"issue": str(1000 - i), "numbers": sorted(rng.sample(range(1, 81), 20)), "prize_table": None}
            for i in range(n)]


def test_parse_prize_table_follows_api_order():
    flat = [d for row in logic.STANDARD_PRIZE_TABLE.values() for d in row.values()]
    assert len(flat) == 40
    table = logic.parse_prize_table([{"winners": 0, "dividend": d} for d in flat])
    assert table == logic.STANDARD_PRIZE_TABLE


@pytest.mark.parametrize("bad", [None, [], [{"dividend": 1}] * 39, [{"dividend": "x"}] * 40])
def test_parse_prize_table_rejects_bad_input(bad):
    assert logic.parse_prize_table(bad) is None


def test_settle_uses_draw_prize_table_then_falls_back():
    promo = {s: dict(row) for s, row in logic.STANDARD_PRIZE_TABLE.items()}
    promo[1][1] = 75
    numbers = list(range(1, 21))
    assert logic.settle([5], 1, 2, draw(numbers, promo)) == ([5], 150)
    assert logic.settle([5], 1, 2, draw(numbers)) == ([5], 100)
    assert logic.settle([79], 1, 1, draw(numbers)) == ([], 0)
    # 10 星全倒有安慰獎
    assert logic.settle(list(range(71, 81)), 10, 1, draw(numbers)) == ([], 25)


def test_theoretical_rtp_is_below_one():
    for star in range(1, 11):
        assert 0.3 < logic.theoretical_rtp(star) < 1
    assert logic.theoretical_rtp(1) == pytest.approx(20 / 80 * 50 / 25)


def test_missing_counts_and_dormant():
    history = [draw([1] + list(range(2, 21))), draw(list(range(21, 41))), draw(list(range(21, 41)))]
    missing = logic.missing_counts(history)
    assert missing[1] == 0 and missing[21] == 1 and missing[80] == 3
    assert logic.hot_but_dormant(history, top_n=40)[0][1] == 1


@pytest.mark.parametrize("strategy", list(logic.STRATEGIES))
@pytest.mark.parametrize("star", [1, 5, 10])
@pytest.mark.parametrize("n_history", [0, 1, 2, 60])
def test_every_strategy_returns_valid_picks(strategy, star, n_history):
    picks = logic.generate(strategy, make_history(n_history), star, random.Random(1))
    assert len(picks) == star == len(set(picks))
    assert picks == sorted(picks) and all(1 <= n <= 80 for n in picks)


def test_drag_fills_when_pool_is_small():
    # 只有一期與上期有共同號碼，拖牌候選池遠小於星數也不能出錯
    history = [draw(list(range(1, 21))), draw(list(range(1, 2)) + list(range(61, 80)))]
    assert len(logic.gen_drag(history, 10, random.Random(0))) == 10


def test_fill_functions_handle_edge_cases():
    rng = random.Random(0)
    assert logic.fill_remaining_hot([1, 2], 5, [], rng)[:2] == [1, 2]
    assert len(logic.fill_remaining_hot([1, 2], 5, [], rng)) == 5
    assert logic.fill_remaining_rand([3, 1, 2], 2, rng) == [1, 3]
    assert len(set(logic.fill_remaining_rand([], 10, rng))) == 10


def test_backtest_is_reproducible_and_uses_only_past_draws():
    history = make_history(260)
    first = logic.backtest(history, 3, n_tests=40, window=203)
    assert first == logic.backtest(history, 3, n_tests=40, window=203)
    assert {r["strategy"] for r in first} == set(logic.STRATEGIES)
    assert all(r["bets"] == 40 and r["cost"] == 40 * 25 for r in first)
    assert logic.backtest(history, 3, n_tests=500, window=203)[0]["bets"] == 57
