from __future__ import annotations

from pathlib import Path
from typing import Dict

from . import mir
from .types import I64, STR, Type


def build_frame_consts(
    block: mir.BasicBlock,
    temp_types: Dict[str, Type],
    source_name: str | None,
    func_name: str,
    module_label: str,
    line: int,
    fresh_val,
) -> tuple[str, str, str, str]:
    file_label = Path(source_name).name if source_name else "<unknown>"
    file_const = fresh_val()
    func_const = fresh_val()
    mod_const = fresh_val()
    line_const = fresh_val()
    block.instructions.append(mir.Const(dest=file_const, type=STR, value=file_label))
    block.instructions.append(mir.Const(dest=func_const, type=STR, value=func_name))
    block.instructions.append(mir.Const(dest=mod_const, type=STR, value=module_label))
    block.instructions.append(mir.Const(dest=line_const, type=I64, value=line))
    temp_types[file_const] = STR
    temp_types[func_const] = STR
    temp_types[mod_const] = STR
    temp_types[line_const] = I64
    return mod_const, file_const, func_const, line_const
