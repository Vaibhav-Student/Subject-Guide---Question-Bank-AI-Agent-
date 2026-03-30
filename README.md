# AskiFy - AI Academic Assistant

A premium, glassmorphic AI academic assistant allowing users to upload documents (RAG) and chat with multiple AI providers (Gemini, OpenAI).

## Features

- **Robust Error Handling**: Safely parses JSON responses and catches API/Network errors to prevent UI crashes.
- **Multiple AI Providers**: Seamlessly switch between Google Gemini and OpenAI models.
- **Secure Key Management**: API keys are securely stored and retrieved from your browser's local storage.
- **Premium UI/UX**: Built with Vanilla CSS, featuring responsive fluid layouts, CSS Variables for theming, and glassmorphic micro-animations.

## Implementation Details

Core components are located in `frontend/src/`
- `api.js`: Contains a `safeFetch` wrapper with type guards.
- `config/toolsData.js`: Centralized data structure for AI Tools and Models.
- `components/ToolSelector.jsx` & `ModelSelector.jsx`: Dynamic selection UIs.
- `components/ApiKeyInput.jsx`: Secures and saves keys to `localStorage`.

## How to Run Locally

### 1. Start the Backend (Flask API)
Open a new terminal window at the project root:

```powershell
.\venv\Scripts\activate
pip install -r requirements.txt
python app_api.py
```

### 2. Start the Frontend (React Vite App)
Open a second terminal window at the project root:

```powershell
cd frontend
npm install
npm run dev
```

> **Note**: For actual model generation to work, the backend (`app_api.py` and `rag_engine.py`) must be updated to accept the `provider`, `model`, and `api_key` payload parameters sent from `ChatArea.jsx`. The frontend UI and error handling MVP is currently complete.
