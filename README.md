# Down Memory Lane — Slack Childhood Photo Bot

A Slack bot that takes a request like *"my 5-year-old self on a beach"* and
replies **in the same thread** with a generated photo of you at that age, using
a Flux LoRA fine-tuned on your own reference images via Replicate.

```
@memorylane my 5-year-old self on a beach
  └─ 📸 Working on it — you at 5, on a beach.        (posted in <1s)
  └─ ✨ You at 5 — on a beach                        (posted ~40s later)
     [image]
```

---

## How it works, in one paragraph

Slack delivers the mention over a **Socket Mode** WebSocket, so no public URL
or ngrok tunnel is required. The listener does only fast work — parse the
message, write a job row, post an acknowledgement — and returns well inside
Slack's 3-second budget. A background thread pool then calls Replicate,
polls the prediction to completion, downloads the image, and uploads it into
the originating thread using the `thread_ts` recorded on the job.

---

## Project layout

```
memory_lane_bot/
├── main.py                          # entrypoint: wires everything, starts Socket Mode
├── config/
│   └── settings.py                  # every env var, validated once at startup
├── slack_app/                       # Slack side
│   ├── handlers.py                  # event listeners: fast ack, dedupe, enqueue
│   ├── photo_request_worker.py      # background: inference + upload to thread
│   └── messages.py                  # all user-facing copy
├── replicate_client/                # Replicate side
│   ├── inference.py                 # create prediction, poll, timeout, cancel
│   └── training.py                  # offline LoRA fine-tune (run once, not live)
├── core/
│   └── prompt_parser.py             # "my 5-year-old self on a beach" -> prompt
├── store/
│   └── job_store.py                 # SQLite: job state, thread lookup, event de-dupe
├── scripts/
│   ├── stage1_echo_bot.py           # verify Slack alone
│   └── stage2_test_inference.py     # verify Replicate alone
└── tests/                           # 43 tests, fully offline
```

> **Naming note:** the packages are `slack_app/` and `replicate_client/`, not
> `slack/` and `replicate/`. A top-level directory named `replicate/` shadows
> the installed `replicate` PyPI package and breaks `import replicate` in a way
> that is genuinely annoying to debug.

---

## Setup

### 1. Install

