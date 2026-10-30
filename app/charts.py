"""Micro-charts as inline SVG. Presentation only: every number is worked out in `domain/` first and passed in.
Colors come from CSS classes (see app.css) so both themes work and no inline style is needed."""
from markupsafe import Markup, escape


def _svg(w: int, h: int, label: str, body: str) -> Markup:
    return Markup(f'<svg class="mc" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
                  f'aria-label="{escape(label)}">{body}</svg>')


def sparkline(series: list[int], label: str, w: int = 112, h: int = 28) -> Markup:
    """Daily sales, oldest to newest. The last 3 days (the trend window) take the accent color."""
    n = len(series)
    if n < 4:
        return _svg(w, h, label, "")
    mx = max(series + [1])

    def x(k: int) -> float:
        return 4 + (k / (n - 1)) * (w - 8)

    def y(v: int) -> float:
        return h - 4 - (v / mx) * (h - 10)

    pts = [f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(series)]
    older, recent = " ".join(pts[: n - 3]), " ".join(pts[n - 4:])
    area = " ".join(pts) + f" {x(n - 1):.1f},{h - 4} {x(0):.1f},{h - 4}"
    ex, ey = f"{x(n - 1):.1f}", f"{y(series[-1]):.1f}"
    body = (f'<polygon points="{area}" class="fill-accent" fill-opacity=".1"/>'
            f'<polyline points="{older}" class="line stroke-muted"/>'
            f'<polyline points="{recent}" class="line stroke-accent"/>'
            f'<circle cx="{ex}" cy="{ey}" r="6" class="fill-panel"/><circle cx="{ex}" cy="{ey}" r="4" class="fill-accent"/>')
    return _svg(w, h, label, body)


def bullet(days: float | None, incl: float | None, level: str, reorder_line: float, label: str,
           w: int = 164, h: int = 20, scale: float = 90) -> Markup:
    """Days of stock left as a bar, the reorder line as a tick, and a ring for days including everything on order."""
    def x(d: float) -> float:
        return 4 + (min(d, scale) / scale) * (w - 8)

    track = f'<rect x="4" y="6" width="{w - 8}" height="8" rx="4" class="fill-line"/>'
    if days is None or incl is None:
        return _svg(w, h, label, track)
    cls = {"crit": "fill-crit", "serious": "fill-serious"}.get(level) or ("fill-warn" if days < 45 else "fill-accent")
    body = (track + f'<rect x="4" y="6" width="{max(x(days) - 4, 4):.1f}" height="8" rx="4" class="{cls}"/>'
            f'<rect x="{x(reorder_line) - 1:.1f}" y="1" width="2" height="18" rx="1" class="fill-ink"/>'
            f'<circle cx="{x(incl):.1f}" cy="10" r="6" class="fill-panel"/>'
            f'<circle cx="{x(incl):.1f}" cy="10" r="4" class="fill-panel stroke-ink2 ring2"/>')
    return _svg(w, h, label, body)


def stage_bar(parts: list[tuple[int, int]], label: str, w: int = 140, scale_max: int = 400) -> Markup:
    """Units by stage as one stacked bar. `parts` is (units, step) with step 1..4 = placed, in production, on the way,
    arrived. One blue ramp, so the bar reads as progress."""
    h = 12
    if not any(u for u, _ in parts):
        return _svg(w, h, label, f'<rect x="0" y="2" width="{w}" height="8" rx="4" class="fill-line"/>')
    shown = [(u, s) for u, s in parts if u]
    # Bigger orders get longer bars, but never past the chart: the scale grows when the total would not fit.
    room = w - 6 - 2 * (len(shown) - 1) - 4 * len(shown)
    scale, x, out = room / max(scale_max, sum(u for u, _ in shown)), 0.0, ""
    for units, step in shown:
        seg = units * scale + 4
        out += f'<rect x="{x:.1f}" y="2" width="{seg:.1f}" height="8" rx="2" class="fill-st{step}"/>'
        x += seg + 2
    return _svg(w, h, label, out)


def dot_plot(days: int, threshold: int, over: int, label: str, w: int = 176, scale: int = 30) -> Markup:
    """How long an order has waited (dot) against the SOP limit (tick)."""
    def x(d: int) -> float:
        return 4 + (min(d, scale) / scale) * (w - 8)

    cls = "fill-serious" if over >= 8 else "fill-warn"
    body = (f'<line x1="4" x2="{w - 4}" y1="10" y2="10" class="stroke-line" stroke-width="1"/>'
            f'<rect x="{x(threshold) - 1:.1f}" y="2" width="2" height="16" rx="1" class="fill-ink"/>'
            f'<circle cx="{x(days):.1f}" cy="10" r="6" class="fill-panel"/><circle cx="{x(days):.1f}" cy="10" r="4" class="{cls}"/>')
    return _svg(w, 20, label, body)


