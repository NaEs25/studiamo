# Contributing to Studiamo

Thanks for taking a look. This project runs both as a self-hosted app and as the managed
`studiamo.cloud` service from the same codebase, so a few conventions below exist to keep
that split clean rather than out of pure preference.

## Getting a dev environment running

1. Copy the self-hosted environment template and fill it in:
   ```bash
   cp .env.selfhosted.example .env
   ```
2. Start Postgres:
   ```bash
   docker compose up -d
   ```
3. Install Python dependencies (Python 3.12):
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Build the CSS once (see "Frontend" below), then run the app:
   ```bash
   uvicorn app.main:app --reload --port 5004
   ```

The schema creates itself on first boot via `app/schema.py`, there is no separate migration
step to run.

## Database schema

`app/schema.py` is the single source of truth for every table, column, index, and
constraint. It re-applies itself on every startup (`ensure_schema_up_to_date()`), so:

- **Never** modify the database directly (no manual `ALTER TABLE` against a running
  instance). Edit `app/schema.py` instead, then restart the app to apply it.
- Every statement must be idempotent: `IF NOT EXISTS` on tables/columns/indexes, or a
  `DO $$ ... $$` guard for constraints (which have no `IF NOT EXISTS` form).
- This approach can only **add**. Renaming, dropping, or backfilling a column needs a
  real one-off migration, not a line in this file.
- `tests/test_schema_drift.py` guards this: it builds `app/schema.py` into a throwaway
  Postgres namespace and diffs it against the real database. Run it against a database
  you're pointed at before opening a PR that touches schema.

## Frontend

- Tailwind is compiled ahead of time, not loaded from a CDN:
  ```bash
  ./scripts/build_css.sh
  ```
  fetches the standalone CLI binary to `bin/tailwindcss` (gitignored, platform-specific) on
  first run, then builds `tailwind-built.css`. For live rebuilds while editing templates,
  run the CLI directly with `--watch`:
  ```bash
  bin/tailwindcss -c tailwind.config.js -i app/static/css/tailwind-input.css -o app/static/css/tailwind-built.css --watch
  ```
- No inline `<script>` tags in templates; JavaScript lives in `app/static/js/` and loads
  with `defer`.
- Bind click handlers with `addEventListener`, not inline `onclick="..."` in template
  strings, for anything new. (Some existing files predate this rule and still use
  `onclick`, that's tracked debt, not the pattern to copy.)
- Prefer the design system's token classes (`bg-paperBg`, `text-stoneMuted`, etc., defined
  in `tailwind.config.js` from `style.css` custom properties) over raw Tailwind colors
  (`bg-amber-600`) or hand-written hex values.

## Tests

```bash
pytest tests/
```

Tests that need a real database connection skip themselves (with a clear reason) when one
isn't configured, so the suite still runs somewhere without Postgres available.

## APP_MODE

Most behavior differences between self-hosted and cloud are gated on the `APP_MODE`
environment variable (`app/config.py`, `config.IS_CLOUD` / `config.IS_SELFHOSTED`). If
you're adding a feature that should behave differently in each mode, that's the flag to
branch on, keep cloud-only concerns (billing, managed Gemini key, Google OAuth) out of the
self-hosted code path and vice versa.

## Git

Stage files explicitly (`git add path/to/file.py`), not `git add -A` / `git add .`. It's
easy to accidentally sweep in unrelated local changes otherwise.

## Pull Requests

- Keep PRs focused on one change. Small and reviewable beats a large bundled diff.
- Explain the *why* in the PR description, not just the what, especially for anything
  touching auth, billing, or multi-tenant data isolation (`user_uuid` scoping).
- Run `pytest tests/` before opening the PR.

## Reporting bugs / security issues

Regular bugs: open a GitHub issue.
Security vulnerabilities: see [SECURITY.md](SECURITY.md), please don't file those as
public issues.
