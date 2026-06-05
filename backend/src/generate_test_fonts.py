"""生成测试用字体文件，用于一键测试提取替换功能"""
import os
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.fontBuilder import FontBuilder

from .config import DEFAULT_GLYPH_NAMES, GLYPH_NAME_TO_UNICODE
from .logger import get_logger

logger = get_logger(__name__)


def _build_test_font(
    family_name: str,
    style: str,
    glyph_shapes: dict,
    output_path: str,
    units_per_em: int = 1000,
):
    """
    用 FontBuilder 构建一个真实可用的 TTF 测试字体

    Args:
        family_name: 字体家族名
        style: 样式名（如 Regular）
        glyph_shapes: {glyph_name: {"width": int, "points": [...], ...}}
        output_path: 输出路径
        units_per_em: UPM
    """
    # 收集所有需要的 glyph 名称（含 .notdef）
    glyph_names = [".notdef"] + list(glyph_shapes.keys())

    # 构建 cmap：glyph_name -> unicode
    cmap = {}
    for name in glyph_shapes:
        if name in GLYPH_NAME_TO_UNICODE:
            cmap[GLYPH_NAME_TO_UNICODE[name]] = name
        elif len(name) == 1:
            cmap[ord(name)] = name

    fb = FontBuilder(units_per_em, isTTF=True)
    fb.setupGlyphOrder(glyph_names)
    fb.setupCharacterMap(cmap)

    # 绘制字形
    fb.setupGlyf({
        name: _draw_glyph(fb, name, info)
        for name, info in [(".notdef", {"width": 500})] + list(glyph_shapes.items())
    })

    # 水平度量
    metrics = {}
    metrics[".notdef"] = (500, 0)
    for name, info in glyph_shapes.items():
        metrics[name] = (info.get("width", 600), info.get("lsb", 0))
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        "familyName": family_name,
        "styleName": style,
    })
    fb.setupOS2()
    fb.setupPost()

    fb.font.save(output_path)
    logger.info(f"Test font generated: {output_path}")


def _draw_glyph(fb, name, info):
    """为一个字形绘制简单的矩形轮廓"""
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    pen = TTGlyphPen(None)
    w = info.get("width", 600)
    h = info.get("height", 700)
    x_off = info.get("x_offset", 50)
    y_off = info.get("y_offset", 0)

    # 画一个简单矩形代表字形
    pen.moveTo((x_off, y_off))
    pen.lineTo((x_off + w - 100, y_off))
    pen.lineTo((x_off + w - 100, y_off + h))
    pen.lineTo((x_off, y_off + h))
    pen.closePath()

    return pen.glyph()


def _make_shape(width=600, height=700, x_offset=50, y_offset=0):
    return {"width": width, "height": height, "x_offset": x_offset, "y_offset": y_offset}


def generate_source_font(output_path: str) -> str:
    """
    生成源字体（包含所有默认字符，矩形轮廓）
    """
    shapes = {}
    for name in DEFAULT_GLYPH_NAMES:
        # 每个字符用不同尺寸的矩形，便于验证替换后的差异
        idx = DEFAULT_GLYPH_NAMES.index(name)
        w = 500 + (idx % 10) * 20
        h = 600 + (idx % 8) * 25
        shapes[name] = _make_shape(width=w, height=h, x_offset=40 + idx % 5 * 10)

    _build_test_font(
        family_name="TestSource",
        style="Regular",
        glyph_shapes=shapes,
        output_path=output_path,
    )
    return output_path


def generate_target_font(output_path: str) -> str:
    """
    生成目标字体（包含所有默认字符，但轮廓不同）
    """
    shapes = {}
    for name in DEFAULT_GLYPH_NAMES:
        # 目标字体用统一的小矩形，替换后应该变成源字体的不同尺寸
        shapes[name] = _make_shape(width=400, height=500, x_offset=80)

    _build_test_font(
        family_name="TestTarget",
        style="Regular",
        glyph_shapes=shapes,
        output_path=output_path,
    )
    return output_path


def generate_test_fonts(output_dir: str = "/data/fonts") -> tuple:
    """
    生成一对测试字体文件

    Args:
        output_dir: 输出目录

    Returns:
        (source_path, target_path)
    """
    os.makedirs(output_dir, exist_ok=True)

    source_path = os.path.join(output_dir, "test_source.ttf")
    target_path = os.path.join(output_dir, "test_target.ttf")

    generate_source_font(source_path)
    generate_target_font(target_path)

    logger.info(f"Test fonts generated in {output_dir}")
    return source_path, target_path
