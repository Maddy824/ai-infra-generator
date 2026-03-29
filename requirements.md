# Requirements Document

## Introduction

The AI Infrastructure Generator is a tool that generates Docker, Docker Compose, and Kubernetes infrastructure configurations from repository analysis. The system uses a three-phase architecture: deterministic repository analysis (Understand), AI-powered planning (Plan), and template-based configuration generation (Generate). The tool maintains state in a `.ai-infra/` directory and uses a validated Infra Model as the contract between AI planning and deterministic generation.

## Implementation Status

> **Last audited:** 2026-03-29
>
> This section tracks which requirements are fully implemented in code vs.
> partially implemented or not yet started.  Each requirement heading below
> carries a status badge.  The legend is:
>
> | Badge | Meaning |
> |-------|---------|
> | **[DONE]** | All acceptance criteria are satisfied by working, tested code. |
> | **[PARTIAL]** | Core behaviour works; specific ACs are called out as gaps. |
> | **[NOT STARTED]** | No implementation exists yet. |

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 1 | Repository Analysis | DONE | All ACs met. |
| 2 | Pluggable Detector Architecture | DONE | |
| 3 | Infra Model Schema | DONE | All sub-models, env kinds, validation. |
| 4 | AI Planning Layer | DONE | 4 LLM backends, retry, summary. |
| 5 | Docker Configuration Generation | DONE | Per-language Dockerfile branching added. |
| 6 | Kubernetes Manifest Generation | DONE | HPA now branches on workload_type. |
| 7 | State Directory Management | DONE | |
| 8 | CI/CD Pipeline Generation | DONE | 4 providers. |
| 9 | Fix Loop and Self-Healing | DONE | |
| 10 | Command-Line Interface | DONE | |
| 11 | Web User Interface | NOT STARTED | Next.js + shadcn/ui app not yet built. |
| 12 | Backend API | DONE | CORS middleware added. |
| 13 | Infra Model Serialization | DONE | |
| 14 | Testing and Validation | PARTIAL | AC2-5: per-fixture golden snapshots empty. AC6: integration tests not written. |
| 15 | LLM Integration | DONE | Ollama, Claude, OpenAI, Gemini. |
| 16 | Ingress Controller Configuration | DONE | nginx/traefik/ALB annotations added. |
| 17 | Resource Sizing and Scaling | DONE | GPU requests added to deployment template. |
| 18 | Multi-Service Dependency Management | DONE | |
| 19 | Secret and Configuration Management | PARTIAL | AC6: generated files do not yet include a secret-management README. |
| 20 | Incremental Regeneration | DONE | Generator uses `_write_if_changed` + `StateManager.mark_clean`. |
| 21 | hints.yaml Schema and Override Rules | PARTIAL | AC4: no strict schema validation on hints.yaml fields — invalid keys are silently ignored. |
| 22 | Initialization Command | DONE | |
| 23 | Helm Chart Generation | DONE | `values_overrides` now rendered. |
| 24 | Cluster Provisioning (IaC) | DONE | |
| 25 | Monitoring and Observability | DONE | |
| 26 | Multi-Tenant Control Plane | DONE | |

## Scope (v1)

The following features are fully in scope for v1:

- **Cluster provisioning** — the tool generates Terraform IaC files for managed Kubernetes clusters on AWS (EKS), GCP (GKE), and Azure (AKS). Enabled via `iac.enabled: true` in the Infra Model.
- **Helm charts** — v1 generates full Helm chart directories (Chart.yaml, values.yaml, templates/) alongside raw Kubernetes YAML. Enabled via `helm.enabled: true`.
- **Multi-tenant control plane** — the tool supports namespace-isolated multi-tenant deployments with per-tenant ResourceQuotas and NetworkPolicies. Enabled via `multi_tenancy.enabled: true`.
- **GitLab CI, Bitbucket Pipelines, CircleCI** — CI/CD generation supports GitHub Actions, GitLab CI, Bitbucket Pipelines, and CircleCI. Configured via `cicd.providers` list.
- **Runtime monitoring and observability** — the tool generates Prometheus ServiceMonitors, alerting rules, and Grafana dashboard JSON. Enabled via `monitoring.enabled: true`.

## Glossary

