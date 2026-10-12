# ============================================================
# MCP 行程管家服务模块
# 功能：提供租车查询/预订、旅游团语义检索、保险查询/购买的 MCP 工具接口
# 启动命令：python mcp_server/mcp_trip_server.py
# 访问地址：http://127.0.0.1:8003/mcp
#
# 混合数据源架构：
#   ┌─────────────────────────────────────────────────────────────┐
#   │                     数据源分布                               │
#   ├─────────────────────────────────────────────────────────────┤
#   │  MySQL 数据库          │  Milvus 向量数据库                  │
#   │  - car_rentals (租车)  │  - tour_groups (旅游团语义检索)     │
#   │  - insurances (保险)   │    使用 RAG + Qwen Embedding        │
#   └─────────────────────────────────────────────────────────────┘
#
# 调用流程图：
#
#   AI 智能体（如 Claude）
#        │
#        ▼
#   ┌─────────────────────────────┐
#   │  MCP Server (端口 8003)      │
#   │  create_trip_mcp_server()   │
#   │  FastMCP("TripTools")       │
#   └──────────────┬──────────────┘
#                  │
#        ┌─────────┴─────────┐
#        │  根据工具名称路由   │
#        └─────────┬─────────┘
#                  │
#   ┌──────────────┼──────────────┬──────────────┐
#   ▼              ▼              ▼              ▼
# query_car    query_tour     query_        order_*
# _rental      _group         insurance    （预订）
#   │              │              │              │
#   │              │              │              │
#   ▼              ▼              ▼              ▼
# MySQL        Milvus+API     MySQL        直接返回
# 查询         语义检索       查询         模拟结果
#   │              │              │              │
#   │        ┌─────┴─────┐       │              │
#   │        ▼           ▼       │              │
#   │   Qwen API    Milvus       │              │
#   │   Embedding   向量搜索     │              │
#   │        │           │       │              │
#   │        └─────┬─────┘       │              │
#   │              ▼             │              │
#   │        返回匹配旅游团       │              │
#   │              │             │              │
#   └──────────────┴─────────────┘              │
#                  │                            │
#                  ▼                            ▼
#         结果处理 + JSON 序列化          返回预订成功消息
#                  │                            │
#                  └────────────┬───────────────┘
#                               ▼
#                      JSON 字符串返回给 AI 智能体
#
# 旅游团语义检索（RAG）详细流程：
#
#   用户输入: "想看雪山的地方"
#        │
#        ▼
#   ┌─────────────────────────┐
#   │ Qwen Embedding API      │
#   │ text-embedding-v3       │
#   │ 文本 → 向量 (1024维)     │
#   └───────────┬─────────────┘
#               │
#               ▼
#   ┌─────────────────────────┐
#   │ Milvus 向量数据库        │
#   │ COSINE 相似度搜索        │
#   │ 可选: city 过滤条件      │
#   └───────────┬─────────────┘
#               │
#               ▼
#   返回 Top-K 匹配结果
#   (tour_id, tour_name, city, days, price, similarity)
#
# 返回格式示例：
#   {
#     "status": "success",
#     "data": [
#       {
#         "tour_id": "T001",
#         "tour_name": "丽江雪山探秘5日游",
#         "city": "丽江",
#         "days": 5,
#         "price": 3999.0,
#         "similarity": 0.8956
#       }
#     ]
#   }
#
# 数据库/集合说明：
#   MySQL:
#     car_rentals   - 租车表（公司、车型、价格、座位数等）
#     insurances    - 保险表（类型、保额、保障范围等）
#   Milvus:
#     tour_groups   - 旅游团向量集合（嵌入向量 + 元数据）
# ============================================================

import os  # 路径处理，用于定位项目根目录
import sys

# 将项目根目录加入 sys.path，保证按脚本直接运行时能导入 config / create_logger / utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json  # JSON 处理
from datetime import date, datetime, timedelta  # 时间处理
from decimal import Decimal  # 高精度小数类型
import requests  # HTTP 请求，用于调用 Qwen Embedding API

