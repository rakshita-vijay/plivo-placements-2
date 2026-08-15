# Down Memory Lane — Complete Setup Walkthrough

From downloading the zip to a working Slack bot. Assumes no prior experience
with Slack apps, Replicate, or Python virtual environments.

---

## Before you start: the shape of this

There are **seven phases**. Phases 1–4 are setup you do once. Phase 5 is the
long one — the model trains for 20–40 minutes while you do nothing. Phases 6–7
are testing and running.

| Phase | What | Your time | Waiting time |
|---|---|---|---|
| 1 | Unzip and install Python packages | 10 min | — |
| 2 | Create the Slack app | 15 min | — |
| 3 | Get your Replicate token | 5 min | — |
| 4 | Prepare and upload your photos | 15 min | — |
| 5 | Train the LoRA model | 5 min | **20–40 min** |
| 6 | Fill in `.env` and test in stages | 15 min | — |
| 7 | Run the bot and demo it | 5 min | — |

**Total: about 1 hour of your attention, plus 20–40 minutes of waiting.**

Start phase 5 as early as you can — the training runs on Replicate's servers,
so you can do phases 6's reading while it works.

**What it costs.** Training a Flux LoRA runs roughly **$2–3** of Replicate
credit, and each generated image is a few cents. You'll need a payment method
on your Replicate account. Check the current rates on the model pages — these
change.

**What you need to have already:**
- A computer with internet, and permission to install software on it
- A Slack workspace where you can add apps. If your work Slack blocks this,
  create a free personal workspace at <https://slack.com/get-started> — takes
  two minutes and works identically
- About 20 photos of yourself
- A payment method for Replicate

---

# Phase 1 — Get the code running locally

## Step 1.1 — Download and unzip

Download `memory_lane_bot.zip` and unzip it somewhere you can find again — your
Desktop or Documents folder is fine. You should end up with a folder called
`memory_lane_bot` containing `main.py`, `README.md`, and several subfolders.

## Step 1.2 — Check you have Python

Open a terminal:
- **Mac:** press `Cmd + Space`, type `Terminal`, press Enter
- **Windows:** press the Start key, type `powershell`, press Enter
- **Linux:** `Ctrl + Alt + T`

Type this and press Enter:

```bash
python3 --version
```

If you see `Python 3.9` or higher, you're set. On Windows you may need
`python --version` instead.

If you get "command not found" or a version below 3.9, install Python from
<https://www.python.org/downloads/>. **On Windows, tick "Add Python to PATH"
on the first screen of the installer** — if you miss it, nothing below will
work. Close and reopen your terminal afterwards.

## Step 1.3 — Move into the project folder

In the terminal, type `cd ` (with a space after it), then **drag the
`memory_lane_bot` folder from your file manager onto the terminal window** and
press Enter. That fills in the path for you without typing it.

Confirm you're in the right place:

```bash
ls          # Mac/Linux
dir         # Windows
```

You should see `main.py`, `README.md`, `requirements.txt` and the subfolders.
If you don't, you're in the wrong directory — try step 1.3 again.

## Step 1.4 — Create a virtual environment

This keeps the project's packages separate from the rest of your system, so
nothing you install here can break anything else.

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

If Windows refuses with a message about execution policies, run this once, then
retry the activate line:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**How you know it worked:** your terminal prompt now starts with `(venv)`.

> **Important for later:** that `(venv)` prefix disappears if you close the
> terminal. Every time you come back to this project, `cd` into the folder and
> run the `activate` line again. If a command later fails with
> "ModuleNotFoundError", this is almost always why.

## Step 1.5 — Install the packages

```bash
pip install -r requirements.txt
```

Takes a minute or two. Some warnings in yellow are normal; red `ERROR` lines
are not.

## Step 1.6 — Prove the code is healthy

```bash
python -m pytest tests/ -q
```

**Expected output:** `43 passed`.

This runs entirely offline with no tokens — it's testing the logic, not your
setup. If you see 43 passed, the code is intact and every problem from here on
is a configuration issue, not a code issue. That's a useful thing to know.

---

# Phase 2 — Create the Slack app

You're creating an app in Slack's admin console and collecting **two tokens**
from it. Keep a text file open to paste them into as you go.

## Step 2.1 — Create the app

1. Go to <https://api.slack.com/apps>
2. Sign in if asked
3. Click **Create New App**
4. Choose **From scratch**
5. App Name: `Memory Lane` (or anything)
6. Pick your workspace from the dropdown
7. Click **Create App**

