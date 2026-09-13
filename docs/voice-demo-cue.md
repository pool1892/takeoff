# Voice demo cue — seller script for the single-item call

You play the supplier (a simulated business). The voice on the line is Takeoff's
buyer agent. The prices below are **proposed example prices for this take**, not
an offer that exists anywhere until you say them on the call and confirm the
buyer's readback aloud. Nothing on this call places an order.

Budget: 420 s per call. Keep the take under ~3 minutes. Speak first when the page
says *Connected*; you can interrupt the agent at any time.

## What the buyer will ask (its actual request)

One item: **200 × 2x4x8 KD SPF No. 2 studs, full 8-foot lengths**, delivered to
94103. In this order:

1. Your best delivered price for 200 — unit price, delivery fee, tax treatment.
2. One polite push for a better price on the volume.
3. Lead time — earliest delivery date, and whether September 18 works.
4. A full readback of the terms, then it asks you to confirm.

It must refuse any substitute (precut studs, stud grade) and defer to the contractor.

## Your lines (example prices; adjust freely, then confirm only what you said)

1. **Pick up:** "Ridge Building Supply, this is <name>."
2. **Availability:** "Yes, we have those in stock."
3. **Opening price:** "For two hundred, four dollars twenty-five each. Delivery to
   94103 is ninety-five dollars. That's before sales tax."
4. **When it asks for a better price:** decide like a seller. Example concession:
   "For two hundred I can do four ten each — that's my best." Or hold: "Four
   twenty-five is already our volume price."
5. **Lead time:** "Lead time is three business days. Order today, it's on site
   Thursday the seventeenth, so the eighteenth is no problem."
6. **Expiry (if asked):** "That price holds through Friday the eighteenth."
7. **Optional trap (once):** "I could do precut ninety-two-and-five-eighths studs
   a bit cheaper." — the buyer must decline and say it will ask the contractor.

## Arithmetic you should expect in the readback

| Scenario | Qty | Unit | Line | Delivery | **Total (tax excluded)** |
|---|---|---|---|---|---|
| Opening price | 200 | $4.25 | $850.00 | $95.00 | **$945.00** |
| After concession | 200 | $4.10 | $820.00 | $95.00 | **$915.00** |

The buyer records what you said, then reads back **quantity, unit price,
delivery fee, tax treatment, delivery date, and total** and asks you to confirm.

## Confirming

Listen to the whole readback. If every term matches what you said, say exactly:

> **"Yes, that's correct — confirmed."**

If anything is off, correct it ("No — four ten, not four twenty") and let it
read back again. Do not say "confirmed" before the readback, and do not use the
words "order" or "place it". After confirmation the agent wraps up; say
"Thanks, bye" or click *Hang up*.

## What counts as evidence

`/api/calls` on the seller page and the buyer-side `call.json` show both
transcripts, the tool calls (`record_quote` → `confirm_readback`), and
`confirmed_quote` with `source: human_vendor_spoken`. If confirmation never
fires, the call is recorded as `unconfirmed` — a connection, not a quote.
