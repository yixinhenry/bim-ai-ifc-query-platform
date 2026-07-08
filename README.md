# BIM AI IFC Query Platform

This is a LangChain-based experimental platform for AI in BIM security research.

The platform is organized around IFC projects. Each uploaded IFC file becomes one project. A project can contain multiple conversations, and every conversation has its own required system prompt and chat history.

## Core Design

- `IfcOpenShell` handles trusted IFC parsing and querying.
- `LangChain` connects the LLM with IFC query tools.
- `SQLite` persists projects, conversations, system prompts, and messages.
- `Streamlit` provides the first UI with a project sidebar and chat workspace.

## Setup

```powershell
$env:PIP_CACHE_DIR="E:\BIM_AI_Deps\pip-cache"
python -m venv E:\BIM_AI_Deps\bim-ai-ifc
E:\BIM_AI_Deps\bim-ai-ifc\Scripts\python.exe -m pip install --cache-dir E:\BIM_AI_Deps\pip-cache -r requirements.txt
```

Model configuration is kept in code/environment variables, not in the UI. Create `.env`:

```text
DEEPSEEK_API_KEY=your_api_key
BIM_AI_MODEL=deepseek-v4-flash
BIM_AI_BASE_URL=https://api.deepseek.com
BIM_AI_TEMPERATURE=0
```

Run:

```powershell
E:\BIM_AI_Deps\bim-ai-ifc\Scripts\python.exe -m streamlit run app.py
```

Runtime data is stored under `E:\BIM_AI_Data`, including the SQLite database and uploaded IFC files.

## Workflow

1. Upload an IFC file in the left sidebar to create a project.
2. Create a new chat under that project and enter a system prompt.
3. Ask IFC questions in the chat.

Each conversation preserves its own system prompt and message history, so different user identities, access policies, and query constraints can be tested independently.
