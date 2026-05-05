# Sensei Wiki

A domain-agnostic conversational agent that researches any topic, compiles a living knowledge wiki in Obsidian, and teaches through Socratic voice interaction.

Built for **GOSIM Agentic Hackathon 2026 · STATION F, Paris**.

**Stack:** Python FastAPI + React + Speechmatics + GLM-Z1 (Z.AI R9S) + MiniMax + Tavily + ChromaDB + Obsidian

---

## Setup

### 1. Configure environment

```bash
cp .env.example backend/.env
# Fill in all API keys in backend/.env
```

### 2. Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. Obsidian

1. Download Obsidian from obsidian.md (free)
2. Open the `obsidian-vault/` folder as a vault
3. Enable Graph View (built-in plugin)
4. Position Obsidian on the right half of your screen

---

## Run

```bash
# Terminal 1 — Backend
cd backend && uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
# Opens at http://localhost:5173
```

---

## Usage

- **Research:** Say "I want to learn about [topic]"
- **Query:** Ask any question about researched topics
- **Quiz:** Say "Quiz me"
- **Note:** Say "Add a note: [your note]"
- **Sources:** Say "Review my sources" or use the sidebar
- **Study plan:** Say "What should I study more?"

---

## Architecture

```
raw/        → immutable source material (scraped + uploaded)
wiki/       → LLM-compiled concept pages (living documents)
ChromaDB    → index over wiki pages (not raw sources)
```

Under 50 wiki pages: LLM reads index.md directly.
Over 50 wiki pages: ChromaDB over wiki pages for retrieval.

---

MIT License · Built at GOSIM Agentic Hackathon 2026