- **Analyzer**: Component that deterministically extracts raw facts from a repository
- **Planner**: AI-powered component that reasons about raw facts to produce a validated Infra Model
- **Generator**: Component that uses Jinja2 templates to produce infrastructure configurations from the Infra Model
- **Infra_Model**: Pydantic-validated schema serving as the contract between Planner and Generator
- **Detector**: Pluggable module that analyzes specific languages or frameworks
- **State_Directory**: The `.ai-infra/` directory containing analyzer output, infra model, hints, and logs
- **Hints_File**: User-provided YAML file (`hints.yaml`) containing overrides and preferences
- **Fix_Loop**: Iterative repair mechanism that parses deployment logs and patches the Infra Model
- **CLI**: Command-line interface built with Typer
- **Web_UI**: Browser-based interface built with Next.js
- **Backend_API**: FastAPI service providing endpoints for both CLI and Web_UI

## Project Structure

The following directory structure defines the organization of the AI Infrastructure Generator codebase:

```
ai-infra/
├── ai_infra/                        # main package (underscore for valid Python import)
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py              # LLM backend, timeouts, state dir path, all env-var reads
│   ├── analyzer/
│   │   ├── __init__.py
│   │   ├── core.py                  # orchestrates detectors, writes analyzer_output.json
│   │   └── detectors/
│   │       ├── __init__.py
│   │       ├── base.py              # detector interface (ABC)
│   │       ├── python.py
│   │       ├── node.py
│   │       └── go.py
│   ├── planner/
│   │   ├── __init__.py
│   │   ├── planner.py               # LLM orchestration, retry logic
│   │   └── prompts.py               # all prompt templates centralized
│   ├── generator/
│   │   ├── __init__.py
│   │   ├── generator.py             # orchestrates template rendering
│   │   └── templates/
│   │       ├── dockerfile/
│   │       ├── compose/
│   │       ├── k8s/
│   │       ├── ci/                  # GitHub Actions, GitLab CI, Bitbucket, CircleCI
│   │       ├── helm/                # Chart.yaml, values.yaml, templates/
│   │       ├── iac/                 # Terraform: aws/, gcp/, azure/
│   │       ├── monitoring/          # ServiceMonitor, alerting rules, Grafana dashboard
│   │       └── tenancy/             # namespace, resource-quota, network-policy
│   ├── models/
│   │   ├── __init__.py
│   │   └── infra_model.py           # Pydantic schema, single source of truth
│   ├── state/
│   │   ├── __init__.py
│   │   └── state_manager.py         # atomic writes, dirty/clean markers, state.json
│   ├── fix/
│   │   ├── __init__.py
│   │   └── fix_loop.py              # log parser, error schema, patch logic
│   └── api/
│       ├── __init__.py
│       └── app.py                   # FastAPI app, SSE endpoints
├── cli/
│   ├── __init__.py
│   └── main.py                      # Typer entry point, all commands
├── tests/
│   ├── conftest.py                  # shared fixtures, pytest config
│   ├── analyzer/
│   │   ├── __init__.py
│   │   └── test_detectors.py
│   ├── planner/
│   │   ├── __init__.py
│   │   └── test_planner.py
│   ├── generator/
│   │   ├── __init__.py
│   │   └── test_generator.py
│   ├── fix/
│   │   ├── __init__.py
│   │   └── test_fix_loop.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── test_infra_model.py      # validation, round-trip, rejection scenarios
│   ├── fixtures/                    # fixture repos (FastAPI, Express, Django, Go)
│   │   ├── fastapi_app/
│   │   ├── express_app/
│   │   ├── django_app/
│   │   └── go_app/
│   └── golden/                      # expected output snapshots per fixture
│       ├── fastapi_app/
│       ├── express_app/
│       ├── django_app/
│       └── go_app/
├── pyproject.toml                   # dependencies, build config, pytest config
└── README.md
```

### Key Architectural Principles

1. **Centralized Configuration**: `settings.py` is the only place that reads environment variables or sets defaults for LLM backend, timeout values, and `.ai-infra/` path. Every other module imports from `ai_infra.config.settings` — no scattered `os.getenv()` calls elsewhere. This makes configuration testable and swappable in one place.

2. **Shared Test Fixtures**: `conftest.py` at the tests root holds shared pytest fixtures — the loaded fixture repos, a temporary state directory, a mock LLM backend. Subfolders inherit it automatically.

3. **Golden Test Pattern**: `golden/` mirrors `fixtures/` exactly. For every fixture repo there is a corresponding golden directory containing the expected Dockerfile, docker-compose.yml, and K8s manifests. When a generator test runs against `fastapi_app/`, it compares output against `golden/fastapi_app/`. This makes regressions immediately obvious.

