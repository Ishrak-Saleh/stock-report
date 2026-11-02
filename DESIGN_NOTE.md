# Stock Report: design note

## 1. The design and why

The app is for the person who does the weekly reorder at a small product business. Each screen states one decision as a headline sentence ("3 products need a reorder, and Phone is out. Suggested order: 1,963 units.") and puts one filled green button next to it.

**Three layers.** Business rules live only in `app/domain/`, as pure functions that take `today` as an argument. Services load rows and call the rules. Routers and templates never work out a number. I chose this so a number can be tested without a database or a clock, and so two screens can never show different answers for the same product.

**Stack.** FastAPI, Jinja2, HTMX and SQLite. There is no front-end build, dialogs are native `<dialog>` elements loaded by HTMX, and the database is one file. It is small enough to run on a laptop in under five minutes.

**Companies and suppliers.** Every company's rows are filtered by one database hook, so no route can forget the filter. A supplier sees only orders whose supplier email matches their login, and can only confirm an order and add tracking, as the SOP says. Another company's row answers 404, not 403, so it does not confirm that the row exists.

**Look.** Dark, flat and tonal: surfaces are separated by tone and a 1 px line, with one green accent. Status is always an icon plus a label. On lists the icon sits beside the name and a hover or tap card holds the words, so rows stay quiet. Explaining text and chart keys follow the same idea: each panel has a round "i" beside its title, and its card draws the same marks as the chart (the stage bar colours, the match bar, the reorder line). Tests enforce the type scale and the no-shadow, no-gradient rule.

**Beyond the SOP: the stock gap.** It answers a question a reorder list cannot: which products will have empty shelves that ordering today can no longer prevent? It counts the empty days before a new order placed today could land (the product's lead time), assuming open orders land on their expected dates. Orders whose product runs dry before they arrive are ranked first on Chase and Orders. It reuses the runway rules and changes no SOP number. It is staff only, because a supplier cannot see other suppliers' orders.

## 2. What works and what does not

**Works.** Every "must" and "should" in SOP section 3: products and forecast, supplier orders with stages and tracking, arrivals with oldest-first matching, history and adjustments, per-product settings, the chase list with the 2-day repeat rule, a test-mode Outbox, an old-data warning, and staff and supplier logins. It also has sign up with separate companies, a sales CSV import, and a 390 px phone layout where the page never scrolls sideways, a wide table scrolls inside its own card, the main action fills the card and tap targets are 44 px. 296 tests pass, and `pip-audit` reports no known vulnerabilities.

**Does not work, or is only a demo.**
- Email is test mode only. Messages go to the Outbox, and "Send by email" opens a Gmail compose tab. Nothing is delivered by the app.
- There is no email check at sign up, so anyone who knows a supplier's address could sign up as that supplier.
- Sign-in throttling and sessions live in memory.
- Expected arrival is order date plus lead time, because the SOP has no expected-date field. It is an estimate and the screens say so.
- The SOP's suggested order size ignores units already on order, so it can be too large. The order dialog warns about it.
- I have not checked it on a real phone, and I have not clicked the Gmail link signed in.

## 3. How the numbers were checked against section 4

- The rule tests in `tests/test_domain.py` and `tests/test_runway.py` use small worked examples I calculated by hand from the SOP. For example, 6 a day for the last 3 days and 3 a day for the 4 before gives 30 sold, a trend of 2 (clamped) and an adjusted burn of 8.6. They also cover the edges: no sales, no earlier days, and a trend above 2 or below 0.5.
- On the demo data, the headline total (1,963 units) equals the three suggested orders on the rows (777, 1,044 and 142).
- The chase tests cover the boundaries of each rule: at least 2 days, at least 10 days, and more than 10 days.
- My first stock gap counted 90 days and flagged Healthy products. I compared it with the SOP's own definition of Healthy and corrected it to the product's lead time. A test now holds that.

## 4. How I used AI

I wrote this app. I used AI-assisted coding to write code faster, and I read, ran and tested what it produced. The problems I found and fixed are listed in the README.

## 5. One more week

1. **Email.** Real delivery behind the Outbox, and an email check or invite link so a supplier address cannot be claimed by a guesser.
2. **Part 2 of the stock gap.** A staff-set "rush" flag on an order that the supplier can see, so a supplier knows which order matters most.
3. **A real browser pass.** Hover, Tab and tap on every symbol, the light theme on every page, and a real phone.
4. **Storage.** Move sessions and sign-in throttling out of memory, and deploy it.