import mysql.connector  # MySQL 数据库驱动
from pymilvus import connections, Collection  # Milvus 向量数据库客户端

from python_a2a import FastMCP, create_fastapi_app  # MCP 框架：FastMCP 用于定义工具，create_fastapi_app 转为 FastAPI 服务
import uvicorn  # ASGI 服务器，用于运行 FastAPI 应用

from config import Config  # 项目配置
from create_logger import logger  # 日志模块
from utils.format import DateEncoder, default_encoder  # 日期格式化工具


conf = Config()


def get_embedding(text: str) -> list:
    """
    调用 Qwen Embedding API 生成文本向量

    参数：
        text (str): 待向量化的文本，如 "想看雪山的地方"

    返回：
        list: 文本向量（维度由 config.embedding_dim 决定，默认 1024）

    工作流程：
        1. 构造请求头（Bearer Token 认证）
        2. 调用 text-embedding-v3 模型
        3. 返回 embedding 向量
    """
    import requests
    headers = {
        "Authorization": f"Bearer {conf.api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "text-embedding-v3",        # Qwen 文本嵌入模型
        "input": [text],                      # 输入文本列表
        "dimensions": conf.embedding_dim      # 输出向量维度
    }
    response = requests.post(conf.embedding_url, headers=headers, json=payload, timeout=30)
    return response.json()["data"][0]["embedding"]


def search_tour_groups_in_milvus(query_text: str, city: str = None, limit: int = 5) -> list:
    """
    在 Milvus 中进行语义搜索，找到最匹配的旅游团

    参数：
        query_text (str): 用户查询描述，如 "想看雪山的地方"
        city (str, optional): 城市过滤条件
        limit (int): 返回结果数量上限，默认 5

    返回：
        list: 匹配的旅游团列表，每个元素包含 tour_id, tour_name, city, days, price, similarity

    工作流程：
        1. 连接 Milvus 向量数据库
        2. 加载旅游团集合
        3. 调用 get_embedding 将查询文本转为向量
        4. 执行 COSINE 相似度搜索
        5. 可选按城市过滤
        6. 返回 Top-K 结果
    """
    from pymilvus import connections, Collection
    # 连接 Milvus 服务
    connections.connect(alias="default", host=conf.milvus_host, port=conf.milvus_port)
    # 获取旅游团集合
    collection = Collection(conf.tour_group_collection)
    collection.load()  # 加载集合到内存

    # 执行向量搜索
    results = collection.search(
        data=[get_embedding(query_text)],           # 查询向量
        anns_field="embedding",                     # 搜索的向量字段
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},  # 余弦相似度
        limit=limit,                                # 返回数量
        output_fields=["tour_id", "tour_name", "city", "days", "price",
                       "total_seats", "remaining_seats", "agency", "rating",
                       "departure_dates", "highlights"],
        expr=f'city == "{city}"' if city else None  # 可选城市过滤
    )

    # 解析搜索结果
    tour_list = []
    for hits in results:
        for hit in hits:
            tour_list.append({
                "tour_id": hit.entity.get("tour_id"),
                "tour_name": hit.entity.get("tour_name"),
                "city": hit.entity.get("city"),
                "days": hit.entity.get("days"),
                "price": hit.entity.get("price"),
                "similarity": round(hit.distance, 4),  # 相似度得分
            })
    return tour_list


