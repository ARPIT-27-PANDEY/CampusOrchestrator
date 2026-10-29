# Deploying CampusOrchestrator to Render

The app runs as **two Render web services**, defined in [`render.yaml`](render.yaml):

| Service | What runs in it | Dockerfile |
|---|---|---|
| `campusos-api` | FastAPI backend **and** the 4 MCP servers (separate processes, MCP over HTTP on `127.0.0.1`), plus the official IIT Roorkee PDFs | [`infra/render/Dockerfile`](infra/render/Dockerfile) |
| `campusos-web` | Next.js frontend; its `/api/*` route proxies to the API server-side | [`frontend/Dockerfile`](frontend/Dockerfile) |

Why one container for the backend and MCP servers: Render's free plan allows 750 running hours a month
and free services sleep when idle. Six separate services would exceed the hours, and a sleeping MCP
server would make tool calls time out. Inside the container the MCP servers listen only on `127.0.0.1`,
so only the backend is public. If any process dies, the container exits and Render restarts it. The
academics index is rebuilt in memory at every start (about 10 s for the official corpus).

## Access control (required)

The API refuses to start in production without access control, so that nobody can spend your Groq quota
anonymously (see [docs/security.md](docs/security.md)). In the Render dashboard, `campusos-api` ->
**Environment**:

| Variable | Value |
|---|---|
| `ACCESS_PASSWORD` | a password you share with the people who may use the assistant (>= 8 characters) |
| `SESSION_SECRET` | generated automatically by the Blueprint (`generateValue`); keep it secret |
| `ACCESS_MODE` | `password` (set by `render.yaml`) |
| `CORS_ORIGINS` | the **web** URL (allowed Origin for sign-in and chat) |
| `TRUSTED_PROXY_HOPS` | `2` (Render load balancer in front of the web proxy and of the API) |

**Set `ACCESS_PASSWORD` before the next deploy**, otherwise the API logs "Refusing to start" and keeps
restarting. To run a deliberately open demo instead, set `ALLOW_OPEN_ACCESS=true` (not recommended with
a Groq key).

`campusos-web` needs only `BACKEND_URL` = the **api** URL. It is read at request time on the server, so
changing it needs a restart, not a rebuild, and it never reaches the browser.

## 1. Before you start

- A **GitHub** account (Render deploys from a Git repo) and a **Render** account.
- A **Groq API key**: <https://console.groq.com/keys>. Without it, set `LLM_PROVIDER=mock` (canned offline answers).
- The official PDFs in `services/academics_mcp/data/iitr/` (run `make fetch-sources` if they are not committed).

## 2. Create or update the services

New deployment: Render dashboard -> **New** -> **Blueprint** -> pick the repository. Paste `GROQ_API_KEY`
and `ACCESS_PASSWORD` when asked, then **Apply** (first build 5-10 minutes).

Existing deployment: push to `main`; the Blueprint syncs `render.yaml` and both services redeploy. Add
`ACCESS_PASSWORD` in the dashboard first (see above).

## 3. Check the URLs

If Render added a suffix to a service name (e.g. `campusos-api-x7k2.onrender.com`):
1. `campusos-api` -> **Environment** -> `CORS_ORIGINS` = the real **web** URL.
2. `campusos-web` -> **Environment** -> `BACKEND_URL` = the real **api** URL.
3. Update both in `render.yaml` too. No trailing slashes.

## 4. Test it

- `https://<api-url>/api/health` -> `"status": "ok"`, `"access_mode": "password"`, `campus_time` in IST.
- `https://<api-url>/api/sources` -> 4 servers `available`.
- `https://<web-url>/chat` -> sign-in form; after signing in ask *"What events are happening today?"*.
- `https://<web-url>/evals` -> evaluation runs (public, read-only).

## Good to know

- **Sleeping:** free services sleep after 15 minutes without traffic; the first visit then takes about a minute.
- **Memory:** the API container measured about 425 MB of the free plan's 512 MB after start-up and a few
  questions (official corpus, hashing embedder). FastEmbed would not fit the free plan, so `render.yaml`
  pins lexical search (`EMBEDDING_PROVIDER=hashing`, `RETRIEVAL_MODE=dense`, `LIBRARY_SEARCH_MODE=keyword`).
  On an instance with at least 1 GB, install the `fastembed` extras in `infra/render/Dockerfile` and set
  `fastembed` / `hybrid` / `hybrid`. If the logs show an out-of-memory kill, move `campusos-api` to a paid instance.
- **Rate limits:** 10 questions per minute per session (burst 5), 5 sign-in attempts per minute per client,
  4 concurrent runs. Groq's free tier allows about 8K tokens a minute for `gpt-oss-120b`.
- **Traces:** in production the stored traces keep no question text and no tool arguments, and expire after 24 h.
- **Updates:** every push to `main` redeploys both services. **Logs:** each service's **Logs** tab.

## Test the production image locally (optional)

```bash
docker build -f infra/render/Dockerfile -t campusos-api-render .
docker run --rm -p 8090:10000 -e PORT=10000 -e LLM_PROVIDER=mock -e ACCESS_MODE=password \
  -e ACCESS_PASSWORD=local-test-pass -e SESSION_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))") \
  -e CORS_ORIGINS=http://localhost:3000 -e COOKIE_SECURE=false campusos-api-render
```

`COOKIE_SECURE=false` is only for local HTTP; Render serves HTTPS.
