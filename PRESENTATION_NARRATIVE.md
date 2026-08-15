# Down Memory Lane — Client Presentation Narrative

Three parts, mapped to the assignment's required sections. Written to be read
aloud to a **non-technical client audience**. Suggested pacing for a 5–7 minute
Loom: ~90s on Part 1, ~2min on Part 2, ~2min on Part 3, ~1min close.

---

## Part 1 — Bot Flow Overview
### Slide title: *"A memory, on request"*

**The story to tell**

Open with the user, not the technology. InspireWorks wants memory-sharing to
feel effortless — and the most effortless place for a team is the chat window
they already have open all day.

Walk through one real interaction:

> Priya types in Slack: **"@memorylane my 5-year-old self on a beach"**
>
> Within a second, the bot replies in that thread: *"📸 Working on it — you at
> 5, on a beach. This usually takes 30–60 seconds."*
>
> About forty seconds later, in the same thread, the photo appears. Not Priya's
> real childhood photo — a photo of the childhood she describes, rendered with
> her own face.

**The three points to land**

1. **No new tool to learn.** No app to install, no web dashboard, no login.
   If you can send a Slack message, you can use this.
2. **The conversation is never left waiting in silence.** The acknowledgement is
   instant and specific — it repeats back the age and the scene, so the user
   knows they were understood before the wait begins.
3. **Everything stays in the thread.** Ten people can be making requests in ten
   different threads at once; each reply lands exactly where it was asked for.
   Nothing spills into the main channel.

**Show, don't tell:** a screen recording of one real request is worth more than
any diagram on this slide.

---

## Part 2 — High-Level Architecture & Integrations
### Slide title: *"Four moving parts"*

**Diagram description** — draw as a horizontal flow, left to right, with the
back-arrow drawn *underneath* returning to Slack:

```
   ┌──────────┐   secure, outbound-only    ┌───────────────────┐
   │  SLACK   │◄──────── WebSocket ───────►│  MEMORY LANE BOT  │
   │ workspace│                            │  (your server)    │
   └──────────┘                            └─────────┬─────────┘
        ▲                                            │
        │                                  ┌─────────┴─────────┐
        │                                  │                   │
        │                            ┌─────▼─────┐     ┌───────▼───────┐
        │                            │ REQUEST   │     │  REPLICATE    │
        │                            │  LEDGER   │     │  Flux LoRA    │
        │                            │ (database)│     │ (your model)  │
        │                            └───────────┘     └───────┬───────┘
        │                                                      │
        └──────────── finished photo, same thread ─────────────┘
```

**Narrate each box in plain language**

| Box | Say this |
|---|---|
| **Slack** | Where your team already works. The bot appears as a normal member of the channel. |
| **Memory Lane Bot** | The small service we've built. It's the translator: it understands the request, orchestrates the work, and delivers the result. |
| **Request Ledger** | A record of every request — who asked, in which thread, what was generated, whether it worked. This is what makes the system supportable. |
| **Replicate + your Flux LoRA** | The image engine. Critically, this is *your* private model, trained on your reference photos, not a generic public one. That's why the faces look like the person. |

**The two things a client actually cares about here**

- **Security posture.** The connection to Slack is a WebSocket that our server
  opens *outbound*. Nothing needs to be exposed to the public internet — no
  open ports, no public URL, no inbound firewall changes. For most IT teams
  this turns a multi-week approval into a same-day one.

- **The model is trained once, ahead of time.** Fine-tuning takes 15–40 minutes.
  We did that as a one-time setup step. At request time we're only *using* the
  trained model, which is why the answer comes back in under a minute instead
  of after lunch. Worth stating explicitly — clients often assume the AI is
  "learning" on every request, and that assumption drives bad expectations
  about both cost and speed.

---

## Part 3 — Data Flow & Processing Logic
### Slide title: *"What happens in those 40 seconds"*

**Walk the seven steps.** Build them one at a time on the slide if you can.

1. **The message arrives.** Slack pushes the mention to our service the instant
   it's posted.

2. **We answer Slack immediately.** Slack gives any bot three seconds to confirm
   receipt, or it assumes we're broken and sends the message again. So we
   confirm first and do the real work afterwards. This is the single most
   important design decision in the system, and it's why the bot never
   double-posts or silently drops a request.

3. **We read the request.** From *"my 5-year-old self on a beach"* we pull out
   two things: the **age** (5) and the **scene** (on a beach). If the age is
   missing we assume a young child and say so, rather than guessing silently.
   If there's no scene at all, we ask for one with an example — we never send a
   half-understood request to the image engine.

4. **We write it down.** The request goes into the ledger with its thread
   address before any work starts. This is the piece that keeps concurrent
   requests from colliding: each job carries its own return address, so the
   answer can't land in the wrong conversation. It's also how we ignore
   duplicates — if Slack re-sends the same message, we recognise it and don't
   generate (or pay for) the image twice.

5. **We compose the prompt and hand it to the model.** The user's words are
   wrapped in photographic direction — natural light, film grain, faded
   colour, unposed — plus the private token that tells the model *whose face
   this is*. That token is the difference between a photo of a child and a
   photo of **this person** as a child.

6. **We wait, with a limit.** We check on the job every couple of seconds. If it
   hasn't finished in five minutes, we stop waiting, cancel the job so it stops
   costing money, and tell the user plainly. A slow answer is a problem; a
   silent one is a broken product.

7. **We deliver into the same thread.** The finished image is uploaded directly
   into Slack — not linked. Uploading matters: the engine's own links expire
   within the hour, so a linked photo would quietly turn into a dead image in
   the channel history next week. Uploaded, it lives in Slack permanently,
   searchable alongside everything else.

**Close on failure handling — this is what separates a demo from a product:**

> Every failure has a defined, human answer. The engine errors — we say so, in
> thread, with a reference id. It takes too long — we cancel and tell you.
> Someone fires off twenty requests — we queue three and hold the rest. Slack
> hiccups and resends — we notice and ignore it. The user is never left
> watching a thread where nothing happens.

**Optional closing slide — where this goes next:** slash commands
(`/memorylane`), a style picker (80s Polaroid, 90s disposable camera), multiple
variations per request, and per-person LoRAs so a whole team can use one bot.
The architecture already supports all four; they're feature work, not rebuilds.