## Non-Functional Requirements

### Performance

- THE System SHALL complete repository analysis for repos up to 500 MB within 60 seconds on standard hardware (4-core CPU, 8 GB RAM).
- THE System SHALL complete Dockerfile and docker-compose generation within 10 seconds after a validated Infra Model exists (excluding LLM calls).
- THE Planner SHALL enforce a 30-second timeout per LLM call. On timeout, THE System SHALL retry once, then return a descriptive error.
- THE Analyzer SHALL not load or process binary files (images, compiled artifacts). Files over 1 MB SHALL be skipped during dependency scanning.

### Reliability

- THE System SHALL use atomic writes (write to a temp file, then rename) when updating any file in `.ai-infra/` to prevent partial writes or corruption on failure.
- WHEN any command fails mid-execution, THE System SHALL leave the State_Directory in its last known valid state. It SHALL NOT write partial Infra Model files.
- THE System SHALL validate `.ai-infra/infra_model.v1.json` on read at the start of every command that depends on it, and fail fast with a descriptive error if the file is corrupt or schema-invalid.
- WHEN any configured LLM backend is unavailable or unreachable, THE System SHALL fail immediately with a clear error message identifying the backend and SHALL NOT write any partial Infra_Model files to the State_Directory.

### Operating System Support

- THE System is primarily designed and tested for Linux (Ubuntu 22.04+).
- THE System SHALL run on macOS (12+) without modification.
- Windows users SHALL run the tool via WSL2 (Windows Subsystem for Linux). Native Windows execution is not supported in v1. The README SHALL include WSL2 setup guidance.
- All generated infrastructure files (Dockerfile, compose, K8s manifests) target Linux containers regardless of the host OS used to generate them.

## Requirements

### Requirement 1: Repository Analysis [DONE]

**User Story:** As a developer, I want the system to analyze my repository structure, so that infrastructure can be generated based on actual project characteristics.

#### Acceptance Criteria

1. WHEN a repository path is provided, THE Analyzer SHALL extract language, framework, entrypoint, and detected ports into analyzer_output.json
2. WHEN a repository contains `requirements.txt` or `pyproject.toml`, THE Analyzer SHALL detect Python dependencies and framework
3. WHEN a repository contains `package.json`, THE Analyzer SHALL detect Node.js dependencies and framework
4. WHEN a repository contains `go.mod`, THE Analyzer SHALL detect Go version and key packages
5. WHEN a repository contains an existing `Dockerfile`, THE Analyzer SHALL extract port, base image, and entrypoint hints
6. THE Analyzer SHALL map infrastructure dependencies to inferred services deterministically without LLM calls
7. WHEN `psycopg2` or `asyncpg` is detected, THE Analyzer SHALL infer PostgreSQL service requirement
8. WHEN `redis` or `aioredis` is detected, THE Analyzer SHALL infer Redis service requirement
9. WHEN `celery` or `bullmq` is detected, THE Analyzer SHALL infer worker queue requirement
10. WHEN `boto3` is detected, THE Analyzer SHALL infer S3 or AWS service requirement
11. WHEN `pymongo` is detected, THE Analyzer SHALL infer MongoDB service requirement
12. THE Analyzer SHALL write output to `.ai-infra/analyzer_output.json` in the repository root

### Requirement 2: Pluggable Detector Architecture [DONE]

**User Story:** As a maintainer, I want detectors to be pluggable modules, so that new language support can be added without modifying core engine code.

#### Acceptance Criteria

1. THE Analyzer SHALL load detectors as separate modules
2. WHEN a new detector module is added, THE Analyzer SHALL discover and use it without core engine modifications
3. THE Detector SHALL implement a standard interface for language and framework detection
4. WHEN multiple detectors match a repository, THE Analyzer SHALL execute all matching detectors
5. THE Analyzer SHALL merge detector outputs into a single analyzer_output.json file

### Requirement 3: Infra Model Schema Definition [DONE]

**User Story:** As a system architect, I want a strict contract between AI planning and generation, so that invalid configurations never reach the template layer.

#### Acceptance Criteria

1. THE Infra_Model SHALL define version, project_name, routing, capabilities, services, cluster_assumptions, helm, iac, cicd, monitoring, and multi_tenancy fields
2. THE Infra_Model SHALL validate all fields using Pydantic at runtime
3. WHEN Infra_Model validation fails, THE System SHALL reject the model and return a descriptive error
4. THE Infra_Model SHALL support three environment variable kinds: literal, ref, and secret
5. THE Infra_Model SHALL define service types: app, database, cache, and worker
6. THE Infra_Model SHALL define scale profiles: dev, prod, and heavy
7. THE Infra_Model SHALL define workload types: latency-sensitive, batch, background, and api
8. THE Infra_Model SHALL include version field for schema evolution
9. THE Infra_Model SHALL be serialized to `.ai-infra/infra_model.v1.json`

