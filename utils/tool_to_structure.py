from __future__ import annotations
from typing import Type, cast, Any
from pydantic import Field, create_model
from langchain_core.tools import StructuredTool


def wrap_to_structured_tool(base_tool):
    """
    通用适配器：将 MCP 工具转换为 LangChain 的 StructuredTool。

    核心改进：
    1. 使用 (Type, Field) 或 (Type, Default) 元组模式，彻底规避 Optional[p_type] 的 IDE 报红问题。
    2. 避免使用字符串 "Union"，从而根除 Pydantic V2 的 model_rebuild() 报错。
    3. 严格区分必填项（无默认值）和选填项（默认值为 None）。
    """
    # 1. 优先尝试获取底层工具自带的 Schema
    args_schema = getattr(base_tool, 'args_schema', None)

    # 2. 如果自带 Schema 为空，则从 metadata 中动态重建
    if not args_schema:
        metadata = getattr(base_tool, 'metadata', {}) or {}
        parameters = metadata.get('parameters', {})
        properties = parameters.get('properties', {})
        required_fields = parameters.get('required', [])

        if properties:
            fields: dict[str, Any] = {}

            # 类型映射表
            type_mapping = {
                'integer': int,
                'number': float,
                'string': str,
                'boolean': bool,
                'array': list,
                'object': dict
            }

            for param_name, param_info in properties.items():
                # A. 提取基础信息
                raw_type = param_info.get('type', 'string')
                # 使用 cast 告诉 IDE 这是一个 Type，消除潜在警告
                p_type = cast(Type, type_mapping.get(raw_type, str))
                p_desc = param_info.get('description', '')

                # B. 核心逻辑：判断是否必填
                if param_name in required_fields:
                    # 【必填参数】
                    # 格式：(类型, Field对象) -> Pydantic 认为这是必填项
                    fields[param_name] = (
                        p_type,
                        Field(description=p_desc)
                    )
                else:
                    # 【选填参数】
                    # 格式：(类型, 默认值) -> Pydantic 认为这是选填项，且允许为 None
                    # 这种写法比 Optional[p_type] 更稳健，且不会触发 IDE 报红
                    fields[param_name] = (
                        p_type,
                        None  # 这里直接给 None 作为默认值，等同于 Optional
                    )

            # 动态创建 Pydantic 模型
            # 注意：这里的字段名不能包含空格，做一个简单的清洗
            safe_name = base_tool.name.replace(' ', '_').replace('-', '_')
            model_name = f"{safe_name}_Args"

            try:
                args_schema = create_model(model_name, **fields)
            except Exception as e:
                print(f"[Warning] 动态创建 Schema 失败: {e}")
                args_schema = None

    # 3. 构建并返回 StructuredTool
    return StructuredTool.from_function(
        func=base_tool.func,
        name=base_tool.name,
        description=base_tool.description,
        args_schema=args_schema
    )
# from pydantic import Field, create_model
# from langchain_core.tools import StructuredTool
#
#
# def wrap_to_structured_tool(base_tool):
#     """
#     通用适配器：将 python_a2a 的普通 Tool 包装成支持多参数的 StructuredTool。
#     只接收一个参数 base_tool，自动解析其元数据并生成 Pydantic 模型。
#     """
#     # 1. 优先尝试获取底层工具自带的 Schema
#     args_schema = getattr(base_tool, 'args_schema', None)
#
#     # 2. 如果自带 Schema 为空，则从 metadata 中动态重建
#     if not args_schema:
#         metadata = getattr(base_tool, 'metadata', {}) or {}
#         properties = metadata.get('parameters', {}).get('properties', {})
#
#         # 只有当确实存在参数定义时，才动态生成 Pydantic 模型
#         if properties:
#             fields = {}
#             type_mapping = {'integer': int, 'number': float, 'string': str, 'boolean': bool}
#
#             for param_name, param_info in properties.items():
#                 # 提取类型和描述，安全地处理缺失情况
#                 p_type = type_mapping.get(param_info.get('type', 'string'), str)
#                 p_desc = param_info.get('description', '')
#                 fields[param_name] = (p_type, Field(description=p_desc))
#
#             # 动态创建 Pydantic 模型类
#             args_schema = create_model(f"{base_tool.name}_Args", **fields)
#
#     # 3. 生成并返回标准的 StructuredTool
#     return StructuredTool.from_function(
#         func=base_tool.func,
#         name=base_tool.name,
#         description=base_tool.description,
#         args_schema=args_schema  # 传入解析后的 Schema（支持多参数）
#     )