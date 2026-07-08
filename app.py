from __future__ import annotations

from pathlib import Path

import streamlit as st
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


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("E:/BIM_AI_Data")
PROJECT_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "app.db"


def save_uploaded_ifc(uploaded_file, project_name: str) -> Path:
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    safe_project = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in project_name).strip("_")
    safe_project = safe_project or "project"
    target_dir = PROJECT_DIR / safe_project
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / uploaded_file.name
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
    conversation = get_conversation(DB_PATH, conversation_id)
    messages = list_messages(DB_PATH, conversation_id)

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

    add_message(DB_PATH, conversation_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Querying IFC model with LangChain tools..."):
            updated_messages = list_messages(DB_PATH, conversation_id)
            try:
                answer = run_ifc_agent(
                    ifc_path=project["ifc_path"],
                    system_prompt=conversation["system_prompt"],
                    messages=updated_messages,
                )
            except Exception as exc:
                answer = f"Agent execution failed: `{exc}`"
            st.markdown(answer)
    add_message(DB_PATH, conversation_id, "assistant", answer)
    st.rerun()


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="BIM AI IFC Query", layout="wide")
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
        return

    render_chat(project_id, conversation_id)


if __name__ == "__main__":
    main()
