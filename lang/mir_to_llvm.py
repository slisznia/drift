from __future__ import annotations

from llvmlite import binding as llvm  # type: ignore
from llvmlite import ir  # type: ignore

from . import mir
from .types import BOOL, ERROR, F64, I64, STR, Type


def lower_function(fn: mir.Function) -> tuple[str, bytes]:
    """
    Minimal MIR → LLVM lowering for straight-line functions (single block, no control flow):
    - params (Int64, Bool, Float64, String as i8*; others default to i8*)
    - const/move/copy
    - binary ops (+, -, *, /) on Int64
    - return
    """
    llvm.initialize()
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    target = llvm.Target.from_default_triple()
    tm = target.create_target_machine()
    if len(fn.blocks) != 1:
        raise ValueError("minimal lowering only supports single-block functions")
    block = fn.blocks[fn.entry]

    llvm_module = ir.Module(name=f"{fn.name}_module")
    llvm_module.triple = llvm.get_default_triple()
    llvm_module.data_layout = tm.target_data

    param_types = [_llvm_type(p.type) for p in fn.params]
    func_ty = ir.FunctionType(_llvm_type(fn.return_type), param_types)
    llvm_fn = ir.Function(llvm_module, func_ty, name=fn.name)
    entry = llvm_fn.append_basic_block(name="entry")
    builder = ir.IRBuilder(entry)

    env: dict[str, ir.Value] = {p.name: arg for p, arg in zip(fn.params, llvm_fn.args)}

    for instr in block.instructions:
        if isinstance(instr, mir.Const):
            env[instr.dest] = _const(builder, instr.type, instr.value)
        elif isinstance(instr, mir.Move):
            env[instr.dest] = env[instr.source]
        elif isinstance(instr, mir.Copy):
            env[instr.dest] = env[instr.source]
        elif isinstance(instr, mir.Binary):
            env[instr.dest] = _lower_binary(builder, instr, env)
        else:
            raise NotImplementedError(f"unsupported instruction in minimal lowering: {instr}")

    term = block.terminator
    if isinstance(term, mir.Return):
        retval = env[term.value] if term.value else None
        builder.ret(retval)
    else:
        raise NotImplementedError("only return is supported in minimal lowering")

    llvm_mod = llvm.parse_assembly(str(llvm_module))
    llvm_mod.verify()
    obj = tm.emit_object(llvm_mod)
    return str(llvm_module), obj


def _llvm_type(ty: Type) -> ir.Type:
    if ty == I64:
        return ir.IntType(64)
    if ty == BOOL:
        return ir.IntType(1)
    if ty == F64:
        return ir.DoubleType()
    if ty == STR:
        return ir.IntType(8).as_pointer()
    if ty == ERROR:
        return ir.IntType(8).as_pointer()
    return ir.IntType(8).as_pointer()


def _const(builder: ir.IRBuilder, ty: Type, val: object) -> ir.Value:
    if ty == I64:
        return ir.Constant(ir.IntType(64), int(val))
    if ty == BOOL:
        return ir.Constant(ir.IntType(1), int(bool(val)))
    if ty == F64:
        return ir.Constant(ir.DoubleType(), float(val))
    if ty == STR:
        data = bytearray(str(val).encode("utf-8"))
        data.append(0)
        gv = ir.GlobalVariable(builder.module, ir.ArrayType(ir.IntType(8), len(data)), name=f".str{len(data)}")
        gv.linkage = "internal"
        gv.global_constant = True
        gv.initializer = ir.Constant(gv.type.pointee, data)
        return gv.bitcast(ir.IntType(8).as_pointer())
    raise NotImplementedError(f"const of type {ty}")


def _lower_binary(builder: ir.IRBuilder, instr: mir.Binary, env: dict[str, ir.Value]) -> ir.Value:
    lhs = env[instr.left]
    rhs = env[instr.right]
    op = instr.op
    if op == "+":
        return builder.add(lhs, rhs, name=instr.dest)
    if op == "-":
        return builder.sub(lhs, rhs, name=instr.dest)
    if op == "*":
        return builder.mul(lhs, rhs, name=instr.dest)
    if op == "/":
        return builder.sdiv(lhs, rhs, name=instr.dest)
    raise NotImplementedError(f"binary op {op}")
