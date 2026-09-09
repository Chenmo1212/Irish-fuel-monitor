# Fly.io Telegram Bot Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Before dispatching subagents, analyze tasks for parallelism and group into batches. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure and deploy the Telegram-only fuel monitor bot on Fly.io using a persistent volume for SQLite storage.

**Architecture:** A lightweight single-process container running the Telegram Bot with background scheduling, accessing a persistent SQLite database located at a Fly.io Volume.

**Tech Stack:** Docker, Fly.io CLI (flyctl), Python 3.11.

**Spec:** No architectural spec file needed (this is a Bounded task).

## Global Constraints
- Target container runtime: Python 3.11-slim
- Working directory: `/app`
- Database location: `/app/data/fuel.db` (bound to persistent volume `/app/data`)
- No public HTTP port required (pure Telegram bot worker/polling service)

---

## Tasks

### Task 1: Create `.dockerignore`

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Write `.dockerignore` content**
- [ ] **Step 2: Verify file is in root directory**
- [ ] **Step 3: Commit `.dockerignore`**

---

### Task 2: Create `Dockerfile`

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Write `Dockerfile` with Python 3.11-slim, installing dependencies from requirements.txt, copying app code, and launching `bot.py`**
- [ ] **Step 2: Verify Dockerfile syntax**
- [ ] **Step 3: Commit `Dockerfile`**

---

### Task 3: Create `fly.toml`

**Files:**
- Create: `fly.toml`

- [ ] **Step 1: Write `fly.toml` containing application details, regions, and persistent volume mounting to `/app/data`**
- [ ] **Step 2: Verify fly.toml format**
- [ ] **Step 3: Commit `fly.toml`**
