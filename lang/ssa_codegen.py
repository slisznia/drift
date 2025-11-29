"""SSA-to-LLVM codegen (minimal)."""

from __future__ import annotations

from pathlib import Path

from llvmlite import ir, binding as llvm  # type: ignore

from . import mir
from .types import I64, Type


def emit_dummy_main_object(out_path: Path) -> None:
    """Emit a trivial main that returns 0."""
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()

    mod = ir.Module(name="ssa_dummy")
    int32 = ir.IntType(32)
    fn_ty = ir.FunctionType(int32, [])
    main_fn = ir.Function(mod, fn_ty, name="main")
    entry_bb = main_fn.append_basic_block(name="entry")
    builder = ir.IRBuilder(entry_bb)
    builder.ret(int32(0))

    target = llvm.Target.from_default_triple()
    tm = target.create_target_machine()
    obj = tm.emit_object(llvm.parse_assembly(str(mod)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(obj)


def _llvm_int(ty: Type) -> ir.IntType:
    # Treat Int/Int64 as i32 for now.
    if ty.name in {"Int", "Int64"}:
        return ir.IntType(32)
    raise NotImplementedError(f"unsupported type {ty}")


def emit_simple_main_object(fn: mir.Function, out_path: Path) -> None:
    """Lower a single-block SSA function with consts/moves + return into LLVM."""
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()

    if len(fn.blocks) != 1:
        raise RuntimeError("simple backend supports single-block functions only")
    entry_block = next(iter(fn.blocks.values()))
    if entry_block.params:
        raise RuntimeError("simple backend does not support params yet")

    mod = ir.Module(name="ssa_main")
    ret_ir_ty = _llvm_int(fn.return_type)
    llvm_main = ir.Function(mod, ir.FunctionType(ret_ir_ty, []), name="main")
    llvm_bb = llvm_main.append_basic_block("entry")
    builder = ir.IRBuilder(llvm_bb)

    values: dict[str, ir.Value] = {}

    for instr in entry_block.instructions:
        if isinstance(instr, mir.Const):
            if not isinstance(instr.value, int):
                raise RuntimeError("simple backend supports int const only")
            ir_ty = _llvm_int(instr.type)
            values[instr.dest] = ir_ty(instr.value)
        elif isinstance(instr, mir.Move):
            values[instr.dest] = values[instr.source]
        else:
            raise RuntimeError(f"unsupported instruction {instr}")

    term = entry_block.terminator
    if not isinstance(term, mir.Return):
        raise RuntimeError("simple backend supports only return terminator")
    if term.value is None:
        builder.ret(ret_ir_ty(0))
    else:
        if term.value not in values:
            raise RuntimeError(f"return value {term.value} undefined")
        builder.ret(values[term.value])

    target = llvm.Target.from_default_triple()
    tm = target.create_target_machine()
    obj = tm.emit_object(llvm.parse_assembly(str(mod)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(obj)
