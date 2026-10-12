import os

# 项目根目录
project_root = os.path.dirname(os.path.abspath(__file__))
#print(project_root)
# 生产环境
# env = "prod"
# 测试环境
env = "test"
# 开发环境
# env = "dev"
# 预生产环境
# env = "pre_prod"


#定义配置文件
class Config:

    def __init__(self):
        # 大模型配置
        self.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        self.model_name = 'qwen3.6-plus'

        # mysql数据库配置
        self.host = 'localhost'
        # 如果mysql还没有这个用户，需要先手动创建这个用户和密码，工作中一般不用root，会root会有安全风险
        #CREATE USER 'smart_yoyage'@'%' IDENTIFIED BY '<你的密码>';
        #GRANT ALL PRIVILEGES ON travel_rag.* TO 'smart_yoyage'@'%';
        #FLUSH PRIVILEGES;
        self.user = 'smart_yoyage' # 不是root
        self.password = '{YOU_API_KEY}'
        self.port = 3307
        self.database = 'travel_rag'

        # 日志配置
        self.log_file = os.path.join(project_root, 'logs', 'app.log')
        # 查询天气的城市映射
        self.city_codes = {
            "北京": "101010100",
            "上海": "101020100",
            "杭州": "101210101",
            "南京": "101190101",
            "成都": "101270101",
            "广州": "101280101"
        }
        self.weather_api_key = "{YOU_API_KEY}"
        self.weather_base_url = "https://n34gkkucg8.re.qweatherapi.com"
        self.weather_api_host = "ht64222fr2.re.qweatherapi.com"
        self.weather_timezone = "Asia/Shanghai"
        #Milvus 向量数据库配置
        self.milvus_host = "localhost"
        self.milvus_port = 19530
        self.tour_group_collection = "tour_groups"

        # Qwen Embedding API 配置
        self.embedding_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        self.embedding_dim = 1024

        #
        self.intent = {
            "weather": "WeatherQueryAssistant",
            "flight": "TicketAssistant",
            "train": "TicketAssistant",
            "concert": "TicketAssistant",
            "order": "TicketAssistant",
            "car_rental": "TripAssistant",
            "tour_group": "TripAssistant",
            "insurance": "TripAssistant",
            "trip_order": "TripAssistant",
        }

        self.temperature = 0.1 # 大模型的随机性
        # 天气定时更新调度时间（北京时间）
        self.weather_schedule_time = "01:00"

        # 天气数据源配置
        # 可选值："database"（从数据库获取） / "api"（直接从和风API获取）
        self.weather_source = "api"


    def get_mysql_config(self, env:str):
        """
        通过不同的环境获取不同的数据库配置
        :return:
        """
        # TODO 各环境的真实连接信息尚未拆分，当前统一返回 __init__ 中的本地配置。
        #      部署时按环境替换为各自的实际地址，不要把生产库账号写死在这个文件里。
        env_configs = {
            'prod': (self.host, self.user, self.password, self.database),
            'pre_prod': (self.host, self.user, self.password, self.database),
            'test': (self.host, self.user, self.password, self.database),
            'dev': (self.host, self.user, self.password, self.database),
        }
        return env_configs.get(env, (self.host, self.user, self.password, self.database))


if __name__ == '__main__':
    print(Config().log_file)
    print(Config().api_key)
    print(Config().get_mysql_config(env))