### Requirement 4: AI Planning Layer [DONE]

**User Story:** As a developer, I want AI to reason about my project's infrastructure needs, so that implicit dependencies and sizing are handled intelligently.

#### Acceptance Criteria

1. WHEN the plan command is executed, THE Planner SHALL read analyzer_output.json and hints.yaml
2. WHEN the plan command is executed, THE Planner SHALL produce a validated infra_model.json
3. WHEN Celery is detected without Redis in dependencies, THE Planner SHALL add Redis service with appropriate depends_on linkage
4. WHEN GPU hint is provided in hints.yaml, THE Planner SHALL set needs_gpu to true in capabilities block
5. WHEN video streaming signals are detected, THE Planner SHALL increase memory limits in sizing block
6. WHEN Pydantic validation fails on LLM output, THE Planner SHALL retry with schema error feedback
7. WHEN Pydantic validation fails after retry limit, THE Planner SHALL return a human-readable error message
8. THE Planner SHALL write a human-readable plan summary to `.ai-infra/plan.md`
9. THE Planner SHALL support Ollama for local LLM execution
10. THE Planner SHALL support Claude API for complex planning scenarios
11. THE Planner SHALL centralize all LLM prompts and model selection in the planner module

### Requirement 5: Docker Configuration Generation [DONE]

**User Story:** As a developer, I want to generate Dockerfiles and Docker Compose configurations, so that I can containerize my application without manual configuration.

#### Acceptance Criteria

1. WHEN the generate command is executed, THE Generator SHALL produce a Dockerfile from the Infra_Model
2. WHEN the generate command is executed, THE Generator SHALL produce a docker-compose.yml from the Infra_Model
3. THE Generator SHALL use Jinja2 templates for all file generation
4. THE Generator SHALL consume only validated Infra_Model data, never raw analyzer output
5. WHEN env kind is literal, THE Generator SHALL inline the value in docker-compose.yml
6. WHEN env kind is ref, THE Generator SHALL use `${VAR}` syntax in docker-compose.yml
7. WHEN env kind is secret, THE Generator SHALL use Docker secret mount in docker-compose.yml
8. THE Generator SHALL create one service block per entry in the services array
9. THE Generator SHALL populate depends_on, ports, volumes, and environment from Infra_Model fields
10. THE Generator SHALL support Python, Node, Go, and Java base language templates
11. THE Generator SHALL derive port mapping, entrypoint, and base image from Infra_Model fields

### Requirement 6: Kubernetes Manifest Generation [DONE]

**User Story:** As a DevOps engineer, I want to generate Kubernetes manifests, so that I can deploy applications to Kubernetes clusters without manual YAML authoring.

#### Acceptance Criteria

1. WHEN the generate command is executed with --target k8s, THE Generator SHALL produce Deployment manifests
2. WHEN the generate command is executed with --target k8s, THE Generator SHALL produce Service manifests
3. WHEN the generate command is executed with --target k8s, THE Generator SHALL produce Ingress manifests
4. WHEN the generate command is executed with --target k8s, THE Generator SHALL produce HorizontalPodAutoscaler manifests
5. WHEN scale is dev, THE Generator SHALL set replicas to 1, cpu_requests to 100m, and memory_requests to 256Mi
6. WHEN scale is prod, THE Generator SHALL set replicas to 2, cpu_requests to 250m, and enable HPA
7. WHEN scale is heavy, THE Generator SHALL set replicas to 3 or more, cpu_requests to 500m, and configure aggressive HPA
8. WHEN workload_type is latency-sensitive, THE Generator SHALL configure HPA with lower CPU threshold
9. WHEN workload_type is batch, THE Generator SHALL configure HPA with higher CPU threshold tolerance
10. WHEN env kind is literal, THE Generator SHALL inline the value in a ConfigMap
11. WHEN env kind is ref, THE Generator SHALL use valueFrom.configMapKeyRef in the Deployment
12. WHEN env kind is secret, THE Generator SHALL use valueFrom.secretKeyRef in the Deployment
13. THE Generator SHALL populate containerPort and targetPort from Infra_Model port fields
14. THE Generator SHALL use cluster_assumptions block for ingress controller, cert-manager, and storage class configuration
15. THE Generator SHALL produce manifests that are valid for kubectl apply

