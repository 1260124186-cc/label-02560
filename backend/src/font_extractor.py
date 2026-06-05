"""字体字符提取和替换核心模块"""
import copy
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph

from .config import DEFAULT_GLYPH_NAMES, GLYPH_NAME_TO_UNICODE, NON_STANDARD_GLYPH_NAMES
from .exceptions import (
    FontLoadError, GlyphNotFoundError, FontSaveError, VariableFontError,
    MissingGlyphError, GlyphComponentError, GlyphNameConflictError
)
from .glyph_alias import GlyphAliasResolver
from .validator import (
    validate_font_file, validate_glyphs_exist, validate_output_path, is_variable_font
)
from .logger import get_logger

logger = get_logger(__name__)


class FontExtractor:
    """字体字符提取和替换器"""

    def __init__(self):
        self.source_font: Optional[TTFont] = None
        self.target_font: Optional[TTFont] = None
        self.source_path: Optional[Path] = None
        self.target_path: Optional[Path] = None
        self.extracted_glyphs: Dict[str, Any] = {}
        self.alias_resolver: Optional[GlyphAliasResolver] = None
        self._name_mapping: Dict[str, str] = {}

    def load_source_font(self, font_path: str) -> "FontExtractor":
        """
        加载源字体文件

        Args:
            font_path: 源字体文件路径

        Returns:
            self，支持链式调用
        """
        logger.info(f"Loading source font: {font_path}")
        self.source_font = validate_font_file(font_path)
        self.source_path = Path(font_path)
        return self

    def load_target_font(self, font_path: str) -> "FontExtractor":
        """
        加载目标字体文件

        Args:
            font_path: 目标字体文件路径

        Returns:
            self，支持链式调用
        """
        logger.info(f"Loading target font: {font_path}")
        self.target_font = validate_font_file(font_path)
        self.target_path = Path(font_path)
        return self

    def set_alias_resolver(self, resolver: GlyphAliasResolver) -> "FontExtractor":
        """
        设置字形名别名解析器

        Args:
            resolver: GlyphAliasResolver 实例

        Returns:
            self，支持链式调用
        """
        self.alias_resolver = resolver
        return self

    def resolve_glyph_names_for_extract(
        self,
        glyph_names: List[str],
    ) -> Tuple[List[str], List[str]]:
        """在 extract 前统一解析字形名

        流程：
        1. 若有 alias_resolver，执行名称解析（映射表 + Unicode 码位映射 + 冲突处理）
        2. 返回 (源字体中要提取的字形名列表, 跳过的字形名列表)
        3. 同时构建 _name_mapping 记录源名→目标名的映射，供 replace 时使用

        Args:
            glyph_names: 原始字形名列表

        Returns:
            (解析后用于提取的源字形名列表, 跳过的字形名列表)
        """
        if self.source_font is None or self.target_font is None:
            raise FontLoadError("Source and target fonts must be loaded before resolving names")

        if self.alias_resolver is None:
            return glyph_names, []

        resolved, skipped, conflict_report = self.alias_resolver.resolve_glyph_names(
            self.source_font, self.target_font, glyph_names
        )

        source_glyph_order = set(self.source_font.getGlyphOrder())
        target_glyph_order = set(self.target_font.getGlyphOrder())

        source_names_for_extract = []
        self._name_mapping = {}

        for orig, resolved_name in zip(glyph_names, resolved):
            if orig in skipped:
                continue
            if resolved_name in source_glyph_order:
                source_names_for_extract.append(resolved_name)
            elif orig in source_glyph_order:
                source_names_for_extract.append(orig)
                if orig != resolved_name:
                    self._name_mapping[orig] = resolved_name
            else:
                logger.warning(f"Glyph '{orig}' (resolved: '{resolved_name}') not found in source font, skipping")
                skipped.append(orig)

        logger.info(
            f"Name resolution: {len(source_names_for_extract)} to extract, "
            f"{len(self._name_mapping)} name mappings, {len(skipped)} skipped"
        )
        return source_names_for_extract, skipped

    def extract_glyphs(
        self,
        glyph_names: Optional[List[str]] = None,
        progress_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        从源字体提取指定字符

        Args:
            glyph_names: 要提取的字符名称列表，默认使用配置中的列表
            progress_callback: 进度回调，接收 (current, total, glyph_name) 参数

        Returns:
            提取的字符数据字典
        """
        if self.source_font is None:
            raise FontLoadError("Source font not loaded")

        if glyph_names is None:
            glyph_names = DEFAULT_GLYPH_NAMES

        logger.info(f"Extracting {len(glyph_names)} glyphs from source font")

        existing, missing = validate_glyphs_exist(self.source_font, glyph_names)

        if missing:
            logger.warning(f"Some glyphs not found in source font: {len(missing)} missing")

        # 预先检查是否为可变字体，避免每个 glyph 重复检查
        self._source_is_variable = is_variable_font(self.source_font)
        self._source_has_gvar = self._source_is_variable and "gvar" in self.source_font

        self.extracted_glyphs = {}
        total = len(existing)

        for i, glyph_name in enumerate(existing):
            glyph_data = self._extract_single_glyph(glyph_name)
            if glyph_data:
                self.extracted_glyphs[glyph_name] = glyph_data
            if progress_callback:
                progress_callback(i + 1, total, glyph_name)

        logger.info(f"Successfully extracted {len(self.extracted_glyphs)} glyphs")
        return self.extracted_glyphs

    def _extract_single_glyph(self, glyph_name: str) -> Optional[Dict[str, Any]]:
        """
        提取单个字符的所有相关数据

        Args:
            glyph_name: 字符名称

        Returns:
            字符数据字典

        Raises:
            FontLoadError: 字体表访问失败
        """
        glyph_data = {
            "name": glyph_name,
            "glyf": None,
            "hmtx": None,
            "vmtx": None,
            "cmap": None,
            "gvar": None,
        }

        # 提取glyf表数据（轮廓）
        if "glyf" in self.source_font:
            glyf_table = self.source_font["glyf"]
            if glyph_name in glyf_table:
                try:
                    glyph_data["glyf"] = copy.deepcopy(glyf_table[glyph_name])
                except Exception as e:
                    logger.warning(f"Failed to copy glyf data for {glyph_name}: {e}")

        # 提取CFF表数据（对于OTF字体）
        if "CFF " in self.source_font:
            glyph_data["cff"] = self._extract_cff_glyph(self.source_font["CFF "], glyph_name)

        # 提取hmtx（水平度量）
        if "hmtx" in self.source_font:
            hmtx = self.source_font["hmtx"]
            if glyph_name in hmtx.metrics:
                glyph_data["hmtx"] = hmtx.metrics[glyph_name]

        # 提取vmtx（垂直度量，如果存在）
        if "vmtx" in self.source_font:
            vmtx = self.source_font["vmtx"]
            if glyph_name in vmtx.metrics:
                glyph_data["vmtx"] = vmtx.metrics[glyph_name]

        # 提取cmap映射
        glyph_data["cmap"] = self._get_glyph_unicode(glyph_name)

        # 提取可变字体数据（使用缓存的检查结果）
        if self._source_has_gvar:
            gvar = self.source_font["gvar"]
            if glyph_name in gvar.variations:
                try:
                    glyph_data["gvar"] = copy.deepcopy(gvar.variations[glyph_name])
                except Exception as e:
                    logger.warning(f"Failed to copy gvar data for {glyph_name}: {e}")

        logger.debug(f"Extracted glyph: {glyph_name}")
        return glyph_data

    def _extract_cff_glyph(self, cff, glyph_name: str) -> Optional[Any]:
        """提取CFF字体的字符数据"""
        try:
            top_dict = cff.cff.topDictIndex[0]
            char_strings = top_dict.CharStrings
            if glyph_name in char_strings:
                return copy.deepcopy(char_strings[glyph_name])
        except Exception as e:
            logger.debug(f"CFF extraction failed for {glyph_name}: {e}")
        return None

    def _collect_composite_dependencies(
        self, glyph_name: str, source_font: TTFont, visited: Optional[set] = None
    ) -> List[str]:
        """
        递归收集复合字形的所有组件依赖字形名称。

        复合字形 (composite glyph) 在 glyf 表中由多个 component 引用其他字形组成。
        此方法递归遍历组件树，收集所有被引用的字形名称。

        Args:
            glyph_name: 起始字形名称
            source_font: 字体对象（从中读取 glyf 表）
            visited: 已访问的字形集合，防止循环引用

        Returns:
            依赖字形名称列表（不包含 glyph_name 自身）
        """
        if visited is None:
            visited = set()

        if glyph_name in visited:
            return []

        visited.add(glyph_name)
        dependencies = []

        if "glyf" not in source_font:
            return dependencies

        glyf_table = source_font["glyf"]
        glyph = glyf_table.get(glyph_name)
        if glyph is None:
            return dependencies

        if not hasattr(glyph, "components") or not glyph.components:
            return dependencies

        for comp in glyph.components:
            comp_name = comp.glyphName
            if comp_name and comp_name not in visited:
                dependencies.append(comp_name)
                sub_deps = self._collect_composite_dependencies(comp_name, source_font, visited)
                dependencies.extend(sub_deps)

        return dependencies

    def _append_glyph_to_target(
        self, glyph_name: str, glyph_data: Dict[str, Any],
        write_cmap: bool = True
    ) -> bool:
        """
        在目标字体中新增 glyph 槽位，更新 glyf/hmtx/maxp/loca/post 表，
        可选写入 cmap 映射。

        Args:
            glyph_name: 字形名称
            glyph_data: 从源字体提取的字形数据字典
            write_cmap: 是否将 Unicode 映射写入目标 cmap 表

        Returns:
            是否追加成功
        """
        if self.target_font is None:
            raise FontLoadError("Target font not loaded")

        glyph_order = list(self.target_font.getGlyphOrder())
        if glyph_name in glyph_order:
            logger.debug(f"Glyph '{glyph_name}' already in target, skip append")
            return False

        logger.info(f"Appending new glyph slot: {glyph_name}")

        glyph_order.append(glyph_name)
        self.target_font.setGlyphOrder(glyph_order)

        if "glyf" in self.target_font and glyph_data.get("glyf"):
            self.target_font["glyf"][glyph_name] = glyph_data["glyf"]
        elif "glyf" in self.target_font:
            from fontTools.ttLib.tables._g_l_y_f import Glyph as EmptyGlyph
            self.target_font["glyf"][glyph_name] = EmptyGlyph()

        if "hmtx" in self.target_font:
            if glyph_data.get("hmtx"):
                self.target_font["hmtx"].metrics[glyph_name] = glyph_data["hmtx"]
            else:
                self.target_font["hmtx"].metrics[glyph_name] = (500, 0)

        if "maxp" in self.target_font:
            self.target_font["maxp"].numGlyphs = len(glyph_order)

        if "post" in self.target_font:
            post = self.target_font["post"]
            if hasattr(post, "extraNames") and hasattr(post, "mapping"):
                if glyph_name not in post.mapping:
                    post.extraNames.append(glyph_name)
                    post.mapping[glyph_name] = len(glyph_order) - 1

        if write_cmap and glyph_data.get("cmap") is not None:
            unicode_val = glyph_data["cmap"]
            self._write_cmap_entry(glyph_name, unicode_val)

        logger.debug(f"Appended glyph '{glyph_name}' (total glyphs: {len(glyph_order)})")
        return True

    def _write_cmap_entry(self, glyph_name: str, unicode_val: int) -> None:
        """
        将字形写入目标字体的 cmap 子表。

        仅写入 platformID=3 (Windows) / encodingID=1 (Unicode BMP) 格式4 子表
        和 platformID=0 (Unicode) 格式4 子表。

        Args:
            glyph_name: 字形名称
            unicode_val: Unicode 码点
        """
        if "cmap" not in self.target_font:
            return

        glyph_order = self.target_font.getGlyphOrder()
        gid = glyph_order.index(glyph_name) if glyph_name in glyph_order else None
        if gid is None:
            return

        cmap = self.target_font["cmap"]
        for table in cmap.tables:
            if table.format == 4 and table.platEncID in (0, 1, 3):
                if table.platformID in (0, 3):
                    if hasattr(table, "cmap") and table.cmap is not None:
                        table.cmap[unicode_val] = glyph_name

        logger.debug(f"Wrote cmap entry: U+{unicode_val:04X} -> {glyph_name}")

    def _validate_glyf_components(self, font: TTFont) -> List[Tuple[str, str]]:
        """
        校验字体中所有复合字形 (composite glyph) 的组件引用，
        检查被引用的字形是否存在于 glyphOrder 中。

        Args:
            font: TTFont 对象

        Returns:
            列表，每项为 (glyph_name, component_name) 表示组件引用不存在的字形；
            空列表表示全部通过。
        """
        if "glyf" not in font:
            return []

        glyph_order = set(font.getGlyphOrder())
        invalid = []

        glyf_table = font["glyf"]
        for glyph_name in glyph_order:
            glyph = glyf_table.get(glyph_name)
            if glyph is None:
                continue
            if not hasattr(glyph, "components") or not glyph.components:
                continue
            for comp in glyph.components:
                comp_name = comp.glyphName
                if comp_name and comp_name not in glyph_order:
                    invalid.append((glyph_name, comp_name))

        return invalid

    def _get_glyph_unicode(self, glyph_name: str) -> Optional[int]:
        """获取字符的Unicode码点"""
        # 首先从cmap表查找（最可靠，直接反映字体实际映射）
        if "cmap" in self.source_font:
            cmap = self.source_font.getBestCmap()
            if cmap:
                for unicode_val, name in cmap.items():
                    if name == glyph_name:
                        return unicode_val

        # 非标准字符名称：优先从字体的所有cmap子表中查找
        # 不同字体对glyph22-31的映射可能不同，需要遍历所有子表
        if glyph_name in NON_STANDARD_GLYPH_NAMES:
            logger.debug(f"Non-standard glyph '{glyph_name}' - searching all cmap subtables")
            if "cmap" in self.source_font:
                for table in self.source_font["cmap"].tables:
                    if hasattr(table, "cmap") and table.cmap:
                        for unicode_val, name in table.cmap.items():
                            if name == glyph_name:
                                logger.debug(
                                    f"Found '{glyph_name}' -> U+{unicode_val:04X} "
                                    f"in cmap subtable (platform={table.platformID})"
                                )
                                return unicode_val

            # 如果所有cmap子表都找不到，说明该字符没有Unicode映射
            # 这在字体中是合法的（未编码字符），按glyph名称直接处理即可
            logger.debug(f"Non-standard glyph '{glyph_name}' has no cmap entry, treating as unencoded")
            return None

        # 标准字符从配置映射查找
        if glyph_name in GLYPH_NAME_TO_UNICODE:
            return GLYPH_NAME_TO_UNICODE[glyph_name]

        return None

    def replace_glyphs(
        self,
        glyphs_data: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Any] = None,
        missing_glyph_mode: str = "strict",
        write_cmap: bool = True
    ) -> "FontExtractor":
        """
        将提取的字符替换到目标字体

        若存在 _name_mapping（别名解析产生的源名→目标名映射），
        则在替换时将源名下的字形数据写入目标名对应的槽位。

        Args:
            glyphs_data: 要替换的字符数据，默认使用已提取的数据
            progress_callback: 进度回调，接收 (current, total, glyph_name) 参数
            missing_glyph_mode: 缺字处理模式
                - "strict": 缺字即失败，列出缺字清单（默认，与现行为一致）
                - "append": 在目标中新增 glyph 槽位，从源复制数据
            write_cmap: append 模式下是否将 Unicode 映射写入目标 cmap 表

        Returns:
            self，支持链式调用

        Raises:
            MissingGlyphError: strict 模式下目标字体缺字时抛出
        """
        if self.target_font is None:
            raise FontLoadError("Target font not loaded")

        if glyphs_data is None:
            glyphs_data = self.extracted_glyphs

        if not glyphs_data:
            raise GlyphNotFoundError("No glyphs to replace")

        if missing_glyph_mode not in ("strict", "append"):
            raise ValueError(f"Invalid missing_glyph_mode: {missing_glyph_mode!r}, must be 'strict' or 'append'")

        logger.info(f"Replacing {len(glyphs_data)} glyphs in target font (mode={missing_glyph_mode})")

        target_glyph_order = set(self.target_font.getGlyphOrder())

        remapped_data: Dict[str, Any] = {}
        reverse_mapping = {v: k for k, v in self._name_mapping.items()}

        for src_name, data in glyphs_data.items():
            if src_name in self._name_mapping:
                tgt_name = self._name_mapping[src_name]
                remapped_data[tgt_name] = data
                logger.debug(f"Name mapping during replace: source '{src_name}' -> target '{tgt_name}'")
            else:
                remapped_data[src_name] = data

        missing_in_target = [
            name for name in remapped_data if name not in target_glyph_order
        ]

        if missing_glyph_mode == "strict" and missing_in_target:
            logger.error(f"Target font missing {len(missing_in_target)} glyphs: {missing_in_target}")
            raise MissingGlyphError(
                f"Target font is missing {len(missing_in_target)} glyphs: {missing_in_target}",
                missing_glyphs=missing_in_target
            )

        if missing_glyph_mode == "append" and missing_in_target:
            self._ensure_composite_deps_in_source(missing_in_target, remapped_data)

        replaced_count = 0
        appended_count = 0
        total = len(remapped_data)
        for i, (glyph_name, glyph_data) in enumerate(remapped_data.items()):
            if glyph_name in target_glyph_order:
                if self._replace_single_glyph(glyph_name, glyph_data):
                    replaced_count += 1
            elif missing_glyph_mode == "append":
                if self._append_glyph_to_target(glyph_name, glyph_data, write_cmap=write_cmap):
                    appended_count += 1
            if progress_callback:
                progress_callback(i + 1, total, glyph_name)

        logger.info(f"Replaced {replaced_count} glyphs, appended {appended_count} new glyphs")
        return self

    def _ensure_composite_deps_in_source(
        self, glyph_names: List[str], glyphs_data: Dict[str, Any]
    ) -> None:
        """
        对需要追加到目标字形的字形，从源字体递归收集复合字形组件依赖，
        将缺失的依赖字形数据一并加入 glyphs_data。

        如果依赖字形已在目标字体中存在，则无需从源复制；
        如果依赖字形不在目标字体中也不在源字体中，记录警告。

        Args:
            glyph_names: 需要追加的字形名称列表
            glyphs_data: 字形数据字典（会被就地修改）
        """
        if self.source_font is None:
            logger.warning("Source font not loaded, cannot resolve composite dependencies")
            return

        target_glyph_order = set(self.target_font.getGlyphOrder())
        all_deps_needed = set()

        for name in glyph_names:
            deps = self._collect_composite_dependencies(name, self.source_font)
            for dep_name in deps:
                if dep_name not in target_glyph_order and dep_name not in glyphs_data:
                    all_deps_needed.add(dep_name)

        for dep_name in all_deps_needed:
            if dep_name in self.source_font.getGlyphOrder():
                dep_data = self._extract_single_glyph(dep_name)
                if dep_data:
                    glyphs_data[dep_name] = dep_data
                    logger.info(f"Collected composite dependency: {dep_name}")
            else:
                logger.warning(
                    f"Composite dependency '{dep_name}' not found in source font either; "
                    f"target font may have broken composite reference"
                )

    def _replace_single_glyph(self, glyph_name: str, glyph_data: Dict[str, Any]) -> bool:
        """
        替换单个字符（仅处理目标字体中已存在的字形槽位）

        Args:
            glyph_name: 字符名称
            glyph_data: 字符数据

        Returns:
            是否替换成功
        """
        replaced_any = False

        # 替换glyf表数据
        if glyph_data.get("glyf") and "glyf" in self.target_font:
            try:
                self.target_font["glyf"][glyph_name] = glyph_data["glyf"]
                replaced_any = True
            except Exception as e:
                logger.warning(f"Failed to replace glyf for {glyph_name}: {e}")

        # 替换CFF数据
        if glyph_data.get("cff") and "CFF " in self.target_font:
            try:
                self._replace_cff_glyph(glyph_name, glyph_data["cff"])
                replaced_any = True
            except Exception as e:
                logger.warning(f"Failed to replace CFF for {glyph_name}: {e}")

        # 替换hmtx
        if glyph_data.get("hmtx") and "hmtx" in self.target_font:
            try:
                self.target_font["hmtx"].metrics[glyph_name] = glyph_data["hmtx"]
                replaced_any = True
            except Exception as e:
                logger.warning(f"Failed to replace hmtx for {glyph_name}: {e}")

        # 替换vmtx
        if glyph_data.get("vmtx") and "vmtx" in self.target_font:
            try:
                self.target_font["vmtx"].metrics[glyph_name] = glyph_data["vmtx"]
                replaced_any = True
            except Exception as e:
                logger.warning(f"Failed to replace vmtx for {glyph_name}: {e}")

        # 替换可变字体数据
        if glyph_data.get("gvar") and "gvar" in self.target_font:
            try:
                self._replace_gvar_data(glyph_name, glyph_data["gvar"])
                replaced_any = True
            except VariableFontError as e:
                logger.warning(f"Skipped gvar for {glyph_name}: {e}")
            except Exception as e:
                logger.warning(f"Failed to replace gvar for {glyph_name}: {e}")

        if replaced_any:
            logger.debug(f"Replaced glyph: {glyph_name}")
        return replaced_any

    def _replace_cff_glyph(self, glyph_name: str, cff_data: Any) -> None:
        """替换CFF字体的字符数据"""
        cff = self.target_font["CFF "]
        top_dict = cff.cff.topDictIndex[0]
        char_strings = top_dict.CharStrings
        if glyph_name in char_strings:
            char_strings[glyph_name] = cff_data
        else:
            logger.debug(f"CFF CharString not found for {glyph_name} in target")

    def _replace_gvar_data(self, glyph_name: str, gvar_data: Any) -> None:
        """
        替换可变字体变体数据，处理轴顺序差异

        Raises:
            VariableFontError: 轴不兼容
        """
        if "gvar" not in self.target_font:
            return

        gvar = self.target_font["gvar"]

        if not self._check_axis_compatibility():
            raise VariableFontError(f"Axis incompatibility for {glyph_name}")

        # 检查轴顺序是否一致，不一致则需要重映射
        src_axis_order = [a.axisTag for a in self.source_font["fvar"].axes]
        tgt_axis_order = [a.axisTag for a in self.target_font["fvar"].axes]

        if src_axis_order == tgt_axis_order:
            # 轴顺序一致，直接替换
            gvar.variations[glyph_name] = gvar_data
            logger.debug(f"Replaced gvar data for {glyph_name} (axes match)")
        else:
            # 轴顺序不同，需要重映射 gvar 的 tuple variation 坐标
            remapped = self._remap_gvar_axes(gvar_data, src_axis_order, tgt_axis_order)
            gvar.variations[glyph_name] = remapped
            logger.info(
                f"Replaced gvar data for {glyph_name} with axis remapping: "
                f"{src_axis_order} -> {tgt_axis_order}"
            )

    def _remap_gvar_axes(
        self,
        gvar_data: list,
        src_order: List[str],
        tgt_order: List[str]
    ) -> list:
        """
        重映射 gvar 变体数据的轴坐标顺序

        gvar 中每个 TupleVariation 的 axes 字典键是轴标签，
        所以实际上 fonttools 内部已经用标签做 key，不需要按索引重排。
        但如果目标字体有额外的轴，需要确保不引入无效坐标。

        Args:
            gvar_data: 源字体的 gvar variations 列表
            src_order: 源字体轴顺序
            tgt_order: 目标字体轴顺序

        Returns:
            重映射后的 variations 列表
        """
        remapped = []
        src_tags = set(src_order)

        for variation in gvar_data:
            # TupleVariation 的 axes 是 {axisTag: (minValue, peakValue, maxValue)}
            if hasattr(variation, "axes") and isinstance(variation.axes, dict):
                # 只保留目标字体中存在的轴坐标
                new_axes = {}
                for tag, coords in variation.axes.items():
                    if tag in set(tgt_order):
                        new_axes[tag] = coords
                    else:
                        logger.debug(f"Dropping axis '{tag}' not in target font")
                variation.axes = new_axes
            remapped.append(variation)

        return remapped

    def _check_axis_compatibility(self) -> bool:
        """检查源字体和目标字体的可变轴是否兼容（标签、范围、默认值、相关表）"""
        if not (is_variable_font(self.source_font) and is_variable_font(self.target_font)):
            return False

        source_axes = {a.axisTag: a for a in self.source_font["fvar"].axes}
        target_axes = {a.axisTag: a for a in self.target_font["fvar"].axes}

        # 检查源字体的轴是否都在目标字体中
        if not set(source_axes.keys()).issubset(set(target_axes.keys())):
            logger.warning(
                f"Axis tag mismatch - Source: {set(source_axes.keys())}, "
                f"Target: {set(target_axes.keys())}"
            )
            return False

        # 检查共有轴的范围和默认值兼容性
        for tag, src_axis in source_axes.items():
            tgt_axis = target_axes[tag]

            # 检查默认值是否一致
            if src_axis.defaultValue != tgt_axis.defaultValue:
                logger.warning(
                    f"Axis '{tag}' default mismatch - "
                    f"Source: {src_axis.defaultValue}, Target: {tgt_axis.defaultValue}"
                )

            # 检查范围是否兼容（源轴范围应在目标轴范围内）
            if src_axis.minValue < tgt_axis.minValue or src_axis.maxValue > tgt_axis.maxValue:
                logger.warning(
                    f"Axis '{tag}' range mismatch - "
                    f"Source: [{src_axis.minValue}, {src_axis.maxValue}], "
                    f"Target: [{tgt_axis.minValue}, {tgt_axis.maxValue}]"
                )
                return False

        # 检查变体相关表的一致性
        variation_tables = ["HVAR", "VVAR", "MVAR"]
        for table_tag in variation_tables:
            src_has = table_tag in self.source_font
            tgt_has = table_tag in self.target_font
            if src_has and not tgt_has:
                logger.warning(
                    f"Source font has '{table_tag}' table but target does not. "
                    f"Variation metrics may be incomplete."
                )
            elif not src_has and tgt_has:
                logger.debug(
                    f"Target font has '{table_tag}' table but source does not. "
                    f"Existing target variation metrics will be preserved."
                )

        # 检查gvar表的轴数量是否匹配
        if "gvar" in self.source_font and "gvar" in self.target_font:
            src_axis_count = len(self.source_font["fvar"].axes)
            tgt_axis_count = len(self.target_font["fvar"].axes)
            if src_axis_count != tgt_axis_count:
                logger.warning(
                    f"Axis count differs - Source: {src_axis_count}, Target: {tgt_axis_count}. "
                    f"gvar data will be remapped."
                )

            # 检查轴顺序
            src_order = [a.axisTag for a in self.source_font["fvar"].axes]
            tgt_order = [a.axisTag for a in self.target_font["fvar"].axes]
            if src_order != tgt_order:
                logger.info(
                    f"Axis order differs - Source: {src_order}, Target: {tgt_order}. "
                    f"gvar coordinates will be remapped."
                )

        return True

    def save(self, output_path: str) -> Path:
        """
        保存修改后的字体文件

        保存前会校验 glyf 表中所有复合字形的组件引用，
        确保被引用的字形在目标字体中均存在。

        Args:
            output_path: 输出文件路径

        Returns:
            保存的文件路径

        Raises:
            GlyphComponentError: 复合字形组件引用了不存在的字形
        """
        if self.target_font is None:
            raise FontLoadError("Target font not loaded")

        invalid_refs = self._validate_glyf_components(self.target_font)
        if invalid_refs:
            details = "; ".join(
                f"{glyph} -> {comp}" for glyph, comp in invalid_refs
            )
            logger.error(f"Invalid glyf component references: {details}")
            raise GlyphComponentError(
                f"Found {len(invalid_refs)} invalid component reference(s): {details}"
            )

        output = validate_output_path(output_path)

        try:
            logger.info(f"Saving font to: {output_path}")
            self.target_font.save(str(output))
            logger.info(f"Font saved successfully: {output_path}")
            return output
        except Exception as e:
            logger.error(f"Failed to save font: {e}")
            raise FontSaveError(f"Failed to save font: {e}")

    def close(self) -> None:
        """关闭字体文件"""
        if self.source_font:
            self.source_font.close()
            self.source_font = None
        if self.target_font:
            self.target_font.close()
            self.target_font = None
        logger.info("Font files closed")

    def get_extraction_report(self) -> Dict[str, Any]:
        """
        获取提取报告

        Returns:
            提取报告字典
        """
        return {
            "source_font": str(self.source_path) if self.source_path else None,
            "target_font": str(self.target_path) if self.target_path else None,
            "source_is_variable": is_variable_font(self.source_font) if self.source_font else False,
            "target_is_variable": is_variable_font(self.target_font) if self.target_font else False,
            "extracted_glyphs_count": len(self.extracted_glyphs),
            "extracted_glyphs": list(self.extracted_glyphs.keys()),
        }


def extract_and_replace(
    source_font_path: str,
    target_font_path: str,
    output_path: str,
    glyph_names: Optional[List[str]] = None,
    progress_callback: Optional[Any] = None,
    missing_glyph_mode: str = "strict",
    write_cmap: bool = True,
    mapping_path: Optional[str] = None,
    conflict_strategy: str = "abort",
) -> Tuple[Path, Dict[str, Any]]:
    """
    一键提取和替换字符的便捷函数

    Args:
        source_font_path: 源字体文件路径
        target_font_path: 目标字体文件路径
        output_path: 输出文件路径
        glyph_names: 要提取的字符名称列表
        progress_callback: 进度回调，接收 (phase, current, total, glyph_name) 参数
            phase: "extract" 或 "replace"
        missing_glyph_mode: 缺字处理模式，"strict" 或 "append"
        write_cmap: append 模式下是否将 Unicode 映射写入目标 cmap 表
        mapping_path: 源名→目标名映射文件路径（JSON），可选
        conflict_strategy: 冲突策略，"abort"/"skip"/"first"

    Returns:
        (输出文件路径, 提取报告)
    """
    extractor = FontExtractor()

    def _extract_cb(current, total, name):
        if progress_callback:
            progress_callback("extract", current, total, name)

    def _replace_cb(current, total, name):
        if progress_callback:
            progress_callback("replace", current, total, name)

    try:
        extractor.load_source_font(source_font_path)
        extractor.load_target_font(target_font_path)

        if mapping_path:
            resolver = GlyphAliasResolver(conflict_strategy=conflict_strategy)
            resolver.load_mapping(mapping_path)
            extractor.set_alias_resolver(resolver)

            if glyph_names is None:
                glyph_names = list(DEFAULT_GLYPH_NAMES)
            resolved_names, skipped = extractor.resolve_glyph_names_for_extract(glyph_names)
            if skipped:
                logger.warning(f"Skipped {len(skipped)} glyphs due to conflicts: {skipped}")
            extractor.extract_glyphs(resolved_names, progress_callback=_extract_cb)
        else:
            extractor.extract_glyphs(glyph_names, progress_callback=_extract_cb)

        extractor.replace_glyphs(
            progress_callback=_replace_cb,
            missing_glyph_mode=missing_glyph_mode,
            write_cmap=write_cmap
        )
        output = extractor.save(output_path)
        report = extractor.get_extraction_report()
        return output, report
    finally:
        extractor.close()
