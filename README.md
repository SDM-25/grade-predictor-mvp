# Exam Readiness Predictor

> **Predict your exam score before you sit the exam.**

A study tracking app that uses spaced repetition principles and mastery decay to predict your exam readiness. Track topics, log study sessions, and get AI-powered recommendations on what to study next. Built with Streamlit for rapid iteration, designed for migration to Next.js.

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Streamlit](https://img.shields.io/badge/streamlit-1.28+-red.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

---

## Screenshots

<!-- Add screenshots here after deployment -->
| Dashboard | Topics | Recommendations |
|-----------|--------|-----------------|
| *Coming soon* | *Coming soon* | *Coming soon* |

---

## Features

### Core Tracking
- **Multi-course support** - Track multiple courses simultaneously
- **Topic mastery** - 0-5 scale with automatic decay over time
- **Assessment tracking** - Exams, assignments, quizzes with due dates
- **Study logging** - Sessions, exercises, timed practice attempts

### Smart Predictions
- **Readiness score** - Weighted prediction based on topic mastery
- **Coverage analysis** - See which topics need attention
- **Decay modeling** - Mastery decreases without review (spaced repetition)
- **Gap detection** - Automatic identification of weak areas

### Recommendations
- **Prioritized tasks** - What to study next, ranked by impact
- **At-risk alerts** - Courses below readiness threshold
- **Weekly planner** - Auto-generated study schedule

### User Experience
- **Demo data** - One-click sample data for new users
- **PDF import** - Extract topics from course outlines
- **Persistent login** - Cookie-based "Remember me"
- **Mobile-friendly** - Responsive design

---

## Quickstart

### Prerequisites
- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/SDM-25/grade-predictor-mvp.git
cd grade-predictor-mvp

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

The app will open at `http://localhost:8501`. A local SQLite database (`grade_predictor.db`) is created automatically.

### First Run
1. Register with email/password
2. Click **"Load Demo Data"** to explore with sample data, OR
3. Add your first course in the sidebar

---

## Configuration

### Environment Variables

Create a `.env` file or set these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite:///grade_predictor.db` |

**Database URL formats:**
```bash
# SQLite (local development)
DATABASE_URL=sqlite:///grade_predictor.db

# PostgreSQL (production)
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

### Streamlit Cloud Deployment

For Streamlit Cloud, add secrets in `.streamlit/secrets.toml`:

```toml
# Database (Supabase/Postgres)
DB_HOST = "your-host.supabase.co"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = "your-password"
DB_PORT = 5432

# Admin access (optional)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = "$2b$12$..."  # bcrypt hash
```

See `.env.example` for a complete template.

---

## Project Structure

```
├── app.py                 # Main Streamlit application
├── db.py                  # Database layer (SQLite/Postgres)
├── services/              # Business logic (API-ready)
│   ├── core.py           # CRUD operations
│   ├── metrics.py        # Mastery & readiness calculations
│   ├── dashboard.py      # Dashboard data aggregation
│   └── recommendations.py # Study recommendations
├── migrations/            # Database migrations
│   └── runner.py         # Migration runner
├── pdf_extractor.py      # PDF topic extraction
└── requirements.txt
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Streamlit |
| Backend | Python |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Auth | bcrypt + secure cookies |
| PDF Parsing | PyMuPDF |

---

## Roadmap

### Current: Streamlit MVP
- [x] Multi-course tracking
- [x] Mastery decay algorithm
- [x] Readiness predictions
- [x] Study recommendations
- [x] Demo data onboarding
- [x] Database migrations
- [x] PostgreSQL support

### Next: Migration to Next.js
- [ ] FastAPI backend (services layer ready)
- [ ] Next.js frontend
- [ ] Supabase Auth
- [ ] Real-time updates
- [ ] Mobile app (React Native)

### Future
- [ ] Spaced repetition scheduling
- [ ] AI-powered study suggestions
- [ ] Collaborative study groups
- [ ] Integration with calendar apps

---

## Privacy & Disclaimer

**This is an independent project, not affiliated with any educational institution.**

- Your data is stored locally (SQLite) or in your own database (PostgreSQL)
- No data is sent to third parties
- You are responsible for your own data backups
- This tool provides predictions, not guarantees of exam performance

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Quick steps:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- Built with [Streamlit](https://streamlit.io/)
- Mastery decay inspired by spaced repetition research
- Icons from emoji standards

---

<p align="center">
  <sub>Built with ❤️ for students who want to study smarter, not harder.</sub>
</p>
