# Contributing to AI Infrastructure Generator

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/your-username/ai-infra-generator.git
cd ai-infra-generator/ai-infra
pip install -e ".[dev]"
pytest  # Make sure all tests pass
```

## Project Structure

```
ai-infra/
├── ai_infra/           # Core library
│   ├── analyzer/       # Repository analysis (detectors)
│   ├── planner/        # AI planning (LLM integration)
│   ├── generator/      # Template rendering (Jinja2)
│   ├── fix/            # Self-healing fix loop
│   ├── models/         # Pydantic schemas
│   ├── state/          # State management
│   ├── config/         # Settings
│   └── api/            # FastAPI server
├── cli/                # Typer CLI commands
└── tests/              # Pytest test suite
```

## How to Contribute

### Adding a Language Detector

1. Create `ai_infra/analyzer/detectors/your_language.py`
2. Inherit from `BaseDetector` and implement `matches()` + `detect()`
3. The analyzer auto-discovers it — no registration needed
4. Add a fixture in `tests/conftest.py`
5. Write tests

### Adding a Jinja2 Template

1. Create the template in `ai_infra/generator/templates/{target}/`
2. The generator already has routing logic for all targets
3. Add golden snapshot tests in `tests/golden/`

### Adding an LLM Backend

1. Add config fields in `ai_infra/config/settings.py`
2. Add a `_call_{backend}()` method in `ai_infra/planner/planner.py`
3. Update the backend routing in `_call_llm()`

## Testing

```bash
pytest                     # Run all tests
pytest -x                  # Stop on first failure
pytest --cov=ai_infra      # With coverage
pytest tests/analyzer/     # Run specific test module
```

## Code Style

- Type hints on all public functions
- Docstrings on all public classes and methods
- Keep modules focused: analyzers don't call LLMs, generators don't call analyzers

## Pull Request Process

1. Fork and create a feature branch
2. Make your changes with tests
3. Ensure all 107+ tests pass
4. Submit a PR with a clear description
