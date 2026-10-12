# ============================================================
# MCP 票务服务模块
# 功能：提供火车票、机票、演唱会票的查询与预定的 MCP 工具接口
# 数据源：MySQL 数据库（train_tickets / flight_tickets / concert_tickets 表）
# 启动命令：python mcp_server/mcp_ticket_server.py
# 访问地址：http://127.0.0.1:8001/mcp
#
# 调用流程图：
#
#   AI 智能体（如 Claude）
#        │
#        ▼
#   ┌─────────────────────────────┐
#   │  MCP Server (端口 8001)      │
#   │  create_ticket_mcp_server() │
#   │  FastMCP("TicketTools")     │
#   └──────────────┬──────────────┘
#                  │
#        ┌─────────┴─────────┐
#        │  根据工具名称路由   │
#        └─────────┬─────────┘
#                  │
#   ┌──────────────┼──────────────┬──────────────┐
#   ▼              ▼              ▼              ▼
# query_train  query_flight  query_concert   order_*（预定）
#   │              │              │              │
#   └──────────────┴──────────────┘              │
#                  │                             │
#                  ▼                             ▼
#         TicketService 方法              直接返回模拟结果
#                  │                      （演示模式）
#                  ▼
#         _execute_query(sql, params)
#                  │
#                  ▼
#         ┌──────────────────┐
#         │  MySQL 数据库     │
#         │  参数化查询       │
#         │  (防 SQL 注入)    │
#         └────────┬─────────┘
#                  │
#        ┌─────────┴─────────┐
#        │   查询结果处理     │
#        │  转换 date/Decimal │
#        │  序列化为 JSON     │
#        └─────────┬─────────┘
#                  ▼
#         JSON 字符串返回给 AI 智能体
#
#   返回格式示例：
#   {
#     "status": "success",
#     "data": [
#       {
#         "id": 1,
#         "departure_city": "北京",
#         "arrival_city": "上海",
#         "departure_time": "2026-05-01 08:00:00",
#         "arrival_time": "2026-05-01 12:30:00",
#         "train_number": "G101",
#         "seat_type": "二等座",
#         "price": 553.0,
#         "remaining_seats": 120
#       }
#     ]
#   }
#
# 数据库表说明：
#   train_tickets    - 火车票表（车次、座位类型、余票等）
#   flight_tickets   - 机票表（航班号、舱位类型、余票等）
#   concert_tickets  - 演唱会票表（艺人、场馆、票类型等）
# ============================================================

import os  # 路径处理，用于定位项目根目录
import sys

# 将项目根目录加入 sys.path，保证按脚本直接运行时能导入 config / create_logger / utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from python_a2a import FastMCP, create_fastapi_app  # MCP 框架：FastMCP 用于定义工具，create_fastapi_app 转为 FastAPI 服务
import uvicorn  # ASGI 服务器，用于运行 FastAPI 应用

from config import Config
from create_logger import logger
from utils.format import DateEncoder, default_encoder

# 加载配置文件中的数据库连接参数
conf = Config()


