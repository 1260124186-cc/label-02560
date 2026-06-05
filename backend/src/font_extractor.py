"""字体字符提取和替换核心模块"""
import copy
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph

from .config import DEFAULT_GLYPH_NAMES, GLYPH_NAME_TO_UNICODE, NON_STANDARD_GLYPH_NAMES
from .exceptions import (
    FontLoadError, GlyphNotFoundError, FontSaveError, VariableFontError
)
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
        progress_callback: Optional[Any] = None
    ) -> "FontExtractor":
        """
        将提取的字符替换到目标字体
        
        Args:
            glyphs_data: 要替换的字符数据，默认使用已提取的数据
            progress_callback: 进度回调，接收 (current, total, glyph_name) 参数
            
        Returns:
            self，支持链式调用
        """
        if self.target_font is None:
            raise FontLoadError("Target font not loaded")
        
        if glyphs_data is None:
            glyphs_data = self.extracted_glyphs
        
        if not glyphs_data:
            raise GlyphNotFoundError("No glyphs to replace")
        
        logger.info(f"Replacing {len(glyphs_data)} glyphs in target font")
        
        replaced_count = 0
        total = len(glyphs_data)
        for i, (glyph_name, glyph_data) in enumerate(glyphs_data.items()):
            if self._replace_single_glyph(glyph_name, glyph_data):
                replaced_count += 1
            if progress_callback:
                progress_callback(i + 1, total, glyph_name)
        
        logger.info(f"Successfully replaced {replaced_count} glyphs")
        return self
    
    def _replace_single_glyph(self, glyph_name: str, glyph_data: Dict[str, Any]) -> bool:
        """
        替换单个字符
        
        Args:
            glyph_name: 字符名称
            glyph_data: 字符数据
            
        Returns:
            是否替换成功
        """
        # 检查目标字体是否有该字符
        glyph_order = self.target_font.getGlyphOrder()
        
        if glyph_name not in glyph_order:
            logger.warning(f"Glyph {glyph_name} not in target font, skipping")
            return False
        
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
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            保存的文件路径
        """
        if self.target_font is None:
            raise FontLoadError("Target font not loaded")
        
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
    progress_callback: Optional[Any] = None
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
        extractor.extract_glyphs(glyph_names, progress_callback=_extract_cb)
        extractor.replace_glyphs(progress_callback=_replace_cb)
        output = extractor.save(output_path)
        report = extractor.get_extraction_report()
        return output, report
    finally:
        extractor.close()
