"""自定义异常模块"""


class FontExtractorError(Exception):
    """字体提取器基础异常"""
    pass


class FontLoadError(FontExtractorError):
    """字体加载异常"""
    pass


class GlyphNotFoundError(FontExtractorError):
    """字符未找到异常"""
    pass


class FontSaveError(FontExtractorError):
    """字体保存异常"""
    pass


class ValidationError(FontExtractorError):
    """验证异常"""
    pass


class VariableFontError(FontExtractorError):
    """可变字体处理异常"""
    pass


class MissingGlyphError(FontExtractorError):
    """目标字体缺字异常，携带缺字清单"""

    def __init__(self, message: str, missing_glyphs: list = None):
        super().__init__(message)
        self.missing_glyphs = missing_glyphs or []


class GlyphComponentError(FontExtractorError):
    """复合字形组件引用异常，组件指向的字形在目标中不存在"""
    pass
