# Exam Readiness Predictor (Streamlit + SQLite) — MVP

Local MVP app to track exam readiness for a single final exam (default 120 marks).

## Features
- Track topic mastery (0–5) + last reviewed date
- Edit topic point weights (defaults seeded from 2021 exam prior; editable)
- Log lectures (attendance + topics covered)
- Log timed practice (past papers/mocks)
- Dashboard: predicted marks, readiness, gaps, pacing

## Run it
```bash
pip install -r requirements.txt
streamlit run app.py
```

A local SQLite DB (`grade_predictor.db`) will be created next to `app.py`.

## Mastery scale
0 not started • 1 skim • 2 examples • 3 easy w/notes • 4 timed exam • 5 teach it
