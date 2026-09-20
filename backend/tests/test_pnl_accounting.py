from app.engine import fee_inclusive_avg_entry


def test_fee_inclusive_avg_entry_single_fill():
    entry = fee_inclusive_avg_entry(
        current_avg=0.0,
        current_qty=0.0,
        price=81108.70,
        qty=0.01,
        fee=2.1088262,
    )
    assert round(entry, 5) == 81319.58262


def test_fee_inclusive_avg_entry_weighted_add():
    first = fee_inclusive_avg_entry(0.0, 0.0, 100.0, 1.0, 1.0)
    second = fee_inclusive_avg_entry(first, 1.0, 110.0, 1.0, 1.1)
    assert second == 106.05
