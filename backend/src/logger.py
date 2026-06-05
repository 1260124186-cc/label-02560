"""日志配置模块"""
import sys
from loguru import logger

# 移除默认处理器
logger.remove()

# 添加控制台输出
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)

# 添加文件输出
logger.add(
    "logs/font_extractor_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8"
)


def get_logger(name: str):
    """获取带模块名的logger"""
    return logger.bind(name=name)