# ============================================================
# 行程服务类 —— 封装租车、旅游团、保险的查询与预订逻辑
# 混合数据源：MySQL（租车、保险）+ Milvus（旅游团 RAG 检索）
# ============================================================
class TripService:
    """
    行程查询与预订服务类

    混合数据源架构：
    ┌────────────────────────────────────────────────────────────┐
    │                        TripService                          │
    ├─────────────────────────┬──────────────────────────────────┤
    │      MySQL 查询          │       Milvus RAG 检索            │
    │  - query_car_rental()   │  - query_tour_group()            │
    │  - query_insurance()    │    (语义搜索旅游团)                │
    ├─────────────────────────┼──────────────────────────────────┤
    │      预订方法            │                                  │
    │  - order_car_rental()   │                                  │
    │  - order_tour_group()   │                                  │
    │  - order_insurance()    │                                  │
    └─────────────────────────┴──────────────────────────────────┘
    """

    def __init__(self):
        """初始化方法：建立 MySQL 数据库连接"""
        self.conn = mysql.connector.connect(
            host=conf.host,          # 数据库主机地址
            port=conf.port,
            user=conf.user,          # 数据库用户名
            password=conf.password,  # 数据库密码
            database=conf.database   # 数据库名称
        )

    def _execute_query(self, sql: str, params: list = None) -> str:
        """
        执行 SQL 查询，返回 JSON 格式的结果

        参数：
            sql (str): SQL 查询语句，使用 %s 占位符（防 SQL 注入）
            params (list): SQL 参数列表

        返回值：
            str: JSON 字符串，格式为：
                 - {"status": "success", "data": [...]}       查询到数据
                 - {"status": "no_data", "message": "..."}    无匹配数据
                 - {"status": "error", "message": "..."}      SQL 执行异常

        关键知识点：
          - dictionary=True：cursor 返回字典而非元组，便于通过列名访问
          - default_encoder：将 date/datetime/Decimal 转为可序列化的字符串
          - DateEncoder：json.dumps 的自定义编码器类
        """
        try:
            # 创建游标，dictionary=True 使结果以字典列表形式返回
            cursor = self.conn.cursor(dictionary=True)
            # 执行参数化查询，参数自动转义防止 SQL 注入
            cursor.execute(sql, params or [])
            results = cursor.fetchall()
            cursor.close()

            # 处理特殊类型（日期、Decimal 等无法直接 JSON 序列化的类型）
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)

            # 根据是否有数据返回不同的 JSON 结构
            if results:
                response = {"status": "success", "data": results}
            else:
                response = {"status": "no_data", "message": "未找到行程数据，请确认查询条件。"}

            return json.dumps(response, cls=DateEncoder, ensure_ascii=False)

        except Exception as e:
            logger.error(f"行程查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    # ========== 租车查询（MySQL） ==========

    def query_car_rental(self, pickup_city: str, return_city: str, date: str, car_type: str = None) -> str:
        """
        查询租车信息（从 MySQL car_rentals 表查询）

        参数：
            pickup_city: 取车城市，如 "成都"
            return_city: 还车城市，如 "成都"
            date: 取车日期，格式 "YYYY-MM-DD"
            car_type: 车型类型（可选），如 "经济型"、"SUV"、"豪华型"、"MPV"

        返回：
            JSON 字符串，包含租车公司信息、车型、价格等
        """
        logger.info(f"查询租车: {pickup_city} -> {return_city}, {date}, {car_type}")
        sql = ("SELECT id, company, pickup_city, return_city, pickup_date, car_type, "
               "car_model, price_per_day, total_available, transmission, seats, deposit "
               "FROM car_rentals "
               "WHERE pickup_city = %s AND return_city = %s AND pickup_date = %s")
        params = [pickup_city, return_city, date]
        if car_type:
            sql += " AND car_type = %s"
            params.append(car_type)
        return self._execute_query(sql, params)

    # ========== 旅游团查询（Milvus RAG） ==========

    def query_tour_group(self, query_text: str, city: str = None) -> str:
        """
        查询旅游团信息（从 Milvus 向量数据库进行语义检索）

        这是 RAG（检索增强生成）的核心方法：
        1. 用户输入自然语言描述（如 "想看雪山的地方"）
        2. 调用 Qwen Embedding API 将文本转为向量
        3. 在 Milvus 中进行向量相似度搜索
        4. 返回语义最匹配的旅游团

        参数：
            query_text (str): 用户查询描述，如 "想看雪山的地方"、"适合亲子游的短途旅行"
            city (str, optional): 城市过滤条件

        返回值：
            str: JSON 字符串，包含匹配的旅游团列表及相似度得分
        """
        logger.info(f"查询旅游团: query='{query_text}', city='{city}'")
        try:
            # 调用 Milvus 语义搜索 tour_list结构是[{},{}]
            tour_list = search_tour_groups_in_milvus(query_text, city, limit=5)

            if tour_list:
                return json.dumps({"status": "success", "data": tour_list}, ensure_ascii=False)
            else:
                return json.dumps({
                    "status": "no_data",
                    "message": f"未找到匹配的旅游团。{'请确认城市名称，' if city else ''}或尝试其他搜索条件。"
                }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"旅游团 RAG 查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": f"旅游团查询出错：{str(e)}"}, ensure_ascii=False)

    # ========== 保险查询（MySQL） ==========

    def query_insurance(self, insurance_type: str = None) -> str:
        """
        查询旅行保险产品信息（从 MySQL insurances 表查询）

        参数：
            insurance_type: 保险类型（可选），如 "综合型"、"意外型"、"医疗型"、"境外型"

        返回：
            JSON 字符串，包含保险产品的保额、保障范围、价格等信息
        """
        logger.info(f"查询保险: {insurance_type}")
        sql = ("SELECT id, insurance_type, name, company, coverage, price, "
               "duration_days, max_coverage, medical_coverage, baggage_coverage, flight_delay "
               "FROM insurances")
        params = []
        if insurance_type:
            sql += " WHERE insurance_type = %s"
            params.append(insurance_type)
        return self._execute_query(sql, params)

    # ========== 预订方法（演示环境：仅模拟返回，未实际写入数据库） ==========

    def order_car_rental(self, date: str, car_type: str, number: int) -> str:
        """
        预订租车（模拟）

        参数：
            date: 租车日期
            car_type: 车型
            number: 租车数量
        """
        logger.info(f"预订租车: {date}, {car_type}, {number}辆")
        return f"恭喜，租车预订成功！日期：{date}，车型：{car_type}，数量：{number}辆。"

    def order_tour_group(self, date: str, tour_name: str, number: int) -> str:
        """
        报名旅游团（模拟）

        参数：
            date: 出发日期
            tour_name: 旅游团名称
            number: 报名人数
        """
        logger.info(f"报名旅游团: {date}, {tour_name}, {number}人")
        return f"恭喜，旅游团报名成功！团名：{tour_name}，日期：{date}，人数：{number}人。"

    def order_insurance(self, insurance_type: str, date: str, number: int) -> str:
        """
        购买旅行保险（模拟）

        参数：
            insurance_type: 保险类型
            date: 生效日期
            number: 购买份数
        """
        logger.info(f"购买保险: {insurance_type}, {date}, {number}份")
        return f"恭喜，旅行保险购买成功！类型：{insurance_type}，日期：{date}，份数：{number}份。"


