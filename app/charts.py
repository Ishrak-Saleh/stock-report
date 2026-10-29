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
    scale, x, out = (w - 6) / scale_max, 0.0, ""
    for units, step in parts:
        if not units:
            continue
        seg = max(units * scale, 4)
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