You land on the app's settings page. The left sidebar is where everything below
happens.

## Step 2.2 — Turn on Socket Mode → get your first token

Socket Mode lets the bot connect out to Slack rather than Slack connecting in
to you. That's why you don't need a public web address, a tunnel, or any
firewall changes.

1. In the left sidebar, click **Socket Mode**
2. Toggle **Enable Socket Mode** on
3. Slack asks you to generate an app-level token. Name it `socket-token`
4. Click **Generate**
5. **Copy the token that appears — it starts with `xapp-`**

Paste it into your scratch file labelled `SLACK_APP_TOKEN`.

> Lost it? It's under **Basic Information → App-Level Tokens** — click the
> token name to view it again.

## Step 2.3 — Add permissions

1. Left sidebar → **OAuth & Permissions**
2. Scroll to **Scopes** → **Bot Token Scopes**
3. Click **Add an OAuth Scope** and add these **six**, one at a time:

| Scope | Why |
|---|---|
| `app_mentions:read` | See messages that mention the bot |
| `chat:write` | Post replies |
| `files:write` | **Upload the generated image** |
| `im:history` | Read direct messages |
| `im:read` | See direct message channels |
| `im:write` | Open direct messages |

> `files:write` is the one people forget. Without it the bot works but can't
> upload — it falls back to posting a raw link that expires within the hour.

## Step 2.4 — Subscribe to events

1. Left sidebar → **Event Subscriptions**
2. Toggle **Enable Events** on
3. It will *not* ask for a Request URL — that's Socket Mode working correctly
4. Expand **Subscribe to bot events**
5. Click **Add Bot User Event** and add both:
   - `app_mention`
   - `message.im`
6. Click **Save Changes** at the bottom right

## Step 2.5 — Enable direct messages (optional)

Only needed if you want to DM the bot instead of mentioning it in a channel.

1. Left sidebar → **App Home**
2. Scroll to **Show Tabs** → enable the **Messages Tab**
3. Tick **Allow users to send Slash commands and messages from the messages tab**

Without this, the DM box is greyed out even though the permissions are correct.

## Step 2.6 — Install to your workspace → get your second token

1. Left sidebar → **Install App**
2. Click **Install to Workspace**
3. Review and click **Allow**
4. **Copy the Bot User OAuth Token — it starts with `xoxb-`**

Paste it into your scratch file labelled `SLACK_BOT_TOKEN`.

> **Remember this:** if you change scopes later, you must come back here and
> click **Reinstall to Workspace**, or the new permission won't take effect.
> This is the second most common source of confusing failures.

## Step 2.7 — Invite the bot to a channel

1. Open Slack
2. Create a channel — call it `#memory-lane`
3. In the message box type `/invite @Memory Lane` and press Enter, selecting
   your bot from the autocomplete

The bot won't respond yet. It isn't running. That's expected.

---

# Phase 3 — Get your Replicate token

1. Go to <https://replicate.com> and sign in (GitHub sign-in is quickest)
2. Add a payment method: <https://replicate.com/account/billing>
   — training won't start without one
3. Go to <https://replicate.com/account/api-tokens>
4. Copy your token. **It starts with `r8_`**

Paste into your scratch file as `REPLICATE_API_TOKEN`.

---

# Phase 4 — Prepare your photos

The quality of your final images depends more on this step than on anything
else you'll do. Rushing here produces a model that generates a generic child
instead of a recognisable young you.

## Step 4.1 — Choose about 20 photos

**Good set:**
- Just you in the frame — crop other people out, or don't use the photo
- Your face clearly visible and reasonably large
- Varied: different backgrounds, lighting, angles, clothing, expressions
- A mix of close-up face shots and waist-up shots
- Recent-ish, so they're consistently the same person

**Avoid:**
- Sunglasses, heavy shadow across the face, motion blur
- Group photos, even if you're the main subject
- 20 near-identical selfies from one session — variety is what teaches the
  model your face rather than one particular lighting setup
- Heavy filters

15 good photos beat 25 mediocre ones.

## Step 4.2 — Zip them

Put the photos in a folder, then create a zip containing **the image files
directly**, not a folder containing them.

**Mac/Linux** — from inside the project folder:
```bash
zip -j data/my_photos.zip /path/to/your/photos/*.jpg
```
The `-j` flag is what flattens the folder structure. Drag your photos folder
onto the terminal to get its path.

**Windows:** open the folder containing your photos, select all the image files
(`Ctrl + A`), right-click → **Send to** → **Compressed (zipped) folder**.
Selecting the *files* rather than the *folder* is what matters. Then move the
resulting zip into the project's `data` folder and rename it `my_photos.zip`.

