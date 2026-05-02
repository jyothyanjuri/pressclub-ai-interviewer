# PressClub AI Voice Interviewer

An AI voice agent that conducts structured founder interviews and produces newsworthy pitch briefings. Replaces the human interviewer in PressClub's PR workflow.

## How It Works

| Phase | What Happens |
|---|---|
| **Research** | Upload a prior sales transcript + company URL + LinkedIn URL. Claude researches all sources and produces a briefing doc with ranked interview questions. |
| **Interview** | A Vapi voice agent — pre-loaded with the briefing doc — conducts a 20–30 minute browser call with the founder. |
| **Synthesis** | Claude reads the full interview transcript, scores each newsworthy signal, and produces `output.md` for Weida's pitch pipeline. |

## Setup

```bash
cp .env.example .env
# Fill in API keys in .env

pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000)

You also need to set your Vapi public key in `static/interview.html`:
```js
window.VAPI_PUBLIC_KEY = 'your-vapi-public-key-here';
```

## API Keys Required

| Key | Used For |
|---|---|
| `ANTHROPIC_API_KEY` | Research agent + synthesis agent |
| `VAPI_API_KEY` | Creating voice assistants |
| `VAPI_PUBLIC_KEY` | Browser SDK (safe to expose) |
| `GEMINI_API_KEY` | LLM inside Vapi |
| `OXYLABS_USERNAME` + `OXYLABS_PASSWORD` | LinkedIn scraping |
| `OPENAI_API_KEY` | Whisper audio transcription |

## Running Benchmarks

```bash
python -m tests.benchmark
```

Runs all 8 pipeline steps with pass/fail output and timing.

## Stretch Goals

**Stretch 1 — Dynamic follow-ups:** Set `VAPI_CUSTOM_LLM_URL` to your server's `/chat/completions` endpoint. Vapi will call Claude between every turn, enabling signal-aware follow-up logic. No other changes needed.

**Stretch 2 — Rambling interruption:** Uncomment the `stopSpeakingPlan` block in `services/vapi_service.py`. Vapi will interrupt the founder after 50 words of rambling and redirect.

## File Structure

```
main.py                    FastAPI: all routes + Vapi webhook
agents/
  research_agent.py        Phase 1: research → briefing_doc.json
  synthesis_agent.py       Phase 3: transcript → output.md
services/
  transcriber.py           Audio/txt → clean text (Whisper)
  crawler_service.py       Oxylabs LinkedIn wrapper
  website_reader.py        URL → structured content (Claude)
  vapi_service.py          Vapi assistant configuration
  storage.py               Local file persistence
prompts/
  research.txt             Signal detection framework
  interviewer.txt          Journalist persona + rules
  synthesizer.txt          Pitch generator instructions
static/
  index.html               Upload form
  interview.html           Live call (Vapi browser SDK)
  results.html             Scorecard + download
tests/
  benchmark.py             All 8 steps with pass/fail
  fixtures/                Sample transcript + expected outputs
```

## Output Format

`output.md` contains:
- Interview summary
- Newsworthy scorecard (confirmed / unconfirmed / needs follow-up per signal)
- Structured notes by signal type
- Recommended pitch angle with specific data points
- Full timestamped transcript

Ready for direct ingestion into PressClub's pitch generation pipeline.
