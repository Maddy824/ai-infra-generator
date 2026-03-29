# AI Infrastructure Generator

A CLI tool that analyzes your repository, uses AI to plan the ideal infrastructure, and generates production-ready configs — Dockerfiles, Compose, Kubernetes manifests, Helm charts, Terraform, CI/CD pipelines, monitoring, and multi-tenant isolation.

Point it at a repo. Get infrastructure.

---

## How It Works

The tool follows a three-phase pipeline:

1. **Understand** — Scans your codebase deterministically. No AI. Extracts language, framework, ports, and dependency information from files like `requirements.txt`, `package.json`, or `go.mod`.

2. **Plan** — Sends the analysis + your optional hints to an LLM (Ollama runs locally by default — no API keys needed). The LLM produces a structured infrastructure plan. If the plan is invalid, it automatically retries with the validation error injected back into the prompt.

3. **Generate** — Renders Jinja2 templates using the validated plan. Pure deterministic output. No LLM calls in this phase.

---

## Quick Start

**Requirements:** Python 3.11+. Optionally, [Ollama](https://ollama.ai) for local AI planning.

```bash
cd ai-infra
pip install -e ".[dev]"
```

Then run the four commands in order:

```bash
# 1. Set up the state directory
ai-infra init /path/to/your/repo

# 2. Analyze the codebase (no AI)
ai-infra analyze /path/to/your/repo

# 3. Let AI plan the infrastructure
ai-infra plan /path/to/your/repo

# 4. Generate config files
ai-infra generate /path/to/your/repo --target all
```

That's it. Your repo now has Dockerfiles, Compose, Kubernetes manifests, and more.

---

## What It Generates

| Target | Output | When |
|---|---|---|
| `compose` | Dockerfiles + docker-compose.yml | Always |
| `k8s` | Deployments, Services, Ingress, HPA, ConfigMaps, Secrets | Always |
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

Dependencies like `psycopg2`, `redis`, `celery`, `boto3`, and `pymongo` are automatically mapped to their corresponding infrastructure services (PostgreSQL, Redis, worker queues, S3, MongoDB).

---

## Configuration

Everything is controlled through environment variables prefixed with `AI_INFRA_`. No config files required.

### LLM Backends

The default backend is **Ollama**, which runs locally and needs no API key.

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
| `AI_INFRA_CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model |
| `AI_INFRA_GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model |
| `AI_INFRA_LLM_TIMEOUT` | `30` | Request timeout in seconds |
| `AI_INFRA_LLM_MAX_RETRIES` | `2` | Retries on validation failure |

---

## User Hints

After running `ai-infra init`, you'll find a `hints.yaml` file inside `.ai-infra/`. Edit it to steer the AI planner. Hints always override analyzer output.

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

## Fix Loop (Self-Healing)

When a deployment fails, feed the logs back in:

```bash
# Preview what would change
ai-infra fix /path/to/repo --logs crash.log --dry-run

# Apply the fix
ai-infra fix /path/to/repo --logs crash.log
```

The fix loop classifies errors and applies targeted patches:

| Error | Detection Pattern | Auto-Fix |
|---|---|---|
| OOM | `OOMKilled`, `Out of memory` | Doubles memory limits |
| CrashLoop | `CrashLoopBackOff` | Adds missing `depends_on` |
| Image Pull | `ImagePullBackOff` | LLM suggests fix |
| Build | `COPY failed`, `build failed` | LLM suggests fix |
| Runtime | `FATAL`, `panic`, `Traceback` | LLM suggests fix |

---

## API Server

For programmatic access or building a frontend:

```bash
uvicorn ai_infra.api.app:app --reload --port 8000
```

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/analyze` | Run analysis |
| `POST` | `/api/plan` | Run AI planner |
| `POST` | `/api/generate` | Generate configs |
| `POST` | `/api/fix` | Run fix loop |
| `GET` | `/api/stream/*` | SSE streaming variants |
| `GET` | `/health` | Health check |

---

## Testing

```bash
cd ai-infra
pytest                     # Run all tests
pytest --cov=ai_infra      # With coverage
```

---

## Project Structure

```
ai-infra/
├── ai_infra/
│   ├── analyzer/       # Repository analysis (language detectors)
│   ├── planner/        # AI planning (LLM integration + prompts)
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
