"""SSA-to-LLVM codegen stubs."""

from __future__ import annotations

from pathlib import Path

from llvmlite import ir, binding as llvm  # type: ignore


def emit_dummy_main_object(out_path: Path) -> None:
    """Emit a trivial main that returns 0; ignores the SSA program for now."""
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
    with llvm.create_mcjit_compiler(llvm.parse_assembly(str(mod)), tm) as engine:
        engine.finalize_object()
        obj = tm.emit_object(llvm.parse_assembly(str(mod)))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(obj)
