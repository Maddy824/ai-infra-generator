# AI Infrastructure Generator — Comprehensive Usage Guide

This guide walks you through every feature of `ai-infra` with detailed examples, explanations of every method, and real-world workflows.

---

## Table of Contents

1. [Installation](#1-installation)
2. [Your First Run (5 Minutes)](#2-your-first-run)
3. [Command Reference](#3-command-reference)
4. [Configuration Reference](#4-configuration-reference)
5. [User Hints (hints.yaml)](#5-user-hints)
6. [Generation Targets](#6-generation-targets)
7. [The Fix Loop (Self-Healing)](#7-the-fix-loop)
8. [API Server](#8-api-server)
9. [Adding a New Language Detector](#9-adding-a-new-language-detector)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Installation

### System Requirements

| Requirement | Minimum |
|---|---|
| Python | 3.11+ |
| OS | Linux, macOS, Windows (WSL2) |
| Disk | ~50 MB for the tool itself |

### Step-by-step

```bash
# Clone the repository
git clone https://github.com/your-username/ai-infra-generator.git
cd ai-infra-generator/ai-infra

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify installation
ai-infra --help
```

### Install Ollama (Optional — for local AI planning)

Ollama lets you run AI models locally for free. No API keys, no internet needed.

```bash
# macOS / Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the default model
ollama pull qwen2.5-coder:7b

# Verify it's running
curl http://localhost:11434/api/tags
```

> **Tip:** You can use any Ollama model. Larger models (like `llama3:70b`) give better results but need more RAM. The default `qwen2.5-coder:7b` works well on 8GB+ machines.

---

## 2. Your First Run

Let's analyze a FastAPI project end-to-end.

### Step 1: Initialize

```bash
ai-infra init /path/to/my-fastapi-app
```

**What happens:**
- Creates `.ai-infra/` directory inside your repo
- Generates a starter `hints.yaml` with commented examples
- Creates an empty `state.json` for tracking regeneration

**Output:**
```
✔ Initialized .ai-infra/ in /path/to/my-fastapi-app
  Created hints.yaml — edit this to customize your infrastructure
```

### Step 2: Analyze

```bash
ai-infra analyze /path/to/my-fastapi-app
```

**What happens (no AI involved):**
1. Scans for `requirements.txt`, `package.json`, `go.mod`
2. Detects language (`python`) and framework (`fastapi`)
3. Reads your source code to find the entrypoint (`main.py`) and port (`8000`)
4. Maps dependencies to infrastructure services:
   - `psycopg2` → **PostgreSQL**
   - `redis` → **Redis**
   - `celery` → **Background Worker**
5. Checks for existing `Dockerfile` or `docker-compose.yml`
6. Writes all facts to `.ai-infra/analyzer_output.json`

**Output:**
```
Analyzing repository: /path/to/my-fastapi-app
Analysis complete
  Language:  python
  Framework: fastapi
  Services:  postgres, redis, worker
```

### Step 3: Plan (AI)

```bash
ai-infra plan /path/to/my-fastapi-app
```

**What happens:**
1. Reads `analyzer_output.json` (from Step 2) and `hints.yaml`
2. Sends both to the LLM (Ollama by default) with the full Pydantic schema
3. LLM returns a JSON infrastructure plan
4. Pydantic validates the response — if invalid, automatically retries up to 3 times
5. Writes the validated model to `.ai-infra/infra_model.v1.json`
6. Generates a human-readable summary at `.ai-infra/plan.md`

**Output:**
```
Planning infrastructure for /path/to/my-fastapi-app
  Using backend: ollama (qwen2.5-coder:7b)
  ✔ Plan generated successfully
  Services: web, postgres, redis, worker
  Scale: dev (1 replica each)
  Plan saved to .ai-infra/plan.md
```

### Step 4: Generate

```bash
# Generate everything
ai-infra generate /path/to/my-fastapi-app --target all

# Or generate specific targets
ai-infra generate /path/to/my-fastapi-app --target compose    # Docker only
ai-infra generate /path/to/my-fastapi-app --target k8s        # Kubernetes only
```

**What happens:**
1. Reads `infra_model.v1.json` (from Step 3)
2. Routes to the appropriate generators based on `--target`
3. Renders Jinja2 templates with the validated model data
4. Writes files to the repo (skips unchanged files for speed)

**Output:**
```
Generating infrastructure (target: all)
  ✔ Dockerfile.web
  ✔ Dockerfile.worker
  ✔ docker-compose.yml
  ✔ k8s/deployment-web.yaml
  ✔ k8s/deployment-postgres.yaml
  ✔ k8s/service-web.yaml
  ✔ k8s/ingress.yaml
  ✔ .github/workflows/deploy.yml
  Generated 8 files
```

---

## 3. Command Reference

### `ai-infra init [REPO_PATH]`

| Argument | Default | Description |
|---|---|---|
| `REPO_PATH` | `.` (current directory) | Path to the repository |

**Behavior:**
- Creates `.ai-infra/` with `state.json`, `hints.yaml`, and `logs/` subdirectory.
- Safe to re-run: won't overwrite existing files.

---

### `ai-infra analyze [REPO_PATH]`

| Argument | Default | Description |
|---|---|---|
| `REPO_PATH` | `.` | Path to the repository |

**Behavior:**
- Discovers all applicable detectors (Python, Node, Go).
- Runs every matching detector and merges results.
- Writes `analyzer_output.json` to `.ai-infra/`.
- **Does not use AI** — fully deterministic.

**Requires:** `ai-infra init` has been run.

---

### `ai-infra plan [REPO_PATH]`

| Argument | Default | Description |
|---|---|---|
| `REPO_PATH` | `.` | Path to the repository |

**Behavior:**
- Reads `analyzer_output.json` + `hints.yaml`.
- Calls the configured LLM backend.
- Validates LLM output against the Pydantic InfraModel schema.
- On validation failure: sends the error back to the LLM for automatic repair.
- Writes `infra_model.v1.json` and `plan.md`.

**Requires:** `ai-infra analyze` has been run.

---

### `ai-infra generate [REPO_PATH]`

| Argument | Default | Description |
|---|---|---|
| `REPO_PATH` | `.` | Path to the repository |
| `--target` | `compose` | What to generate (see table below) |
| `--force` | `false` | Regenerate all files even if unchanged |

**Available targets:**

| Target | Generates |
|---|---|
| `compose` | Dockerfiles + docker-compose.yml |
| `k8s` | Kubernetes YAML manifests |
| `ci` | CI/CD pipeline configs |
| `helm` | Helm chart (requires `helm.enabled: true`) |
| `iac` | Terraform files (requires `iac.enabled: true`) |
| `monitoring` | Prometheus + Grafana (requires `monitoring.enabled: true`) |
| `tenancy` | Multi-tenant configs (requires `multi_tenancy.enabled: true`) |
| `all` | All of the above |

**Requires:** `ai-infra plan` has been run.

---

### `ai-infra fix [REPO_PATH]`

| Argument | Default | Description |
|---|---|---|
| `REPO_PATH` | `.` | Path to the repository |
| `--logs` | (required) | Path to the log file containing deployment errors |
| `--dry-run` | `false` | Preview changes without writing to disk |

**Behavior:**
- Parses the log file using regex patterns to classify errors.
- For OOM errors: doubles memory limits automatically.
- For CrashLoop: fixes missing `depends_on` entries.
- For complex errors (image pull, build): calls the LLM for a fix.
- Regenerates only affected files.

---

## 4. Configuration Reference

All settings use the `AI_INFRA_` prefix as environment variables.

### LLM Backend

| Variable | Default | Options |
|---|---|---|
| `AI_INFRA_LLM_BACKEND` | `ollama` | `ollama`, `openai`, `claude`, `gemini` |
| `AI_INFRA_LLM_TIMEOUT` | `30` | Seconds before timeout |
| `AI_INFRA_LLM_MAX_RETRIES` | `2` | Retries on validation failure |

### Ollama (Local AI — Free)

| Variable | Default |
|---|---|
| `AI_INFRA_OLLAMA_URL` | `http://localhost:11434` |
| `AI_INFRA_OLLAMA_MODEL` | `qwen2.5-coder:7b` |

### OpenAI

| Variable | Default |
|---|---|
| `OPENAI_API_KEY` | _(required)_ |
| `AI_INFRA_OPENAI_MODEL` | `gpt-4o` |
| `AI_INFRA_OPENAI_BASE_URL` | `https://api.openai.com/v1` |

### Claude (Anthropic)

| Variable | Default |
|---|---|
| `ANTHROPIC_API_KEY` | _(required)_ |
| `AI_INFRA_CLAUDE_MODEL` | `claude-sonnet-4-20250514` |

### Gemini (Google)

| Variable | Default |
|---|---|
| `GEMINI_API_KEY` | _(required)_ |
| `AI_INFRA_GEMINI_MODEL` | `gemini-2.0-flash` |

### Analyzer

| Variable | Default | Description |
|---|---|---|
| `AI_INFRA_ANALYZER_MAX_FILE_SIZE` | `1048576` | Skip files larger than this (bytes) |
| `AI_INFRA_ANALYZER_TIMEOUT` | `60` | Timeout for analysis (seconds) |

---

## 5. User Hints

After running `ai-infra init`, edit `.ai-infra/hints.yaml` to override AI decisions.

### Example: Basic Customization

```yaml
# Scale up for production
scale: prod

# Use a specific cloud registry
registry: ghcr.io/my-org

# Request GPU nodes
needs_gpu: true
```

### Example: Enable Enterprise Features

```yaml
# Enable Helm chart generation
helm: true

# Enable Terraform for AWS EKS
iac_provider: aws
iac_region: us-east-1

# Enable monitoring
monitoring: true

# Enable multi-tenancy with specific tenants
tenants:
  - name: acme
    cpu: "4"
    memory: "8Gi"
  - name: globex
    cpu: "2"
    memory: "4Gi"

# Generate CI/CD for multiple providers
ci_providers:
  - github_actions
  - gitlab_ci
```

### Example: Override Ingress

```yaml
# Use Traefik instead of nginx
ingress_controller: traefik
ingress_class_name: traefik
tls_enabled: true
```

**Rule:** Hints always win over analyzer output. If you set `scale: prod` in hints, the AI planner will always use production scaling regardless of what it otherwise would have chosen.

---

## 6. Generation Targets

### Docker & Compose (`--target compose`)

Generates per-language, multi-stage Dockerfiles and a complete `docker-compose.yml`.

**What you get:**
- `Dockerfile.web` — Multi-stage build for your app
- `Dockerfile.worker` — If a background worker was detected
- `docker-compose.yml` — All services wired with `depends_on`, ports, volumes, and environment variables

**Run it:**
```bash
docker-compose up --build
```

---

### Kubernetes (`--target k8s`)

Generates deployment-ready manifests for any K8s cluster.

**What you get:**
- `k8s/deployment-{service}.yaml` — One per service
- `k8s/service-{service}.yaml` — ClusterIP services
- `k8s/ingress.yaml` — Ingress with TLS (if enabled)
- `k8s/hpa-{service}.yaml` — HorizontalPodAutoscaler (prod/heavy scale)
- `k8s/configmap.yaml` — Non-secret environment variables
- `k8s/secret.yaml` — Secret placeholders

**Apply it:**
```bash
kubectl apply -f k8s/
```

---

### CI/CD (`--target ci`)

Generates pipeline configs for your CI/CD provider.

| Provider | Output File |
|---|---|
| GitHub Actions | `.github/workflows/deploy.yml` |
| GitLab CI | `.gitlab-ci.yml` |
| Bitbucket Pipelines | `bitbucket-pipelines.yml` |
| CircleCI | `.circleci/config.yml` |

Enable multiple providers by setting `ci_providers` in hints.yaml.

---

### Helm Charts (`--target helm`)

**Requires:** `helm.enabled: true` in the InfraModel (set via hints: `helm: true`).

**What you get:**
- `helm/Chart.yaml` — Chart metadata
- `helm/values.yaml` — Default values
- `helm/templates/` — Templated K8s manifests

**Install it:**
```bash
helm install my-release ./helm
```

---

### Terraform IaC (`--target iac`)

**Requires:** `iac.enabled: true` (set via hints: `iac_provider: aws`).

**What you get:**
- `terraform/main.tf` — Managed K8s cluster (EKS, GKE, or AKS)

**Provision it:**
```bash
cd terraform
terraform init
terraform plan
terraform apply
```

---

### Monitoring (`--target monitoring`)

**Requires:** `monitoring.enabled: true` (set via hints: `monitoring: true`).

**What you get:**
- `monitoring/servicemonitor-{service}.yaml` — Prometheus ServiceMonitors
- `monitoring/alerting-rules.yaml` — Alert rules (CPU, memory, restarts)
- `monitoring/grafana-dashboard.json` — Pre-built Grafana dashboard

**Apply it:**
```bash
kubectl apply -f monitoring/
```

---

### Multi-Tenancy (`--target tenancy`)

**Requires:** `multi_tenancy.enabled: true` (set via hints: `tenants: [acme, globex]`).

**What you get:**
- `tenancy/{tenant}/namespace.yaml` — Isolated namespace
- `tenancy/{tenant}/resource-quota.yaml` — CPU/memory quotas
- `tenancy/{tenant}/network-policy.yaml` — Inter-tenant network isolation

---

## 7. The Fix Loop

When a deployment fails, feed the logs back to `ai-infra`:

```bash
# Capture kubectl logs
kubectl logs deployment/web > crash.log

# Let ai-infra diagnose and fix
ai-infra fix /path/to/repo --logs crash.log --dry-run
```

### Error Classification

| Error Type | Detection | Auto-Fix |
|---|---|---|
| **OOM** | `OOMKilled`, `Out of memory` | Doubles `memory_limits` |
| **CrashLoop** | `CrashLoopBackOff` | Adds missing `depends_on` |
| **Image Pull** | `ImagePullBackOff`, `ErrImagePull` | LLM suggests image fix |
| **Build** | `COPY failed`, `build failed` | LLM suggests Dockerfile fix |
| **Runtime** | `FATAL`, `panic`, `Traceback` | LLM suggests config fix |

### Dry Run vs Apply

```bash
# Preview changes (safe — nothing is written)
ai-infra fix . --logs crash.log --dry-run
# Output:
#   [web] sizing.memory_limits: '512Mi' -> '1024Mi'

# Apply the fix
ai-infra fix . --logs crash.log
# Output:
#   ✔ Patched infra_model.v1.json
#   ✔ Regenerated k8s/deployment-web.yaml
```

---

## 8. API Server

For programmatic access or to build a Web UI:

```bash
# Start the server
uvicorn ai_infra.api.app:app --reload --port 8000
```

### REST Endpoints

```bash
# Analyze
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo"}'

# Plan
curl -X POST http://localhost:8000/api/plan \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo"}'

# Generate
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo", "target": "all"}'

# Fix
curl -X POST http://localhost:8000/api/fix \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo", "log_path": "/path/to/crash.log"}'
```

### SSE Streaming

For real-time progress updates, use the streaming endpoints:

```javascript
const eventSource = new EventSource(
  'http://localhost:8000/api/stream/generate?repo_path=/path/to/repo&target=all'
);

eventSource.addEventListener('status', (e) => {
  console.log('Status:', JSON.parse(e.data));
});

eventSource.addEventListener('result', (e) => {
  console.log('Files:', JSON.parse(e.data));
});

eventSource.addEventListener('done', () => {
  eventSource.close();
});
```

---

## 9. Adding a New Language Detector

Adding support for a new language (e.g., Ruby, Rust, Java) requires exactly **one file**.

### Step 1: Create the Detector

```python
# ai_infra/analyzer/detectors/ruby.py

from pathlib import Path
from ai_infra.analyzer.detectors.base import BaseDetector

class RubyDetector(BaseDetector):
    def matches(self, repo_path: Path) -> bool:
        return (repo_path / "Gemfile").is_file()

    def detect(self, repo_path: Path) -> dict | None:
        if not self.matches(repo_path):
            return None
        # Parse Gemfile, detect Rails/Sinatra, find ports, etc.
        return {
            "language": "ruby",
            "framework": "rails",
            "entrypoint": "config.ru",
            "detected_port": 3000,
            "dependencies": {
                "raw": ["rails", "pg", "redis"],
                "inferred_services": ["postgres", "redis"],
            },
            "existing_infra_files": [],
        }
```

### Step 2: Done

That's it. The analyzer will automatically discover and run your detector via `pkgutil.iter_modules`. No registration code, no config changes.

---

## 10. Troubleshooting

### "Cannot connect to Ollama"

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama if it's not running
ollama serve

# Pull a model if you don't have one
ollama pull qwen2.5-coder:7b
```

### "No infra model found. Run plan first."

Commands must be run in order: `init` → `analyze` → `plan` → `generate`. You can't skip steps.

### "Validation failed after 3 attempts"

The LLM is struggling to produce valid JSON. Try:
1. Use a more capable model: `AI_INFRA_OLLAMA_MODEL=llama3:8b`
2. Switch to a cloud backend: `AI_INFRA_LLM_BACKEND=openai`
3. Increase retries: `AI_INFRA_LLM_MAX_RETRIES=4`

### Generated files are not changing

The generator uses hash-based caching to skip unchanged files. Use `--force` to regenerate:

```bash
ai-infra generate . --target all --force
```

### "Module not found" errors

Make sure you installed in editable mode from the `ai-infra/` directory:

```bash
cd ai-infra
pip install -e ".[dev]"
```
