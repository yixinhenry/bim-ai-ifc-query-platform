from __future__ import annotations

import os
import time
from typing import Any

from bim_ai import ifc_tools


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
REQUEST_INTERVAL = 0

MODEL_NAME = os.getenv("BIM_AI_MODEL", DEEPSEEK_MODEL)
BASE_URL = os.getenv("BIM_AI_BASE_URL", DEEPSEEK_BASE_URL)
TEMPERATURE = float(os.getenv("BIM_AI_TEMPERATURE", "0"))
MAX_HISTORY_MESSAGES = int(os.getenv("BIM_AI_MAX_HISTORY_MESSAGES", "20"))


def _require_langchain() -> None:
    missing = []
    for module in ["langchain_core", "langchain_openai"]:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        raise RuntimeError(
            "LangChain packages are not installed. Install dependencies with `pip install -r requirements.txt`."
        )


def _build_tools(ifc_path: str):
    from langchain_core.tools import StructuredTool

    def model_overview() -> str:
        """Return IFC schema, entity count, and common entity types."""
        return ifc_tools.model_overview(ifc_path)

    def list_entities_by_type(ifc_type: str, limit: int = 50) -> str:
        """List IFC entities by IFC type."""
        return ifc_tools.list_entities_by_type(ifc_path, ifc_type, int(limit))

    def get_entity_by_global_id(global_id: str) -> str:
        """Get detailed IFC entity information by GlobalId."""
        return ifc_tools.get_entity_by_global_id(ifc_path, global_id)

    def get_entity_by_step_id(step_id: int) -> str:
        """Get detailed IFC entity information by STEP id."""
        return ifc_tools.get_entity_by_step_id(ifc_path, int(step_id))

    def get_property_sets(global_id: str) -> str:
        """Get property sets and quantity sets by GlobalId."""
        return ifc_tools.get_property_sets(ifc_path, global_id)

    def find_by_attribute(ifc_type: str, attribute: str, value: str, limit: int = 50) -> str:
        """Find IFC entities by simple attribute text matching."""
        return ifc_tools.find_by_attribute(ifc_path, ifc_type, attribute, value, int(limit))

    def get_spatial_structure() -> str:
        """Return project, site, building, storey, and space entities."""
        return ifc_tools.spatial_structure(ifc_path)

    return [
        StructuredTool.from_function(
            name="ifc_model_overview",
            description="Return IFC schema, entity count, and the most common IFC entity types.",
            func=model_overview,
        ),
        StructuredTool.from_function(
            name="ifc_list_entities_by_type",
            description="List IFC entities by IFC type, such as IfcWall, IfcDoor, IfcSpace, or IfcBuildingStorey.",
            func=list_entities_by_type,
        ),
        StructuredTool.from_function(
            name="ifc_get_entity_by_global_id",
            description="Get detailed IFC entity information by GlobalId.",
            func=get_entity_by_global_id,
        ),
        StructuredTool.from_function(
            name="ifc_get_entity_by_step_id",
            description="Get detailed IFC entity information by STEP id.",
            func=get_entity_by_step_id,
        ),
        StructuredTool.from_function(
            name="ifc_get_property_sets",
            description="Get property sets and quantity sets for one IFC entity by GlobalId.",
            func=get_property_sets,
        ),
        StructuredTool.from_function(
            name="ifc_find_by_attribute",
            description="Find IFC entities by simple attribute text matching. Parameters: ifc_type, attribute, value, limit.",
            func=find_by_attribute,
        ),
        StructuredTool.from_function(
            name="ifc_spatial_structure",
            description="Return project, site, building, storey, and space entities.",
            func=get_spatial_structure,
        ),
    ]


def _to_lc_history(messages: list[dict[str, Any]], max_history: int):
    from langchain_core.messages import AIMessage, HumanMessage

    lc_messages = []
    for msg in messages[-max_history:]:
        if msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_messages.append(AIMessage(content=msg["content"]))
    return lc_messages


def run_ifc_agent(
    ifc_path: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> str:
    _require_langchain()
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    if REQUEST_INTERVAL > 0:
        time.sleep(REQUEST_INTERVAL)

    tools = _build_tools(ifc_path)
    llm = ChatOpenAI(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        base_url=BASE_URL,
        api_key=DEEPSEEK_API_KEY,
    )
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=(
            system_prompt
            + "\n\nUse IFC tools for model facts. Respect the user's role and permission policy. "
            "Return concise answers with relevant GlobalIds, STEP ids, and IFC types when available."
        ),
    )
    history = _to_lc_history(messages[:-1], MAX_HISTORY_MESSAGES)
    user_input = messages[-1]["content"] if messages else ""
    result = agent.invoke({"messages": [*history, HumanMessage(content=user_input)]})
    final_message = result["messages"][-1]
    return str(final_message.content)
