# BIM AI IFC Query Platform

This is a lightweight Streamlit platform for querying IFC building models with LangChain, DeepSeek, and IfcOpenShell.

Each uploaded IFC file becomes a project. Each project can have multiple conversations, and every conversation keeps its own system prompt and chat history.

## Features

- IFC parsing and model queries through `IfcOpenShell`
- LLM tool calling through `LangChain`
- Local project, prompt, and chat storage with `SQLite`
- Browser-based IFC viewer inside the Streamlit app
- Optional IFC editing tools for explicit update and delete requests

## Requirements

- Python 3.11 or newer
- A DeepSeek API key
- Internet access for the embedded IFC viewer frontend dependency

## Setup

Clone the repository and enter the project directory:

```powershell
git clone https://github.com/yixinhenry/bim-ai-ifc-query-platform.git
cd bim-ai-ifc-query-platform
```

Create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set your API key:

```text
DEEPSEEK_API_KEY=your_deepseek_api_key
BIM_AI_MODEL=deepseek-v4-flash
BIM_AI_BASE_URL=https://api.deepseek.com
BIM_AI_TEMPERATURE=0
BIM_AI_DATA_DIR=data
```

Run the app:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the URL printed by Streamlit, usually `http://localhost:8501`.

## Workflow

1. Upload an IFC file in the left sidebar to create a project.
2. Open the project and create a new conversation.
3. Enter a system prompt for that conversation.
4. Ask questions about the IFC model in the chat panel.

Runtime data is stored under `BIM_AI_DATA_DIR`. The default is the local `data` folder, which is ignored by Git.

## Sample IFC Files

The `ifc_files` folder contains public sample IFC files for local testing. See `ifc_files/SOURCES.txt` for source information.

## Notes

The app is intended for research and local experimentation. IFC modification tools write changes back to the uploaded project IFC file only when the user explicitly asks for an update or deletion.
