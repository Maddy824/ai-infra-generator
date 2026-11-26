# AI Infrastructure Generator

Generate Docker, Docker Compose, Kubernetes, Helm, Terraform, CI/CD, and monitoring configurations from repository analysis — powered by AI planning.

## Overview

`ai-infra` is a three-phase tool:

1. **Understand** — Deterministically analyze your repository to extract raw facts (language, framework, dependencies, ports).
2. **Plan** — Produce a validated Infra Model using deterministic offline defaults or a model backend with optional user hints.
3. **Generate** — Render Jinja2 templates into Dockerfiles, docker-compose.yml, Kubernetes manifests, Helm charts, Terraform IaC, CI/CD pipelines (GitHub Actions, GitLab CI, Bitbucket, CircleCI), Prometheus/Grafana monitoring, and multi-tenant configs.

## Quick Start

### Prerequisites

- Python 3.11+
- (Optional) [Ollama](https://ollama.ai) running locally for AI planning
- (Optional) `OPENAI_API_KEY` for OpenAI / GPT models
- (Optional) `ANTHROPIC_API_KEY` for Claude models
- (Optional) `GEMINI_API_KEY` for Google Gemini models

### Installation

```bash
pip install -e ".[dev]"
```

### Usage

For a first run without a model backend:

```bash
ai-infra run /path/to/your/repo --offline
```

The generated configs are a starting point for review, and Secrets contain placeholders. Generation skips existing and hand-edited manifests unless you explicitly pass `--force`. The fix loop preflights protected manifests and retains the original model if regeneration is blocked or incomplete. Existing `.dockerignore` files are always preserved, even with force. Offline Compose publishes application ports on loopback only and keeps dependencies internal.

For step-by-step generation with a model backend:

```bash
# 1. Initialize the state directory
ai-infra init /path/to/your/repo

# 2. Analyze the repository
ai-infra analyze /path/to/your/repo

# 3. Run the AI planner (requires Ollama or Claude)
ai-infra plan /path/to/your/repo

# 4. Generate infrastructure configs
ai-infra generate /path/to/your/repo --target compose      # Docker + Compose
ai-infra generate /path/to/your/repo --target k8s          # Kubernetes manifests
ai-infra generate /path/to/your/repo --target ci           # CI/CD pipelines
ai-infra generate /path/to/your/repo --target helm         # Helm chart
ai-infra generate /path/to/your/repo --target iac          # Terraform cluster provisioning
ai-infra generate /path/to/your/repo --target monitoring   # Prometheus + Grafana
ai-infra generate /path/to/your/repo --target tenancy      # Multi-tenant namespaces
ai-infra generate /path/to/your/repo --target all          # Everything

# 5. Fix deployment failures
ai-infra fix /path/to/your/repo --logs build.log
ai-infra fix /path/to/your/repo --logs build.log --dry-run  # Preview only
```

### WSL2 (Windows)

Native Windows is not supported in v1. Use WSL2:

```bash
wsl --install -d Ubuntu-22.04
# Then install Python 3.11+ inside WSL2 and follow the Linux instructions above.
```

## Configuration

All configuration is centralized in environment variables with the `AI_INFRA_` prefix:

| Variable | Default | Description |
|---|---|---|
| `AI_INFRA_LLM_BACKEND` | `ollama` | LLM backend: `ollama`, `openai`, `claude`, or `gemini` |
| `AI_INFRA_OLLAMA_URL` | `http://localhost:11434` | Ollama API URL |
| `AI_INFRA_OLLAMA_MODEL` | `qwen2.5-coder:7b` | Ollama model name |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `AI_INFRA_OPENAI_MODEL` | `gpt-4o` | OpenAI model name |
| `AI_INFRA_OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL (Azure OpenAI, local proxies) |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `AI_INFRA_CLAUDE_MODEL` | `claude-opus-5-5` | Claude model name |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `AI_INFRA_GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name |
| `AI_INFRA_LLM_TIMEOUT` | `300` | LLM request timeout (seconds) |
| `AI_INFRA_LLM_MAX_TOKENS` | `16000` | Max tokens per response (Claude) |
| `AI_INFRA_CLAUDE_FALLBACKS` | `true` | Retry a declined request on the recommended fallback model |
| `AI_INFRA_LLM_MAX_RETRIES` | `2` | Max retries on validation failure |

### Backend examples

```bash
# Ollama (default — no API key needed, runs locally)
ollama pull qwen2.5-coder:7b
ai-infra plan /path/to/repo

# OpenAI
AI_INFRA_LLM_BACKEND=openai OPENAI_API_KEY=sk-... ai-infra plan /path/to/repo

# Claude
AI_INFRA_LLM_BACKEND=claude ANTHROPIC_API_KEY=sk-ant-... ai-infra plan /path/to/repo

# Gemini
AI_INFRA_LLM_BACKEND=gemini GEMINI_API_KEY=AI... ai-infra plan /path/to/repo

# Azure OpenAI (uses OpenAI-compatible endpoint)
AI_INFRA_LLM_BACKEND=openai OPENAI_API_KEY=... AI_INFRA_OPENAI_BASE_URL=https://my-resource.openai.azure.com/openai/deployments/gpt-4o ai-infra plan /path/to/repo
```

## User Hints

Edit `.ai-infra/hints.yaml` to guide model-based planning:

```yaml
scale: prod
needs_gpu: true
registry: ghcr.io
cluster_auth: aws
helm: true
iac_provider: aws
iac_region: us-west-2
ci_providers: [github_actions, gitlab_ci]
monitoring: true
tenants: [acme, globex]
```

Hints guide model-based planning but are not enforced overrides; `--offline` uses analyzer output alone.

## State Directory

```
.ai-infra/
├── analyzer_output.json   # Raw facts from repo analysis
├── infra_model.v1.json    # Validated infrastructure model
├── hints.yaml             # Optional user guidance
├── plan.md                # Human-readable plan summary
├── state.json             # Dirty/clean tracking for incremental runs
└── logs/                  # Fix loop audit logs
```

## Supported Languages

| Language | Detector | Frameworks |
|---|---|---|
| Python | `requirements.txt`, `pyproject.toml` | FastAPI, Flask, Django |
| Node.js | `package.json` | Express, Next.js, NestJS, Koa, Fastify |
| Go | `go.mod` | Gin, Echo, Fiber, Chi, Gorilla/mux |

## Dependency → Service Inference

| Dependency | Inferred Service |
|---|---|
| `psycopg2`, `asyncpg`, `pg` | PostgreSQL |
| `redis`, `aioredis`, `ioredis` | Redis |
| `celery`, `bullmq` | Worker queue |
| `boto3`, `@aws-sdk/*` | S3 / AWS |
| `pymongo`, `mongoose` | MongoDB |

## API Server

Start the FastAPI backend for Web UI integration:

```bash
AI_INFRA_ALLOWED_ROOT="$PWD" python -m ai_infra.api.app
```

The server binds to `127.0.0.1:8000`, requires a localhost Host header and an allowed localhost Origin on mutating POST requests (or no Origin from loopback clients only), and rejects repository and log paths outside `AI_INFRA_ALLOWED_ROOT` (the working directory by default).

Endpoints:
- `POST /api/analyze` — Run analysis
- `POST /api/plan` — Run planner
- `POST /api/generate` — Generate configs
- `POST /api/fix` — Run fix loop
- `POST /api/jobs/{analyze,plan,generate,fix}` — Start a job using the corresponding REST endpoint body; returns a stream URL
- `GET /api/stream/{job_id}` — Read-only SSE progress and result
- `GET /health` — Health check

## Generation Targets

| Target | Output | Enabled By |
|---|---|---|
| `compose` | Dockerfiles + docker-compose.yml | Always |
| `k8s` | Deployment, Service, Ingress, HPA, ConfigMap, Secret | Always |
| `ci` | CI/CD pipelines | `cicd.providers` list |
| `helm` | Chart.yaml, values.yaml, templates/ | `helm.enabled: true` |
| `iac` | Terraform main.tf (EKS/GKE/AKS) | `iac.enabled: true` |
| `monitoring` | ServiceMonitor, alerting rules, Grafana dashboard | `monitoring.enabled: true` |
| `tenancy` | Namespace, ResourceQuota, NetworkPolicy per tenant | `multi_tenancy.enabled: true` |
| `all` | All of the above | — |

## CI/CD Providers

| Provider | Config File | Key |
|---|---|---|
| GitHub Actions | `.github/workflows/deploy.yml` | `github_actions` |
| GitLab CI | `.gitlab-ci.yml` | `gitlab_ci` |
| Bitbucket Pipelines | `bitbucket-pipelines.yml` | `bitbucket_pipelines` |
| CircleCI | `.circleci/config.yml` | `circleci` |

## Cloud Providers (IaC)

| Provider | Cluster Type | Default Instance |
|---|---|---|
| AWS | EKS | `t3.medium` |
| GCP | GKE | `e2-medium` |
| Azure | AKS | `Standard_D2s_v3` |

## Testing

```bash
pytest
pytest --cov=ai_infra
```

## License

MIT