def match_bar(parts: list[tuple[str, int]], label: str, w: int = 180) -> Markup:
    """Where an arrival's units went. `parts` is (kind, units): order (blue ramp), free ("not from an order", gray),
    none (unmatched, dashed). Names are written beside the bar, so color is never the only signal."""
    total = sum(u for _, u in parts)
    if not total:
        return _svg(w, 12, label, "")
    scale, x, out, step = (w - 2 * len(parts)) / total, 0.0, "", 2
    for kind, units in parts:
        seg = max(units * scale, 4)
        if kind == "order":
            out += f'<rect x="{x:.1f}" y="2" width="{seg:.1f}" height="8" rx="2" class="fill-st{step}"/>'
            step = min(step + 1, 4)
        elif kind == "free":
            out += f'<rect x="{x:.1f}" y="2" width="{seg:.1f}" height="8" rx="2" class="fill-muted"/>'
        else:
            out += (f'<rect x="{x + .5:.1f}" y="2.5" width="{seg - 1:.1f}" height="7" rx="2" fill="none" '
                    f'class="stroke-warn" stroke-dasharray="3 2"/>')
        x += seg + 2
    return _svg(w, 12, label, out)


def _nice_max(m: float) -> float:
    from math import floor, log10
    raw = max(m, 1) / 4
    mag = 10 ** floor(log10(raw))
    return next(c * mag for c in (1, 2, 2.5, 5, 10) if c * mag >= raw) * 4


def step_chart(series: list[tuple[str, str, list[tuple[float, float]]]], x_min: int, x_max: int, today,
               label: str, *, markers: list[tuple[float, float, str, str]] = (), bands: list[tuple[float, float]] = (),
               tick: int = 15, w: int = 720, h: int = 240) -> Markup:
    """A step line over days (negative = past, 0 = today). `series` is (name, ser-a | ser-b, points). `markers` are
    (day, level, ser-a | ser-b, text). `bands` are spans with no stock. app.js turns data-chart into a hover tooltip."""
    from datetime import timedelta
    from json import dumps

    left, right, top, bottom = 52, 16, 24, 32
    pw, ph = w - left - right, h - top - bottom
    span = x_max - x_min or 1
    top_val = _nice_max(max((y for _, _, pts in series for _, y in pts), default=1))

    def x(d: float) -> float:
        return left + (d - x_min) / span * pw

    def y(v: float) -> float:
        return top + ph - v / top_val * ph

    def level(pts, d):
        v = pts[0][1]
        for px, py in pts:
            if px <= d:
                v = py
            else:
                break
        return v

    out = ""
    for i in range(5):
        v = top_val / 4 * i
        txt = f"{v / 1000:g}K" if v >= 1000 else f"{v:g}"
        out += (f'<line class="stroke-line" stroke-width="1" x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                f'<text x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{txt}</text>')
    for d in range(x_max, x_min - 1, -tick):  # ticks count back from the right edge
        day = today + timedelta(days=d)
        when = "Today" if d == 0 else f"{day:%b} {day.day}"
        out += f'<text x="{x(d):.1f}" y="{h - 10}" text-anchor="middle">{when}</text>'
    for a, b in bands:
        if a < x_max:
            b = min(b, x_max)
            out += (f'<rect x="{x(a):.1f}" y="{top}" width="{x(b) - x(a):.1f}" height="{ph}" class="band-crit"/>')
            if x(b) - x(a) >= 96:
                out += f'<text class="t2" x="{(x(a) + x(b)) / 2:.1f}" y="{top + 14}" text-anchor="middle">Out of stock</text>'
    for _, cls, pts in series:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(px):.1f} {y(py):.1f}" for i, (px, py) in enumerate(pts) if px <= x_max)
        out += f'<path d="{d}" class="line stroke-{cls}"/>'
    for mx, my, cls, text in markers:
        if x_min <= mx <= x_max:
            out += (f'<circle cx="{x(mx):.1f}" cy="{y(my):.1f}" r="6" class="fill-panel"/>'
                    f'<circle cx="{x(mx):.1f}" cy="{y(my):.1f}" r="4" class="fill-{cls}"/>')
            if text:
                out += f'<text class="t2" x="{x(mx):.1f}" y="{y(my) - 12:.1f}" text-anchor="middle">{escape(text)}</text>'
    data = {"x0": x_min, "x1": x_max, "today": today.isoformat(),
            "series": [{"name": n, "cls": c, "v": [round(level(p, d)) for d in range(x_min, x_max + 1)]} for n, c, p in series]}
    svg = (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}" data-w="{w}" data-l="{left}" data-pw="{pw}" '
           f'data-t="{top}" data-ph="{ph}">{out}<line class="xhair stroke-ink2" stroke-width="1" y1="{top}" y2="{top + ph}" '
           f'visibility="hidden"/><rect class="chit" x="{left}" y="{top}" width="{pw}" height="{ph}" fill="transparent"/></svg>')
    return Markup(f'<div class="cwrap" data-chart="{escape(dumps(data))}">{svg}<div class="tip" hidden></div></div>')
