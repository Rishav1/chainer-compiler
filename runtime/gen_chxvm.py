import argparse
import os
import subprocess
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(project_root, 'common'))
import codegen_util
from chxvm_defs import *


parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", required=True, help="")
parser.add_argument("--output-dir", required=True, help="")
parser.add_argument("--protoc-exe", required=True, help="")
args = parser.parse_args()

output_dir = args.output_dir

GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'


def colored_name(typ, name):
    s = sigil(typ)
    if s == '$':
        color = GREEN
    elif s == '*':
        color = YELLOW
    else:
        color = RED
    return '"{}{}" << {} << "{}"'.format(color, s, name, RESET)


def gen_chxvm_proto():
    with open(os.path.join(args.input_dir, 'chxvm.proto.tmpl')) as f:
        chxvm_proto = f.read()

    chxvm_ops = ''
    for i, op in enumerate(XC_ALL_OPS):
        chxvm_ops += '        %s = %d;\n' % (op.name, i + 1)

    chxvm_proto = chxvm_proto.replace('%ChxVM_OPS%', chxvm_ops)

    with open(output_dir + '/chxvm.proto', 'w') as f:
        f.write('// Auto-generated by gen_chxvm.py\n\n')
        f.write(chxvm_proto)

    subprocess.check_call([args.protoc_exe, 'chxvm.proto', '--cpp_out=.'])


def gen_gen_chxvm_ops_h():
    lines = []

    for op in XC_ALL_OPS:
        lines.append('class %sOp : public ChxVMOp {' % op.name)
        lines.append('public:')
        lines.append('explicit %sOp(const XCInstructionProto& inst);' % op.name)

        args = ['ChxVMState* st']
        if op.typed:
            for typ, name in op.inputs:
                if typ == ARRAY:
                    args.append('const chainerx::Array& %s' % name)
                elif typ == OPTIONAL_ARRAY:
                    args.append(
                        'const nonstd::optional<chainerx::Array>& %s' % name)
                elif typ == ARRAY_LIST:
                    args.append('const std::vector<chainerx::Array>& %s' % name)
                elif typ == SEQUENCE:
                    args.append('const ChxVMSequence& %s' % name)
                elif typ == OPAQUE:
                    args.append('const ChxVMOpaque& %s' % name)
                elif typ == SHAPE:
                    args.append('const chainerx::Shape& %s' % name)
                elif typ == SCALAR:
                    args.append('const chainerx::Scalar& %s' % name)
                elif typ == OPTIONAL_SCALAR:
                    args.append('const nonstd::optional<chainerx::Scalar>& %s' % name)
                else:
                    assert typ in FIELD_TYPES, 'Unknown type: %s' % typ

            output_ctypes = []
            for typ, name in op.outputs:
                if typ == ARRAY_LIST:
                    output_ctypes.append('std::vector<chainerx::Array>')
                elif typ == SEQUENCE:
                    args.append('ChxVMSequence* %s' % name)
                elif typ == OPAQUE:
                    output_ctypes.append('ChxVMOpaque*')
                elif typ == SHAPE:
                    output_ctypes.append('chainerx::Shape')
                elif typ == SCALAR:
                    output_ctypes.append('chainerx::Scalar')
                else:
                    output_ctypes.append('chainerx::Array')

            if len(output_ctypes) == 0:
                rettype = 'void'
            elif len(output_ctypes) == 1:
                rettype = output_ctypes[0]
            else:
                rettype = 'std::tuple<' + ', '.join(output_ctypes) + '>'
        else:
            rettype = 'void'
        lines.append('%s RunImpl(%s);' % (rettype, ', '.join(args)))
        lines.append('virtual void Run(ChxVMState* st);')

        lines.append('private:')
        for inp in op.inputs:
            ctype = inp.c_storage_type()
            lines.append('%s %s;' % (ctype, inp.name))

        for out in op.outputs:
            ctype = out.c_storage_type()
            lines.append('%s %s;' % (ctype, out.name))

        if op.has_custom_field:
            lines.append('~%sOp() override;' % op.name)
            lines.append('void InitImpl();')
            lines.append('class %sImpl;' % op.name)
            lines.append('%sImpl* impl_{nullptr};' % op.name)

        lines.append('};')

    with open(output_dir + '/gen_chxvm_ops.h', 'w') as f:
        f.write(r'''// Auto-generated by gen_chxvm.py

#pragma once

#include <memory>
#include <string>

#include <chainerx/stack_vector.h>

#include <runtime/chxvm_op.h>
#include <runtime/chxvm_state.h>
#include <runtime/chxvm.pb.h>

namespace chainer_compiler {
namespace runtime {

''')
        f.writelines(codegen_util.format_code(lines))
        f.write(r'''
}  // namespace runtime
}  // namespace chainer_compiler
''')


