from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv

from bim_ai import ifc_tools


load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
REQUEST_INTERVAL = 0

MODEL_NAME = os.getenv("BIM_AI_MODEL", DEEPSEEK_MODEL)
BASE_URL = os.getenv("BIM_AI_BASE_URL", DEEPSEEK_BASE_URL)
TEMPERATURE = float(os.getenv("BIM_AI_TEMPERATURE", "0"))
MAX_HISTORY_MESSAGES = int(os.getenv("BIM_AI_MAX_HISTORY_MESSAGES", "20"))
LogCallback = Callable[[str, str], None]


def _emit_log(log_callback: LogCallback | None, content: str, level: str = "info") -> None:
    if log_callback is not None:
        log_callback(content, level)


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


def _build_tools(ifc_path: str, log_callback: LogCallback | None = None):
    from langchain_core.tools import StructuredTool

    def call_tool(tool_name: str, detail: str, func, *args, **kwargs):
        _emit_log(log_callback, f"开始 {tool_name}：{detail}")
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            _emit_log(log_callback, f"{tool_name} 失败：{exc}", "error")
            raise
        _emit_log(log_callback, f"完成 {tool_name}")
        return result

    def model_overview() -> str:
        """Return IFC schema, entity count, and common entity types."""
        return call_tool("模型概览", "读取 schema、实体数量和常见实体类型", ifc_tools.model_overview, ifc_path)

    def list_entities_by_type(ifc_type: str, limit: int = 50) -> str:
        """List IFC entities by IFC type."""
        return call_tool(
            "按类型查询实体",
            f"类型={ifc_type}，上限={limit}",
            ifc_tools.list_entities_by_type,
            ifc_path,
            ifc_type,
            int(limit),
        )

    def get_entity_by_global_id(global_id: str) -> str:
        """Get detailed IFC entity information by GlobalId."""
        return call_tool(
            "按 GlobalId 查询实体",
            f"GlobalId={global_id}",
            ifc_tools.get_entity_by_global_id,
            ifc_path,
            global_id,
        )

    def get_entity_by_step_id(step_id: int) -> str:
        """Get detailed IFC entity information by STEP id."""
        return call_tool(
            "按 STEP id 查询实体",
            f"STEP id={step_id}",
            ifc_tools.get_entity_by_step_id,
            ifc_path,
            int(step_id),
        )

    def get_property_sets(global_id: str) -> str:
        """Get property sets and quantity sets by GlobalId."""
        return call_tool(
            "读取属性集",
            f"GlobalId={global_id}",
            ifc_tools.get_property_sets,
            ifc_path,
            global_id,
        )

    def find_by_attribute(ifc_type: str, attribute: str, value: str, limit: int = 50) -> str:
        """Find IFC entities by simple attribute text matching."""
        return call_tool(
            "按属性查找实体",
            f"类型={ifc_type}，属性={attribute}，值包含={value}，上限={limit}",
            ifc_tools.find_by_attribute,
            ifc_path,
            ifc_type,
            attribute,
            value,
            int(limit),
        )

    def get_spatial_structure() -> str:
        """Return project, site, building, storey, and space entities."""
        return call_tool("读取空间结构", "读取项目、场地、建筑、楼层和空间", ifc_tools.spatial_structure, ifc_path)

    def update_text_attribute_by_global_id(global_id: str, attribute: str, value: str) -> str:
        """Write a modified IFC copy after changing one editable text attribute by GlobalId."""
        return call_tool(
            "修改文本属性",
            f"GlobalId={global_id}，属性={attribute}",
            ifc_tools.update_text_attribute_by_global_id,
            ifc_path,
            global_id,
            attribute,
            value,
        )

    def update_text_attribute_by_step_id(step_id: int, attribute: str, value: str) -> str:
        """Write a modified IFC copy after changing one editable text attribute by STEP id."""
        return call_tool(
            "修改文本属性",
            f"STEP id={step_id}，属性={attribute}",
            ifc_tools.update_text_attribute_by_step_id,
            ifc_path,
            int(step_id),
            attribute,
            value,
        )

    def update_property_single_value(global_id: str, pset_name: str, property_name: str, value: str) -> str:
        """Write a modified IFC copy after changing an existing IfcPropertySingleValue."""
        return call_tool(
            "修改属性集值",
            f"GlobalId={global_id}，属性集={pset_name}，属性={property_name}",
            ifc_tools.update_property_single_value,
            ifc_path,
            global_id,
            pset_name,
            property_name,
            value,
        )

    def delete_product_by_global_id(global_id: str) -> str:
        """Write a modified IFC copy after deleting one supported IFC product by GlobalId."""
        return call_tool(
            "删除 IFC 产品",
            f"GlobalId={global_id}",
            ifc_tools.delete_product_by_global_id,
            ifc_path,
            global_id,
        )

    def delete_product_by_step_id(step_id: int) -> str:
        """Write a modified IFC copy after deleting one supported IFC product by STEP id."""
        return call_tool(
            "删除 IFC 产品",
            f"STEP id={step_id}",
            ifc_tools.delete_product_by_step_id,
            ifc_path,
            int(step_id),
        )

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
        StructuredTool.from_function(
            name="ifc_update_text_attribute_by_global_id",
            description=(
                "Modify an editable text attribute on one IFC entity by GlobalId and write a new IFC copy. "
                "Editable attributes: Name, Description, ObjectType, LongName, Tag. "
                "Use only when the user explicitly asks to change the IFC file."
            ),
            func=update_text_attribute_by_global_id,
        ),
        StructuredTool.from_function(
            name="ifc_update_text_attribute_by_step_id",
            description=(
                "Modify an editable text attribute on one IFC entity by STEP id and write a new IFC copy. "
                "Editable attributes: Name, Description, ObjectType, LongName, Tag. "
                "Use only when the user explicitly asks to change the IFC file."
            ),
            func=update_text_attribute_by_step_id,
        ),
        StructuredTool.from_function(
            name="ifc_update_property_single_value",
            description=(
                "Modify an existing IfcPropertySingleValue in a property set for one entity by GlobalId and "
                "write a new IFC copy. Use only when the user explicitly asks to change the IFC file."
            ),
            func=update_property_single_value,
        ),
        StructuredTool.from_function(
            name="ifc_delete_product_by_global_id",
            description=(
                "Delete one supported IFC product by GlobalId and write a new IFC copy. "
                "Supported targets include IfcElement, IfcElementType, IfcSpatialElement, "
                "IfcSpatialElementType, and IfcAnnotation. Use only when the user explicitly asks to delete."
            ),
            func=delete_product_by_global_id,
        ),
        StructuredTool.from_function(
            name="ifc_delete_product_by_step_id",
            description=(
                "Delete one supported IFC product by STEP id and write a new IFC copy. "
                "Supported targets include IfcElement, IfcElementType, IfcSpatialElement, "
                "IfcSpatialElementType, and IfcAnnotation. Use this for requests like 'delete door #978497'."
            ),
            func=delete_product_by_step_id,
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
    log_callback: LogCallback | None = None,
) -> str:
    _emit_log(log_callback, "检查 LangChain 和 IFC 依赖")
    _require_langchain()
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    if REQUEST_INTERVAL > 0:
        time.sleep(REQUEST_INTERVAL)

    _emit_log(log_callback, f"载入当前对话记忆：{max(0, len(messages) - 1)} 条历史消息")
    tools = _build_tools(ifc_path, log_callback)
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
            "Return concise answers with relevant GlobalIds, STEP ids, and IFC types when available. "
            "IFC modification tools may be used only when the user explicitly requests a change. "
            "IFC deletion tools may be used only when the user explicitly requests deletion of a specific target. "
            "This project has one working IFC file. Apply explicit changes in place and report that same project IFC path."
        ),
    )
    _emit_log(log_callback, f"Agent 已准备，当前项目 IFC：{ifc_path}")
    history = _to_lc_history(messages[:-1], MAX_HISTORY_MESSAGES)
    user_input = messages[-1]["content"] if messages else ""
    result = agent.invoke({"messages": [*history, HumanMessage(content=user_input)]})
    final_message = result["messages"][-1]
    _emit_log(log_callback, "Agent 已完成回答")
    return str(final_message.content)