### Requirement 7: State Directory Management [DONE]

**User Story:** As a developer, I want the system to track state across runs, so that iterative workflows are safe and predictable.

#### Acceptance Criteria

1. THE System SHALL create a `.ai-infra/` directory in the repository root
2. THE System SHALL write analyzer_output.json to the State_Directory
3. THE System SHALL write infra_model.v1.json to the State_Directory
4. THE System SHALL write plan.md to the State_Directory
5. THE System SHALL create a logs subdirectory in the State_Directory
6. THE System SHALL support hints.yaml in the State_Directory for user overrides
7. WHEN hints.yaml exists, THE System SHALL merge hints with analyzer output during planning
8. THE System SHALL maintain dirty and clean markers for incremental runs

### Requirement 8: CI/CD Pipeline Generation [DONE]

**User Story:** As a DevOps engineer, I want to generate CI/CD pipeline configurations, so that I can automate build and deployment workflows.

#### Acceptance Criteria

1. WHEN the generate command includes `--target ci` flag, THE Generator SHALL produce CI/CD pipeline files for all providers listed in `cicd.providers`
2. THE Generator SHALL support GitHub Actions, GitLab CI, Bitbucket Pipelines, and CircleCI
3. THE Generator SHALL include build image step in each pipeline
4. THE Generator SHALL include push to registry step in each pipeline
5. THE Generator SHALL include a deploy step using kubectl apply
6. THE Generator SHALL populate registry name from `cicd.registry` in the Infra_Model
7. THE Generator SHALL populate cluster authentication method from `cicd.cluster_auth` in the Infra_Model
8. THE Generator SHALL support optional lint and test steps controlled by `cicd.lint` and `cicd.run_tests`
9. THE Generator SHALL support auto-deploy configuration via `cicd.auto_deploy`

### Requirement 9: Fix Loop and Self-Healing [DONE]

**User Story:** As a developer, I want the system to analyze deployment failures and suggest fixes, so that I can resolve issues faster.

#### Acceptance Criteria

1. WHEN the fix command is executed with --logs argument, THE System SHALL parse the provided log file
2. THE System SHALL map raw logs to structured error schema with kind, component, and evidence fields
3. THE System SHALL support error kinds: build, runtime, oom, crashloop, and image_pull
4. WHEN an OOM error is detected, THE Planner SHALL increase memory_limits for the affected service
5. WHEN a CrashLoop error is detected, THE Planner SHALL inspect depends_on and suggest ordering fixes
6. WHEN a build error is detected, THE Planner SHALL propose patches to base image or entrypoint
7. THE Planner SHALL propose targeted patches to Infra_Model, not full regeneration
8. WHEN patches are proposed, THE Generator SHALL regenerate only files affected by patched services
9. WHEN the fix command includes --dry-run flag, THE System SHALL print planned changes and diffs without writing files
10. THE System SHALL write fix loop logs to `.ai-infra/logs/` directory
11. *Note: For v1, the `severity` field on InfraError is explicitly skipped. The fix loop treats all extracted errors as blocking issues. Do not add `severity` until real-world log data justifies it.*

### Requirement 10: Command-Line Interface [DONE]

**User Story:** As a developer, I want a command-line interface, so that I can integrate the tool into my existing workflows and scripts.

#### Acceptance Criteria

1. THE CLI SHALL provide an init command that runs the initialization workflow defined in Requirement 22
2. THE CLI SHALL provide an analyze command that runs the Analyzer
3. THE CLI SHALL provide a plan command that runs the Planner
4. THE CLI SHALL provide a generate command that runs the Generator
5. THE CLI SHALL provide a fix command that runs the Fix_Loop
6. THE CLI SHALL accept --target flag for generate command to specify docker-compose or k8s
7. THE CLI SHALL accept --logs flag for fix command to specify log file path
8. THE CLI SHALL accept --dry-run flag for fix command to preview changes
9. THE CLI SHALL display progress and status messages during execution
10. THE CLI SHALL return non-zero exit code on errors
11. THE CLI SHALL be built using Typer framework

### Requirement 11: Web User Interface [NOT STARTED]

**User Story:** As a user, I want a browser-based interface, so that I can use the tool without installing CLI tools.

#### Acceptance Criteria