Verify it looks right:
```bash
unzip -l data/my_photos.zip
```
You should see a flat list of image filenames with no folder prefixes.

## Step 4.3 — Create the destination model on Replicate

Training needs somewhere to put the finished model, and that place must exist
first.

1. Go to <https://replicate.com/create>
2. **Model name:** `memory-lane-lora`
3. **Visibility:** Private
4. **Hardware:** leave the default
5. Click **Create model**

Note the full name shown at the top — it'll be `your-username/memory-lane-lora`.
Write it down; you need it in the next step.

---

# Phase 5 — Train the model (the 20–40 minute wait)

## Step 5.1 — Create your .env file

The project ships with a template. Copy it:

**Mac/Linux:**
```bash
cp .env.example .env
```
**Windows:**
```powershell
copy .env.example .env
```

Open the new `.env` file in any text editor (TextEdit, Notepad, VS Code) and
fill in the four values from your scratch file:

```
SLACK_BOT_TOKEN=xoxb-...your actual token...
SLACK_APP_TOKEN=xapp-...your actual token...
REPLICATE_API_TOKEN=r8_...your actual token...
LORA_MODEL_VERSION=leave-this-for-now
LORA_TRIGGER_WORD=TOK
```

Rules that trip people up:
- No quotes around the values
- No spaces around the `=`
- The file is named exactly `.env` — not `.env.txt`. On Windows, Notepad may
  silently add `.txt`; choose "All Files" in the Save dialog to prevent it

Leave `LORA_MODEL_VERSION` as-is. It gets filled in at the end of this phase.

> **Never commit or share this file.** It contains credentials that can spend
> money and post to your Slack. `.gitignore` already excludes it.

## Step 5.2 — Start training

One command, substituting your Replicate username:

```bash
python -m replicate_client.training \
  --photos-zip data/my_photos.zip \
  --destination your-username/memory-lane-lora \
  --trigger-word TOK \
  --wait
```

**Windows PowerShell** uses backticks instead of backslashes for line
continuation — or just put it all on one line, which is simpler.

**What you'll see:** a training id, a URL to watch progress, then a status line
every 30 seconds cycling through `starting` → `processing` → `succeeded`.

**Leave this terminal open.** Closing it stops the status updates, though the
training itself continues on Replicate's servers — you can always follow it at
the printed URL or at <https://replicate.com/trainings>.

Now wait 20–40 minutes.

## Step 5.3 — Save the version id

When it finishes you'll see:

```
Training succeeded.
Set LORA_MODEL_VERSION=your-username/memory-lane-lora:a1b2c3d4e5f6...
```

Copy that whole value — including the `:` and the long hash — into your `.env`:

```
LORA_MODEL_VERSION=your-username/memory-lane-lora:a1b2c3d4e5f6...
```

> **The single most important consistency check:** `LORA_TRIGGER_WORD` in
> `.env` must exactly match the `--trigger-word` you trained with (`TOK`). This
> word is the handle the model uses to mean "this specific person's face". Get
> it wrong and everything will run without error while producing photos of a
> child who isn't you. If your images come back looking like a stranger, check
> this first.

**If training failed with a "version not found" error:** Replicate has
published a newer trainer since this was built. Go to
<https://replicate.com/ostris/flux-dev-lora-trainer>, copy the current version
hash from the API tab, and re-run with
`--trainer-version ostris/flux-dev-lora-trainer:THAT_HASH`.

---

# Phase 6 — Test in stages

Don't skip to running the whole bot. Each of these tests one connection, so a
failure tells you exactly which piece is wrong. This takes five minutes and
saves far more.

## Stage 1 — Is Slack wired up correctly?

```bash
python scripts/stage1_echo_bot.py
```

**Expected:** `Stage 1 echo bot connecting. Mention the bot in a channel...`
and then the terminal sits there. That's correct — it's listening.

Go to Slack, into `#memory-lane`, and post:

```
@Memory Lane hello
```

**Expected:** a threaded reply within a second: *"✅ Stage 1 OK. I heard: hello"*

If you got that, your tokens, scopes, Socket Mode, and threading all work. Stop
the script with `Ctrl + C`.

If nothing happens, see Troubleshooting below before going further.

## Stage 2 — Does image generation work?

```bash
python scripts/stage2_test_inference.py
```

**Expected:** it prints the parsed age and scene, the full prompt, a prediction
id, then after 30–60 seconds a URL.

