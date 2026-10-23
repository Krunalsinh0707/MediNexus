# MediNexus — Enterprise AI Healthcare & Hospital Management Platform

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat&logo=vite&logoColor=white)](https://vitejs.dev/)
[![Gemini](https://img.shields.io/badge/Google_Gemini-1.5_Flash-8E75B2?style=flat&logo=google&logoColor=white)](https://ai.google.dev/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)

**MediNexus** is a production-grade, full-stack **Hospital Management & Clinical Intelligence System** engineered for healthcare networks, clinicians, and patients. It combines multi-department hospital administration, role-based workflows, automated hematology intelligence (CBC AI Engine v2.0), context-aware clinical communication, RAG-grounded AI consultation (Google Gemini 1.5 Flash + ChromaDB), ReportLab PDF exports, and hardened security infrastructure powered by **PostgreSQL 18**.

---

## 📑 Table of Contents

- [Core Highlights](#-core-highlights)
- [Key Features](#-key-features)
  - [1. Role-Based Healthcare Portals](#1-role-based-healthcare-portals)
  - [2. Intelligent CBC AI Engine v2.0](#2-intelligent-cbc-ai-engine-v20)
  - [3. Clinical Communication & RAG Chatbot](#3-clinical-communication--rag-chatbot)
  - [4. Appointment & Multi-Department Triage](#4-appointment--multi-department-triage)
  - [5. Medical Reports & Document OCR](#5-medical-reports--document-ocr)
  - [6. Enterprise Security Hardening](#6-enterprise-security-hardening)
- [Tech Stack](#-tech-stack)
- [Project Architecture](#-project-architecture)
- [Knowledge Graph (Graphify)](#-knowledge-graph-graphify)
- [Quick Start Guide](#-quick-start-guide)
  - [Prerequisites](#prerequisites)
  - [Environment Setup](#1-environment-setup)
  - [Database Configuration](#2-database-configuration)
  - [Backend Setup](#3-backend-setup)
  - [Frontend Setup](#4-frontend-setup)
  - [Docker Compose Deployment](#5-docker-compose-deployment)
- [Default Seed Accounts & Testing](#-default-seed-accounts--testing)
- [Security & Compliance](#-security--compliance)
- [License & Disclaimer](#-license--disclaimer)

---

## 🌟 Core Highlights

- **Multi-Role Portals**: Dedicated, purpose-built dashboards for **Patients**, **Doctors**, and **Hospital Administrators**.
- **CBC AI Engine v2.0**: High-precision complete blood count interpretation with age/gender-stratified reference ranges, 5-tier clinical severity grading, and a 0–100 CBC Health Score.
- **RAG Clinical Assistant**: LLM-driven medical chatbot powered by **Google Gemini 1.5 Flash** with **ChromaDB** vector memory, hardcoded emergency triage safety overrides, and offline clinical fallbacks.
- **Doctor-Patient Messaging Console**: Real-time clinical chat threads with priority flags (Routine, Urgent, Emergency), audit trails, and physician escalation.
- **Full Security Hardening**: Magic-byte MIME file validation, path traversal defense, sliding-window rate limiting, OTP password resets via SMTP, and strict HTTP security headers (CSP, HSTS, X-Frame-Options).
- **PostgreSQL 18 Architecture**: Enterprise relational schema managed by SQLAlchemy 2.x and Alembic with identity sequence synchronization.
- **Interactive Codebase Knowledge Graph**: Integrated **Graphify** AST-level analysis mapping 950+ nodes and 3,400+ relationships with visual graph exploration (`graphify-out/graph.html`).

---

## 🚀 Key Features

### 1. Role-Based Healthcare Portals

- **Patient Portal**:
  - Book, reschedule, and track specialist appointments with real-time doctor availability.
  - Interactive CBC report analysis: manual biometric input or PDF file intake.
  - Patient chat console connecting to designated doctors or the AI health assistant.
  - One-click Emergency Request triage queue.
  - Personal health record locker with downloadable PDF diagnostic summaries.
- **Doctor Portal**:
  - Comprehensive clinical console for managing appointments, consultation status, and daily schedules.
  - Patient detail inspection: medical history, past lab results, and automated CBC severity scores.
  - Real-time clinical chat with patients, status flagging, and case notes.
- **Hospital Admin Command Center**:
  - Global hospital telemetry: live patient intake, active emergency alerts, appointment analytics.
  - Doctor directory and department staffing management across 14 clinical specialties.
  - Append-only system audit trails and security monitoring.

### 2. Intelligent CBC AI Engine v2.0

- **Multi-Layer Biomarker Processing**: Analyzes White Blood Cells (WBC), Red Blood Cells (RBC), Hemoglobin (HGB), Hematocrit (HCT), Platelets (PLT), MCV, MCH, and MCHC.
- **Stratified Reference Ranges**: Automatically adjusts standard thresholds based on biological gender and age categories.
- **5-Tier Severity Stratification**: Normal, Mild, Moderate, High, Critical / Panic alerts.
- **CBC Health Score (0–100)**: Quantitative wellness metric based on weighted biomarker deviation penalties.
- **Dual Explanation Output**: Generates both clear patient-facing guidance and detailed clinical physician interpretations.

### 3. Clinical Communication & RAG Chatbot

- **Google Gemini 1.5 Flash Grounding**: Medical Q&A grounded in authenticated patient lab reports and vector embeddings stored in **ChromaDB**.
- **Emergency Safety Interceptor**: Deterministic regex and clinical rule-based filter detecting life-threatening symptoms (chest pain, stroke symptoms, respiratory distress, acute trauma) to instantly provide emergency dispatch guidance.
- **Offline Clinical Fallback**: Resilient offline advisory engine delivering reliable first-aid and department guidance even when external LLM APIs are unreachable.
- **Two-Way Clinical Messaging**: Structured clinical conversations between patients and assigned department doctors.

### 4. Appointment & Multi-Department Triage

- **14 Pre-Configured Clinical Departments**:
  - Cardiology, Oncology, Orthopedics, Neurology, Pulmonology, Gastroenterology, Endocrinology, Hematology, Nephrology, Dermatology, Pediatrics, Gynecology, General Medicine, and Emergency.
- **Intelligent Routing**: Directs patient symptoms and requests to appropriate specialists.
- **Availability Validation**: Dynamic slot allocation preventing doctor overbooking and double-scheduling.

### 5. Medical Reports & Document OCR

- **Dual Ingestion**: Support for manual metric entry and scanned lab PDF processing.
- **OCR Pipeline**: Automated text extraction via `pdfplumber` and `pytesseract` with fuzzy numerical normalization.
- **ReportLab PDF Exporter**: Instant generation of branded, tamper-evident clinical lab reports (`diabetes_report_*.pdf`, `cbc_report_*.pdf`) complete with hospital branding, physician disclaimers, and metric summaries.

### 6. Enterprise Security Hardening

- **File Upload Security (`file_security.py`)**:
  - Magic-byte validation (`application/pdf`, `image/png`, `image/jpeg`).
  - Strict filename sanitization (`secure_filename`) preventing directory traversal (`../`).
  - Max file size enforcement (10 MB).
- **Adaptive Rate Limiting (`rate_limiter.py`)**:
  - Sliding-window in-memory rate limiter on sensitive endpoints (`/auth/login`, `/auth/register`, `/password-reset/*`, `/emergency/*`).
- **Cryptographic Authentication**:
  - JWT Bearer tokens with configurable expiration.
  - Passwords hashed using Bcrypt with secure salt rounds.
  - 6-digit numeric OTP generation with 10-minute expiry for password recovery via Gmail SMTP.
- **HTTP Security Headers**:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), camera=(), microphone=()`
  - HTTP Strict Transport Security (`HSTS`) enabled in production.

---

## 🛠 Tech Stack

| Domain | Technologies & Libraries |
| :--- | :--- |
| **Backend Framework** | FastAPI (Python 3.11+), Pydantic v2, Uvicorn, ASGI |
| **Database & ORM** | PostgreSQL 18, SQLAlchemy 2.x, Alembic, psycopg3 driver |
| **AI & Vector Retrieval** | Google Generative AI (`gemini-1.5-flash`), ChromaDB |
| **Document Processing** | ReportLab (PDF generation), pdfplumber, pytesseract, Pillow |
| **Security & Auth** | python-jose (JWT), passlib, bcrypt, smtplib (OTP via Gmail) |
| **Frontend Framework** | React 19, Vite 8, React Router DOM v7 |
| **UI & Styling** | Vanilla CSS, TailwindCSS, Custom Glassmorphism System |
| **Charts & Graphics** | Recharts, Chart.js, react-chartjs-2 |
| **Icons & Animations** | Lucide React, Framer Motion v12 |
| **Code Intelligence** | Anytechie Graphify (AST graph analysis & visual exploration) |
| **DevOps & Containers** | Docker, Docker Compose, Nginx Reverse Proxy |

---

## 📁 Project Architecture

```
MediNexus/
├── backend/
│   ├── src/
│   │   ├── api.py                      # FastAPI entry point, CORS & security middlewares
│   │   ├── auth.py                     # JWT token handling & password hashing
│   │   ├── cbc_analysis.py             # CBC AI Engine v2.0 & severity logic
│   │   ├── database.py                 # PostgreSQL connection pool & session manager
│   │   ├── models.py                   # SQLAlchemy ORM models (User, Doctor, Department, etc.)
│   │   ├── pdf_generator.py            # ReportLab PDF clinical report engine
│   │   ├── pdf_service.py              # OCR & PDF document text extraction
│   │   ├── sms_service.py              # SMS notification service wrapper
│   │   ├── config/
│   │   │   └── version_config.py       # Centralized version metadata (v2.1.0)
│   │   ├── security/
│   │   │   ├── file_security.py        # Magic-byte validation & upload protection
│   │   │   └── rate_limiter.py         # Sliding window rate limiter
│   │   ├── services/
│   │   │   ├── email_service.py        # SMTP email dispatch & OTP templates
│   │   │   └── otp_service.py          # OTP generation & validation lifecycle
│   │   └── routers/
│   │       ├── admin_router.py         # Hospital admin telemetry & doctor management
│   │       ├── analytics_router.py     # Patient demographic & appointment statistics
│   │       ├── appointments_router.py  # Patient & doctor appointment workflows
│   │       ├── auth_router.py          # User registration, login, & session check
│   │       ├── cbc_router.py           # CBC calculation & PDF analysis endpoints
│   │       ├── chatbot_router.py       # Context-aware RAG clinical chatbot
│   │       ├── clinical_chat_router.py # Real-time clinical chat & physician escalation
│   │       ├── communication_router.py # Hospital messaging & announcements
│   │       ├── departments_router.py   # Department directories & doctor lookups
│   │       ├── doctors_router.py       # Doctor profiles & availability schedules
│   │       ├── emergency_router.py     # Emergency intake & high-priority dispatch
│   │       ├── medical_reports_router.py# Patient medical history & report attachments
│   │       ├── notifications_router.py # Notification queues & alerts
│   │       ├── password_reset.py       # Forgot password & OTP verification
│   │       └── reports_router.py       # Clinical report persistence & PDF streaming
│   ├── alembic/                        # Alembic database migration revisions
│   ├── scripts/                        # Database migration & validation utilities
│   ├── seed_test_doctors.py            # Automated seed script for 28 clinical doctors
│   ├── test_appointment_flow.py        # Relational appointment verification suite
│   ├── Dockerfile                      # Backend container configuration
│   ├── requirements.txt                # Python backend dependencies
│   └── .env.example                    # Environment variable template
├── frontend/
│   ├── src/
│   │   ├── App.jsx                     # Router config & protected routes
│   │   ├── components/                 # Glassmorphic UI modals, sidebars, & navbars
│   │   ├── pages/                      # Role-specific portal views
│   │   │   ├── patient/                # Dashboard, Appointments, CBC, Chat, History
│   │   │   ├── doctor/                 # Clinical Dashboard, Appointments, Chat Console
│   │   │   ├── admin/                  # Admin Login & Management
│   │   │   └── departments/            # Department discovery
│   │   └── services/                   # Axios API service integrations
│   ├── Dockerfile                      # Production Nginx container
│   ├── nginx.conf                      # Nginx reverse proxy configuration
│   └── package.json                    # Frontend dependencies
├── graphify-out/                       # Graphify Code Intelligence Artifacts
│   ├── graph.html                      # Interactive 2D/3D visual code graph
│   ├── graph.json                      # Full AST dependency graph
│   ├── GRAPH_REPORT.md                 # Graph structure & community report
│   └── DOMAINS.md                      # Extracted functional domains & compass
├── docs/                               # Architecture & migration documentation
├── docker-compose.yml                  # Full-stack container orchestration
├── .env.example                        # Root environment template
└── README.md
```

---

## 🕸 Knowledge Graph (Graphify)

This repository includes a precomputed, comprehensive **Graphify Code Knowledge Graph** (`graphify-out/`):

- **Graph Complexity**: 956 nodes, 3,402 edges across 127 functional communities.
- **Core Abstractions**: `User`, `Department`, `Doctor`, `ClinicalConversation`, `ClinicalMessage`, `Appointment`, `ClinicalAlert`, `ClinicalAIAnalysis`.
- **Interactive Visualization**: Open [graphify-out/graph.html](graphify-out/graph.html) directly in any browser to inspect module dependencies, call graphs, and architectural cohesion.
- **Updating the Graph**:
  ```bash
  # Re-extract AST code elements and rebuild the graph
  graphify update .
  ```

---

## ⚙️ Quick Start Guide

### Prerequisites

- **Python**: 3.11 or higher
- **Node.js**: v18 or higher (v20+ recommended)
- **PostgreSQL**: Version 15+ (v18 recommended)
- **Tesseract OCR** (Optional, for scanned medical PDF extraction)

---

### 1. Environment Setup

Clone the repository and copy the environment template:

```bash
git clone https://github.com/Krunalsinh0707/MediNexus MediNexus
cd MediNexus

# Create backend .env
cp .env.example backend/.env
```

Edit `backend/.env` with your credentials:

```env
# Security & JWT
SECRET_KEY=YOUR_SECURE_RANDOM_SECRET_KEY_MIN_32_CHARS
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# PostgreSQL URL is supplied separately as HMS_DATABASE_URL in the process environment.

# Google Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-1.5-flash

# SMTP Email (Optional, for Password Reset OTP)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your-hospital-notifications@example.com
SMTP_PASSWORD=your-google-app-password
```

---

### 2. Database Configuration

The local `medinexus` database is provisioned separately. Set
`HMS_DATABASE_URL` explicitly for local development; deployments must supply
their own URL. Do not use the old `DATABASE_URL` or `DB_*` settings. See
[`backend/docs/module_database_foundation.md`](backend/docs/module_database_foundation.md)
for the guarded initialization steps. Never bootstrap a populated database.

---

### 3. Backend Setup

```bash
cd backend

# Create & activate virtual environment
python -m venv venv

# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize an authorized, confirmed-empty medinexus database using the
# guarded fresh bootstrap described in backend/docs/module_database_foundation.md.
# For an existing model-shaped a8b9c0d1e2f3 database, assess the additive
# upgrade separately; do not run the historical chain on an unknown schema.

# Launch development server
uvicorn src.api:app --reload --port 8000
```

- **Backend API**: `http://localhost:8000`
- **Interactive OpenAPI Documentation (Swagger)**: `http://localhost:8000/docs`
- **System Health Check**: `http://localhost:8000/health`

---

### 4. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start Vite dev server
npm run dev
```

- **Web Application**: `http://localhost:5173`

---

### 5. Docker Compose Deployment

To launch FastAPI and the Nginx frontend against a separately provisioned
PostgreSQL database, set a deployment-specific `HMS_DATABASE_URL` first:

```bash
# Build and run all services in background
docker-compose up -d --build
```

- **Web Portal (Nginx)**: `http://localhost`
- **API Server**: `http://localhost:8000`
Docker Compose does not create or select a database by default.

---

## 🔑 Default Seed Accounts & Testing

### 1. Hospital Administrator
- **Email**: `admin@gmail.com`
- **Password**: supplied by the local operator
- **Portal**: `/admin/login`

### 2. Clinical Doctors (28 Pre-Seeded Accounts)
Use operator-provided credentials for development doctor accounts.

| Department | Sample Doctor | Email |
| :--- | :--- | :--- |
| **Cardiology** | Dr. Aarav Shah | `aarav.shah.test@healthanalyzer.com` |
| **Oncology** | Dr. Arjun Patel | `arjun.patel.test@healthanalyzer.com` |
| **Neurology** | Dr. Rahul Joshi | `rahul.joshi.test@healthanalyzer.com` |
| **Pulmonology** | Dr. Vivek Shah | `vivek.shah.test@healthanalyzer.com` |
| **Orthopedics** | Dr. Dev Mehta | `dev.mehta.test@healthanalyzer.com` |
| **Pediatrics** | Dr. Harsh Shah | `harsh.shah.test@healthanalyzer.com` |
| **Emergency** | Dr. Raj Shah | `raj.shah.test@healthanalyzer.com` |

*(Refer to [DOCTOR.MD](DOCTOR.MD) for the complete list of all 28 doctor credentials.)*

### 3. Patient Account
- Register a new account at `/register` or `/patient/login` with any valid email and mobile number.

---

## 🛡️ Security & Compliance

- **Sanitized Uploads**: Uploaded patient files are vetted for legitimate magic bytes and size constraints; executable file extensions and path navigation characters (`..`, `/`, `\`) are strictly prohibited.
- **Brute-Force Mitigation**: Sliding-window rate limiters shield authentication and OTP routes against credential stuffing and automated abuse.
- **Safe Clinical Fallbacks**: The conversational agent enforces safety guardrails, immediately routing emergency queries to emergency medical services.
- **Audit Trails**: All clinical interactions, appointment state modifications, and admin actions are recorded in PostgreSQL audit logs.

---

## 📄 License & Disclaimer

**Disclaimer**: MediNexus is an informational clinical decision support and hospital management system. It does not replace professional clinical evaluation, diagnosis, or emergency dispatch protocols. Always consult licensed medical practitioners for health emergencies.
