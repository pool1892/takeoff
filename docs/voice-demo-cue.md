# Voice demo cue — seller script for the quote-producing take

You play the supplier (a simulated business). The voice on the line is Takeoff's
buyer agent. The prices below are **proposed example prices for this take**, not
an offer that exists anywhere until you say them on the call and confirm the
buyer's readback aloud. Nothing on this call places an order.

Budget: 420 s per call. Keep the take under ~4 minutes. Speak first when the page
says *Connected*; you can interrupt the agent at any time.

## What the buyer will ask for (its actual request)

Delivered to 94103 by September 18, 2026:

1. 200 × 2x4x8 KD SPF No. 2 studs, full 8-foot lengths
2. 60 × 2x6x10 KD SPF No. 2
3. 40 sheets × 7/16 OSB 4x8, rated sheathing, Exposure 1

It knows a competing documented offer of $2,300 delivered (Second Shift
Materials) and may use it. It may counter or ask for a bundle; it must refuse
any substitution or later delivery.

## Your lines (example prices; adjust freely, then confirm only what you said)

1. **Pick up:** "Ridge Building Supply, this is <name>."
2. **Availability:** "Yes, all three are in stock."
3. **Unit prices:** "Studs are four dollars ten each. The two-by-six-by-tens are
   nine seventy-five each. The seven-sixteenths OSB is eighteen fifty a sheet."
4. **Delivery and date:** "Delivery to 94103 is a hundred and twenty dollars,
   and we can have it there Thursday, September 17."
5. **Tax:** "Prices are before sales tax; tax is added on the invoice."
6. **Expiry (if asked):** "That price is good through Friday, September 18."
7. **If it counters or mentions the $2,300 quote:** decide like a real seller.
   A simple concession: "I can waive the delivery fee if you take all three lines
   from us." Otherwise: "That's my best price."
8. **Optional trap (once):** "I could do two-by-six-by-eights instead of tens if
   that helps." — the buyer must decline and say it will ask the contractor.

## Arithmetic you should expect in the readback

| Line | Qty | Unit price | Line total |
|---|---|---|---|
| 2x4x8 KD SPF #2 | 200 | $4.10 | $820.00 |
| 2x6x10 KD SPF #2 | 60 | $9.75 | $585.00 |
| 7/16 OSB 4x8 | 40 | $18.50 | $740.00 |
| Subtotal | | | **$2,145.00** |
| Delivery to 94103 | | | $120.00 |
| **Total (tax excluded)** | | | **$2,265.00** |
| If delivery waived | | | **$2,145.00** |

The buyer records what you said, then reads back **quantities, unit prices,
delivery fee, delivery date, tax treatment, and total** and asks you to confirm.

## Confirming

Listen to the whole readback. If every term matches what you said, say exactly:

> **"Yes, that's correct — confirmed."**

If anything is off, correct it ("No — the OSB is eighteen fifty, not eighteen
fifteen") and let it read back again. Do not say "confirmed" before the readback,
and do not use the words "order" or "place it". After confirmation the agent
wraps up; say "Thanks, bye" or click *Hang up*.

## What counts as evidence

`/api/calls` on the seller page and the buyer-side `call.json` show both
transcripts, the tool calls (`record_quote` → `confirm_readback`), and
`confirmed_quote` with `source: human_vendor_spoken`. If confirmation never
fires, the call is recorded as `unconfirmed` — a connection, not a quote.