Open that URL in your browser. **Look at the face.** This is your quality
checkpoint — if the likeness is poor, that's a training-data problem, and no
amount of bot configuration will fix it. Better photos and re-training is the
answer.

Try your own prompt:
```bash
python scripts/stage2_test_inference.py "my 10-year-old self in a classroom"
```

---

# Phase 7 — Run the bot

```bash
python main.py
```

**Expected:**
```
Down Memory Lane is connecting to Slack (Socket Mode)...
LoRA version: your-username/m...
Trigger word: TOK
```

Then it waits. In Slack:

```
@Memory Lane my 5-year-old self on a beach
```

**What should happen:**
1. Within a second, a threaded reply: *"📸 Working on it — you at 5, on a
   beach. This usually takes 30-60 seconds."*
2. After 30–60 seconds, in that same thread, the image.

Try the three examples from the assignment brief:
```
@Memory Lane my 2-year-old self in my house's backyard
@Memory Lane my 5-year-old self on a beach
@Memory Lane my 10-year-old self in a classroom
```

**The bot only works while this terminal is running.** `Ctrl + C` stops it.
Closing the terminal stops it. This matters for your demo — keep it running the
whole time you're recording.

---

# Worth demonstrating on camera

Since a working bot is one of your deliverables, these are the behaviours that
show judgment rather than just a happy path. Each takes seconds to trigger:

| Do this | Shows |
|---|---|
| Post a request, wait for the image | The core flow |
| Post a second request in the **same thread** before the first finishes | Concurrency handling — it declines and explains, rather than doubling up |
| Post requests in **two different threads** at once | They genuinely run in parallel and each lands in the right place |
| Send `@Memory Lane hello` | Friendly help text instead of a crash |
| Send `@Memory Lane my 5-year-old self` with no scene | Graceful rejection with an example |
| Point at the terminal log while it runs | Job ids, prediction ids, timings — the audit trail |

The second row is the most interesting one to a technical reviewer, because
it's the case most prototypes get wrong.

---

# Troubleshooting

## Nothing happens when I mention the bot

Work down this list in order:

1. **Is the script actually running?** The terminal should be sitting open with
   no prompt returned. If you see your normal prompt, it exited.
2. **Is the bot in the channel?** Type `/invite @Memory Lane` in that channel.
3. **Did you save the Event Subscriptions page?** The **Save Changes** button
   at the bottom right is easy to miss. Go back and confirm `app_mention` is
   listed.
4. **Did you reinstall after changing scopes?** OAuth & Permissions →
   **Reinstall to Workspace**.
5. **Are you actually mentioning it?** The `@Memory Lane` must be a real blue
   mention chip, selected from autocomplete — not plain typed text.

## `ModuleNotFoundError: No module named 'slack_bolt'`

Your virtual environment isn't active. Look for `(venv)` at the start of your
prompt. Re-run the activate command from step 1.4.

## `Configuration error: Required environment variable ... is not set`

The `.env` file is missing, misnamed, or in the wrong folder. It must sit next
to `main.py`. On Windows, check it isn't secretly `.env.txt` — enable file
extensions in File Explorer's View menu to see the truth.

## `Slack rejected the bot token`

The `SLACK_BOT_TOKEN` value is wrong. It must be the **Bot User OAuth Token**
starting with `xoxb-` from OAuth & Permissions — not the app-level `xapp-`
token, and not the Client Secret. It's easy to paste the wrong one.

## The bot replies but the image never arrives

Look at the terminal — the error will be there, and the bot also posts a
readable explanation in the thread:
- *"out of credit"* → add funds at <https://replicate.com/account/billing>
- *"could not find that model version"* → `LORA_MODEL_VERSION` is wrong; re-copy
  it from your training output
- *"took longer than 300s"* → cold start. Just try again; the second request is
  usually much faster

## The image posts as a link instead of a picture

Missing `files:write` scope. Add it in OAuth & Permissions, then **Reinstall to
Workspace**, then restart the bot.

## The generated face doesn't look like me

Check `LORA_TRIGGER_WORD` matches your training trigger word exactly. If it
does, this is a training-data quality issue — see Phase 4.1 and retrain with a
better photo set. This is the most common real-world cause.

## Everything worked yesterday, nothing works today

You opened a new terminal and the virtual environment isn't active. `cd` into
the project folder and run the activate command.

---

# Quick reference — starting up again later

```bash
cd /path/to/memory_lane_bot
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1
python main.py
```

Everything else — tokens, trained model, `.env` — is already done and persists.
