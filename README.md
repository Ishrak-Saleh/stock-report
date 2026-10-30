# Stock Report

Shows a small product business how much stock it has, how fast each product sells, when to reorder, and where every
supplier order is. Built for the SOP "Stock Report" assignment. FastAPI, Jinja2, HTMX and SQLite. All data is fake.

## Run it in under 5 minutes

You need Python 3.12 or newer.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q          # optional: the tests
scripts\demo.ps1                           # starts the app on a throwaway database
```

On macOS or Linux use `.venv/bin/pip` and `scripts/demo.sh`.

Open the `localhost` address the terminal prints. The demo script gives three demo accounts the placeholder password
`P@ss123`, which is for demo data only (use `scripts\demo.ps1 -Password 'other'` to change it):

| Account | Role | Sees |
|---|---|---|
| `sam@example.com` | staff | everything |
| `acme@acme.example.com` | supplier | only Acme Manufacturing's orders; can confirm and add tracking |
| `nova@nova.example.com` | supplier | only Nova Imports' orders; can confirm and add tracking |

To open it from a phone or another computer on your network, run `scripts\demo.ps1 -Lan` (or `LAN=1 scripts/demo.sh`)
and use the network address it prints. The server only listens on this computer unless you ask for that, and on Windows
you may need to allow Python through the firewall.

`scripts/demo.ps1` uses a fresh database every time, so you can click anything and start over. To run on your own
`stock.db` instead: `.venv\Scripts\python -u -m uvicorn app.main:app --port 8000`. The first start creates the
accounts and prints a random password once (set `DEMO_PASSWORD` first to choose one). Do not use `--reload` on Windows: it leaves stray server processes behind.

Create your own account at `/signup`. **Buy stock** makes a new company with its own products, orders and suppliers, separate from the demo's
Company 1 (the empty Stock page has a "Load sample data" button). **Supply stock** makes a supplier login: it sees the orders buyers address to its
email, so add the supplier in Settings with the same email. There is no email check (demo only) and passwords need 6 or more characters.
To start over on `stock.db`: stop the server, then run `.venv\Scripts\python -m app.reset` (it keeps a copy as `stock.db.bak`).

## Settings you can change with environment variables

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `sqlite:///stock.db` | Which database to use. Tests and the demo script use a throwaway one. |
| `DEMO_PASSWORD` | random, printed once | Password given to the demo accounts when they are created. |
| `SECRET_KEY` | random per start | Signs the session cookie. Set it to keep people signed in across restarts. |
| `SENDER_NAME` | `Sam` | Name that signs follow-up messages. |

No secret is stored in the repository.

## How it is built

```
app/domain/     the SOP rules as pure functions (forecast, orders, matching, chase, runway, messages)
app/services/   load rows, call the rules, save results (products, orders, arrivals, stock, chase, settings, users)
app/routers/    thin: read the request, call a service, render a template
app/templates/  pages and dialogs; native <dialog> opened by an HTMX swap into #modal-host
app/charts.py   inline SVG charts, colored by CSS classes so both themes work
design/         the design pages the screens were built from
tests/          unit tests for the rules, page tests on a throwaway database
```

Business rules live only in `app/domain/`. Routers and templates never recompute a number.

## What works

Every (must) and (should) in SOP section 3: products and forecast, supplier orders with stages, tracking, history and
messages, arrivals with oldest-first matching and hand fixes, stock history and adjustments, settings with per-product
overrides, the chase list with the 2-day repeat rule, a test-mode Outbox, an old-data warning, and staff and supplier
logins. It works at 390px as well as on a laptop.

## Honest limits

- Email is test mode only: messages are saved in the Outbox and nothing is delivered.
- Expected arrival is order date plus lead time. The SOP has no expected-date field, so this is an assumption.
- The SOP's suggested order size ignores units already on order, so it can overshoot. The order dialog says so.
- The warehouse count is the last count plus what is recorded in the app. Imported daily sales set the burn and do not
  change the count.
- Sign-in throttling and sessions are simple and live in memory. Good for a demo, not for production.
- Products can be edited and added but not deleted, because they carry history.
- `pip-audit` has not been run yet.