def gen_gen_chxvm_ops_cc():
    lines = []

    for op in XC_ALL_OPS:
        # Emit constructor.
        lines.append('%sOp::%sOp(const XCInstructionProto& inst)'
                     ': ChxVMOp(inst) {' %
                     (op.name, op.name))
        for i, inp in enumerate(op.inputs):
            enum = inp.typ.replace('OPTIONAL_', '')
            lines.append('CHECK_EQ(XCValueProto::%s, ' % enum +
                         'inst.inputs(%d).type()) ' % i +
                         '<< "Unexpected type for input#%d of %s";' % (i, op.name))
            pfn = inp.proto_field_name()
            name = inp.name
            if not inp.is_repeated():
                lines.append('%s = inst.inputs(%d).%s();' % (name, i, pfn))
            elif inp.typ == INTS:
                lines.append('CHECK_LE(inst.inputs(%d).ints().size(), '
                             '(int)chainerx::kMaxNdim);' % i)
                lines.append('%s = %s(' % (name, STACK_VECTOR) +
                             'inst.inputs(%d).ints().begin(), ' % i +
                             'inst.inputs(%d).ints().end());' % i)
            else:
                lines.append('%s.assign(inst.inputs(%d).%s().begin(),' % (name, i, pfn) +
                             'inst.inputs(%d).%s().end());' % (i, pfn))

        for i, (typ, name) in enumerate(op.outputs):
            if typ == ARRAY_LIST:
                lines.append('%s.assign(inst.outputs().begin(), '
                             'inst.outputs().end());' % name)
            else:
                lines.append('%s = inst.outputs(%d);' % (name, i))

        if op.has_custom_field:
            lines.append('InitImpl();')

        lines.append('}')

        # Emit Run.
        lines.append('void %sOp::Run(ChxVMState* st) {' % op.name)

        lines.append('if (st->trace_level() && !debug_info().empty()) '
                     'std::cerr << "# " << debug_info() << std::endl;')

        line = 'if (st->trace_level()) std::cerr'
        if op.outputs:
            for typ, name in op.outputs:
                if typ == ARRAY_LIST:
                    line += ' << ArrayListToString(%s)' % name
                else:
                    line += ' << %s' % colored_name(typ, name)
            line += ' << " = "'
        line += ' << "%s("' % (op.name)
        for i, (typ, name) in enumerate(op.inputs):
            if i:
                line += ' << ", "'
            if typ in [ARRAY, OPTIONAL_ARRAY, SEQUENCE, OPAQUE, SHAPE, SCALAR, OPTIONAL_SCALAR]:
                line += ' << %s' % colored_name(typ, name)
            elif typ in (INT, FLOAT):
                line += ' << %s' % name
            elif typ in [STRING, INT_VALUES, DOUBLES]:
                line += ' << "%s"' % name
            elif typ == INTS:
                line += ' << StackVectorToString(%s)' % name
            elif typ == ARRAY_LIST:
                line += ' << ArrayListToString(%s)' % name
            else:
                raise RuntimeError('Unknown type: %s' % typ)
        line += ' << ")"'
        line += ' << std::endl;'
        lines.append(line)

        line = 'if (st->trace_level()) std::cerr'
        for typ, name in op.inputs:
            if typ in [ARRAY, OPTIONAL_ARRAY, SEQUENCE]:
                line += ' << " " << %s << "="' % colored_name(typ, name)
                line += ' << st->GetVarString(%s)' % name
            elif typ == ARRAY_LIST:
                line += ' << st->GetVarListString(%s)' % name
        if op.outputs:
            line += ' << " ->"'
        if not line.endswith('std::cerr'):
            line += ';'
            lines.append(line)

        if op.typed:
            args = ['st']

            # TODO(hamaji): Remove this code by removing null gradients.
            conds = []
            for typ, name in op.inputs:
                if typ in ARG_TYPES and typ != ARRAY_LIST:
                    conds.append('(%s >= 0 && st->GetVar(%s)->IsNull())' %
                                 (name, name))
            if conds:
                lines.append('if (%s) {' % (' || '.join(conds)))
                lines.append('WARN_ONCE("%s skipped\\n");' % op.name)
                for typ, oname in op.outputs:
                    if typ in ARG_TYPES and typ != ARRAY_LIST:
                        lines.append('st->SetVar(%s, ChxVMVar());' % oname)
                lines.append('return;')
                lines.append('}')

            for typ, name in op.inputs:
                if typ == ARRAY:
                    args.append('st->GetArray(%s)' % name)
                elif typ == OPTIONAL_ARRAY:
                    args.append('st->GetOptionalArray(%s)' % name)
                elif typ == ARRAY_LIST:
                    args.append('st->GetArrayList(%s)' % name)
                elif typ == SEQUENCE:
                    args.append('*st->GetSequence(%s)' % name)
                elif typ == OPAQUE:
                    args.append('st->GetOpaque(%s)' % name)
                elif typ == SHAPE:
                    args.append('st->GetShape(%s)' % name)
                elif typ == SCALAR:
                    args.append('st->GetScalar(%s)' % name)
                elif typ == OPTIONAL_SCALAR:
                    args.append('st->GetOptionalScalar(%s)' % name)

            outputs = []
            for output in op.outputs:
                typ, name = output
                if typ == SEQUENCE:
                    args.append('st->CreateSequence(%s)' % name)
                else:
                    outputs.append(output)

            call = 'RunImpl(%s)' % ', '.join(args)
            if len(outputs) == 1:
                typ, name = outputs[0]
                if typ == ARRAY_LIST:
                    lines.append('st->SetArrayList(%s, %s);' % (name, call))
                elif typ == OPAQUE:
                    lines.append('st->SetOpaque(%s, %s);' % (name, call))
                elif typ == SHAPE:
                    lines.append('st->SetShape(%s, %s);' % (name, call))
                elif typ == SCALAR:
                    lines.append('st->SetScalar(%s, %s);' % (name, call))
                else:
                    lines.append('st->SetArray(%s, %s);' % (name, call))
            elif outputs:
                lines.append('auto r_ = ' + call + ';')
                for i, (typ, output) in enumerate(outputs):
                    # TODO(hamaji): Revisit optional outputs.
                    if typ == OPAQUE:
                        lines.append('if (%s >= 0) st->SetOpaque(%s, std::get<%d>(r_));' % (output, output, i))
                        lines.append('else delete std::get<%d>(r_);' % i)
                    else:
                        lines.append('if (%s >= 0) st->SetArray(%s, std::get<%d>(r_));' % (output, output, i))
                    lines.append(line)
            else:
                lines.append(call + ';')
        else:
            lines.append('RunImpl(st);')

        line = 'if (st->trace_level()) std::cerr'
        for typ, name in op.outputs:
            if typ in [ARRAY, OPTIONAL_ARRAY, SEQUENCE, OPAQUE, SHAPE, SCALAR, OPTIONAL_SCALAR]:
                line += ' << " " << %s << "="' % colored_name(typ, name)
                line += ' << st->GetVarString(%s)' % name
            elif typ == ARRAY_LIST:
                line += ' << st->GetVarListString(%s)' % name
            else:
                raise RuntimeError('Unknown output type: %s' % typ)
        line += ' << std::endl;'
        lines.append(line)

        if op.outputs:
            inputs_str = ', '.join([name for typ, name in op.inputs
                                    if typ == ARRAY or typ == OPTIONAL_ARRAY])
            outputs_str = ', '.join(op.output_names)
            lines.append('if (st->check_infs()) st->CheckInfs({%s}, {%s});' %
                         (inputs_str, outputs_str))
            lines.append('if (st->check_nans()) st->CheckNans({%s}, {%s});' %
                         (inputs_str, outputs_str))

        lines.append('}')

    lines.append('ChxVMOp* MakeChxVMOp(const XCInstructionProto& inst) {')
    lines.append('switch (inst.op()) {')
    for op in XC_ALL_OPS:
        lines.append('case XCInstructionProto::%s:' % (op.name))
        lines.append('return new %sOp(inst);' % (op.name))
    lines.append('default:')
    lines.append('CHECK(false) << "Unknown op: " ' +
                 '<< static_cast<int>(inst.op());')
    lines.append('}')
    lines.append('}')

    with open(output_dir + '/gen_chxvm_ops.cc', 'w') as f:
        f.write(r'''// Auto-generated by gen_chxvm.py

#include <string>
#include <sstream>

#include <common/log.h>
#include <runtime/gen_chxvm_ops.h>

namespace chainer_compiler {
namespace runtime {

std::string StackVectorToString(const chainerx::StackVector<int64_t, chainerx::kMaxNdim>& s) {
    std::ostringstream oss;
    for (int v : s) {
        oss << (oss.str().empty() ? '(' : ',');
        oss << v;
    }
    oss << ')';
    return oss.str();
}

std::string ArrayListToString(const std::vector<int>& s) {
    std::ostringstream oss;
    for (int v : s) {
        oss << (oss.str().empty() ? '(' : ',');
        oss << '$' << v;
    }
    oss << ')';
    return oss.str();
}

''')
        f.writelines(codegen_util.format_code(lines))
        f.write(r'''
}  // namespace runtime
}  // namespace chainer_compiler
''')


if __name__ == '__main__':
    gen_chxvm_proto()
    gen_gen_chxvm_ops_h()
    gen_gen_chxvm_ops_cc()