1. THE Web_UI SHALL provide a repository input view for URL or local path entry
2. THE Web_UI SHALL provide a hints.yaml editor in the repository input view
3. THE Web_UI SHALL provide a live plan review view with visual editor for Infra_Model
4. THE Web_UI SHALL support scale toggles, service on/off switches, and domain configuration in the plan review view
5. WHEN Infra_Model is edited in Web_UI, THE System SHALL write changes to `.ai-infra/infra_model.json`
6. THE Web_UI SHALL provide a file viewer with syntax highlighting for generated configurations
7. THE Web_UI SHALL support copy and download actions for generated files
8. THE Web_UI SHALL display streaming progress via Server-Sent Events
9. THE Web_UI SHALL be built using Next.js and shadcn/ui
10. THE Web_UI SHALL communicate with Backend_API via HTTP

### Requirement 12: Backend API [DONE]

**User Story:** As a system integrator, I want a REST API, so that both CLI and Web UI can use the same backend logic.

#### Acceptance Criteria

1. THE Backend_API SHALL provide endpoints for analyze, plan, generate, and fix operations
2. THE Backend_API SHALL support Server-Sent Events for streaming progress updates
3. THE Backend_API SHALL serve both CLI and Web_UI clients
4. THE Backend_API SHALL configure CORS to allow browser access
5. THE Backend_API SHALL validate all input using Pydantic models
6. THE Backend_API SHALL return structured error responses with descriptive messages
7. THE Backend_API SHALL be built using FastAPI framework
8. THE Backend_API SHALL support async request handling

### Requirement 13: Infra Model Serialization [DONE]

**User Story:** As a developer, I want round-trip serialization integrity of the Infra Model, so that the Pydantic model (`model.json()`) -> disk -> `model_validate()` preserves semantic equivalence without data loss.

#### Acceptance Criteria

1. WHEN a valid infra_model.json file is provided, Pydantic SHALL parse it into an Infra_Model object
2. WHEN an invalid infra_model.json file is provided, Pydantic SHALL raise a descriptive validation error
3. THE mechanism SHALL format Infra_Model objects back into valid JSON files on disk
4. FOR ALL valid Infra_Model objects, serializing then deserializing SHALL produce an equivalent object (round-trip property)
5. THE serialization SHALL use consistent indentation and formatting
6. Pydantic SHALL validate schema version compatibility

### Requirement 14: Testing and Validation [PARTIAL]

**User Story:** As a maintainer, I want comprehensive test coverage, so that regressions are caught early and the system remains reliable.

#### Acceptance Criteria

1. THE System SHALL include pytest unit tests for all Analyzer detectors
2. THE System SHALL include golden tests for generated Dockerfiles against fixture repositories — **[GAP: per-fixture golden dirs (`tests/golden/fastapi_app/` etc.) are empty; only `enterprise_stack/` golden snapshots exist]**
3. THE System SHALL include golden tests for generated docker-compose.yml against fixture repositories — **[GAP: same as AC2]**
4. THE System SHALL include golden tests for generated Kubernetes manifests against fixture repositories — **[GAP: same as AC2]**
5. THE System SHALL include snapshot tests for FastAPI, Express, Django, and Go application stacks — **[GAP: fixture dirs exist but have no golden output files]**
6. THE System SHALL include integration tests for the complete analyze-plan-generate workflow — **[GAP: no integration test file exists yet]**
7. THE System SHALL include tests for Infra_Model validation and rejection scenarios
8. THE System SHALL include tests for Fix_Loop error parsing and patch generation

### Requirement 15: LLM Integration and Model Selection [DONE]

**User Story:** As a system administrator, I want to configure LLM backends, so that I can use local models for development and cloud models for production.

#### Acceptance Criteria

1. THE System SHALL support Ollama as an LLM backend
2. THE System SHALL support Claude API as an LLM backend
3. THE System SHALL allow LLM backend selection via configuration
4. WHEN Ollama is selected, THE System SHALL use local model execution
5. WHEN Claude API is selected, THE System SHALL use remote API calls
6. THE System SHALL centralize LLM configuration in a single module
7. THE System SHALL support model-specific prompt templates
8. THE System SHALL handle LLM API errors gracefully with retry logic

### Requirement 16: Ingress Controller Configuration [DONE]

**User Story:** As a platform engineer, I want to configure ingress controllers, so that generated manifests match my cluster's ingress setup.

#### Acceptance Criteria