```bash
python -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Create the Slack app

At <https://api.slack.com/apps> → **Create New App** → *From scratch*.

| Where | What to set |
|---|---|
| **Socket Mode** | Toggle **on**. Generate an App-Level Token with scope `connections:write` → this is `SLACK_APP_TOKEN` (`xapp-…`) |
| **OAuth & Permissions** → Bot Token Scopes | `app_mentions:read`, `chat:write`, `files:write`, `im:history`, `im:read`, `im:write` |
| **Event Subscriptions** | Toggle **on**. Subscribe to bot events: `app_mention`, `message.im` |
| **Install App** | Install to workspace → copy the Bot User OAuth Token → `SLACK_BOT_TOKEN` (`xoxb-…`) |

Then invite the bot to a channel: `/invite @yourbotname`.

> `files:write` is the scope people forget. Without it the image upload fails
> and the bot falls back to posting a raw Replicate link that expires in an hour.

### 3. Train the LoRA (once, offline — 15–40 minutes)

This is deliberately **not** part of the live bot flow. Training is too slow to
sit inside a Slack request, so it runs ahead of time and the resulting version
id is pasted into `.env`.

1. Collect ~20 photos of yourself — varied settings, good lighting, ideally
   solo. Zip them flat: `zip -j data/my_photos.zip photos/*.jpg`
2. Create an **empty** model at <https://replicate.com/create> (e.g.
   `your-username/memory-lane-lora`). This is the training destination.
3. Run:

```bash
export REPLICATE_API_TOKEN=r8_...
python -m replicate_client.training \
  --photos-zip data/my_photos.zip \
  --destination your-username/memory-lane-lora \
  --trigger-word TOK \
  --wait
```

4. Copy the printed version id into `LORA_MODEL_VERSION`, and make sure
   `LORA_TRIGGER_WORD` matches `--trigger-word`. **If the trigger word doesn't
   match, the model will not render your likeness** — it will produce a generic
   child. This is the single most common failure.

### 4. Run

```bash
python main.py
```

---

## Staged verification

Each stage is independently runnable, so a failure is localised immediately.

| Stage | Command | Confirms |
|---|---|---|
| 1 — Slack scaffold | `python scripts/stage1_echo_bot.py` then mention the bot | Tokens, scopes, Socket Mode, in-thread replies |
| 2 — Replicate inference | `python scripts/stage2_test_inference.py` | LoRA version id, trigger word, likeness quality |
| 3 — Prompt parsing | `pytest tests/test_prompt_parser.py -v` | Age + scene extraction across phrasings |
| 4 — Async + state | `pytest tests/test_job_store.py tests/test_end_to_end.py -v` | Threading, dedupe, concurrent threads, failure paths |
| 5 — Full bot | `python main.py` then mention the bot | Everything together |

Run the whole offline suite with `pytest tests/ -q` — 43 tests, no network,
no credentials needed.

---

## Error handling

| Failure | Behaviour |
|---|---|
| Missing env var | Startup fails immediately with the variable name |
| Message has no usable scene | Bot replies with a worked example, no job created |
| Empty message / `help` | Bot posts usage help |
| Replicate rejects or errors | Job marked `failed`, error posted in-thread with job id |
| Prediction exceeds `PREDICTION_TIMEOUT_SECONDS` | Prediction **cancelled** (stops billing), job marked `timed_out`, user told to retry |
| Slack redelivers an event | Second delivery ignored via `processed_slack_events` — no duplicate image, no double spend |
| Image upload fails (e.g. missing scope) | Falls back to posting the Replicate URL, with an expiry warning |
| Second request in the same thread | Rejected with a friendly message; user told to start a new thread for parallel runs |
| Replicate rate limits us (429) | Job marked failed, user told to retry in a minute — no raw HTTP error shown |
| Replicate 401 / 402 / 404 | Translated into the specific fix (bad token / no credit / wrong version id) |
| Message from another bot | Ignored, so two bots cannot loop |
| One user floods requests | Capped at 3 concurrent jobs per user |
| Unexpected exception in a worker | Logged with traceback; user still gets a reply rather than silence |

---

## Judgment calls

**Concurrent requests in the same thread: reject, don't queue.**

If a second request arrives in a thread while the first is still generating,
the bot says so and declines it. It does not queue.

Queuing looked tempting and I decided against it for three reasons. First, a
queued request has no honest ETA — the user is told "soon" and then waits an
unknown multiple of 40 seconds with the thread apparently idle, which is worse
than a clear "not yet". Second, images arriving in a thread minutes after the
message that asked for them read as non-sequiturs; the conversational context
that made the request legible has scrolled away. Third, a queue is an unbounded
spend commitment taken on the user's behalf — someone firing off eight messages
in frustration gets eight billable generations, and the natural fix (queue
depth limits, cancellation, position reporting) is a real feature, not a
prototype detail.

Rejecting is one comparison against the store, it's instantly understandable,
and it preserves the useful property that *a thread is a conversation about one
photo*. Parallelism is still available — the rejection message tells users to
start a new thread, and different threads genuinely do run concurrently up to
`WORKER_THREAD_COUNT`. If usage later shows people want a burst of variations,
the right answer isn't a queue: it's a "give me 4 variations" parameter on a
single request.

---

## Known limitations

These are deliberate prototype boundaries, not oversights.

- **One LoRA for the whole workspace.** Everyone who talks to the bot gets
  images of whoever the model was trained on. There is no per-user model
  lookup, so this is a single-person demo, not a team feature.
- **State is local to one process.** The SQLite file lives next to the bot.
  Two instances of this bot pointed at the same workspace would not see each
  other's jobs, so the de-duplication and same-thread guards only hold for a
  single process.
- **In-flight jobs are lost on restart.** Jobs are recorded, but nothing
  resumes them. Restart during generation leaves rows stuck in `submitted` and
  the user never gets a reply — and because those rows still count as active,
  that thread stays blocked until the row is cleared by hand.
- **No retries.** A single transient Replicate error fails the request. The
  user is told, and retrying is their job. (429s during polling are the one
  exception — a throttled status check doesn't abandon a running prediction.)
- **Prompt parsing is rule-based.** It handles the phrasings in the tests well
  and degrades predictably: unrecognised age defaults to 6 and says so.
  Genuinely unusual phrasing ("me before I started school") will pass the whole
  string through as the scene rather than failing, which is the right failure
  mode but not a smart one.
- **No moderation beyond Replicate's built-in safety checker.** Whatever the
  user types becomes part of the prompt.
- **Timeout ceiling is a guess.** 300s comfortably covers a warm model; a cold
  start on a rarely-used LoRA can exceed it, and the user sees a timeout for
  something that would have succeeded.

## How this would scale

Roughly in the order I'd actually do it, with the trigger for each.

**1. Replace polling with webhooks.** *Trigger: more than a handful of
concurrent users.* Every in-flight job currently holds a thread that spends
99% of its life in `time.sleep`. `WORKER_THREAD_COUNT` is therefore a hard
ceiling on concurrency for a workload that is almost entirely waiting.
Replicate can POST to a webhook on completion, which turns each job from "a
held thread" into "a database row plus a callback" — concurrency stops being
bounded by threads at all. This is the single highest-leverage change and it's
why `job_store` already keys on `prediction_id`: the webhook handler needs to
map an incoming prediction back to a Slack thread, and that lookup already
exists. Note this reintroduces the public-URL requirement that Socket Mode let
us avoid, so it's a real trade against the deployment simplicity that makes
this easy to get approved.

**2. Move the queue out of process.** *Trigger: needing more than one bot
instance, or wanting jobs to survive deploys.* `ThreadPoolExecutor` → SQS/Redis
with a separate worker process, SQLite → Postgres. The interface the rest of
the code sees (`worker.submit(job, request)`) doesn't change; that boundary was
drawn with this move in mind. This is also what fixes "in-flight jobs lost on
restart", since a job stays on the queue until a worker acks it.

**3. Per-user LoRAs.** *Trigger: the second person asks to use it.* This is the
change most likely to be requested first and it's more than a lookup table.
Each user needs an onboarding flow (upload ~20 photos, kick off a 15-40 minute
training, notify on completion), a mapping from Slack user ID to model version,
and a decision about what happens when someone with no trained model asks for a
photo. Budget for the consent and deletion story here too — a trained LoRA is
biometric-derived data about a specific person, and "delete my model" needs to
be a real, working button before this goes past a pilot. Treat this as a
project, not a ticket.

**4. Cost controls before general availability.** *Trigger: opening it beyond a
pilot group.* Each generation costs real money and nothing in this prototype
caps total spend — only per-thread and per-user concurrency, which limits rate,
not total. Before this is open to a workspace I'd want a daily budget per user
and a workspace-wide kill switch. Cheapest version: a count in the existing
store plus a config limit. Worth doing early because the failure mode is a
surprise invoice rather than an error message.

**5. Operational visibility.** *Trigger: the first "it's broken" report you
can't reproduce.* Today diagnosis means reading stdout. The job table already
holds what's needed (status, prediction id, error, timings); it just needs to
be queryable — p50/p95 generation time, failure rate by cause, and a way to go
from "this thread got nothing" to the Replicate run in one hop. A slash command
that returns the last N jobs and their statuses would cover most of it and
takes an hour.

**What I would not build yet:** retries with backoff (the current failures are
mostly not transient — bad version id, out of credit, cold start — and retrying
those just spends money twice), circuit breakers (one upstream, no fallback to
break over to), and any image storage layer (Slack already stores the uploaded
file permanently and searchably, which is the whole reason the bot uploads
rather than links).

**Why the predictions API instead of `replicate.run()`.** `replicate.run()`
blocks with no timeout control and hands back no prediction id until it
finishes. We need the id early — it goes in the store the moment Replicate
issues it, so an operator can trace any Slack thread to a Replicate run.

**Why a separate thread pool.** Bolt acks the event before running the listener,
but its default listener pool is shared and small. A 60-second Replicate poll
running in it would starve other events. Our pool is dedicated and sized by
`WORKER_THREAD_COUNT`.

**Why SQLite rather than a dict.** Same interface either way, but state survives
a restart, and `INSERT` on a primary key gives atomic event de-duplication for
free. Every operation opens a short-lived connection, which is thread-safe.

---

## Note on training data

Only train on photos of yourself, or of someone who has explicitly agreed. The
LoRA reproduces the likeness of whoever is in the reference set, so the consent
question is settled at training time, not at prompt time.
