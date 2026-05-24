# Clinical Note Intelligence Platform

AI-powered clinical documentation platform that records doctor-patient conversations,
generates explainable SOAP notes with clinical reasoning, extracts medical entities,
suggests ICD-10/CPT billing codes, detects drug interactions, and tracks longitudinal
patient health intelligence.

## Prerequisites

- Node.js 20+
- Python 3.11+
- Docker + Docker Compose
- Git

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/yourusername/clinical-note-platform.git
cd clinical-note-platform

# 2. Copy env files
cp backend/.env.example backend/.env
cp ml-service/.env.example ml-service/.env
cp frontend/.env.example frontend/.env

# 3. Start all services
docker-compose up --build

# 4. Run database migration (new terminal)
docker-compose exec backend npx prisma migrate dev --name init

# 5. Seed the database
docker-compose exec backend node prisma/seed.js

# 6. Pull Ollama model (new terminal)
docker-compose exec ollama ollama pull llama3.1:8b
```

## Service URLs

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:5000/api |
| ML Service | http://localhost:8000 |
| Ollama | http://localhost:11434 |
| FastAPI Docs | http://localhost:8000/docs |
| Prisma Studio | Run: `docker-compose exec backend npx prisma studio` |

## Default Login Credentials

All accounts use password: `Password123!`

| Role | Email |
|------|-------|
| Admin | admin@clinic.com |
| Doctor | doctor@clinic.com |
| Nurse | nurse@clinic.com |
| Receptionist | receptionist@clinic.com |

## Project Structure
