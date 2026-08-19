<p align="center">
  <img src="app/static/images/logo.png" alt="Studiamo logo" width="120">
</p>

<h1 align="center">Studiamo</h1>

<p align="center">
  <strong>Learn once. Remember forever.</strong><br>
  Turns your YouTube videos, PDFs, and lecture notes into AI-generated active-recall
  flashcards, scheduled with spaced repetition right before memory fades.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12">
  <img src="https://img.shields.io/badge/self--hosted%20or%20cloud-yes-amber.svg" alt="Self-hosted or cloud">
</p>

---

> **Self-hosting?** Skip straight to the **[Self-Hosting Guide](SELFHOSTING.md)**, > quickstart, backups, updating, and troubleshooting, without reading the rest of this
> README first.

## 🛠 Status & Architecture Note

Studiamo is an agile project built and shipped in a rapid 4-week sprint using modern AI-assisted workflows. 
The core focus has been speed, working features, and getting an active recall engine into learners' hands. 

Refactoring, optimizations, and PRs are always welcome!


 **[Screenshot: Dashboard, study goals with video/PDF cards grouped by learning goal, SRS stage badges visible]**

## What it does

1. **Import** a YouTube video, PDF, or pasted text.
2. **AI analysis** (Google Gemini) extracts a summary, matches it to a learning goal, and
   generates active-recall quiz questions at five difficulty stages.
3. **Spaced scheduling** assigns each card a review date on an Ebbinghaus-inspired
   interval, so review happens right before you'd naturally forget it.
4. **Review** in the web app, or get a Telegram nudge when a card comes due.
5. **Fact-checking** cross-references generated claims so you're not memorizing an AI
   hallucination.

> **[Screenshot: Study Studio, video/PDF pane on the left, synced notes and flashcard generation on the right]**

## Features

- **Side-by-side Study Studio**: watch the source video or read the source PDF while
  taking notes and generating flashcards in the same view.
- **5-stage SRS**: Stage 0 (immediate) through Stage 4 (14–30 days), with distinct,
  progressively harder question banks generated per stage, not the same questions
  repeated.
- **AI fact-verification**: disputed claims in generated content are flagged with the
  actual consensus and a severity rating.
- **Telegram review bot**: get a deep-linked notification when a card is due, review it
  from your phone.
- **Gamification**: XP, levels, streaks, and a cross-user leaderboard.
- **PWA**: installable, works offline for already-loaded content.
- **No data lock-in**: export your data (flashcards, stats, documents) as a structured
  archive at any time.

> **[Screenshot: Quiz/flashcard review, a flipped flashcard showing the AI-generated answer and grading buttons]**

## Self-hosted or cloud, your choice

Studiamo runs from a single codebase in two modes, controlled by the `APP_MODE`
environment variable.

| | Self-Hosted (`APP_MODE=selfhosted`) | Cloud (`APP_MODE=cloud`) |
|---|---|---|
| Cost | Free, open source | Managed subscription |
| Auth | Local username + password | Google Sign-In |
| Gemini API key | Bring your own (free tier from Google AI Studio works) | Included |
| Database | Your own PostgreSQL (Docker Compose provided) | Managed |
| Telegram | Bring your own bot via `@BotFather` | Shared managed bot |
| Data | 100% yours, on your own infrastructure | Hosted for you |

## Quickstart (self-hosted)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker with the Compose plugin (Linux) installed and running.

```bash
git clone https://github.com/NaEs25/studiamo.git
cd studiamo

cp .env.selfhosted.example .env
# Set YB_SECRET_KEY (openssl rand -hex 32), and optionally GEMINI_API_KEY,
# or leave the Gemini key unset and add it later from Settings (BYOK)

docker compose up -d
```

Then open `http://localhost:5004` and create your first account. One command pulls the
prebuilt image and starts both the app and its Postgres database, the schema creates
itself on first boot, no separate migration step needed. See
[`SELFHOSTING.md`](SELFHOSTING.md) for full setup details, backups, and running without Docker.

Get a free Gemini API key at [Google AI Studio](https://aistudio.google.com/apikey), it
has a generous free tier and is all you need to run Studiamo self-hosted. Goal/daily
recommendations need a separate, also-free YouTube Data API v3 key, without it everything
else works, recommendations just stay empty, see
[`SELFHOSTING.md`](SELFHOSTING.md) for details and for running without Docker.

## Documentation

- [`SELFHOSTING.md`](SELFHOSTING.md): self-hosting setup, Docker Compose, backups, and configuration.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): dev environment setup, schema conventions, and PR guidelines.
- [`SECURITY.md`](SECURITY.md): how to report a vulnerability.


## Tech stack

Python 3.12 / FastAPI · PostgreSQL · Google Gemini (`gemini-3.5-flash-lite`) · Tailwind
CSS (compiled, no CDN) · vanilla ES6 JavaScript, no frontend build step.

## License

[GNU AGPL v3.0](LICENSE). Running a modified version of this code as a network service
requires making your modified source available to your users, see the LICENSE file for
the exact terms.
