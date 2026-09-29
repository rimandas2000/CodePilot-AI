# CodePilot AI — GenAI + RAG Coding Workspace

CodePilot AI is a Streamlit-based coding workspace with a redesigned dark/orange interface, local code execution, local RAG, and switchable AI backends.

## Included pages

- Sign In / Create Account
- Home with a general-purpose AI chat box
- AI Mentor Chat (coding-focused + optional local RAG)
- Compiler / Run Code
- Debug & Fix
- Explain Code
- Improve Code
- Generate Tests
- Convert Code
- Dashboard
- Recent Activity
- Settings
- About

The old **Resources** block (Cheat Sheets / Project Ideas / Documentation) has been removed from the navigation.

## AI providers

Open **Settings** in the app to switch between:

1. **Local Ollama** — no cloud API key required.
2. **OpenAI / ChatGPT API** — enter your OpenAI API key and model.
3. **Google Gemini API** — enter your Gemini API key and model.
4. **Groq API** — optional additional OpenAI-compatible provider.

The **Cloud AI APIs** toggle controls routing:

- OFF → requests use Ollama.
- ON → requests use the selected cloud provider.

The **Use local RAG knowledge** toggle is independent, so ChromaDB context can be used with either Ollama or a cloud provider.

API keys can be entered in Settings or supplied through environment variables. For shared/cloud deployments, environment secrets are recommended.

## Windows setup

### 1. Install prerequisites

- Python 3.11 or 3.12
- Ollama (only required if you want local AI)
- Optional compilers/runtimes for the Run Code page:
  - GCC / G++ for C/C++
  - JDK for Java
  - Node.js for JavaScript

### 2. Open this folder in VS Code

```powershell
cd CodePilot_AI
```

### 3. Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

Or use Command Prompt:

```bat
.venv\Scripts\activate.bat
```

### 4. Install packages

```powershell
python -m pip install -r requirements.txt
```

### 5. Optional: prepare Ollama

```powershell
ollama pull qwen2.5-coder:7b
```

Make sure Ollama is running.

### 6. Build / refresh the local RAG database

```powershell
python backend/ingest.py
```

### 7. Start CodePilot AI

```powershell
python -m streamlit run backend/app.py
```

Open the local address Streamlit prints, normally:

```text
http://localhost:8501
```

You can also run `start_windows.bat`.

## Cloud API configuration

You can configure everything from the **Settings** page. Alternatively copy `.env.example` to `.env` and fill in the values you want.

Example:

```env
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:7b

OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
```

The model fields are editable in Settings, so use a model that your API account actually has access to.

## Privacy notes

- Local account credentials are stored in `data/users.json` using PBKDF2-SHA256 for new/updated passwords.
- Local Ollama prompts stay on the machine running Ollama.
- ChromaDB knowledge stays in the project folder.
- When a cloud provider is enabled, prompts sent through AI features are transmitted to that provider.
- If **Remember API keys locally** is enabled, keys are stored in `data/settings.json`. For a shared repository, use environment secrets instead.

## Dashboard reset

The supplied project package starts with a fresh `data/usage.json`, so previous Dashboard progress and Recent Activity are reset. You can reset them again at any time from **Settings → Reset workspace progress / activity**.

## Important local execution note

The Compiler / Run Code feature executes code on the computer running Streamlit. Only execute code you trust.
