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
AuditCallback = Callable[[str, str, dict[str, Any]], None]


def _emit_log(log_callback: LogCallback | None, content: str, level: str = "info") -> None:
    if log_callback is not None:
        log_callback(content, level)


def _emit_audit(audit_callback: AuditCallback | None, event_type: str, status: str, payload: dict[str, Any]) -> None:
    if audit_callback is not None:
        audit_callback(event_type, status, payload)


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


def _build_tools(
    ifc_path: str,
    log_callback: LogCallback | None = None,
    audit_callback: AuditCallback | None = None,
):
    from langchain_core.tools import StructuredTool

    def call_tool(tool_name: str, detail: str, func, *args, **kwargs):
        _emit_log(log_callback, f"开始 {tool_name}：{detail}")
        _emit_audit(audit_callback, "tool_call", "started", {"tool": tool_name, "detail": detail})
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            _emit_log(log_callback, f"{tool_name} 失败：{exc}", "error")
            _emit_audit(audit_callback, "tool_call", "error", {"tool": tool_name, "detail": detail, "error": str(exc)})
            raise
        _emit_log(log_callback, f"完成 {tool_name}")
        _emit_audit(audit_callback, "tool_call", "completed", {"tool": tool_name, "detail": detail, "result": str(result)[:12000]})
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

    def list_openings_with_filling_status(limit: int = 50) -> str:
        """List wall openings with host and filling status, including empty openings."""
        return call_tool(
            "查询洞口状态",
            f"上限={limit}",
            ifc_tools.list_openings_with_filling_status,
            ifc_path,
            int(limit),
        )

    def get_entity_relations_by_step_id(step_id: int) -> str:
        """Return an entity's container, type, material, openings, fillings, and inverse IFC relations."""
        return call_tool(
            "查询实体关系",
            f"STEP id={step_id}",
            ifc_tools.get_entity_relations_by_step_id,
            ifc_path,
            int(step_id),
        )

    def validate_ifc_model() -> str:
        """Validate the IFC model against schema constraints."""
        return call_tool("校验 IFC 模型", "检查 schema 约束", ifc_tools.validate_ifc_model, ifc_path)

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

    def edit_property_set_by_global_id(global_id: str, pset_name: str, properties: dict[str, Any]) -> str:
        """Create or batch-edit a property set. Use null to remove a property."""
        return call_tool(
            "批量修改属性集",
            f"GlobalId={global_id}，属性集={pset_name}",
            ifc_tools.edit_property_set_by_global_id,
            ifc_path,
            global_id,
            pset_name,
            properties,
        )

    def place_product_by_step_id(
        step_id: int,
        x: float,
        y: float,
        z: float,
        rotation_z_degrees: float = 0.0,
    ) -> str:
        """Set a product world position in metres and optional Z-axis rotation."""
        return call_tool(
            "移动构件",
            f"STEP id={step_id}，位置=({x}, {y}, {z})，Z旋转={rotation_z_degrees}",
            ifc_tools.place_product_by_step_id,
            ifc_path,
            int(step_id),
            float(x),
            float(y),
            float(z),
            float(rotation_z_degrees),
        )

    def copy_product_by_step_id(
        source_step_id: int,
        x: float,
        y: float,
        z: float,
        rotation_z_degrees: float = 0.0,
        name: str = "",
    ) -> str:
        """Copy a non-door/non-window product and place the copy in metres."""
        return call_tool(
            "复制构件",
            f"源 STEP id={source_step_id}，位置=({x}, {y}, {z})，Z旋转={rotation_z_degrees}",
            ifc_tools.copy_product_by_step_id,
            ifc_path,
            int(source_step_id),
            float(x),
            float(y),
            float(z),
            float(rotation_z_degrees),
            name,
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

    def fill_unfilled_opening_by_step_id(opening_step_id: int) -> str:
        """Remove an empty IfcOpeningElement to restore its host wall body."""
        return call_tool(
            "填补墙体洞口",
            f"洞口 STEP id={opening_step_id}",
            ifc_tools.fill_unfilled_opening_by_step_id,
            ifc_path,
            int(opening_step_id),
        )

    def restore_window_from_template_by_opening_step_id(
        opening_step_id: int,
        template_window_step_id: int,
        name: str = "",
    ) -> str:
        """Restore a window into an empty opening by copying an existing IfcWindow template."""
        return call_tool(
            "从模板恢复窗口",
            f"洞口 STEP id={opening_step_id}，模板窗 STEP id={template_window_step_id}",
            ifc_tools.restore_window_from_template_by_opening_step_id,
            ifc_path,
            int(opening_step_id),
            int(template_window_step_id),
            name,
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
            name="ifc_list_openings_with_filling_status",
            description=(
                "List IfcOpeningElement entities with their host elements and filling windows or doors. "
                "Use this to find an empty opening before restoring a deleted window or filling a wall hole."
            ),
            func=list_openings_with_filling_status,
        ),
        StructuredTool.from_function(
            name="ifc_get_entity_relations_by_step_id",
            description="Return an entity's container, type, material, openings, fillings, and inverse IFC relations by STEP id.",
            func=get_entity_relations_by_step_id,
        ),
        StructuredTool.from_function(
            name="ifc_validate_model",
            description="Validate the IFC model against schema constraints and report issues.",
            func=validate_ifc_model,
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
            name="ifc_edit_property_set_by_global_id",
            description=(
                "Create or batch-edit an IFC property set by GlobalId. The properties input is a JSON object; "
                "a null value removes the named property. Use only for explicit file edits."
            ),
            func=edit_property_set_by_global_id,
        ),
        StructuredTool.from_function(
            name="ifc_place_product_by_step_id",
            description=(
                "Set a product's world position in metres and optional Z-axis rotation by STEP id. "
                "Use only for explicit file edits."
            ),
            func=place_product_by_step_id,
        ),
        StructuredTool.from_function(
            name="ifc_copy_product_by_step_id",
            description=(
                "Copy a non-door/non-window product and place it at world coordinates in metres. "
                "Use the window restoration tool for windows and doors."
            ),
            func=copy_product_by_step_id,
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
        StructuredTool.from_function(
            name="ifc_fill_unfilled_opening_by_step_id",
            description=(
                "Remove an empty IfcOpeningElement, restoring the original host wall geometry. "
                "Use only when the user explicitly asks to fill an empty hole after a window or door was deleted."
            ),
            func=fill_unfilled_opening_by_step_id,
        ),
        StructuredTool.from_function(
            name="ifc_restore_window_from_template_by_opening_step_id",
            description=(
                "Restore a window in an empty opening by copying an existing IfcWindow template. "
                "Use this for requests to restore a deleted window when the empty opening and a matching template window are known."
            ),
            func=restore_window_from_template_by_opening_step_id,
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
    audit_callback: AuditCallback | None = None,
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
    tools = _build_tools(ifc_path, log_callback, audit_callback)
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
            "For a deleted window, inspect openings to find the empty opening, then restore it from a matching existing window template. "
            "For filling a wall hole, use the empty-opening tool only after verifying the opening has no filling. "
            "This project has one working IFC file. Apply explicit changes in place and report that same project IFC path."
        ),
    )
    _emit_log(log_callback, f"Agent 已准备，当前项目 IFC：{ifc_path}")
    history = _to_lc_history(messages[:-1], MAX_HISTORY_MESSAGES)
    user_input = messages[-1]["content"] if messages else ""
    _emit_audit(audit_callback, "agent_run", "started", {"model": MODEL_NAME, "user_input": user_input})
    try:
        result = agent.invoke({"messages": [*history, HumanMessage(content=user_input)]})
    except Exception as exc:
        _emit_audit(audit_callback, "agent_run", "error", {"error": str(exc)})
        raise
    final_message = result["messages"][-1]
    _emit_log(log_callback, "Agent 已完成回答")
    answer = str(final_message.content)
    _emit_audit(audit_callback, "agent_run", "completed", {"answer": answer[:12000]})
    return answer
