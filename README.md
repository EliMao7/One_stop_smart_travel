# SmartVoyage 一站式智能旅行助手

基于 **A2A（Agent2Agent）协议** 与 **MCP（Model Context Protocol）** 的多智能体旅行助手。
主助手负责意图识别与任务规划，再通过 A2A 协议把子任务分派给专职子代理；子代理通过 MCP 调用底层数据工具。

覆盖场景：天气查询、机票 / 火车票 / 演唱会票查询与预订、租车、旅游团（向量检索）、旅行保险、景点推荐。

---

## 一、整体架构

```
                        ┌──────────────────────────┐
   浏览器  ────────────▶ │  api_server.py  :8080    │  FastAPI + SSE 流式
   (static/index.html)  └────────────┬─────────────┘
                                     │
                        ┌────────────▼─────────────┐
                        │  chat_server.py          │  主助手
                        │  ChatService             │
                        │  意图识别 → 启发式路由 →  │
                        │  Planning + ReAct        │
                        └──┬────────┬──────────────┘
                           │ A2A 协议
          ┌────────────────┼────────────────┬────────────────┐
          ▼                ▼                ▼                │
   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
   │ 天气代理     │  │ 票务代理     │  │ 行程代理     │        │
   │ :5005       │  │ :5006       │  │ :5007       │        │
   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
          │ MCP           │ MCP           │ MCP            │
          ▼                ▼                ▼               ▼
   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐
   │ 天气 MCP     │  │ 票务 MCP     │  │ 行程 MCP     │  │ 直连 LLM │
   │ :8002       │  │ :8001       │  │ :8003       │  │ 景点推荐  │
   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────────┘
          │                │                │
          ▼                ▼                ▼
     和风天气 API      MySQL 票务表     MySQL 租车/保险
                      (或 MySQL)        Milvus 旅游团向量库
```

**主助手处理流程**（`chat_server.py`）：

```
用户输入 → 意图识别(LLM) → 特殊情况判断(超范围/追问)
        → 启发式路由：单意图或独立多意图 → 跳过规划，直接执行（省 1 次 LLM 调用）
                      复杂依赖任务     → planning_agent 生成计划 → ReAct 循环
        → 汇总回复
```

---

## 二、目录结构

```
One_stop_smart_travel/
├── api_server.py            # FastAPI 入口，提供 REST + SSE 接口（:8080）
├── chat_server.py           # 主助手 ChatService，核心对话编排
├── main_prompts.py          # 全部 Prompt 模板（意图识别/规划/总结/景点推荐）
├── memory.py                # 记忆管理：短期对话 + 用户偏好 + 实体历史（MySQL 持久化）
├── config.py                # 全局配置（模型、数据库、天气 API、意图路由表）
├── create_logger.py         # 日志初始化
├── static/index.html        # 前端页面
├── a2a_server/              # A2A 子代理服务
│   ├── weather_server.py    # 天气代理（:5005）
│   ├── ticket_server.py     # 票务代理（:5006）
│   └── trip_server.py       # 行程代理（:5007）
├── mcp_server/              # MCP 工具服务
│   ├── mcp_weather_server.py   # 天气工具（:8002）
│   ├── mcp_ticket_server.py    # 票务工具（:8001）
│   └── mcp_trip_server.py      # 行程工具（:8003）
├── utils/
│   ├── followup.py          # 追问消息识别（三个 A2A 服务共用）
│   ├── tool_to_structure.py # MCP Tool → LangChain StructuredTool 适配
│   ├── format.py            # date/Decimal 的 JSON 序列化
│   ├── spider_weather.py    # 天气数据定时爬取（database 模式下才启用）
│   └── feng_demo.py         # 和风天气 API 调用小样例
└── sql/
    ├── create_all_tables.sql  # 建表语句
    ├── insert_may01_data.sql  # 示例数据
    └── init_tour_group_rag.py # 旅游团向量库初始化（写 Milvus）
```

---

## 三、快速开始

### 1. 环境要求

- **Python 3.10 ~ 3.12**（不支持 3.13/3.14，部分依赖无预编译包）
- MySQL（默认端口 `3307`，库名 `travel_rag`）
- Milvus（默认 `localhost:19530`，仅旅游团语义检索需要）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 填写配置

`config.py` 中存在两处占位符，**必须替换为你自己的值**：

| 配置项 | 位置 | 说明 |
| --- | --- | --- |
| `self.password` | `config.py` | MySQL 密码 |
| `self.weather_api_key` | `config.py` | 和风天气 API Key |

大模型 API Key 从环境变量读取：

```bash
# Linux / macOS
export DASHSCOPE_API_KEY="sk-xxxxxxxx"

# Windows PowerShell
$env:DASHSCOPE_API_KEY="sk-xxxxxxxx"
```

### 4. 初始化数据库

```bash
mysql -u root -p < sql/create_all_tables.sql
mysql -u root -p < sql/insert_may01_data.sql

# 初始化配置里指定的数据库账号（见 config.py 注释）
# CREATE USER 'smart_yoyage'@'%' IDENTIFIED BY '<你的密码>';
# GRANT ALL PRIVILEGES ON travel_rag.* TO 'smart_yoyage'@'%';
# FLUSH PRIVILEGES;

# （可选）初始化旅游团向量库
python sql/init_tour_group_rag.py
```

### 5. 按顺序启动（每个服务占一个终端）

```bash
# 第一层：MCP 工具服务
python mcp_server/mcp_ticket_server.py      # :8001
python mcp_server/mcp_weather_server.py     # :8002
python mcp_server/mcp_trip_server.py        # :8003

# 第二层：A2A 子代理
python a2a_server/weather_server.py         # :5005
python a2a_server/ticket_server.py          # :5006
python a2a_server/trip_server.py            # :5007

# 第三层：主助手 API
python api_server.py                        # :8080
```

打开 <http://127.0.0.1:8080> 即可对话。

> 必须按上述顺序启动：子代理启动时会通过 MCP 拉取工具列表，MCP 未就绪会导致工具加载失败。

---

## 四、API 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 前端页面 |
| POST | `/api/chat` | 发送消息，返回完整回复 |
| POST | `/api/chat/stream` | 发送消息，SSE 流式返回 |
| GET | `/api/memory` | 查看当前记忆状态 |
| POST | `/api/memory/clear` | 清空记忆 |
| POST | `/api/memory/profile` | 更新用户偏好 |
| GET | `/api/agents` | 查看已注册的代理卡片 |

---

## 五、配置说明

`config.py` 中几个关键开关：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `model_name` | `qwen3.6-plus` | 主模型，走 DashScope 的 OpenAI 兼容接口 |
| `intent` | — | 意图 → 子代理名称的路由表 |
| `weather_source` | `api` | `api` 走和风天气；`database` 走本地 MySQL |
| `weather_schedule_time` | `01:00` | 天气数据定时爬取时间（仅 database 模式生效） |
| `temperature` | `0.1` | 降低随机性，保证意图识别输出稳定 |

---

## 六、说明

- 票务、租车、旅游团、保险的**预订接口目前为演示实现**，仅返回成功提示，不会真正写库。
- 景点推荐不走子代理，直接由主模型生成，但会先查一次目的地天气作为事实依据，避免模型虚构天气。