# ============================================================
# 票务服务类 —— 封装所有票务相关的数据库查询和预定逻辑
# ============================================================
class TicketService:
    """
    票务服务类，负责火车票、机票、演唱会票的查询与预定。
    所有查询方法统一通过 _execute_query 执行参数化 SQL，返回标准 JSON 字符串。
    """

    def __init__(self):
        """初始化方法：建立 MySQL 数据库连接"""
        self.conn = mysql.connector.connect(
            host=conf.host,            # 数据库主机地址，如 "localhost" 或 "192.168.1.100"
            port=conf.port,
            user=conf.user,            # 数据库用户名
            password=conf.password,    # 数据库密码
            database=conf.database     # 数据库名称
        )
    # 共用负责执行查询的函数
    def _execute_query(self, sql: str, params: list = None) -> str:
        """
        执行参数化查询的通用方法。

        参数:
            sql:    SQL 语句，使用 %s 作为参数占位符（注意不是 Python 的 % 格式化）
            params: 参数列表，按顺序填充 %s 占位符

        返回:
            JSON 字符串，包含三种可能的结构：
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
            # 执行参数化查询 —— params 中的值会自动转义，防止 SQL 注入
            cursor.execute(sql, params or [])
            #results输出的格式:[{k:v},{k:v},{k:v}]
            results = cursor.fetchall()
            cursor.close()

            # 遍历结果，将 date/datetime/Decimal 类型转换为字符串
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)

            # 根据是否有数据返回不同的 JSON 结构
            return json.dumps(
                {"status": "success", "data": results} if results
                else {"status": "no_data", "message": "未找到票务数据，请确认查询条件。"},
                cls=DateEncoder, ensure_ascii=False  # ensure_ascii=False 保证中文正常显示
            )
        except Exception as e:
            # 记录错误日志并返回错误 JSON
            logger.error(f"票务查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    def query_train(self, departure_city: str, arrival_city: str, date: str, seat_type: str = None) -> str:
        """
        查询火车票。

        参数:
            departure_city: 出发城市，如 "北京"
            arrival_city:   到达城市，如 "上海"
            date:           出发日期，格式 "YYYY-MM-DD"
            seat_type:      座位类型（可选），如 "一等座"、"二等座"

        返回:
            JSON 字符串，包含车次、时间、价格、余票等信息

        SQL 说明：
          - WHERE 条件使用 %s 占位符，参数通过 params 列表传入
          - 如果指定了 seat_type，动态追加 AND 条件
          - DATE(departure_time) 提取日期部分进行匹配
        """
        sql = ("SELECT id, departure_city, arrival_city, departure_time, arrival_time, "
               "train_number, seat_type, price, remaining_seats FROM train_tickets "
               "WHERE departure_city = %s AND arrival_city = %s AND DATE(departure_time) = %s")
        params = [departure_city, arrival_city, date]
        if seat_type:
            sql += " AND seat_type = %s"
            params.append(seat_type)
        return self._execute_query(sql, params)

    def query_flight(self, departure_city: str, arrival_city: str, date: str, cabin_type: str = None) -> str:
        """
        查询机票。

        参数:
            departure_city: 出发城市
            arrival_city:   到达城市
            date:           出发日期，格式 "YYYY-MM-DD"
            cabin_type:     舱位类型（可选），如 "经济舱"、"商务舱"

        返回:
            JSON 字符串，包含航班号、时间、价格、余票等信息
        """
        sql = ("SELECT id, departure_city, arrival_city, departure_time, arrival_time, "
               "flight_number, cabin_type, price, remaining_seats FROM flight_tickets "
               "WHERE departure_city = %s AND arrival_city = %s AND DATE(departure_time) = %s")
        params = [departure_city, arrival_city, date]
        if cabin_type:
            sql += " AND cabin_type = %s"
            params.append(cabin_type)
        return self._execute_query(sql, params)

    def query_concert(self, city: str, artist: str, date: str, ticket_type: str = None) -> str:
        """
        查询演唱会/演出票。

        参数:
            city:        演出城市，如 "北京"
            artist:      艺人名称，如 "周杰伦"
            date:        演出日期，格式 "YYYY-MM-DD"
            ticket_type: 票类型（可选），如 "VIP"、"普通票"

        返回:
            JSON 字符串，包含艺人、场馆、时间、票价、余票等信息
        """
        sql = ("SELECT id, artist, city, venue, start_time, end_time, "
               "ticket_type, price, remaining_seats FROM concert_tickets "
               "WHERE city = %s AND artist = %s AND DATE(start_time) = %s")
        params = [city, artist, date]
        if ticket_type:
            sql += " AND ticket_type = %s"
            params.append(ticket_type)
        return self._execute_query(sql, params)

    # --------------------------------------------------------
    # 预定方法（演示环境：仅模拟返回，未实际写入数据库）
    # --------------------------------------------------------

    def order_train(self, departure_date: str, train_number: str, seat_type: str, number: int) -> str:
        """模拟火车票预定，返回预定成功信息"""
        return f"恭喜，火车票预定成功！日期：{departure_date}，车次：{train_number}，座位：{seat_type}，数量：{number}张。"

    def order_flight(self, departure_date: str, flight_number: str, cabin_type: str, number: int) -> str:
        """模拟机票预定，返回预定成功信息"""
        return f"恭喜，机票预定成功！日期：{departure_date}，航班号：{flight_number}，舱位：{cabin_type}，数量：{number}张。"

    def order_concert(self, start_date: str, artist: str, venue: str, ticket_type: str, number: int) -> str:
        """模拟演唱会票预定，返回预定成功信息"""
        return f"恭喜，演出票预定成功！日期：{start_date}，艺人：{artist}，场馆：{venue}，票类型：{ticket_type}，数量：{number}张。"


def create_ticket_mcp_server():
    """
    创建并启动票务 MCP 服务器。

    流程：
        1. 创建 FastMCP 实例，定义工具名称和描述
        2. 实例化 TicketService 服务对象
        3. 通过 @ticket_mcp.tool() 装饰器将查询/预定方法注册为 MCP 工具
        4. 使用 create_fastapi_app 将 FastMCP 转换为 FastAPI 应用
        5. 通过 uvicorn 启动 ASGI 服务器，监听 8001 端口

    工具注册说明：
        - name:        工具名称，Agent 调用时使用
        - description: 工具描述，Agent 根据此描述决定何时调用该工具
        - 参数类型:    通过 Python 类型注解定义，FastMCP 会自动生成 JSON Schema

    启动后访问地址：
        - MCP 端点: http://127.0.0.1:8001/mcp
        - Agent 通过 MCP 协议与此端点通信
    """
    # 步骤1：创建 FastMCP 实例
    # - name: 工具集合的名称，会显示在 MCP 工具列表中
    # - description: 工具集合的描述，帮助 Agent 理解这组工具的用途
    ticket_mcp = FastMCP(
        name="TicketTools",
        description='票务工具，支持火车票、机票、演唱会票的查询与预定。'
    )

    # 步骤2：创建票务服务实例，用于执行实际的数据库操作
    service = TicketService()

    # --------------------------------------------------------
    # 步骤3：注册查询工具（Query Tools）
    # 每个 @ticket_mcp.tool() 装饰器将一个 Python 函数注册为 MCP 工具
    # Agent 可以根据 description 判断何时调用该工具
    # --------------------------------------------------------

    @ticket_mcp.tool(
        name="query_train",
        description="查询火车票信息，参数：departure_city(出发城市), arrival_city(到达城市), date(日期), seat_type(座位类型，可选)"
    )
    def query_train(departure_city: str, arrival_city: str, date: str, seat_type: str = None) -> str:
        """火车票查询工具 - 根据出发城市、到达城市、日期查询火车票"""
        return service.query_train(departure_city, arrival_city, date, seat_type)

    @ticket_mcp.tool(
        name="query_flight",
        description="查询机票信息，参数：departure_city(出发城市), arrival_city(到达城市), date(日期), cabin_type(舱位类型，可选)"
    )
    def query_flight(departure_city: str, arrival_city: str, date: str, cabin_type: str = None) -> str:
        """机票查询工具 - 根据出发城市、到达城市、日期查询机票"""
        return service.query_flight(departure_city, arrival_city, date, cabin_type)

    @ticket_mcp.tool(
        name="query_concert",
        description="查询演唱会票信息，参数：city(城市), artist(艺人), date(日期), ticket_type(票类型，可选)"
    )
    def query_concert(city: str, artist: str, date: str, ticket_type: str = None) -> str:
        """演唱会票查询工具 - 根据城市、艺人、日期查询演出票"""
        return service.query_concert(city, artist, date, ticket_type)

    # --------------------------------------------------------
    # 步骤3（续）：注册预定工具（Order Tools）
    # 注意：当前预定功能为演示模式，仅返回成功消息，不实际写入数据库
    # --------------------------------------------------------

    @ticket_mcp.tool(
        name="order_train",
        description="根据日期、车次、座位类型、数量预定火车票"
    )
    def order_train(departure_date: str, train_number: str, seat_type: str, number: int) -> str:
        """火车票预定工具 - 模拟预定火车票"""
        return service.order_train(departure_date, train_number, seat_type, number)

    @ticket_mcp.tool(
        name="order_flight",
        description="根据日期、航班号、舱位类型、数量预定机票"
    )
    def order_flight(departure_date: str, flight_number: str, cabin_type: str, number: int) -> str:
        """机票预定工具 - 模拟预定机票"""
        return service.order_flight(departure_date, flight_number, cabin_type, number)

    @ticket_mcp.tool(
        name="order_concert",
        description="根据日期、艺人、场馆、票类型、数量预定演出票"
    )
    def order_concert(start_date: str, artist: str, venue: str, ticket_type: str, number: int) -> str:
        """演唱会票预定工具 - 模拟预定演出票"""
        return service.order_concert(start_date, artist, venue, ticket_type, number)

    # 步骤4：输出服务器启动信息
    logger.info("=== 票务MCP服务器信息 ===")
    logger.info(f"名称: {ticket_mcp.name}")

    # 步骤5：启动服务器
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8001/mcp")
        # create_fastapi_app: 将 FastMCP 实例转换为标准 FastAPI 应用
        # 生成的应用包含 MCP 协议所需的端点（/mcp）
        #将FastMCP转成FastAPI
        ticket_mcp_server = create_fastapi_app(ticket_mcp)
        # uvicorn.run: 启动 ASGI 服务器
        # host="0.0.0.0": 监听所有网络接口（允许外部访问）
        # port=8001: 指定端口号
        uvicorn.run(ticket_mcp_server, host="0.0.0.0", port=8001)
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == '__main__':
    # service = TicketService()
    # train = service.query_train("北京", "成都", "2026-05-01", "二等座")
    # print(train)
    # flight = service.query_flight("北京", "成都", "2026-05-01", "头等舱")
    # print(flight)
    create_ticket_mcp_server()