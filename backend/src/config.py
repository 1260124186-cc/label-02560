"""配置管理模块"""
from typing import List

# 默认需要提取的字符名称列表
DEFAULT_GLYPH_NAMES: List[str] = [
    "exclamdown", "cent", "sterling", "exclam", "quotedbl", "numbersign",
    "dollar", "percent", "ampersand", "quotesingle", "parenleft", "parenright",
    "asterisk", "plus", "comma", "hyphenminus", "period", "slash",
    "glyph22", "glyph23", "glyph24", "glyph25", "glyph26", "glyph27",
    "glyph28", "glyph29", "glyph30", "glyph31",
    "colon", "semicolon", "less", "equal", "greater", "question", "at",
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "bracketleft", "backslash", "bracketright", "asciicircum", "underscore", "grave",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "braceleft", "bar", "braceright", "asciitilde"
]

# 字符名称到Unicode的映射（用于备选查找）
GLYPH_NAME_TO_UNICODE = {
    "exclamdown": 0x00A1,
    "cent": 0x00A2,
    "sterling": 0x00A3,
    "exclam": 0x0021,
    "quotedbl": 0x0022,
    "numbersign": 0x0023,
    "dollar": 0x0024,
    "percent": 0x0025,
    "ampersand": 0x0026,
    "quotesingle": 0x0027,
    "parenleft": 0x0028,
    "parenright": 0x0029,
    "asterisk": 0x002A,
    "plus": 0x002B,
    "comma": 0x002C,
    "hyphenminus": 0x002D,
    "period": 0x002E,
    "slash": 0x002F,
    "zero": 0x0030,
    "one": 0x0031,
    "two": 0x0032,
    "three": 0x0033,
    "four": 0x0034,
    "five": 0x0035,
    "six": 0x0036,
    "seven": 0x0037,
    "eight": 0x0038,
    "nine": 0x0039,
    "colon": 0x003A,
    "semicolon": 0x003B,
    "less": 0x003C,
    "equal": 0x003D,
    "greater": 0x003E,
    "question": 0x003F,
    "at": 0x0040,
    # glyph22-glyph31 是非标准字符名称，不同字体中映射可能不同
    # 不在此处硬编码 Unicode 映射，改为运行时从字体 cmap 表动态查找
    # 如果字体中没有 cmap 映射，则视为未编码字符（unencoded glyph）
    "bracketleft": 0x005B,
    "backslash": 0x005C,
    "bracketright": 0x005D,
    "asciicircum": 0x005E,
    "underscore": 0x005F,
    "grave": 0x0060,
    "braceleft": 0x007B,
    "bar": 0x007C,
    "braceright": 0x007D,
    "asciitilde": 0x007E,
}

# 为A-Z和a-z添加映射
for i, char in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    GLYPH_NAME_TO_UNICODE[char] = ord(char)

for i, char in enumerate("abcdefghijklmnopqrstuvwxyz"):
    GLYPH_NAME_TO_UNICODE[char] = ord(char)

# 非标准字符名称列表（需要特殊处理）
NON_STANDARD_GLYPH_NAMES = {
    "glyph22", "glyph23", "glyph24", "glyph25", "glyph26",
    "glyph27", "glyph28", "glyph29", "glyph30", "glyph31",
}

# 支持的字体格式
SUPPORTED_FORMATS = [".ttf", ".otf", ".ttc", ".woff", ".woff2"]
