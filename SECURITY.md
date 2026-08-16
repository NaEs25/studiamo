# Security Policy

## Supported Versions

Studiamo is a single rolling release, there are no maintained older versions. Security
fixes land on `main` and self-hosters should stay current by pulling the latest image or
running `git pull` and rebuilding.

## Reporting a Vulnerability

Please do not open a public GitHub issue for security vulnerabilities.

Email **hello@studiamo.cloud** with a subject line starting `SECURITY:` and include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce it (a minimal repro is very helpful).
- Whether it affects the managed Cloud service (`studiamo.cloud`), the self-hosted
  Docker deployment, or both.

You should get an acknowledgement within a few days. Please give a reasonable amount of
time to investigate and ship a fix before any public disclosure.

## Scope

In scope:
- The application code in this repository (`app/`), including auth, billing, and
  multi-tenant data isolation (`user_uuid` scoping).
- The Docker Compose self-hosting setup.

Out of scope:
- Third-party services Studiamo integrates with (Google Gemini, Lemon Squeezy, Telegram,
  Supabase), report those directly to the respective provider.
- Denial-of-service reports against the managed `studiamo.cloud` service.
- Findings that require an already-compromised account or physical access to a
  self-hosted deployment's host machine.

## Notes for Self-Hosters

- Never commit `.env` or `vapid_keys.json`, both are gitignored for a reason, they hold
  real API keys and push-notification signing keys.
- Rotate `GEMINI_API_KEY` (and `TELEGRAM_BOT_TOKEN` if you use one) if you ever suspect
  either has leaked.
- `app/schema.py` is the source of truth for the database shape, it re-applies itself on
  every startup. Never apply schema changes straight to the database by hand, that is how
  the schema and the file describing it can silently drift apart.
