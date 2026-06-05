"""验证模块"""
import os
from pathlib import Path
from typing import List, Tuple

from fontTools.ttLib import TTFont

from .config import SUPPORTED_FORMATS
from .exceptions import ValidationError, FontLoadError
from .logger import get_logger

logger = get_logger(__name__)


def validate_font_path(font_path: str) -> Path:
    """
    验证字体文件路径
    
    Args:
        font_path: 字体文件路径
        
    Returns:
        Path对象
        
    Raises:
        ValidationError: 路径无效或格式不支持
    """
    path = Path(font_path)
    
    if not path.exists():
        logger.error(f"Font file not found: {font_path}")
        raise ValidationError(f"Font file not found: {font_path}")
    
    if not path.is_file():
        logger.error(f"Path is not a file: {font_path}")
        raise ValidationError(f"Path is not a file: {font_path}")
    
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        logger.error(f"Unsupported font format: {suffix}")
        raise ValidationError(f"Unsupported font format: {suffix}. Supported: {SUPPORTED_FORMATS}")
    
    logger.info(f"Font path validated: {font_path}")
    return path


def validate_font_file(font_path: str) -> TTFont:
    """
    验证并加载字体文件
    
    Args:
        font_path: 字体文件路径
        
    Returns:
        TTFont对象
        
    Raises:
        FontLoadError: 字体加载失败
    """
    path = validate_font_path(font_path)
    
    try:
        font = TTFont(str(path))
        logger.info(f"Font loaded successfully: {font_path}")
        return font
    except Exception as e:
        logger.error(f"Failed to load font: {font_path}, error: {e}")
        raise FontLoadError(f"Failed to load font: {font_path}, error: {e}")


def validate_glyphs_exist(font: TTFont, glyph_names: List[str]) -> Tuple[List[str], List[str]]:
    """
    验证字符是否存在于字体中
    
    Args:
        font: TTFont对象
        glyph_names: 要验证的字符名称列表
        
    Returns:
        (存在的字符列表, 不存在的字符列表)
    """
    glyph_order = font.getGlyphOrder()
    existing = []
    missing = []
    
    for name in glyph_names:
        if name in glyph_order:
            existing.append(name)
        else:
            missing.append(name)
    
    logger.info(f"Glyph validation: {len(existing)} found, {len(missing)} missing")
    if missing:
        logger.warning(f"Missing glyphs: {missing[:10]}{'...' if len(missing) > 10 else ''}")
    
    return existing, missing


def validate_output_path(output_path: str) -> Path:
    """
    验证输出路径
    
    Args:
        output_path: 输出文件路径
        
    Returns:
        Path对象
        
    Raises:
        ValidationError: 路径无效
    """
    path = Path(output_path)
    
    # 确保父目录存在
    parent = path.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created output directory: {parent}")
        except Exception as e:
            logger.error(f"Failed to create output directory: {parent}, error: {e}")
            raise ValidationError(f"Failed to create output directory: {parent}")
    
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        logger.error(f"Unsupported output format: {suffix}")
        raise ValidationError(f"Unsupported output format: {suffix}. Supported: {SUPPORTED_FORMATS}")
    
    logger.info(f"Output path validated: {output_path}")
    return path


def is_variable_font(font: TTFont) -> bool:
    """
    检查是否为可变字体
    
    Args:
        font: TTFont对象
        
    Returns:
        是否为可变字体
    """
    is_var = "fvar" in font
    logger.info(f"Font is variable: {is_var}")
    return is_var
