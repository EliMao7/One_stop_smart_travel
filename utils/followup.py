"""
公共模块：A2A 服务器追问消息识别工具


"""

# 追问标记常量
# LLM 按 prompt 约定：追问消息必须在开头输出此标记
# 选择 [追问] 而非其他符号的原因：
#   - 中括号包裹，LLM 不会在正常回复中误用
#   - 中文直观，便于调试时肉眼识别
FOLLOWUP_MARKER = "[追问]"

# 启发式兜底中需要排除的"成功/错误回复"关键词
# 这些词出现在正常查询结果或错误提示中，不是追问
_SUCCESS_REPLY_KEYWORDS = (
    "为您查询",
    "查询到",
    "预定成功",
    "预订成功",
    "报名成功",
    "购买成功",
)

_ERROR_REPLY_KEYWORDS = (
    "未找到",
    "未查到",
    "查询出错",
    "查询失败",
)


def is_followup_message(text: str) -> bool:
    """
    判断 LLM 返回的文本是否是追问消息（需要用户补充信息）

    采用两层判断策略，从最可靠到兜底：

    第 1 层：显式标记
        LLM 按 prompt 约定在追问开头输出 [追问]（最可靠，LLM 主动"声明"意图）

    第 2 层：启发式兜底
        对未遵循标记约定的情况（不同模型、temperature 高等），用以下规则捕获：
          - 以问号结尾（？或 ?）
          - 文本较短（追问通常比结果回复短）
          - 不包含已知成功/错误回复关键词（排除误判）

    参数：
        text: LLM 生成的回复文本

    返回：
        True 表示这是追问消息，应设置 TaskState.INPUT_REQUIRED
        False 表示这是正常结果，应设置 TaskState.COMPLETED

    示例：
        >>> is_followup_message("[追问]请问您要从哪个城市出发？")
        True
        >>> is_followup_message("为您查询到北京到成都的火车票...")
        False
        >>> is_followup_message("请问您想查询哪一天的天气？")  # 兜底：短+问号
        True
        >>> is_followup_message("未找到相关天气数据，请确认或修改查询条件。")  # 排除错误回复
        False
    """
    if not text:
        return False

    stripped = text.strip()

    # 第 1 层：显式标记（最可靠）
    if stripped.startswith(FOLLOWUP_MARKER):
        return True

    # 第 2 层：启发式兜底
    is_question = stripped.endswith(("？", "?"))
    is_short = len(stripped) < 100

    # 排除已知的成功回复和错误回复模式，防止误判
    is_not_success_or_error = (
        not any(kw in stripped for kw in _SUCCESS_REPLY_KEYWORDS)
        and not any(kw in stripped for kw in _ERROR_REPLY_KEYWORDS)
    )

    if is_question and is_short and is_not_success_or_error:
        return True

    return False


def strip_followup_marker(text: str) -> str:
    """
    去除追问文本开头的 [追问] 标记，返回干净的追问文本给前端展示

    参数：
        text: 可能包含 [追问] 前缀的原始文本

    返回：
        去除标记后的文本；若原本就没有标记，原样返回

    示例：
        >>> strip_followup_marker("[追问]请问您要从哪个城市出发？")
        '请问您要从哪个城市出发？'
        >>> strip_followup_marker("普通回复文本")
        '普通回复文本'
    """
    if text and text.strip().startswith(FOLLOWUP_MARKER):
        return text.replace(FOLLOWUP_MARKER, "", 1).strip()
    return text