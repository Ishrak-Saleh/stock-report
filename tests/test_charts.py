from app.charts import bullet, dot_plot, sparkline, stage_bar
from app.icons import ICONS, icon


def test_sparkline_highlights_last_three_days_and_escapes_label():
    svg = str(sparkline([1, 2, 3, 4, 5, 6, 7, 9, 9, 9], 'Sales of <b>"X"</b>'))
    assert svg.count("<polyline") == 2 and "stroke-accent" in svg
    assert "<b>" not in svg and "&lt;b&gt;" in svg  # label is escaped


def test_sparkline_with_no_sales_does_not_divide_by_zero():
    assert "<svg" in str(sparkline([0] * 40, "none"))


def test_bullet_bar_severity_and_blank():
    assert "fill-crit" in str(bullet(9.2, 33.9, "crit", 59, "x"))
    assert "fill-serious" in str(bullet(48.0, 48.0, "serious", 59, "x"))
    assert "fill-warn" in str(bullet(40.0, 80.0, "good", 59, "x"))
    assert "fill-accent" in str(bullet(74.4, 120.9, "good", 59, "x"))
    blank = str(bullet(None, None, "good", 59, "No sales"))
    assert "fill-line" in blank and "fill-accent" not in blank


def test_stage_bar_skips_empty_stages_and_uses_one_ramp():
    svg = str(stage_bar([(150, 1), (0, 2), (120, 3), (0, 4)], "270 on order", scale_max=300))
    assert svg.count("<rect") == 2 and "fill-st1" in svg and "fill-st3" in svg and "fill-st2" not in svg
    assert "fill-line" in str(stage_bar([(0, 1)], "none"))


def test_dot_plot_color_by_overdue_days():
    assert "fill-serious" in str(dot_plot(25, 10, 15, "x")) and "fill-warn" in str(dot_plot(11, 10, 1, "x"))


def test_every_icon_renders():
    for name in ICONS:
        assert f"<svg" in str(icon(name, 24))
