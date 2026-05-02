# PressClub AI Interviewer — Setup & Configuration Log

Sprint: May 2026 | Status: Running

---

## What We Built

An end-to-end AI voice interviewer that:
1. Ingests a sales call transcript + company website
2. Runs a Claude research agent to produce a briefing doc
3. Launches a Vapi voice call where GPT-4.1 conducts the interview
4. Receives the transcript via webhook and runs a Claude synthesis agent
5. Produces a newsworthy scorecard + output.md for the pitch pipeline

---

## Stack Installed

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.x | Runtime |
| FastAPI | 0.111.0 | Backend server |
| Uvicorn | 0.29.0 | ASGI server |
| Anthropic SDK | 0.28.0 | Claude research + synthesis agents |
| httpx | 0.27.0 | HTTP client for Vapi + website reader |
| python-dotenv | 1.0.1 | Load .env file |
| python-multipart | 0.0.9 | File upload handling |
| ngrok | 3.20.0+ | Expose localhost for Vapi webhooks |

### Installation

```powershell
pip install -r requirements.txt
winget install ngrok.ngrok
ngrok config add-authtoken YOUR_TOKEN
```

---

## API Keys Configured

All keys stored in `.env` (never committed to git).

| Key | Service | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API | console.anthropic.com → API Keys |
| `VAPI_API_KEY` | Vapi private key | dashboard.vapi.ai → API Keys |
| `VAPI_PUBLIC_KEY` | Vapi public key | dashboard.vapi.ai → API Keys |
| `GEMINI_API_KEY` | Not used (swapped to GPT-4.1) | — |
| `OPENAI_API_KEY` | Not needed for demo | — |
| `OXYLABS_USERNAME/PASSWORD` | Not needed for demo | — |

---

## Vapi Configuration

### Assistant

