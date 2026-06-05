"""命令行入口模块"""
import sys
from pathlib import Path
from typing import Optional, List

import click

from .font_extractor import FontExtractor, extract_and_replace
from .config import DEFAULT_GLYPH_NAMES
from .exceptions import FontExtractorError, MissingGlyphError, GlyphNameConflictError
from .glyph_alias import GlyphAliasResolver
from .logger import get_logger

logger = get_logger(__name__)


@click.group()
@click.version_option(version="1.0.0", prog_name="font-extractor")
def cli():
    """字体字符提取替换工具 - 一键提取字符并替换到另一个字体"""
    pass


@cli.command()
@click.option("-s", "--source", required=True, type=click.Path(exists=True), help="源字体文件路径")
@click.option("-t", "--target", required=True, type=click.Path(exists=True), help="目标字体文件路径")
@click.option("-o", "--output", required=True, type=click.Path(), help="输出字体文件路径")
@click.option("-g", "--glyphs", default=None, help="要提取的字符名称，逗号分隔（默认使用预设列表）")
@click.option(
    "-m", "--mode", "missing_glyph_mode",
    type=click.Choice(["strict", "append"], case_sensitive=False),
    default="strict",
    help="缺字处理模式：strict=缺字即失败（默认），append=在目标中新增字形槽位"
)
@click.option("--no-cmap", is_flag=True, default=False, help="append 模式下不将 Unicode 映射写入目标 cmap 表")
@click.option(
    "--mapping", "mapping_path",
    type=click.Path(exists=True),
    default=None,
    help="源名→目标名映射文件路径（JSON 格式）"
)
@click.option(
    "--conflict", "conflict_strategy",
    type=click.Choice(["abort", "skip", "first"], case_sensitive=False),
    default="abort",
    help="冲突策略：abort=检测到冲突即中止（默认），skip=跳过冲突字形，first=取首个匹配"
)
def extract(source: str, target: str, output: str, glyphs: Optional[str],
            missing_glyph_mode: str, no_cmap: bool,
            mapping_path: Optional[str], conflict_strategy: str):
    """从源字体提取字符并替换到目标字体"""
    glyph_names = None
    if glyphs:
        glyph_names = [g.strip() for g in glyphs.split(",")]

    try:
        click.echo(f"Source: {source}")
        click.echo(f"Target: {target}")
        click.echo(f"Output: {output}")
        click.echo(f"Glyphs: {len(glyph_names) if glyph_names else len(DEFAULT_GLYPH_NAMES)}")
        click.echo(f"Mode: {missing_glyph_mode}")
        if mapping_path:
            click.echo(f"Mapping: {mapping_path}")
            click.echo(f"Conflict: {conflict_strategy}")
        click.echo("-" * 50)

        progress_bars = {}

        def progress_callback(phase, current, total, name):
            if phase not in progress_bars:
                label = "Extracting" if phase == "extract" else "Replacing"
                progress_bars[phase] = click.progressbar(
                    length=total, label=f"{label} glyphs", show_pos=True, show_percent=True
                )
                progress_bars[phase].__enter__()
            progress_bars[phase].update(1)

        try:
            output_path, report = extract_and_replace(
                source_font_path=source, target_font_path=target,
                output_path=output, glyph_names=glyph_names,
                progress_callback=progress_callback,
                missing_glyph_mode=missing_glyph_mode,
                write_cmap=not no_cmap,
                mapping_path=mapping_path,
                conflict_strategy=conflict_strategy,
            )
        finally:
            for bar in progress_bars.values():
                bar.__exit__(None, None, None)

        click.echo("-" * 50)
        click.echo(f"✓ Created: {output_path}")
        click.echo(f"  Variable font: src={report['source_is_variable']}, tgt={report['target_is_variable']}")
        click.echo(f"  Glyphs: {report['extracted_glyphs_count']}")

    except MissingGlyphError as e:
        logger.error(f"Missing glyphs in target: {e.missing_glyphs}")
        click.echo(f"✗ Missing glyphs in target font ({len(e.missing_glyphs)}):", err=True)
        for name in e.missing_glyphs:
            click.echo(f"  - {name}", err=True)
        click.echo("  Hint: use --mode append to add missing glyphs automatically", err=True)
        sys.exit(1)
    except GlyphNameConflictError as e:
        logger.error(f"Glyph name conflict: {e}")
        click.echo(f"✗ Glyph name conflict detected: {e}", err=True)
        if e.conflict_report:
            resolver = GlyphAliasResolver()
            click.echo(resolver.format_conflict_report(e.conflict_report), err=True)
        click.echo("  Hint: use --conflict skip to skip conflicted glyphs, or --conflict first to use first match", err=True)
        sys.exit(1)
    except FontExtractorError as e:
        logger.error(f"Extraction failed: {e}")
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error occurred")
        click.echo(f"✗ Unexpected error ({type(e).__name__}): {e}", err=True)
        sys.exit(2)


