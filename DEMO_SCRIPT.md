# Demo storyboard: from "in trouble" to "every shelf covered" (5 minutes)

**The story in one line.** A small shop opens Stock Report on Monday and sees three products to reorder, one already out, and two that will have **empty shelves no order can prevent**. By the end, every product is healthy, the empty-shelf warnings are gone and only one order is left to chase.

**From:** "3 products need a reorder, and Phone is out. / Suggested order: 1,963 units. 2 will have days with no stock."
**To:** "No product needs a reorder." (Critical 0, Healthy 6, 1 order to chase instead of 5.)

## What is the brief, and what is yours (say this clearly in the video)

| On screen | Where it comes from |
| --- | --- |
| "3 products need a reorder", "Phone is out", Critical / Reorder now / Healthy | The written rules: the reorder and out-of-stock flags. |
| "Suggested order: 1,963 units" | The written rules: the suggested order, added up for the products that need one. |
| Days of stock, Sold 7 days, the runway, order stages, arrivals, chase rules | The written rules. |
| **"2 will have days with no stock"**, the orange calendar symbol, "Empty N days", "Shelf empty N days", the runway sentence, orders ranked by empty shelf | **Your own feature: the stock gap.** Not in the brief. |

Aim for about a third of the video on the stock gap (scenes 2, 3, 4 and 8).

## Before you press record
1. **Stop your server and reset the data.** Your last reset did not go through (the server was still running). In PowerShell:
   `Stop-Process -Id 25208` then `$env:DEMO_PASSWORD = 'P@ss123'; .venv\Scripts\python -m app.reset`. Read its last line; it must say it rebuilt Company 1.
   Or run `scripts\demo.ps1`, which always starts fresh on its own throwaway database.
2. Start the app and sign in as `sam@example.com`, password `P@ss123`.
3. The demo sales end yesterday, so reset again on the day you record, and before each take. The dates in the cards ("Dec 5") move with the day; the numbers of days (33, 22) do not.
4. Have a **private window** ready on the sign-in page (supplier scene). Dark theme, window about 1366 px wide.

## Storyboard (★ = your unique feature)

| # | Time | Screen | You do | Say | What the viewer sees |
| --- | --- | --- | --- | --- | --- |
| 1 | 0:00 | **Stock** | Show the page. Read the first line, then the second. | "Monday morning at a small shop. Three products need a reorder and Phone is already out. And look at the second line: two products will have empty shelves." | Headline on two lines, Critical 2, Reorder now 1. `ss/1-stock-start.png` |
| 2 | 0:30 | ★ **Stock gap on the rows** | Hover the orange calendar symbol on **Phone**, then on **Mouse**. | "A normal reorder list says 'order more'. Mine also says when it is too late. Phone will be empty for 33 days even if I order today, because a new order takes 45 days to arrive." | Card: "Empty 33 days. Days with no stock before a new order placed today could arrive… First order: PHN-001, Dec 5 (est.)". Mouse: "Empty 22 days… MOU-001, Nov 17 (est.)". |
| 3 | 1:10 | ★ **Runway drawer** | Press **Runway** on Phone. Point at the insight sentence, then close it. | "The runway shows it as a picture: the stock line hits zero and stays there until the first order lands." | "33 days with no stock come before day 45 and cannot be prevented by ordering today." and "Chase what is already ordered." |
| 4 | 1:40 | ★ **Orders and Chase ranked by empty shelf** | Open **Orders**: show the calendar symbols and the subtitle "Empty shelf first". Open **PHN-001**: show the orange box. Then open **Chase**: the same orders come first. | "So the orders that matter most come first: the ones whose product runs dry before they land. On the order page it tells me exactly how long the shelf stays empty." | Order page: "Phone is empty for about 33 days before this order lands on Dec 5 (an estimate…)". |
| 5 | 2:20 | **Order dialog** | On Stock, press **Order** on Phone. Show the three size options and the preselected 777. Place it with Acme. Do Mouse (1,044, Acme) and Monitor (142, Nova). | "Now the normal part: the app suggests how many to order, and I place the three orders. Notice the second line: ordering fixes the reorder list, but not the empty shelves." | "No product needs a reorder. Phone is out of stock. / 2 will have days with no stock." Healthy 4. `ss/3-stock-after-orders.png` |
| 6 | 2:50 | **Supplier** (private window) | Sign in as `acme@acme.example.com`. Press **Confirm** on MOU-002. Hover the "i" next to Your orders. Open "What this login can do". Close the window. | "A supplier sees only their own orders. They confirm and add tracking, and they never see my stock gap." | The supplier list, the stage key. `ss/5-supplier-orders.png` |
| 7 | 3:15 | **Arrivals** | Press **Record arrival**: Phone, 1,077 units, today. Show the preview (PHN-001 300, then PHN-002 777). Save. Go to Stock. | "A pallet of phones arrives. The oldest order is filled first and the rest spills into the next." | "No product needs a reorder. / 1 will have days with no stock." Healthy 5. `ss/7-stock-after-phone.png` |
| 8 | 3:45 | ★ **The gap closes** | Record **Mouse, 1,314 units**. Go to Stock. | "Mouse arrives, and the last empty-shelf warning disappears. The gap only closes when the goods arrive, not when I order." | "No product needs a reorder." Critical 0, Healthy 6, no calendar symbols. `ss/8-stock-end.png` |
| 9 | 4:10 | **Arrivals and Chase** | Show the Monitor pallet in "Needs a decision" and press **Not from an order**. Open **Chase**, add HDP-001 to the **Outbox**. | "One pallet matched nothing, so I decide what it was. One order is still overdue, and the follow-up is ready. It is test mode: nothing is sent." | "Every arrival has an order." Chase: 5 orders became 1. `ss/9-chase-end.png` |
| 10 | 4:40 | **Stock** | Back on Stock. Narrow the window to a phone width for a few seconds. | "From a shop in trouble to every shelf covered, and it works on a phone. The part I added myself is the stock gap: it tells you what ordering today can no longer fix." | End on "No product needs a reorder." |

## Tips
- The **first Stock screen is the "bad" picture** and the **last Stock screen is the "good" one**. Keep both on screen for at least three seconds.
- The point of the stock gap, in one sentence: **ordering today fixes the reorder list, but only arrivals fix the empty shelves.** Say it in scene 5 and again in scene 8.
- Do the supplier scene **before** the arrivals: once everything has arrived, Acme has no open orders left.
- Do one practice run, then reset (server stopped) and record. If you run long, shorten scene 9.
- Texts in quotes were read from the app on the demo data. The clicks were not recorded in a browser.
