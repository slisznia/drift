"""SSA-to-LLVM codegen (minimal)."""

from __future__ import annotations

from pathlib import Path

from llvmlite import ir, binding as llvm  # type: ignore

from . import mir
from .types import BOOL, I64, UNIT, Type

# Architecture word size: target x86_64 for now.
WORD_BITS = 64
WORD_INT = ir.IntType(WORD_BITS)


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


def _llvm_type(ty: Type) -> ir.Type:
    """Map Drift types to LLVM types (minimal surface).

    - Int       → word-sized int (currently i64)
    - Int64     → i64
    - Int32     → i32
    - Bool      → i1
    - Void      → void
    """
    if ty.name == "Int":
        return WORD_INT
    if ty.name == "Int64":
        return ir.IntType(64)
    if ty.name == "Int32":
        return ir.IntType(32)
    if ty == BOOL or ty.name == "Bool":
        return ir.IntType(1)
    if ty == UNIT or ty.name == "Void":
        return ir.VoidType()
    raise NotImplementedError(f"unsupported type {ty}")


def emit_simple_main_object(fn: mir.Function, out_path: Path) -> None:
    """Legacy helper kept for compatibility; emit a single function as main."""
    emit_module_object([fn], fn.name, out_path)


def emit_module_object(funcs: list[mir.Function], entry: str, out_path: Path) -> None:
    """Lower a small set of SSA functions (ints + branches + calls) into LLVM."""
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()

    mod = ir.Module(name="ssa_main")
    # First pass: create LLVM functions and basic blocks.
    fn_map: dict[str, ir.Function] = {}
    blocks_map: dict[tuple[str, str], ir.Block] = {}
    for f in funcs:
        ret_ty = _llvm_type(f.return_type)
        param_tys = [_llvm_type(p.type) for p in f.params]
        llvm_fn = ir.Function(mod, ir.FunctionType(ret_ty, param_tys), name=f.name)
        fn_map[f.name] = llvm_fn
        for bname in f.blocks:
            blocks_map[(f.name, bname)] = llvm_fn.append_basic_block(bname)

    # Second pass: PHIs for params + body emission.
    for f in funcs:
        llvm_fn = fn_map[f.name]
        phis: dict[tuple[str, str], ir.Instruction] = {}
        values: dict[str, ir.Value] = {}

        # Map function params.
        for param, llvm_param in zip(f.params, llvm_fn.args):
            llvm_param.name = param.name
            values[param.name] = llvm_param

        # Block params: entry params map to function args; others get PHIs.
        for bname, block in f.blocks.items():
            builder = ir.IRBuilder(blocks_map[(f.name, bname)])
            if bname == f.entry and block.params:
                if len(block.params) != len(f.params):
                    raise RuntimeError(f"entry block params arity mismatch in {f.name}")
                for idx, param in enumerate(block.params):
                    values[param.name] = values[f.params[idx].name]
            else:
                for param in block.params:
                    phi = builder.phi(_llvm_type(param.type), name=param.name)
                    phis[(bname, param.name)] = phi
                    values[param.name] = phi

        # Emit instructions and terminators.
        for bname, block in f.blocks.items():
            builder = ir.IRBuilder(blocks_map[(f.name, bname)])
            for instr in block.instructions:
                if isinstance(instr, mir.Const):
                    if not isinstance(instr.value, (int, bool)):
                        raise RuntimeError("simple backend supports int/bool const only")
                    ir_ty = _llvm_type(instr.type)
                    values[instr.dest] = ir_ty(int(instr.value))
                elif isinstance(instr, mir.Move):
                    values[instr.dest] = values[instr.source]
                elif isinstance(instr, mir.Binary):
                    lhs = values[instr.left]
                    rhs = values[instr.right]
                    if instr.op == "+":
                        values[instr.dest] = builder.add(lhs, rhs, name=instr.dest)
                    elif instr.op == "-":
                        values[instr.dest] = builder.sub(lhs, rhs, name=instr.dest)
                    elif instr.op == "*":
                        values[instr.dest] = builder.mul(lhs, rhs, name=instr.dest)
                    elif instr.op in {"==", "!="}:
                        cmp = builder.icmp_unsigned("==", lhs, rhs, name=f"cmp_{instr.dest}")
                        if instr.op == "!=":
                            cmp = builder.not_(cmp, name=instr.dest)
                        values[instr.dest] = cmp
                    else:
                        raise RuntimeError(f"unsupported binary op {instr.op}")
                elif isinstance(instr, mir.Call):
                    if instr.normal or instr.error:
                        raise RuntimeError("call with edges not yet supported in SSA backend")
                    callee = fn_map.get(instr.callee)
                    if callee is None:
                        raise RuntimeError(f"unknown callee {instr.callee}")
                    args = [values[a] for a in instr.args]
                    call_val = builder.call(callee, args, name=instr.dest)
                    values[instr.dest] = call_val
                else:
                    raise RuntimeError(f"unsupported instruction {instr}")

            term = block.terminator
            if isinstance(term, mir.Return):
                if isinstance(_llvm_type(f.return_type), ir.VoidType):
                    builder.ret_void()
                else:
                    if term.value is None:
                        raise RuntimeError(f"missing return value for non-void function {f.name}")
                    if term.value not in values:
                        raise RuntimeError(f"return value {term.value} undefined")
                    builder.ret(values[term.value])
            elif isinstance(term, mir.Br):
                tgt = term.target.target
                tblock = f.blocks[tgt]
                if len(term.target.args) != len(tblock.params):
                    raise RuntimeError(f"edge to {tgt} has arity {len(term.target.args)} expected {len(tblock.params)}")
                for param, arg in zip(tblock.params, term.target.args):
                    phis[(tgt, param.name)].add_incoming(values[arg], blocks_map[(f.name, bname)])
                builder.branch(blocks_map[(f.name, tgt)])
            elif isinstance(term, mir.CondBr):
                if term.cond not in values:
                    raise RuntimeError(f"cond value {term.cond} undefined")
                cond_val = values[term.cond]
                if cond_val.type != ir.IntType(1):
                    cond_val = builder.icmp_unsigned("!=", cond_val, cond_val.type(0), name=f"cond_{bname}")
                for edge in (term.then, term.els):
                    tgt = edge.target
                    tblock = f.blocks[tgt]
                    if len(edge.args) != len(tblock.params):
                        raise RuntimeError(
                            f"edge to {tgt} has arity {len(edge.args)} expected {len(tblock.params)}"
                        )
                    for param, arg in zip(tblock.params, edge.args):
                        phis[(tgt, param.name)].add_incoming(values[arg], blocks_map[(f.name, bname)])
                builder.cbranch(cond_val, blocks_map[(f.name, term.then.target)], blocks_map[(f.name, term.els.target)])
            else:
                raise RuntimeError(f"unsupported terminator {term}")

    # Debugging aid: print module if LLVM rejects it.
    target = llvm.Target.from_default_triple()
    tm = target.create_target_machine()
    llvm_mod = llvm.parse_assembly(str(mod))
    obj = tm.emit_object(llvm_mod)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(obj)