- **Assistant ID:** `abcbbe84-9859-4182-a77f-ca9370188caa`
- **Created via:** Vapi dashboard (dashboard.vapi.ai → Assistants → Create)
- **Model:** GPT-4.1 (OpenAI, via Vapi's built-in credentials — no separate OpenAI key needed)
- **Voice:** Elliot (Vapi default)
- **Transcriber:** Deepgram nova-2

### How assistant is updated per session

Each time `/start-interview` is called, the server sends a PATCH request to Vapi to update the assistant's system prompt with the current session's briefing doc. The same assistant ID is reused for every interview.

### Webhook

- **Webhook URL set via API:** `https://divisibly-vividly-parachute.ngrok-free.dev/vapi-webhook`
- **Note:** ngrok URL changes every session. Must re-set webhook URL each time ngrok restarts.
- **How to update webhook:** Run this in terminal (replace URL with new ngrok URL):

```powershell
curl -X PATCH https://api.vapi.ai/assistant/abcbbe84-9859-4182-a77f-ca9370188caa `
  -H "Authorization: Bearer YOUR_VAPI_API_KEY" `
  -H "Content-Type: application/json" `
  -d '{"serverUrl": "https://YOUR-NEW-NGROK-URL.ngrok-free.app/vapi-webhook"}'
```

### What to do when ngrok URL changes

Every time ngrok restarts it generates a new URL. Steps each session:

1. Start ngrok: `ngrok http 8000`
2. Copy the new URL from ngrok output (e.g. `https://xxxx-xxxx.ngrok-free.app`)
3. Run the curl command above with the new URL
4. Start the server and run the demo

### Avoid this with a static ngrok domain (recommended)

ngrok free tier includes one permanent static domain — the URL never changes so you only set the webhook once.

1. Go to [ngrok dashboard → Domains](https://dashboard.ngrok.com/cloud-edge/domains) and claim your free static domain
2. Start ngrok with:

```powershell
ngrok http --domain=your-static-domain.ngrok-free.app 8000
```

3. Set the webhook URL once (using your static domain) and never update it again

### Settings tuned during testing

| Setting | Value | Reason |
|---|---|---|
| `silenceTimeoutSeconds` | 60 | Prevent early call termination |
| `endCallPhrases` | "end the interview", "stop the interview" | Avoid accidental trigger on common words |
| `maxDurationSeconds` | 2400 (40 min) | Hard cap |

---

## Interviewer Prompt Tuning

Key rules added after testing:

- Ask ONE question at a time
- Keep responses under 2 sentences
- Never end the call yourself
- Do not stack questions or give preambles

File: `prompts/interviewer.txt`



## How to Run

### Every session (both terminals must stay open)

**Terminal 1 — API server:**
```powershell
cd c:\Users\jyothy.anjuri\pressclub-sprint
uvicorn main:app --reload --port 8000
```

**Terminal 2 — ngrok tunnel:**
```powershell
ngrok http 8000
```

Then update the Vapi webhook URL with the new ngrok URL (see above).

### Demo flow

1. Open `http://localhost:8000`
2. Paste sales call transcript (see `tests/fixtures/sample_transcript.txt`)
3. Enter company website URL (e.g. `https://stripe.com` for testing)
4. Click **Run Research Agent** (~30-60 seconds)
5. Click **Start Interview** — allow microphone
6. Answer questions as the founder
7. Click **End Call**
8. Wait ~30 seconds for synthesis
9. View results — scorecard + download output.md

---

## File Structure

```
pressclub-sprint/
├── main.py                  FastAPI server + all routes
├── agents/
│   ├── research_agent.py    Phase 1: transcript+URL → briefing_doc
│   └── synthesis_agent.py   Phase 3: transcript → output.md scorecard
├── services/
│   ├── transcriber.py       Audio/txt → text
│   ├── crawler_service.py   LinkedIn scraper (optional, not used in demo)
│   ├── website_reader.py    URL → structured content via Claude
│   ├── vapi_service.py      Vapi assistant update + system prompt injection
│   └── storage.py           Session file persistence
├── prompts/
│   ├── research.txt         5-signal newsworthy framework
│   ├── interviewer.txt      Journalist persona + interview rules
│   └── synthesizer.txt      Scorecard output format
├── static/
│   ├── index.html           Upload form
│   ├── interview.html       Live call (Vapi browser SDK)
│   └── results.html         Scorecard + download
├── sessions/                Auto-created, one folder per interview session
├── tests/
│   ├── benchmark.py         8-step pass/fail benchmark suite
│   └── fixtures/            Sample transcript + expected outputs
├── .env                     API keys (never commit)
├── .env.example             Key template
├── .gitignore
└── requirements.txt
```

---

## What's Not Wired for Demo

| Feature | Status | Notes |
|---|---|---|
| LinkedIn scraping | Partially built | See detail below |
| Audio upload (Whisper) | Skipped | No OpenAI key — demo uses text transcript |
| Stretch Goal 1: Dynamic follow-ups | Not implemented | Requires Custom LLM URL + ngrok always-on |
| Stretch Goal 2: Rambling interruption | Not implemented | Uncomment `stopSpeakingPlan` in vapi_service.py |

---

## LinkedIn Scraping — Detail

### What was planned
Use a LinkedIn scraper to pull founder profile (name, role, work history, education) as a third research source alongside transcript + website.

### What was built
`services/crawler_service.py` is fully implemented using Oxylabs API. The research agent calls it as a backup source when a LinkedIn URL is provided.

### What happened
- Oxylabs requires an enterprise plan (~$99/month) — not suitable for a sprint
- Apify account was created (free tier, $5 credits) as a cheaper alternative
- Apify API token was obtained from dashboard.apify.com
- `crawler_service.py` was **not updated** to use Apify — we ran out of time fixing Vapi issues
- The code currently falls back to an empty profile when Oxylabs credentials are missing, which the research agent handles gracefully

### Why it doesn't matter for the demo
The sales call transcript already contains the founder's background in their own words. For the DataSync demo, Priya's Oracle history, CDO role, and "50 people in the world" quote are all in the transcript — LinkedIn would add nothing new.

### To wire it up later
1. In `services/crawler_service.py`, replace the Oxylabs API call with:
   ```python
   APIFY_URL = "https://api.apify.com/v2/acts/bebity~linkedin-profile-scraper/run-sync-get-dataset-items"
   params = {"token": os.environ["APIFY_API_TOKEN"]}
   body = {"profileUrls": [linkedin_url]}
   ```
2. Add to `.env`:
   ```
   APIFY_API_TOKEN=apify_api_xxxx
   ```
3. Map the Apify response fields to the normalized profile dict already defined in `_normalize_profile()`

### LinkedIn field in the UI
The LinkedIn URL field is visible in the upload form but marked **optional**. If left blank, the research agent skips the scrape step entirely and uses transcript + website only. No errors occur.
