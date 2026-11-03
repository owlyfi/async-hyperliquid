import pytest

from benchmarks.fast_cancel import fast_plan, parse_args, summarize


def test_fast_plan_alternates_and_swaps_first_method_each_round() -> None:
    assert fast_plan(0, 4) == (False, True, False, True)
    assert fast_plan(1, 4) == (True, False, True, False)
    assert fast_plan(0, 10).count(True) == 5


def test_summarize_reports_milliseconds() -> None:
    stats = summarize([1_000_000 * value for value in range(1, 101)])
    assert stats["n"] == 100
    assert stats["mean"] == pytest.approx(50.5)
    assert stats["p50"] == pytest.approx(50.5)
    assert stats["min"] == 1
    assert stats["max"] == 100


@pytest.mark.parametrize(
    "argv", (["--orders", "3"], ["--orders", "0"], ["--interval-ms", "100"])
)
def test_parse_args_rejects_unsafe_shapes(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(argv)
