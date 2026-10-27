# Deploying CampusOS AI to Render

The app runs as **two Render web services**, defined in [`render.yaml`](render.yaml):

| Service | What runs in it | Dockerfile |
|---|---|---|
| `campusos-api` | FastAPI backend **and** the 4 MCP servers (separate processes, MCP over HTTP on `127.0.0.1`) | [`infra/render/Dockerfile`](infra/render/Dockerfile) |
| `campusos-web` | Next.js frontend | [`frontend/Dockerfile`](frontend/Dockerfile) |

Why one container for the backend and MCP servers: Render's free plan allows 750 running hours a month
and free services sleep when idle. Six separate services would exceed the hours, and a sleeping MCP
server would make tool calls time out. Inside the container, the MCP servers listen only on
`127.0.0.1`, so only the backend is public. If any process dies, the container exits and Render
restarts it. The handbook index is rebuilt in memory at every start (a few seconds), so no database is needed.

## 1. Before you start

- A **GitHub** account (Render deploys from a Git repo).
- A **Render** account: <https://render.com> → sign up with GitHub.
- A **Groq API key**: <https://console.groq.com/keys>. Without it, set `LLM_PROVIDER=mock` (canned offline answers).

## 2. Push the code to GitHub

Create an **empty** repository on GitHub (no README, no .gitignore), e.g. `campusos-ai`. Then, from the repo root:

```bash
git add .
git commit -m "Add Render deployment"
git remote set-url origin https://github.com/<your-username>/campusos-ai.git
git push -u origin main
```

Never commit `.env`. It is already in `.gitignore`.

## 3. Create the services on Render

1. Render dashboard → **New** → **Blueprint**.
2. Connect GitHub and pick the `campusos-ai` repo. Render reads `render.yaml`.
3. When asked for `GROQ_API_KEY`, paste your key.
4. Click **Apply**. The first build takes about 5–10 minutes.

## 4. Check the URLs

Open each service in the dashboard and look at its URL at the top.

- If they are exactly `https://campusos-api.onrender.com` and `https://campusos-web.onrender.com`, you are done.
- If Render added a suffix (e.g. `campusos-api-x7k2.onrender.com`) because the name was taken:
  1. `campusos-api` → **Environment** → set `CORS_ORIGINS` to the real **web** URL → Save.
  2. `campusos-web` → **Environment** → set `NEXT_PUBLIC_API_BASE_URL` to the real **api** URL →
     **Save, rebuild and deploy** (this value is built into the frontend, so it needs a rebuild).
  3. Optionally update both values in `render.yaml` too, so they stay in sync.

No trailing slash in either URL.

## 5. Test it

- `https://<api-url>/api/health` returns `"status": "ok"`.
- `https://<api-url>/api/sources` lists 4 servers with `"status": "available"`.
- `https://<api-url>/docs` shows the API docs.
- Open the web URL and ask: *"Is the library open today and what's for lunch?"*

## Good to know

- **Sleeping:** free services sleep after 15 minutes without traffic. The first visit after that
  takes about 1 minute while both services wake up. Paid plans (Starter, $7/month per service) don't sleep.
- **Memory:** the API container uses about 390 MB of the free plan's 512 MB. If the logs show it was
  killed for memory, move `campusos-api` to the Starter plan.
- **Groq rate limits:** the free Groq tier allows about 8K tokens a minute for `gpt-oss-120b`, so heavy
  use gives "rate limit" messages. Wait a minute, or upgrade the Groq plan.
- **Updates:** every push to `main` redeploys both services automatically.
- **Logs:** each service's **Logs** tab in the Render dashboard.
- **Custom domain later:** service → **Settings** → **Custom Domains**. Then update the two URL settings in step 4.

## Test the production images locally (optional)

```bash
docker build -f infra/render/Dockerfile -t campusos-api-render .
docker run --rm -p 8090:10000 -e PORT=10000 -e LLM_PROVIDER=mock campusos-api-render
```

Then open <http://localhost:8090/api/sources>.
