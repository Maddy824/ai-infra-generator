# AI Infrastructure Generator

![ai-infra run on the bundled Flask and PostgreSQL example: it detects Python and Flask, then writes a Dockerfile, docker-compose.yml, .env.example and seven Kubernetes manifests](.github/assets/demo.gif)

Generate Docker, Compose, Kubernetes and other infrastructure configs from a repository, with offline defaults or a model-backed plan.

## 60-second quickstart

**Requirements:** Python 3.11+, pip, and a checkout of this repository for the bundled example. No model, API key, Docker daemon, or cluster is needed for offline generation.

Clone the repository, then create a virtual environment and install:

```bash
git clone https://github.com/Maddy824/ai-infra-generator.git
cd ai-infra-generator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./ai-infra
```

Generate configs for the tiny Flask/PostgreSQL app:

```bash
ai-infra run examples/flask-postgres --offline
```

This analyzes the app, builds a validated infrastructure model, and writes Docker, Compose and Kubernetes files next to the app. Open `examples/flask-postgres/docker-compose.yml` or `.ai-infra/plan.md` inside the example directory. Offline planning uses development defaults and does not enable cloud provisioning or CI/CD pipelines.

Here is an excerpt of the actual [generated Compose file](examples/flask-postgres/generated/docker-compose.yml):

```yaml
services:
  web:
    build:
      context: .
      dockerfile: Dockerfile.web
    restart: unless-stopped
    ports:
      - "127.0.0.1:5000:5000"
    depends_on:
      - postgres
    environment:
      PORT: "5000"
      DATABASE_URL: "${DATABASE_URL}"
```

The [generated snapshot](examples/flask-postgres/generated/) is a copy of the offline output, not a second runnable app. Regenerate it with `python examples/regenerate.py` or compare it with fresh output using `python examples/regenerate.py --check`.

**Review before deploying.** The generated configs are a starting point, not a production-readiness guarantee. Secrets contain placeholders. Offline Compose binds the application port to loopback and keeps database and cache ports internal to the Compose network. For this example, copy the generated `.env.example` to `.env` and fill in `POSTGRES_PASSWORD` and a matching `DATABASE_URL` (using `postgres` as the host, `app` as the username and database). Review startup commands, access controls, resource limits, and deployment settings for your environment. Generation does not build or deploy anything.

## Use it on your own project

You can install the command without cloning (Python 3.11+ and git):

```bash
pip install "git+https://github.com/Maddy824/ai-infra-generator@v0.1.0#subdirectory=ai-infra"
ai-infra run path/to/your-repo --offline
```