1. THE Infra_Model SHALL support ingress controller types: nginx, traefik, and alb
2. WHEN ingress controller is nginx, THE Generator SHALL use nginx-specific annotations
3. WHEN ingress controller is traefik, THE Generator SHALL use traefik-specific annotations
4. WHEN ingress controller is alb, THE Generator SHALL use AWS ALB-specific annotations
5. THE Planner SHALL use LLM to generate ingress annotations based on controller type
6. THE System SHALL validate LLM-generated annotations before passing to templates
7. THE Infra_Model SHALL include ingress_class_name and tls_enabled in the cluster_assumptions block

### Requirement 17: Resource Sizing and Scaling [DONE]

**User Story:** As a DevOps engineer, I want intelligent resource sizing, so that applications have appropriate CPU and memory allocations.

#### Acceptance Criteria

1. THE Infra_Model SHALL define cpu_requests, cpu_limits, memory_requests, and memory_limits for each service
2. WHEN scale is dev, THE System SHALL use minimal resource allocations
3. WHEN scale is prod, THE System SHALL use moderate resource allocations and enable autoscaling
4. WHEN scale is heavy, THE System SHALL use aggressive resource allocations and autoscaling
5. WHEN needs_gpu is true, THE System SHALL include GPU resource requests in Kubernetes manifests
6. THE Planner SHALL adjust resource sizing based on detected workload characteristics
7. THE Planner SHALL consider latency_sensitive capability when setting resource limits

### Requirement 18: Multi-Service Dependency Management [DONE]

**User Story:** As a developer, I want automatic dependency ordering, so that services start in the correct sequence.

#### Acceptance Criteria

1. THE Infra_Model SHALL define depends_on relationships between services
2. WHEN a service depends on a database, THE Generator SHALL include the database in depends_on
3. WHEN a worker depends on a queue, THE Generator SHALL include the queue in depends_on
4. THE Generator SHALL translate depends_on to Docker Compose service dependencies
5. THE Generator SHALL use init containers or readiness probes in Kubernetes for dependency ordering
6. THE Planner SHALL infer implicit dependencies from framework and library detection

### Requirement 19: Secret and Configuration Management [PARTIAL]

**User Story:** As a security engineer, I want proper separation of secrets and configuration, so that sensitive data is not exposed in version control.

#### Acceptance Criteria

1. THE Infra_Model SHALL distinguish between literal values, config references, and secret references
2. WHEN env kind is secret, THE Generator SHALL never inline the value in generated files
3. WHEN env kind is secret in Docker Compose, THE Generator SHALL use Docker secrets
4. WHEN env kind is secret in Kubernetes, THE Generator SHALL use Secret resources with secretKeyRef
5. THE Generator SHALL create placeholder Secret manifests with instructions for populating values
6. THE System SHALL document secret management requirements in generated README files — **[GAP: generated output does not yet include a secret-management README]**

### Requirement 20: Incremental Regeneration [DONE]

**User Story:** As a developer, I want to regenerate only changed components, so that iterative workflows are fast and predictable.

#### Acceptance Criteria

1. WHEN the Infra_Model is modified, THE System SHALL identify affected services
2. WHEN the generate command is executed after model changes, THE Generator SHALL regenerate only affected files
3. THE System SHALL preserve user modifications to files outside the State_Directory
4. THE System SHALL track file generation timestamps and state hashes in a manifest file (`.ai-infra/state.json`)
5. WHEN the --force flag is provided, THE Generator SHALL regenerate all files regardless of changes

### Requirement 21: hints.yaml Schema and Override Rules [PARTIAL]

**User Story:** As a user, I want a well-defined structure for `hints.yaml`, so that I know how my overrides merge with analyzer output.

#### Acceptance Criteria

1. THE System SHALL define a strict schema for `hints.yaml` containing override fields (e.g., scale, ingress, environment overrides)
2. WHEN a field exists in both `hints.yaml` and analyzer output, the value in `hints.yaml` SHALL always win and override the analyzer
3. THE Planner SHALL consume the merged context of analyzer output and `hints.yaml`
4. WHEN an invalid field is provided in `hints.yaml`, THE System SHALL return a descriptive validation error — **[GAP: hints.yaml is parsed as free-form YAML dict; invalid keys are silently ignored, no strict schema validation]**
5. `hints.yaml` MAY override `cluster_assumptions.ingress_controller` and `cluster_assumptions.ingress_class_name` fields. When provided, these values follow the hints-always-win rule defined in AC2.

### Requirement 22: Initialization Command (ai-infra init) [DONE]

