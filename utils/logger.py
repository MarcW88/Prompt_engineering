import sys
from loguru import logger
from pathlib import Path


def setup_logger(log_level: str = "INFO", log_dir: str = "./logs") -> None:
    """Configure le logger avec rotation et format structuré"""
    
    logger.remove()
    
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    logger.add(
        sys.stderr,
        format=log_format,
        level=log_level,
        colorize=True
    )
    
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        log_path / "prompt_finder_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="DEBUG",
        rotation="1 day",
        retention="7 days",
        compression="zip"
    )


def get_logger(name: str = None):
    """Retourne le logger configuré"""
    if name:
        return logger.bind(name=name)
    return logger
