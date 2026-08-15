"InspireWorks wanted people to be able to picture their own childhood — to
type a memory and see it. What we built is called Down Memory Lane.

I'll show it working, then how it's put together, then the logic end to end."

---

# SECTION 1 — Overview of the bot flow

*[Switch to Slack, `#memory-lane`]*

"The first decision we made was to add no new software at all.

No app to install, no dashboard, no website. The entire interface is Slack — a
tool your team already has open. The bot is a member of the channel, and you
talk to it the way you'd talk to a colleague.

Two ways in: mention it in any channel it's been invited to, or send it a
direct message. Either way it replies in a thread, so the conversation stays
contained."


*[Type: `@Memory Lane my 5-year-old self on a beach`]*

"One plain sentence. No commands, no syntax, no form to fill in."

*[Ack appears]*

"Under a second, we answer — and look carefully at *what* we answer. *'You at
5, on a beach.'* It repeats back what it understood before doing any work. If
it had misread me, I know immediately, not after a minute of waiting."

*[Image arrives]*

"Forty seconds later, the photograph, in the same thread.

Three things to notice. It's my face, from a model fine-tuned on twenty
photographs of me. It's uploaded into Slack rather than linked, so it lives in
your history permanently and stays searchable. And the caption confirms the
age, the scene, and how long it took."

"That's the product from a user's point of view. Say hello and it gives you
usage examples rather than an error. Ask inside an existing thread and it
continues that thread. And it reads plain English — *'me at 7'*, *'my 4yo
self'*, *'my ten-year-old self'* all work. There is nothing to learn."

---

# SECTION 2 — High-level architecture and integrations

*[Architecture slide — four boxes]*

"Four components. Slack, our service, a request ledger, and the image engine.

**Slack** is where your team already works, and it's the only interface.

**The Memory Lane service** is the small application we built. It's the
translator: it understands the request, orchestrates the work, and delivers
the result.

**The request ledger** records every request — who asked, in which thread,
what was generated, whether it worked, how long it took. This is what makes
the system supportable rather than mysterious.

**The image engine** is Replicate, running a Flux LoRA model. And this is the
important part: it's *your* private model, trained on your reference
photographs, not a generic public one. That's why the faces look like the
person."

## [2:35] Two things that matter commercially

"Two points your IT team will care about.

First, security. The connection to Slack is a WebSocket that our server opens
*outbound*. Nothing is exposed to the public internet — no open ports, no
public web address, no inbound firewall rule. For most organisations that
turns a multi-week security review into a same-day approval.

Second, the model is trained once, ahead of time — roughly twenty minutes on a
GPU, as a one-time setup step. At request time we're only *using* it, which is
why answers come back in under a minute. That matters for your cost and speed
expectations: the system isn't learning on every request.

And the model itself is one line of configuration. Swap it, and the bot doesn't
notice."

---

# SECTION 3 — Data flow and processing logic

## [3:15] The seven steps

*[Data flow slide — build these one at a time if you can]*

"Here's what happens in those forty seconds.

**One — the message arrives.** Slack pushes it to us the instant it's posted.

**Two — we answer Slack immediately.** Slack gives any bot three seconds to
confirm receipt, or it assumes we're broken and sends the message again. So we
confirm first and do the real work afterwards. This is the single most
important design decision in the system, and it's why the bot never
double-posts or silently drops a request.

**Three — we read the request.** From *'my 5-year-old self on a beach'* we pull
two things: the age, five, and the scene, on a beach. Leave the age out and it
assumes a young child *and tells you it assumed*. Ask for your forty-five-year-
old self and it ignores that, because this is a childhood photo bot.

**Four — we write it down.** The request goes into the ledger with its thread
address before any work begins. Each job carries its own return address, so
answers can't land in the wrong conversation, and several people can generate
at once.

**Five — we compose the prompt.** Your words get wrapped in photographic
direction — natural light, film grain, faded colour, unposed — plus a private
token that tells the model whose face this is.

**Six — we wait, with a limit.** We check every couple of seconds. If it hasn't
finished in five minutes we stop waiting, cancel the job so it stops costing
money, and say so.

**Seven — we deliver into the same thread.** Uploaded, not linked, because the
engine's own links expire within the hour."

## [4:35] The paths that aren't happy

*[Back to Slack]*

"Now the part that separates a demo from a product.

*[Type a second request while one is generating]*

Ask for a second photo in a thread that's still working, and it declines and
explains. It doesn't silently queue you with no ETA, and it doesn't spend your
money twice. Start a new thread and they genuinely run in parallel.

*[Type: `@Memory Lane my 5-year-old self`]*

Give it an age but no scene, and it asks for one, with an example. It never
sends a half-understood request to the image engine.

And every failure has a defined, human answer. The engine rate-limits us:
*'try again in a minute'*, not a stack trace. Out of credit, a bad token, a
wrong model version — each becomes the specific thing to fix. A throttled
status check doesn't abandon work we've already paid for. A failed upload falls
back to a link. A message Slack redelivers isn't generated twice. Another bot
mentioning us is ignored, so two bots can't loop. And one person can't
monopolise it — three at a time, then we ask them to wait.

The user is never left watching a thread where nothing happens."

---

## [5:30] Close

"So: no new software, nothing exposed to the internet, answers in under a
minute, and a defined response to every way it can fail — covered by
forty-seven automated tests.

Next steps are per-person models so a whole team can use it, a style picker,
and multiple variations per request. The architecture already supports all
three."

---

## Delivery notes

- **Start the bot before recording.** `python main.py` must be running.
- **Pre-warm the model** with one throwaway generation first. A cold start can
  exceed a minute and will wreck your pacing on camera.
- **Trigger the same-thread rejection *while* the first image is generating** —
  that window is only about 40 seconds, and it's the most impressive moment in
  the demo.
- Slides needed: title, architecture (four boxes), data flow (seven steps).
  Everything else is screen-share of Slack.
- If you run long, trim [1:30] and shorten the failure list in [4:35]. Do not
  cut [3:15] step two or [4:35]'s first demo — those are the two moments that
  show engineering judgment rather than a working API call.
- If you run short, expand step five by showing the actual generated prompt in
  your terminal log.