**User Story:** As a new user, I want an `init` command, so that I can easily scaffold the `.ai-infra/` state directory and start providing hints.

#### Acceptance Criteria

1. WHEN the `ai-infra init` command is executed, THE System SHALL create the `.ai-infra/` directory if it does not exist
2. WHEN the `ai-infra init` command is executed, THE System SHALL generate a starter `hints.yaml` file with common defaults and commented examples
3. WHEN the `.ai-infra/` directory already exists, `ai-infra init` SHALL safely exit or prompt without destructively overwriting existing state

### Requirement 23: Helm Chart Generation [DONE]

**User Story:** As a DevOps engineer, I want to generate Helm charts, so that I can deploy applications using Helm's templating and release management.

#### Acceptance Criteria

1. WHEN `helm.enabled` is true in the Infra_Model, THE Generator SHALL produce a Helm chart directory
2. THE Generator SHALL produce Chart.yaml with chart name, version, and app version
3. THE Generator SHALL produce values.yaml with per-service configuration blocks
4. THE Generator SHALL produce Helm template files for Deployment, Service, and Ingress
5. THE Generator SHALL use the project_name as chart_name when no explicit chart_name is set
6. THE Generator SHALL support custom values_overrides in values.yaml
7. WHEN `helm.enabled` is false, THE Generator SHALL not produce any Helm chart files

### Requirement 24: Cluster Provisioning (IaC) [DONE]

**User Story:** As a platform engineer, I want to generate Terraform files for managed Kubernetes clusters, so that I can provision infrastructure alongside application configs.

#### Acceptance Criteria

1. WHEN `iac.enabled` is true in the Infra_Model, THE Generator SHALL produce Terraform files
2. THE Generator SHALL support AWS EKS cluster provisioning with VPC and node groups
3. THE Generator SHALL support GCP GKE cluster provisioning with node pools and autoscaling
4. THE Generator SHALL support Azure AKS cluster provisioning with node pools and network policies
5. THE Generator SHALL use `iac.region`, `iac.node_count`, and `iac.node_instance_type` from the Infra_Model
6. THE Generator SHALL use `iac.cluster_name` or fall back to project_name
7. THE Generator SHALL write Terraform files to a `terraform/` directory in the repository root
8. WHEN `iac.enabled` is false, THE Generator SHALL not produce any IaC files

### Requirement 25: Monitoring and Observability [DONE]

**User Story:** As a DevOps engineer, I want to generate monitoring configurations, so that I can observe application health and performance in production.

#### Acceptance Criteria

1. WHEN `monitoring.enabled` is true in the Infra_Model, THE Generator SHALL produce monitoring configuration files
2. WHEN `monitoring.prometheus` is true, THE Generator SHALL produce Prometheus ServiceMonitor YAML for each app/worker service
3. WHEN `monitoring.grafana` is true, THE Generator SHALL produce a Grafana dashboard JSON with CPU, memory, request rate, and latency panels
4. WHEN `monitoring.alerting` is true, THE Generator SHALL produce Prometheus alerting rules with configurable thresholds
5. THE Generator SHALL support configurable alert thresholds for CPU, memory, error rate, and p99 latency
6. THE Generator SHALL write monitoring files to a `monitoring/` directory in the repository root
7. WHEN `monitoring.enabled` is false, THE Generator SHALL not produce any monitoring files

### Requirement 26: Multi-Tenant Control Plane [DONE]

**User Story:** As a platform engineer, I want to generate multi-tenant Kubernetes configurations, so that I can isolate workloads across tenants with resource quotas and network policies.

#### Acceptance Criteria

1. WHEN `multi_tenancy.enabled` is true in the Infra_Model, THE Generator SHALL produce per-tenant Kubernetes manifests
2. THE Generator SHALL produce a Namespace manifest for each defined tenant
3. THE Generator SHALL produce a ResourceQuota manifest with CPU and memory limits for each tenant
4. WHEN `multi_tenancy.network_policies` is true, THE Generator SHALL produce NetworkPolicy manifests for inter-tenant isolation
5. THE Generator SHALL support custom namespace names via `tenant.namespace`
6. THE Generator SHALL support shared_services that are accessible across tenant namespaces
7. THE Generator SHALL write tenant files to `k8s/tenants/<tenant_name>/` directories
8. WHEN `multi_tenancy.enabled` is false, THE Generator SHALL not produce any tenant files
9. WHEN tenants list is empty even if enabled, THE Generator SHALL not produce any tenant files