# ============================================================
# MCP 服务器创建与启动
# ============================================================
def create_trip_mcp_server():
    """
    创建并启动行程管家 MCP 服务器

    流程：
        1. 创建 FastMCP 实例，定义工具名称和描述
        2. 实例化 TripService 服务对象
        3. 通过 @trip_mcp.tool() 装饰器将查询/预订方法注册为 MCP 工具
        4. 使用 create_fastapi_app 将 FastMCP 转换为 FastAPI 应用
        5. 通过 uvicorn 启动 ASGI 服务器，监听 8003 端口

    工具注册说明：
        - name:        工具名称，Agent 调用时使用
        - description: 工具描述，Agent 根据此描述决定何时调用该工具
        - 参数类型:    通过 Python 类型注解定义，FastMCP 会自动生成 JSON Schema

    启动后访问地址：
        - MCP 端点: http://127.0.0.1:8003/mcp
    """
    # 步骤1：创建 FastMCP 实例
    trip_mcp = FastMCP(
        name="TripTools",
        description='支持预订租车、语义检索旅游团、购买保险。'
    )

    # 步骤2：创建行程服务实例
    service = TripService()

    # --------------------------------------------------------
    # 步骤3：注册查询工具（Query Tools）
    # --------------------------------------------------------

    @trip_mcp.tool(
        name="query_car_rental",
        description="查询租车信息，参数：pickup_city(取车城市), return_city(还车城市，默认等于取车城市), date(日期，格式YYYY-MM-DD), car_type(车型类型，可选：经济型/SUV/豪华型/MPV)"
    )
    def query_car_rental(pickup_city: str, date: str, return_city: str = None, car_type: str = None) -> str:
        """租车查询工具 - 根据取还车城市、日期、车型查询租车信息"""
        # 默认还车城市等于取车城市
        if return_city is None:
            return_city = pickup_city
        return service.query_car_rental(pickup_city, return_city, date, car_type)

    @trip_mcp.tool(
        name="query_tour_group",
        description="查询旅游团信息（语义搜索），参数：query_text(查询描述，如'想看雪山的地方')，city(城市过滤，可选)"
    )
    def query_tour_group(query_text: str, city: str = None) -> str:
        """旅游团查询工具 - 使用语义搜索查找匹配的旅游团（RAG）"""
        return service.query_tour_group(query_text, city)

    @trip_mcp.tool(
        name="query_insurance",
        description="查询旅行保险产品，参数：insurance_type(保险类型，可选：综合型/意外型/医疗型/境外型)"
    )
    def query_insurance(insurance_type: str = None) -> str:
        """保险查询工具 - 根据保险类型查询保险产品"""
        return service.query_insurance(insurance_type)

    # --------------------------------------------------------
    # 步骤4：注册预订工具（Order Tools）
    # 注意：当前预订功能为演示模式，仅返回成功消息，不实际写入数据库
    # --------------------------------------------------------

    @trip_mcp.tool(
        name="order_car_rental",
        description="根据日期、车型和数量预订租车服务。参数：date(租车日期，格式YYYY-MM-DD), car_type(车型，如经济型/SUV/豪华型/MPV), number(租车数量)"
    )
    def order_car_rental(date: str, car_type: str, number: int) -> str:
        """租车预订工具 - 模拟预订租车"""
        logger.info(f"正在预订租车: {date}, {car_type}, {number}辆")
        return service.order_car_rental(date, car_type, number)

    @trip_mcp.tool(
        name="order_tour_group",
        description="根据出发日期、旅游团名称和人数报名旅游团。参数：date(出发日期，格式YYYY-MM-DD), tour_name(旅游团名称，需与查询结果中的团名一致), number(报名人数)"
    )
    def order_tour_group(date: str, tour_name: str, number: int) -> str:
        """旅游团报名工具 - 模拟报名旅游团"""
        logger.info(f"正在报名旅游团: {date}, {tour_name}, {number}人")
        return service.order_tour_group(date, tour_name, number)

    @trip_mcp.tool(
        name="order_insurance",
        description="根据保险类型、生效日期和份数购买旅行保险。参数：insurance_type(保险类型，如综合型/意外型/医疗型/境外型), date(生效日期，格式YYYY-MM-DD), number(购买份数)"
    )
    def order_insurance(insurance_type: str, date: str, number: int) -> str:
        """保险购买工具 - 模拟购买旅行保险"""
        logger.info(f"正在购买保险: {insurance_type}, {date}, {number}份")
        return service.order_insurance(insurance_type, date, number)

    # 步骤5：启动服务器
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8003/mcp")
        # 将 FastMCP 转换为 FastAPI 应用
        app = create_fastapi_app(mcp_server=trip_mcp)
        # 启动 ASGI 服务器，监听 8003 端口
        uvicorn.run(app, host="127.0.0.1", port=8003)
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == '__main__':
    create_trip_mcp_server()