Files are written into that repository, next to its code. Files you already have, or have edited since generating, are skipped unless you pass `--force` (see [Regenerating Safely](#regenerating-safely)). Use `--target compose` or `--target k8s` to generate only part of the set.

## Switch to a model backend

If you want a plan that incorporates hints or more advanced infrastructure, configure a backend (such as a running local Ollama server with the configured model available), then omit `--offline`:

```bash
AI_INFRA_LLM_BACKEND=ollama ai-infra plan examples/flask-postgres
ai-infra generate examples/flask-postgres --target all
```

The offline step-by-step equivalent is `ai-infra analyze <repo>`, `ai-infra plan <repo> --offline`, then `ai-infra generate <repo> --target all`. Use `ai-infra run <repo> --offline` to do all three in one command.

## How It Works

1. **Understand** — Detects language, framework, ports and inferred dependencies from repository files.
2. **Plan** — Builds a validated infrastructure model from the analysis, either with deterministic offline defaults or with a configured LLM and optional hints.
3. **Generate** — Renders templates from the validated model without model calls.

---

## What It Generates

| Target | Output | When |
|---|---|---|
| `compose` | Multi-stage Dockerfiles, docker-compose.yml, `.env.example`, `.dockerignore` | When selected |
| `k8s` | Deployments (with health probes and dependency wait), Services, Ingress, HPA, PersistentVolumeClaims, ConfigMaps, Secrets | When selected |
| `ci` | CI/CD pipelines (GitHub Actions, GitLab CI, Bitbucket, CircleCI) | When `cicd.providers` is set |
| `helm` | Chart.yaml, values.yaml, templates/ | When `helm.enabled` is true |
| `iac` | Terraform main.tf for EKS / GKE / AKS | When `iac.enabled` is true |
| `monitoring` | Prometheus ServiceMonitors, Grafana dashboards, alert rules | When `monitoring.enabled` is true |
| `tenancy` | Namespace isolation, ResourceQuotas, NetworkPolicies per tenant | When `multi_tenancy.enabled` is true |
| `all` | Everything above | — |

Use `--target` to pick what you need:

```bash
ai-infra generate /path/to/repo --target compose
ai-infra generate /path/to/repo --target k8s
ai-infra generate /path/to/repo --target all
```

---

## Supported Languages

| Language | Detected From | Frameworks |
|---|---|---|
| Python | `requirements.txt`, `pyproject.toml` | FastAPI, Flask, Django, Starlette |
| Node.js | `package.json` | Express, Next.js, NestJS, Koa, Fastify |
| Go | `go.mod` | Gin, Echo, Fiber, Chi, Gorilla/mux |

The analyzer infers dependencies like PostgreSQL, Redis, worker queues, object storage and MongoDB. Offline planning creates defaults for PostgreSQL, MySQL, MongoDB and Redis when inferred. It does not guess worker commands or cloud resources; use a model backend or edit the plan for those. Application commands and environment variable names are conventions that may need adjusting.

---

## Configuration

Everything is controlled through environment variables prefixed with `AI_INFRA_`. No config files required.

### LLM Backends

When not using `--offline`, the default backend is **Ollama**, which runs locally and needs no API key.

```bash
# Ollama (default — free, local)
ollama pull qwen2.5-coder:7b
ai-infra plan /path/to/repo

# OpenAI
AI_INFRA_LLM_BACKEND=openai OPENAI_API_KEY=sk-... ai-infra plan /path/to/repo

# Claude
AI_INFRA_LLM_BACKEND=claude ANTHROPIC_API_KEY=sk-ant-... ai-infra plan /path/to/repo

# Gemini
AI_INFRA_LLM_BACKEND=gemini GEMINI_API_KEY=AI... ai-infra plan /path/to/repo
```

### All Settings

| Variable | Default | Description |
|---|---|---|
| `AI_INFRA_LLM_BACKEND` | `ollama` | `ollama`, `openai`, `claude`, or `gemini` |
| `AI_INFRA_OLLAMA_URL` | `http://localhost:11434` | Ollama server address |
| `AI_INFRA_OLLAMA_MODEL` | `qwen2.5-coder:7b` | Which Ollama model to use |
| `AI_INFRA_OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `AI_INFRA_OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API base URL |
| `AI_INFRA_CLAUDE_MODEL` | `claude-opus-5-5` | Claude model |
| `AI_INFRA_CLAUDE_FALLBACKS` | `true` | Let the Claude API retry a declined request on its recommended fallback model |
| `AI_INFRA_GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model |
| `AI_INFRA_LLM_TIMEOUT` | `300` | Request timeout in seconds |
| `AI_INFRA_LLM_MAX_TOKENS` | `16000` | Max tokens per response (Claude) |
| `AI_INFRA_LLM_MAX_RETRIES` | `2` | Retries on validation failure |

### How images flow from CI to the cluster

Services of type `app` and `worker` are built from your repo (`Dockerfile.<service>`). CI pushes each one as `<registry>/<project>/<service>:<commit-sha>` and `:latest`. The Kubernetes manifests and Helm values reference `:latest`. Each deploy step applies the manifests and then pins every deployment to the commit's image with `kubectl set image`. The Bitbucket pipeline is the exception: it only applies the manifests, so the deployments keep running `:latest`. Databases and caches use their stock images.

When there is more than one app service, the first one is served at `routing.domain` and each of the others gets its own subdomain (`<service>.<domain>`).

---

## Regenerating Safely

ai-infra records a hash of every infrastructure file it writes in `.ai-infra/state.json`. On later runs (including `fix`):

- Existing files that were never generated by the tool are skipped, even if they match the rendered output.
- Previously generated files you have edited are also skipped; unchanged generated files can be updated when the plan changes.
- Pass `--force` explicitly to overwrite existing or edited manifests. Existing `.dockerignore` files are always preserved, and output symlinks are never followed. Review skipped files before deploying, since they may not match the new plan.
- `ai-infra status` lists generated files that were modified or deleted.

---

## User Hints

After running `ai-infra init`, you'll find a `hints.yaml` file inside `.ai-infra/`. Edit it to guide model-based planning; confirm its preferences in the resulting validated model. Offline planning uses only analyzer output and ignores hints.

```yaml
# Scale for production
scale: prod

# Enable Helm chart generation
helm: true

# Provision an AWS EKS cluster via Terraform
iac_provider: aws
iac_region: us-west-2

# Generate CI/CD for GitHub Actions and GitLab
ci_providers:
  - github_actions
  - gitlab_ci

# Enable Prometheus + Grafana monitoring
monitoring: true

# Multi-tenant setup
tenants:
  - name: acme
    cpu: "4"
    memory: "8Gi"
  - name: globex
    cpu: "2"
    memory: "4Gi"
```

---

## Fix Loop

When a deployment fails, feed the logs back in:

```bash
# Preview what would change
ai-infra fix /path/to/repo --logs crash.log --dry-run

# Apply the fix
ai-infra fix /path/to/repo --logs crash.log
```

The fix loop classifies errors and proposes patches to the model. It renders all enabled targets, preflights protected manifests, and saves the model only after regeneration succeeds. A blocked or partially applied fix retains the original model for retry; `--force` can overwrite regular manifests, but never an existing `.dockerignore`. Dry-run writes no files.

| Error | Detection Pattern | Auto-Fix |
|---|---|---|
| OOM | `OOMKilled`, `Out of memory` | Doubles memory limits |
| CrashLoop | `CrashLoopBackOff` | Adds missing `depends_on` |
| Image Pull | `ImagePullBackOff` | LLM suggests fix |
| Build | `COPY failed`, `build failed` | LLM suggests fix |
| Runtime | `FATAL`, `panic`, `Traceback` | Logged for review |

---

## API Server

For programmatic access or building a frontend:

```bash
AI_INFRA_ALLOWED_ROOT="$PWD" python -m ai_infra.api.app
```

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/analyze` | Run analysis |
| `POST` | `/api/plan` | Run model planner |
| `POST` | `/api/generate` | Generate configs |
| `POST` | `/api/fix` | Run fix loop |
| `POST` | `/api/jobs/{analyze,plan,generate,fix}` | Start a job with the same JSON body as its REST endpoint; returns a stream URL |
| `GET` | `/api/stream/{job_id}` | Read-only SSE job updates (`status` → `result` → `done`, or `error`) |
| `GET` | `/health` | Health check |

The server binds to `127.0.0.1:8000` and requires a localhost Host header (`localhost`, `127.0.0.1`, or `[::1]`, with an optional port). Mutating POST requests require an HTTP(S) origin on one of those hosts, or no Origin from a loopback client only. The allowed repository and log-file root defaults to the server's working directory. Set `AI_INFRA_ALLOWED_ROOT` to another directory if needed. Resolved paths outside that root are rejected. This is a local development API, not an authenticated multi-user service.

---

## Testing

```bash
pip install -e "./ai-infra[dev]"
python -m pytest ai-infra/tests
ruff check --config ai-infra/pyproject.toml ai-infra examples
```

---

## Project Structure

```
ai-infra/
├── ai_infra/
│   ├── analyzer/       # Repository analysis (language detectors)
│   ├── planner/        # Offline and model-based planning
│   ├── generator/      # Jinja2 template rendering engine
│   ├── fix/            # Self-healing fix loop
│   ├── models/         # Pydantic schemas (the central contract)
│   ├── state/          # State management (.ai-infra/ directory)
│   ├── config/         # Settings (env var reader)
│   └── api/            # FastAPI server
├── cli/                # Typer CLI commands
└── tests/              # Test suite with fixtures and golden snapshots
```

---

## License

MIT
