from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
from uuid import uuid4

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from bim_ai.agent import MODEL_NAME, run_ifc_agent
from bim_ai.storage import (
    add_message,
    create_conversation,
    create_project,
    get_conversation,
    get_project,
    init_db,
    list_conversations,
    list_messages,
    list_projects,
)
from bim_ai.viewer_server import start_viewer_server


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def runtime_path(env_name: str, default: str) -> Path:
    path = Path(os.getenv(env_name, default)).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


DATA_DIR = runtime_path("BIM_AI_DATA_DIR", "data")
PROJECT_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "app.db"


@st.cache_resource
def get_viewer_base_url(db_path: str) -> str:
    return start_viewer_server(Path(db_path))


def render_viewer_css() -> None:
    st.markdown(
        """
        <style>
        .st-key-ifc-viewer-panel {
            position: fixed;
            top: 3.5rem;
            left: 20rem;
            right: auto;
            width: calc(100vw - 45rem) !important;
            min-width: 0 !important;
            max-width: none !important;
            height: calc(100vh - 4.5rem);
            box-sizing: border-box;
            z-index: 2;
            overflow: hidden;
            background: #111820;
        }
        .st-key-chat-panel {
            position: fixed;
            top: 3.5rem;
            right: 1rem;
            width: 23rem;
            height: calc(100vh - 4.5rem);
            box-sizing: border-box;
            overflow-y: auto;
            padding: 0 0.5rem 2rem;
            z-index: 4;
        }
        .st-key-ifc-viewer-panel iframe {
            width: 100% !important;
            height: calc(100vh - 7rem) !important;
        }
        @media (max-width: 1100px) {
            .st-key-ifc-viewer-panel {
                position: static;
                left: auto;
                right: auto;
                height: auto;
                background: transparent;
            }
            .st-key-ifc-viewer-panel iframe {
                height: 620px !important;
            }
            .st-key-chat-panel {
                position: static;
                width: auto;
                height: auto;
                overflow: visible;
                padding: 0;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def save_uploaded_ifc(uploaded_file, project_name: str) -> Path:
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    safe_project = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in project_name).strip("_")
    safe_project = safe_project or "project"
    target_dir = PROJECT_DIR / f"{safe_project}_{uuid4().hex[:8]}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "model.ifc"
    target.write_bytes(uploaded_file.getbuffer())
    return target


def render_sidebar() -> tuple[int | None, int | None]:
    st.sidebar.caption(f"Model: {MODEL_NAME}")
    st.sidebar.divider()
    st.session_state.setdefault("project_id", None)
    st.session_state.setdefault("conversation_id", None)

    with st.sidebar.expander("New project", expanded=False):
        uploaded = st.file_uploader("IFC file", type=["ifc"], accept_multiple_files=False)
        project_name = st.text_input("Project name")
        if st.button("Create project", use_container_width=True):
            if uploaded is None:
                st.error("Please upload an IFC file.")
            elif not project_name.strip():
                st.error("Please enter a project name.")
            else:
                ifc_path = save_uploaded_ifc(uploaded, project_name.strip())
                create_project(DB_PATH, project_name.strip(), str(ifc_path), uploaded.name)
                st.rerun()

    projects = list_projects(DB_PATH)
    if not projects:
        st.sidebar.info("No IFC projects found.")
        return None, None

    st.sidebar.markdown("### Projects")

    for project in projects:
        with st.sidebar.expander(project["name"], expanded=False):
            st.caption(project["original_filename"])
            if st.button("Open project", key=f"project-{project['id']}", use_container_width=True):
                st.session_state.project_id = project["id"]
                st.session_state.conversation_id = None
            for conversation in list_conversations(DB_PATH, project["id"]):
                if st.button(conversation["title"], key=f"conversation-{conversation['id']}", use_container_width=True):
                    st.session_state.project_id = project["id"]
                    st.session_state.conversation_id = conversation["id"]
            with st.popover("New chat", use_container_width=True):
                title = st.text_input("Title", key=f"title-{project['id']}")
                system_prompt = st.text_area("System prompt", height=160, key=f"system-{project['id']}")
                if st.button("Create", key=f"create-{project['id']}", use_container_width=True):
                    if not title.strip() or not system_prompt.strip():
                        st.error("Title and system prompt are required.")
                    else:
                        st.session_state.project_id = project["id"]
                        st.session_state.conversation_id = create_conversation(
                            DB_PATH,
                            project["id"],
                            title.strip(),
                            system_prompt.strip(),
                        )
                        st.rerun()

    if st.session_state.project_id is None:
        st.session_state.project_id = projects[0]["id"]
    return st.session_state.project_id, st.session_state.conversation_id


def render_chat(project_id: int, conversation_id: int) -> None:
    project = get_project(DB_PATH, project_id)
    conversation = get_conversation(DB_PATH, conversation_id, project_id)
    messages = list_messages(DB_PATH, conversation_id, project_id)

    with st.container(key="ifc-viewer-panel"):
        render_viewer(project)

    with st.container(key="chat-panel"):
        st.title(conversation["title"])
        st.caption(f'Project: {project["name"]} | IFC: {project["original_filename"]}')

        with st.expander("Conversation system prompt", expanded=False):
            st.code(conversation["system_prompt"], language="text")

        for msg in messages:
            if msg["role"] in {"user", "assistant"}:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        prompt = st.chat_input("Ask about this IFC model")
        if not prompt:
            return

        add_message(DB_PATH, conversation_id, "user", prompt, project_id)
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.status("Processing IFC...", expanded=True) as status:
                st.write("Loading this conversation's isolated memory")

                log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
                result_queue: queue.Queue[tuple[str, object]] = queue.Queue()

                def show_log(message: str, level: str = "info") -> None:
                    log_queue.put((level, message))

                updated_messages = list_messages(DB_PATH, conversation_id, project_id)

                def run_agent() -> None:
                    try:
                        result = run_ifc_agent(
                            ifc_path=project["ifc_path"],
                            system_prompt=conversation["system_prompt"],
                            messages=updated_messages,
                            log_callback=show_log,
                        )
                        result_queue.put(("ok", result))
                    except Exception as exc:
                        result_queue.put(("error", exc))

                worker = threading.Thread(target=run_agent, daemon=True)
                worker.start()
                while worker.is_alive() or not log_queue.empty():
                    try:
                        level, message = log_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if level == "error":
                        st.error(message)
                    else:
                        st.write(message)

                worker.join()
                outcome, value = result_queue.get()
                if outcome == "error":
                    exc = value
                    detail = repr(exc) or type(exc).__name__
                    answer = f"Agent execution failed ({type(exc).__name__}): `{detail}`"
                    st.error(f"{type(exc).__name__}: {detail}")
                    status.update(label="IFC processing failed", state="error")
                else:
                    answer = str(value)
                    status.update(label="IFC processing complete", state="complete")
                st.markdown(answer)
        add_message(DB_PATH, conversation_id, "assistant", answer, project_id)
        st.rerun()


def render_viewer(project: dict) -> None:
    model_path = Path(project["ifc_path"])
    if not model_path.is_file():
        st.warning("The project IFC file is unavailable.")
        return
    version = f"{model_path.stat().st_mtime_ns}-{model_path.stat().st_size}"
    st.caption(f"IFC version: {version}")
    viewer_url = get_viewer_base_url(str(DB_PATH))
    components.iframe(
        f"{viewer_url}/?project_id={project['id']}&v={version}",
        height=720,
        scrolling=False,
    )


def main() -> None:
    st.set_page_config(page_title="BIM AI IFC Query", layout="wide")
    render_viewer_css()
    init_db(DB_PATH)

    project_id, conversation_id = render_sidebar()
    if project_id is None:
        st.title("BIM AI IFC Query Platform")
        st.info("Create a project from an IFC file to begin.")
        return
    if conversation_id is None:
        project = get_project(DB_PATH, project_id)
        st.title(project["name"])
        st.info("Create a conversation. A system prompt is required before any query can run.")
        render_viewer(project)
        return

    render_chat(project_id, conversation_id)


if __name__ == "__main__":
    main()
