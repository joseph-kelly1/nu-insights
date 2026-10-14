# Railway deployment

NU Insights runs as one Railway service: Flask serves the built React frontend,
the `/api` routes, and the catalog database at
<https://nuinsights.josephkelly.dev>.

- Project: **NU Insights**
- Service: **nu-insights**, production environment
- Dashboard: <https://railway.com/project/baf9bb7b-c68f-4719-8fc0-afa3aae6176d>
- Railway URL: <https://nu-insights-production.up.railway.app>
- DNS provider: Cloudflare; the domain's nameservers remain there.

## Build and runtime

The multi-stage `Dockerfile` builds React with Node.js, installs Python
dependencies, and generates `var/courses.db` from the checked-in snapshots.
The final image contains the React build, backend, data, and database. It runs
Gunicorn as an unprivileged user on Railway's `PORT` (8080 for this service).
No development server or separate frontend service is needed.

The database contains rebuildable catalog data. User drafts stay in browser
storage; there is no persistent volume or user database. Catalog updates require
a new deployment. Future server-side user data needs persistent storage.

Gunicorn defaults to two workers with four threads each. `WEB_CONCURRENCY`
overrides the worker count. Its 300-second timeout accommodates AI requests;
provider timeouts and Railway's request limits still apply.

## Deploy changes

The initial deployment was uploaded from the local checkout. GitHub automatic
deployments are not connected. From the repository root:

```sh
railway login
railway link --project baf9bb7b-c68f-4719-8fc0-afa3aae6176d --environment production --service nu-insights
railway up --service nu-insights
```

The Docker build uses the lockfile in `frontend/`. `.gitignore` excludes local
secrets and generated artifacts from Railway uploads; `.dockerignore` excludes
them from the container build as well.

Infrastructure settings are in `.railway/railway.ts`. To change them:

```sh
npm ci
railway config plan
railway config apply
```

The infrastructure configuration manages only this service and leaves
environment variables on Railway. It uses the Dockerfile builder, checks
`/api/health` before routing traffic, and restarts failed containers.

## Environment variables

Manage `OPENROUTER_API_KEY` and other `OPENROUTER_*` settings in Railway's service
Variables panel. Values must not be committed or included in frontend settings.
The local OpenRouter settings were copied securely during initial deployment.
`FLASK_DEBUG=0` and `PORT=8080` are configured on Railway.

## Domain

Cloudflare has these records:

| Type | Name | Purpose |
| --- | --- | --- |
| CNAME | `nuinsights` | `olqb4lwx.up.railway.app`, DNS only |
| TXT | `_railway-verify.nuinsights` | Railway's ownership verification token |

Railway handles HTTPS certificate issuance and renewal. If the service or domain
is recreated, use its newly returned DNS target and verification token.

```sh
railway domain status nuinsights.josephkelly.dev --service nu-insights
railway deployment list --service nu-insights --limit 5
railway logs --service nu-insights --lines 100
```

After deploying, check `/`, `/api/health`, course search, Course Builder, and AI
analysis over HTTPS. Unknown API routes and missing assets must return 404,
not the React page.
