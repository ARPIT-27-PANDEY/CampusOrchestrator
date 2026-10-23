# Optional: Google Calendar for the Events server

The events server includes a **read-only** adapter for a **public** Google Calendar using an API key (Calendar API v3 `events.list` / `events.get`). With it enabled, results report `source.mode = "live"`.

## Setup (API key, public calendar)
1. In Google Cloud Console, create a project and enable **Google Calendar API**.
2. Create an **API key** under *APIs & Services → Credentials*. Restrict it to the Calendar API (and to your server's IP if you can).
3. Make the campus calendar public (*Settings → Access permissions → Make available to public*) and copy its **Calendar ID** (e.g. `abc123@group.calendar.google.com`).
4. Configure the events server:
   ```bash
   EVENTS_PROVIDER=google
   GOOGLE_CALENDAR_ID=abc123@group.calendar.google.com
   GOOGLE_CALENDAR_API_KEY=...        # keep in .env; never commit
   CAMPUS_TIMEZONE=Asia/Kolkata
   ```
5. Restart `events-mcp` and check `GET http://localhost:8102/health`, which should report `"provider": "google-calendar", "mode": "live"`.

The calendar id and key come only from configuration; the model can't choose which calendar or URL is queried. Error messages never include the request URL, which contains the key.

## Private calendars (OAuth): not implemented
Private calendars need OAuth 2.0: either a service account with domain-wide delegation, or a user consent flow that stores a refresh token. That would mean adding `google-auth` and a token store, which is deliberately left out of the MVP. Never commit `credentials.json` or `token.json`; both patterns are already in `.gitignore`.

Status: the adapter is unit-tested against mocked HTTP (`services/events_mcp/tests`). It has **not** been run against a real Google Calendar.