@cli.command()
@click.argument("font_path", type=click.Path(exists=True))
def info(font_path: str):
    """显示字体文件信息"""
    try:
        from fontTools.ttLib import TTFont
        from .validator import is_variable_font

        font = TTFont(font_path)
        click.echo(f"Font: {font_path}")
        click.echo("-" * 50)
        click.echo(f"Glyph count: {len(font.getGlyphOrder())}")

        is_var = is_variable_font(font)
        click.echo(f"Variable font: {is_var}")
        if is_var:
            for axis in font["fvar"].axes:
                click.echo(f"  - {axis.axisTag}: {axis.minValue} ~ {axis.maxValue} (default: {axis.defaultValue})")

        click.echo(f"Tables: {', '.join(sorted(font.keys()))}")
        font.close()
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("font_path", type=click.Path(exists=True))
@click.option("-g", "--glyphs", default=None, help="要检查的字符名称，逗号分隔")
def check(font_path: str, glyphs: Optional[str]):
    """检查字体中是否包含指定字符"""
    try:
        from fontTools.ttLib import TTFont
        from .validator import validate_glyphs_exist

        font = TTFont(font_path)
        glyph_names = [g.strip() for g in glyphs.split(",")] if glyphs else DEFAULT_GLYPH_NAMES
        existing, missing = validate_glyphs_exist(font, glyph_names)

        click.echo(f"Font: {font_path}")
        click.echo("-" * 50)
        click.echo(f"✓ Found: {len(existing)}")
        click.echo(f"✗ Missing: {len(missing)}")
        if missing:
            for name in missing:
                click.echo(f"  - {name}")
        font.close()
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("font_a", type=click.Path(exists=True))
@click.argument("font_b", type=click.Path(exists=True))
@click.option("-g", "--glyphs", default=None, help="要对比的字符名称，逗号分隔（默认使用预设列表）")
def diff(font_a: str, font_b: str, glyphs: Optional[str]):
    """
    对比两个字体的字符差异

    示例:
        font-extractor diff fontA.ttf fontB.ttf
        font-extractor diff fontA.ttf fontB.ttf -g "A,B,C"
    """
    try:
        from fontTools.ttLib import TTFont

        fa = TTFont(font_a)
        fb = TTFont(font_b)

        glyph_names = [g.strip() for g in glyphs.split(",")] if glyphs else DEFAULT_GLYPH_NAMES

        click.echo(f"Font A: {font_a}")
        click.echo(f"Font B: {font_b}")
        click.echo(f"Comparing {len(glyph_names)} glyphs...")
        click.echo("=" * 70)

        order_a = set(fa.getGlyphOrder())
        order_b = set(fb.getGlyphOrder())

        identical = 0
        different = 0
        only_a = 0
        only_b = 0
        diff_details = []

        has_glyf_a = "glyf" in fa
        has_glyf_b = "glyf" in fb

        for name in glyph_names:
            in_a = name in order_a
            in_b = name in order_b

            if not in_a and not in_b:
                continue
            if in_a and not in_b:
                only_a += 1
                diff_details.append((name, "only in A", ""))
                continue
            if not in_a and in_b:
                only_b += 1
                diff_details.append((name, "only in B", ""))
                continue

            # 对比轮廓
            diffs = []

            if has_glyf_a and has_glyf_b:
                glyph_a = fa["glyf"].get(name)
                glyph_b = fb["glyf"].get(name)
                if glyph_a and glyph_b:
                    # 对比坐标数量
                    coords_a = len(glyph_a.coordinates) if hasattr(glyph_a, "coordinates") and glyph_a.coordinates else 0
                    coords_b = len(glyph_b.coordinates) if hasattr(glyph_b, "coordinates") and glyph_b.coordinates else 0
                    if coords_a != coords_b:
                        diffs.append(f"points: {coords_a} vs {coords_b}")
                    elif coords_a > 0:
                        if list(glyph_a.coordinates) != list(glyph_b.coordinates):
                            diffs.append("outline differs")

                    # 对比 bounding box
                    try:
                        bbox_a = (glyph_a.xMin, glyph_a.yMin, glyph_a.xMax, glyph_a.yMax)
                        bbox_b = (glyph_b.xMin, glyph_b.yMin, glyph_b.xMax, glyph_b.yMax)
                        if bbox_a != bbox_b:
                            diffs.append(f"bbox: {bbox_a} vs {bbox_b}")
                    except AttributeError:
                        pass

            # 对比度量
            if "hmtx" in fa and "hmtx" in fb:
                ma = fa["hmtx"].metrics.get(name)
                mb = fb["hmtx"].metrics.get(name)
                if ma and mb and ma != mb:
                    diffs.append(f"hmtx: {ma} vs {mb}")

            if diffs:
                different += 1
                diff_details.append((name, "DIFFERENT", "; ".join(diffs)))
            else:
                identical += 1

        # 输出汇总
        click.echo(f"\n{'Glyph':<20} {'Status':<15} {'Details'}")
        click.echo("-" * 70)
        for name, status, details in diff_details:
            marker = "≠" if status == "DIFFERENT" else "△"
            click.echo(f"  {marker} {name:<18} {status:<15} {details}")

        if not diff_details:
            click.echo("  All compared glyphs are identical.")

        click.echo("\n" + "=" * 70)
        click.echo(f"Summary: {identical} identical, {different} different, "
                    f"{only_a} only-in-A, {only_b} only-in-B")

        fa.close()
        fb.close()

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("-d", "--font-dir", default="/data/fonts", help="测试字体目录")
@click.option("-o", "--output-dir", default="/data/output", help="输出目录")
def demo(font_dir: str, output_dir: str):
    """一键演示：生成测试字体 -> 提取替换 -> 对比验证"""
    import os

    try:
        from .generate_test_fonts import generate_test_fonts
        from fontTools.ttLib import TTFont
        from .validator import validate_glyphs_exist

        click.echo("=" * 60)
        click.echo("  Font Glyph Extractor - Demo")
        click.echo("=" * 60)

        # Step 1
        click.echo("\n[1/5] Generating test fonts...")
        source_path, target_path = generate_test_fonts(font_dir)
        click.echo(f"  ✓ Source: {source_path}")
        click.echo(f"  ✓ Target: {target_path}")

        # Step 2
        click.echo("\n[2/5] Source font info:")
        src_font = TTFont(source_path)
        click.echo(f"  Glyph count: {len(src_font.getGlyphOrder())}")
        existing, missing = validate_glyphs_exist(src_font, DEFAULT_GLYPH_NAMES)
        click.echo(f"  Default glyphs: {len(existing)}/{len(DEFAULT_GLYPH_NAMES)}")
        src_font.close()

        # Step 3
        click.echo("\n[3/5] Extracting and replacing...")
        os.makedirs(output_dir, exist_ok=True)
        output_path_str = os.path.join(output_dir, "demo_result.ttf")
        output_path, report = extract_and_replace(
            source_font_path=source_path,
            target_font_path=target_path,
            output_path=output_path_str,
        )
        click.echo(f"  ✓ Glyphs extracted: {report['extracted_glyphs_count']}")

        # Step 4
        click.echo("\n[4/5] Verifying output...")
        out_font = TTFont(str(output_path))
        out_existing, _ = validate_glyphs_exist(out_font, DEFAULT_GLYPH_NAMES)
        click.echo(f"  Output glyphs: {len(out_existing)}/{len(DEFAULT_GLYPH_NAMES)}")
        out_font.close()

        # Step 5: 自动对比
        click.echo("\n[5/5] Comparing fonts (target vs output)...")
        click.echo("  Target = original target font (before replacement)")
        click.echo("  Output = after replacing glyphs from source\n")
        _run_diff(target_path, str(output_path))

        click.echo("\n" + "=" * 60)
        click.echo(f"  ✓ Demo completed! Output: {output_path}")
        click.echo("=" * 60)

    except FontExtractorError as e:
        logger.error(f"Demo failed: {e}")
        click.echo(f"\n✗ Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        logger.exception("Demo unexpected error")
        click.echo(f"\n✗ Unexpected error ({type(e).__name__}): {e}", err=True)
        sys.exit(2)


def _run_diff(font_a_path: str, font_b_path: str):
    """内部对比函数，用于 demo 命令"""
    from fontTools.ttLib import TTFont

    fa = TTFont(font_a_path)
    fb = TTFont(font_b_path)

    order_a = set(fa.getGlyphOrder())
    order_b = set(fb.getGlyphOrder())

    identical = 0
    different = 0

    has_glyf_a = "glyf" in fa
    has_glyf_b = "glyf" in fb

    diff_rows = []

    for name in DEFAULT_GLYPH_NAMES:
        if name not in order_a or name not in order_b:
            continue

        diffs = []
        if has_glyf_a and has_glyf_b:
            ga = fa["glyf"].get(name)
            gb = fb["glyf"].get(name)
            if ga and gb:
                try:
                    ba = (ga.xMin, ga.yMin, ga.xMax, ga.yMax)
                    bb = (gb.xMin, gb.yMin, gb.xMax, gb.yMax)
                    if ba != bb:
                        diffs.append(f"bbox {ba} -> {bb}")
                except AttributeError:
                    pass

        if "hmtx" in fa and "hmtx" in fb:
            ma = fa["hmtx"].metrics.get(name)
            mb = fb["hmtx"].metrics.get(name)
            if ma and mb and ma != mb:
                diffs.append(f"width {ma[0]} -> {mb[0]}")

        if diffs:
            different += 1
            diff_rows.append((name, "; ".join(diffs)))
        else:
            identical += 1

    # 只显示前 15 个差异，避免刷屏
    shown = diff_rows[:15]
    for name, detail in shown:
        click.echo(f"  ≠ {name:<18} {detail}")
    if len(diff_rows) > 15:
        click.echo(f"  ... and {len(diff_rows) - 15} more differences")

    click.echo(f"\n  Summary: {identical} identical, {different} different")

    fa.close()
    fb.close()


@cli.command("cmap-report")
@click.argument("source_font", type=click.Path(exists=True))
@click.argument("target_font", type=click.Path(exists=True))
@click.option("-g", "--glyphs", default=None, help="要检查的字形名称，逗号分隔（默认检查非标准名 glyph22~glyph31）")
@click.option("--json", "output_json", is_flag=True, default=False, help="以 JSON 格式输出报告")
@click.option(
    "--conflict", "conflict_strategy",
    type=click.Choice(["abort", "skip", "first"], case_sensitive=False),
    default="abort",
    help="冲突策略：abort=检测到冲突即告警（默认），skip=跳过，first=取首个匹配"
)
def cmap_report(source_font: str, target_font: str, glyphs: Optional[str],
                output_json: bool, conflict_strategy: str):
    """生成非标准字形名的源/目标 cmap 对照报告

    对 glyph22~glyph31 等非标准名：扫描源/目标全部 cmap 子表，
    生成对照报告（码位、平台 ID、子表索引），供人工确认是否同一字符。
    同时检测冲突（一名多码、一码多名）。
    """
    import json as json_mod
    from fontTools.ttLib import TTFont
    from .config import NON_STANDARD_GLYPH_NAMES

    try:
        src = TTFont(source_font)
        tgt = TTFont(target_font)

        glyph_names = [g.strip() for g in glyphs.split(",")] if glyphs else list(NON_STANDARD_GLYPH_NAMES)

        resolver = GlyphAliasResolver(conflict_strategy=conflict_strategy)

        comparison_report = resolver.generate_cmap_report(src, tgt, glyph_names)
        conflict_report = resolver.detect_conflicts(tgt, glyph_names)

        if output_json:
            result = {
                "source_font": source_font,
                "target_font": target_font,
                "glyph_names": glyph_names,
                "comparison": comparison_report.to_dict(),
                "conflicts": conflict_report.to_dict(),
            }
            click.echo(json_mod.dumps(result, ensure_ascii=False, indent=2))
        else:
            click.echo(resolver.format_cmap_report(comparison_report))
            if conflict_report.has_conflicts:
                click.echo("")
                click.echo(resolver.format_conflict_report(conflict_report))

        src.close()
        tgt.close()

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def list_glyphs():
    """显示默认提取的字符列表"""
    click.echo("Default glyphs to extract:")
    click.echo("-" * 50)
    for i, name in enumerate(DEFAULT_GLYPH_NAMES, 1):
        click.echo(f"{i:3}. {name}")
    click.echo(f"Total: {len(DEFAULT_GLYPH_NAMES)}")


def main():
    """主入口函数"""
    cli()


if __name__ == "__main__":
    main()
