# Contributing to Exam Readiness Predictor

Thank you for your interest in contributing! This document provides guidelines and information for contributors.

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Architecture](#project-architecture)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Style Guide](#style-guide)

---

## Code of Conduct

Please be respectful and constructive in all interactions. We're building software to help students succeed - let's maintain that positive spirit in our community.

---

## Getting Started

### Good First Issues

Look for issues labeled `good first issue` or `help wanted`. These are specifically curated for new contributors.

### Types of Contributions

- **Bug fixes** - Found a bug? Fix it!
- **Documentation** - README improvements, code comments, tutorials
- **Features** - New functionality (please discuss in an issue first)
- **Tests** - We need more test coverage
- **UI/UX** - Design improvements, accessibility

---

## Development Setup

### Prerequisites
- Python 3.10+
- Git

### Local Setup

```bash
# Fork and clone
git clone https://github.com/YOUR-USERNAME/grade-predictor-mvp.git
cd grade-predictor-mvp

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

### Running Tests

```bash
# Run with a fresh test database
DATABASE_URL="sqlite:///test.db" python -c "from db import init_db; init_db(verbose=True)"

# Verify the app starts
streamlit run app.py
```

---

## Project Architecture

```
├── app.py                 # Streamlit UI (views)
├── db.py                  # Database layer (models)
├── services/              # Business logic (controllers)
│   ├── core.py           # CRUD operations
│   ├── metrics.py        # Calculations
│   ├── dashboard.py      # Aggregations
│   └── recommendations.py # AI logic
├── migrations/            # Database migrations
└── pdf_extractor.py      # PDF parsing
```

### Key Design Principles

1. **Services are pure Python** - No Streamlit in `/services`. This enables future API migration.
2. **Explicit parameters** - Functions take explicit args, not `st.session_state`.
3. **JSON-serializable returns** - Services return `dict`/`list`, not DataFrames.
4. **Database portability** - SQLite for dev, PostgreSQL for prod.

---

## Making Changes

### Branch Naming

```
feature/short-description   # New features
fix/issue-number-description # Bug fixes
docs/what-changed           # Documentation
refactor/what-changed       # Code refactoring
```

### Commit Messages

Follow conventional commits:

```
feat: add weekly study planner
fix: correct mastery decay calculation
docs: update README quickstart
refactor: extract metrics to services layer
```

### Before Submitting

1. **Test locally** - Make sure the app runs without errors
2. **Check imports** - No unused imports, proper ordering
3. **Format code** - Consistent style (we follow PEP 8)
4. **Update docs** - If you changed behavior, update README/docstrings

---

## Pull Request Process

1. **Open an issue first** for significant changes
2. **Create a feature branch** from `main`
3. **Make your changes** with clear commits
4. **Test thoroughly** - both happy path and edge cases
5. **Open a PR** with:
   - Clear title describing the change
   - Description of what and why
   - Screenshots for UI changes
   - Link to related issue(s)

### PR Template

```markdown
## What does this PR do?
Brief description of changes.

## Why?
Context and motivation.

## How to test
Steps to verify the changes work.

## Screenshots (if UI changes)
Before/after screenshots.

## Checklist
- [ ] I have tested this locally
- [ ] I have updated documentation if needed
- [ ] My code follows the project style
```

---

## Style Guide

### Python

- **PEP 8** for style
- **Type hints** for function signatures
- **Docstrings** for public functions (Google style)

```python
def compute_mastery(
    topic_id: int,
    as_of_date: date,
    include_decay: bool = True
) -> Tuple[float, Optional[date], int, int, int, float, int]:
    """
    Compute mastery score for a topic.

    Args:
        topic_id: The topic's database ID
        as_of_date: Date to compute mastery for
        include_decay: Whether to apply time decay

    Returns:
        Tuple of (mastery, last_activity, exercise_count, ...)
    """
```

### Streamlit UI

- Use `st.columns()` for layout
- Use `st.form()` for multi-input submissions
- Prefer `st.button()` over `st.form_submit_button()` for single actions
- Use emojis sparingly and consistently

### Database

- All queries via `db.py` functions
- Use parameterized queries (never string interpolation)
- Migrations for schema changes

---

## Questions?

- Open a [Discussion](https://github.com/SDM-25/grade-predictor-mvp/discussions) for questions
- Open an [Issue](https://github.com/SDM-25/grade-predictor-mvp/issues) for bugs/features

---

Thank you for contributing! 🎓
