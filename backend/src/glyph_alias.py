"""字形名对齐与别名解析层

提供源名→目标名映射表支持（CLI -m 或映射文件），
在 extract 前统一解析名称；支持按 Unicode 码位在源/目标各查 cmap 得到实际 glyph 名；
对 glyph22~glyph31 等非标准名扫描全部 cmap 子表生成对照报告；
冲突策略：一名多码、一码多名时告警并中止/跳过可配置。
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from fontTools.ttLib import TTFont

from .config import NON_STANDARD_GLYPH_NAMES
from .logger import get_logger

logger = get_logger(__name__)


class CmapEntry:
    """cmap 子表中一条映射记录"""

    __slots__ = ("codepoint", "platform_id", "encoding_id", "subtable_index", "glyph_name", "subtable_format")

    def __init__(
        self,
        codepoint: int,
        platform_id: int,
        encoding_id: int,
        subtable_index: int,
        glyph_name: str,
        subtable_format: int,
    ):
        self.codepoint = codepoint
        self.platform_id = platform_id
        self.encoding_id = encoding_id
        self.subtable_index = subtable_index
        self.glyph_name = glyph_name
        self.subtable_format = subtable_format

    def to_dict(self) -> Dict[str, Any]:
        return {
            "codepoint": f"U+{self.codepoint:04X}",
            "codepoint_int": self.codepoint,
            "platform_id": self.platform_id,
            "encoding_id": self.encoding_id,
            "subtable_index": self.subtable_index,
            "glyph_name": self.glyph_name,
            "subtable_format": self.subtable_format,
        }


class ConflictRecord:
    """冲突记录：一名多码或一码多名"""

    __slots__ = ("conflict_type", "key", "values")

    def __init__(self, conflict_type: str, key: str, values: List[str]):
        self.conflict_type = conflict_type
        self.key = key
        self.values = values

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_type": self.conflict_type,
            "key": self.key,
            "values": self.values,
        }


class ConflictReport:
    """冲突检测报告"""

    def __init__(self):
        self.name_to_multi_codepoint: List[ConflictRecord] = []
        self.codepoint_to_multi_name: List[ConflictRecord] = []

    @property
    def has_conflicts(self) -> bool:
        return bool(self.name_to_multi_codepoint) or bool(self.codepoint_to_multi_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_conflicts": self.has_conflicts,
            "name_to_multi_codepoint": [r.to_dict() for r in self.name_to_multi_codepoint],
            "codepoint_to_multi_name": [r.to_dict() for r in self.codepoint_to_multi_name],
        }


class CmapComparisonReport:
    """源/目标 cmap 对照报告（用于非标准字形名）"""

    def __init__(self):
        self.entries: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {"entries": self.entries}


class GlyphAliasResolver:
    """字形名对齐与别名解析器

    功能：
    1. 加载源名→目标名映射表（JSON 文件）
    2. 按映射表将源字形名解析为目标字形名
    3. 按 Unicode 码位在源/目标各查 cmap 得到实际字形名
    4. 对非标准字形名扫描全部 cmap 子表生成对照报告
    5. 冲突检测：一名多码、一码多名时告警，支持 abort/skip/first 策略
    """

    CONFLICT_ABORT = "abort"
    CONFLICT_SKIP = "skip"
    CONFLICT_FIRST = "first"
    CONFLICT_STRATEGIES = (CONFLICT_ABORT, CONFLICT_SKIP, CONFLICT_FIRST)

    def __init__(self, conflict_strategy: str = "abort"):
        self._mapping: Dict[str, str] = {}
        self._conflict_strategy = conflict_strategy

    @property
    def mapping(self) -> Dict[str, str]:
        return dict(self._mapping)

    def load_mapping(self, mapping_path: str) -> None:
        """从 JSON 文件加载源名→目标名映射表

        JSON 格式示例：
        {
            "glyph22": "zero",
            "glyph23": "one"
        }

        Args:
            mapping_path: 映射文件路径
        """
        path = Path(mapping_path)
        if not path.exists():
            raise FileNotFoundError(f"Mapping file not found: {mapping_path}")
        if not path.is_file():
            raise ValueError(f"Mapping path is not a file: {mapping_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Mapping file must contain a JSON object, got {type(data).__name__}")

        self._mapping = {}
        for src_name, tgt_name in data.items():
            if not isinstance(src_name, str) or not isinstance(tgt_name, str):
                raise ValueError(
                    f"Mapping keys and values must be strings, got {type(src_name).__name__}->{type(tgt_name).__name__}"
                )
            self._mapping[src_name] = tgt_name

        logger.info(f"Loaded {len(self._mapping)} glyph name mappings from {mapping_path}")

    def load_mapping_from_dict(self, mapping: Dict[str, str]) -> None:
        """从字典加载映射表"""
        self._mapping = dict(mapping)
        logger.info(f"Loaded {len(self._mapping)} glyph name mappings from dict")

    def resolve_name(self, glyph_name: str) -> str:
        """将源字形名解析为目标字形名

        如果映射表中存在该名称，返回映射后的名称；否则返回原名称。

        Args:
            glyph_name: 源字形名

        Returns:
            解析后的字形名
        """
        return self._mapping.get(glyph_name, glyph_name)

    def resolve_names(self, glyph_names: List[str]) -> List[str]:
        """批量解析字形名

        Args:
            glyph_names: 源字形名列表

        Returns:
            解析后的字形名列表
        """
        return [self.resolve_name(n) for n in glyph_names]

    @staticmethod
    def lookup_by_unicode(font: TTFont, codepoint: int) -> Optional[str]:
        """在字体的最佳 cmap 中按 Unicode 码位查找字形名

        Args:
            font: TTFont 对象
            codepoint: Unicode 码位

        Returns:
            字形名，未找到返回 None
        """
        best_cmap = font.getBestCmap()
        if best_cmap:
            return best_cmap.get(codepoint)
        return None

    @staticmethod
    def lookup_by_unicode_all(font: TTFont, codepoint: int) -> List[CmapEntry]:
        """在字体所有 cmap 子表中按 Unicode 码位查找字形名

        Args:
            font: TTFont 对点
            codepoint: Unicode 码位

        Returns:
            所有匹配的 CmapEntry 列表
        """
        results = []
        if "cmap" not in font:
            return results

        for idx, table in enumerate(font["cmap"].tables):
            if not hasattr(table, "cmap") or table.cmap is None:
                continue
            if codepoint in table.cmap:
                results.append(
                    CmapEntry(
                        codepoint=codepoint,
                        platform_id=table.platformID,
                        encoding_id=table.platEncID,
                        subtable_index=idx,
                        glyph_name=table.cmap[codepoint],
                        subtable_format=table.format,
                    )
                )
        return results

    @staticmethod
    def lookup_glyph_name_all_cmap(font: TTFont, glyph_name: str) -> List[CmapEntry]:
        """在字体所有 cmap 子表中查找字形名对应的全部码位映射

        Args:
            font: TTFont 对象
            glyph_name: 字形名

        Returns:
            所有匹配的 CmapEntry 列表
        """
        results = []
        if "cmap" not in font:
            return results

        for idx, table in enumerate(font["cmap"].tables):
            if not hasattr(table, "cmap") or table.cmap is None:
                continue
            for codepoint, name in table.cmap.items():
                if name == glyph_name:
                    results.append(
                        CmapEntry(
                            codepoint=codepoint,
                            platform_id=table.platformID,
                            encoding_id=table.platEncID,
                            subtable_index=idx,
                            glyph_name=name,
                            subtable_format=table.format,
                        )
                    )
        return results

    def build_unicode_mapping(
        self,
        source_font: TTFont,
        target_font: TTFont,
        glyph_names: List[str],
    ) -> Dict[str, str]:
        """按 Unicode 码位在源/目标各查 cmap 得到源名→目标名映射

        对每个源字形名：先在源字体查其 Unicode 码位，再在目标字体中用同一码位查字形名。

        Args:
            source_font: 源字体
            target_font: 目标字体
            glyph_names: 需要映射的源字形名列表

        Returns:
            源名→目标名映射字典
        """
        result = {}
        source_best_cmap = source_font.getBestCmap() or {}
        reverse_source = {v: k for k, v in source_best_cmap.items()}

        target_best_cmap = target_font.getBestCmap() or {}

        for src_name in glyph_names:
            codepoint = reverse_source.get(src_name)
            if codepoint is None:
                logger.debug(f"Glyph '{src_name}' has no cmap entry in source font, skipping unicode mapping")
                continue

            tgt_name = target_best_cmap.get(codepoint)
            if tgt_name is None:
                logger.debug(
                    f"Unicode U+{codepoint:04X} (source glyph '{src_name}') not found in target cmap"
                )
                continue

            if tgt_name != src_name:
                result[src_name] = tgt_name
                logger.debug(f"Unicode mapping: source '{src_name}' -> target '{tgt_name}' (U+{codepoint:04X})")

        if result:
            logger.info(f"Built {len(result)} unicode-based name mappings from cmap")
        return result

    def detect_conflicts(self, font: TTFont, glyph_names: Optional[List[str]] = None) -> ConflictReport:
        """检测字体中的字形名冲突

        冲突类型：
        - name_to_multi_codepoint: 同一字形名映射到多个 Unicode 码位
        - codepoint_to_multi_name: 同一 Unicode 码位映射到多个字形名

        Args:
            font: TTFont 对象
            glyph_names: 限定检测范围的字形名列表，None 表示检测全部

        Returns:
            ConflictReport 冲突报告
        """
        report = ConflictReport()

        if "cmap" not in font:
            return report

        name_to_codepoints: Dict[str, set] = {}
        codepoint_to_names: Dict[int, set] = {}

        for table in font["cmap"].tables:
            if not hasattr(table, "cmap") or table.cmap is None:
                continue
            for codepoint, name in table.cmap.items():
                if glyph_names is not None and name not in glyph_names:
                    continue
                name_to_codepoints.setdefault(name, set()).add(codepoint)
                codepoint_to_names.setdefault(codepoint, set()).add(name)

        for name, codepoints in name_to_codepoints.items():
            if len(codepoints) > 1:
                record = ConflictRecord(
                    conflict_type="name_to_multi_codepoint",
                    key=name,
                    values=sorted(f"U+{cp:04X}" for cp in codepoints),
                )
                report.name_to_multi_codepoint.append(record)
                logger.warning(f"Conflict: glyph '{name}' maps to multiple codepoints: {record.values}")

        for codepoint, names in codepoint_to_names.items():
            if len(names) > 1:
                record = ConflictRecord(
                    conflict_type="codepoint_to_multi_name",
                    key=f"U+{codepoint:04X}",
                    values=sorted(names),
                )
                report.codepoint_to_multi_name.append(record)
                logger.warning(f"Conflict: U+{codepoint:04X} maps to multiple names: {record.values}")

        return report

    def generate_cmap_report(
        self,
        source_font: TTFont,
        target_font: TTFont,
        glyph_names: Optional[List[str]] = None,
    ) -> CmapComparisonReport:
        """生成非标准字形名的源/目标 cmap 对照报告

        对 glyph22~glyph31 等非标准名：扫描源/目标全部 cmap 子表，
        生成对照报告（码位、平台 ID、子表索引），供人工确认是否同一字符。

        Args:
            source_font: 源字体
            target_font: 目标字体
            glyph_names: 需要报告的字形名列表，默认使用 NON_STANDARD_GLYPH_NAMES

        Returns:
            CmapComparisonReport 对照报告
        """
        if glyph_names is None:
            glyph_names = list(NON_STANDARD_GLYPH_NAMES)

        report = CmapComparisonReport()

        for name in glyph_names:
            src_entries = self.lookup_glyph_name_all_cmap(source_font, name)
            tgt_entries = self.lookup_glyph_name_all_cmap(target_font, name)

            entry = {
                "glyph_name": name,
                "source_cmap": [e.to_dict() for e in src_entries],
                "target_cmap": [e.to_dict() for e in tgt_entries],
                "source_count": len(src_entries),
                "target_count": len(tgt_entries),
            }

            src_codepoints = {e.codepoint for e in src_entries}
            tgt_codepoints = {e.codepoint for e in tgt_entries}

            if src_codepoints and tgt_codepoints:
                if src_codepoints & tgt_codepoints:
                    entry["match_status"] = "codepoint_overlap"
                    entry["overlap_codepoints"] = sorted(f"U+{cp:04X}" for cp in (src_codepoints & tgt_codepoints))
                else:
                    entry["match_status"] = "codepoint_mismatch"
            elif src_codepoints and not tgt_codepoints:
                entry["match_status"] = "source_only"
            elif not src_codepoints and tgt_codepoints:
                entry["match_status"] = "target_only"
            else:
                entry["match_status"] = "neither_mapped"

            report.entries.append(entry)

        return report

    def resolve_glyph_names(
        self,
        source_font: TTFont,
        target_font: TTFont,
        glyph_names: List[str],
    ) -> Tuple[List[str], List[str], ConflictReport]:
        """统一解析字形名：映射表 + Unicode 码位映射 + 冲突检测

        处理流程：
        1. 检测目标字体中的冲突
        2. 应用映射表解析
        3. 对仍不匹配的名称按 Unicode 码位在源/目标 cmap 中查找映射
        4. 根据 conflict_strategy 处理冲突

        Args:
            source_font: 源字体
            target_font: 目标字体
            glyph_names: 原始字形名列表

        Returns:
            (解析后字形名列表, 跳过的字形名列表, 冲突报告)
        """
        conflict_report = self.detect_conflicts(target_font, glyph_names)
        skipped: List[str] = []

        if conflict_report.has_conflicts:
            if self._conflict_strategy == self.CONFLICT_ABORT:
                from .exceptions import GlyphNameConflictError
                raise GlyphNameConflictError(
                    f"Glyph name conflicts detected in target font",
                    conflict_report=conflict_report,
                )
            elif self._conflict_strategy == self.CONFLICT_SKIP:
                conflicted_names = set()
                for r in conflict_report.name_to_multi_codepoint:
                    conflicted_names.add(r.key)
                for r in conflict_report.codepoint_to_multi_name:
                    conflicted_names.update(r.values)
                for name in glyph_names:
                    if name in conflicted_names:
                        skipped.append(name)
                        logger.warning(f"Skipping conflicted glyph: {name}")

        resolved = self.resolve_names(glyph_names)

        target_glyph_order = set(target_font.getGlyphOrder())
        still_unresolved = [
            (orig, resolved_name)
            for orig, resolved_name in zip(glyph_names, resolved)
            if resolved_name not in target_glyph_order and resolved_name not in skipped
        ]

        if still_unresolved:
            unicode_mapping = self.build_unicode_mapping(
                source_font, target_font, [name for name, _ in still_unresolved]
            )
            if unicode_mapping:
                final_resolved = []
                for orig, resolved_name in zip(glyph_names, resolved):
                    if orig in skipped:
                        final_resolved.append(resolved_name)
                        continue
                    if resolved_name not in target_glyph_order and orig in unicode_mapping:
                        new_name = unicode_mapping[orig]
                        logger.info(f"Unicode-based resolution: '{orig}' -> '{new_name}' (was '{resolved_name}')")
                        final_resolved.append(new_name)
                    else:
                        final_resolved.append(resolved_name)
                resolved = final_resolved

        if skipped:
            resolved = [r for r, o in zip(resolved, glyph_names) if o not in skipped]

        return resolved, skipped, conflict_report

    def format_cmap_report(self, report: CmapComparisonReport) -> str:
        """将 CmapComparisonReport 格式化为可读文本

        Args:
            report: cmap 对照报告

        Returns:
            格式化文本
        """
        lines = []
        lines.append("=" * 80)
        lines.append("  Glyph Name Cmap Comparison Report (Non-Standard Names)")
        lines.append("=" * 80)

        for entry in report.entries:
            name = entry["glyph_name"]
            status = entry["match_status"]
            lines.append("")
            lines.append(f"  Glyph: {name}  [{status}]")

            if entry["source_cmap"]:
                lines.append(f"    Source font ({entry['source_count']} entries):")
                for sc in entry["source_cmap"]:
                    lines.append(
                        f"      {sc['codepoint']}  platform={sc['platform_id']}  "
                        f"encoding={sc['encoding_id']}  subtable={sc['subtable_index']}  "
                        f"fmt={sc['subtable_format']}"
                    )
            else:
                lines.append("    Source font: no cmap entries")

            if entry["target_cmap"]:
                lines.append(f"    Target font ({entry['target_count']} entries):")
                for tc in entry["target_cmap"]:
                    lines.append(
                        f"      {tc['codepoint']}  platform={tc['platform_id']}  "
                        f"encoding={tc['encoding_id']}  subtable={tc['subtable_index']}  "
                        f"fmt={tc['subtable_format']}"
                    )
            else:
                lines.append("    Target font: no cmap entries")

            if "overlap_codepoints" in entry:
                lines.append(f"    Overlap: {', '.join(entry['overlap_codepoints'])}")

        lines.append("")
        lines.append("=" * 80)
        return "\n".join(lines)

    def format_conflict_report(self, report: ConflictReport) -> str:
        """将 ConflictReport 格式化为可读文本

        Args:
            report: 冲突报告

        Returns:
            格式化文本
        """
        lines = []
        lines.append("=" * 60)
        lines.append("  Glyph Name Conflict Report")
        lines.append("=" * 60)

        if not report.has_conflicts:
            lines.append("  No conflicts detected.")
        else:
            if report.name_to_multi_codepoint:
                lines.append("")
                lines.append("  [1 glyph name -> multiple codepoints]")
                for r in report.name_to_multi_codepoint:
                    lines.append(f"    {r.key} -> {', '.join(r.values)}")

            if report.codepoint_to_multi_name:
                lines.append("")
                lines.append("  [1 codepoint -> multiple glyph names]")
                for r in report.codepoint_to_multi_name:
                    lines.append(f"    {r.key} -> {', '.join(r.values)}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)
