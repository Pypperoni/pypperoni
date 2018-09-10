# Copyright (c) Pypperoni
#
# Pypperoni is licensed under the MIT License; you may
# not use it except in compliance with the License.
#
# You should have received a copy of the License with
# this source code under the name "LICENSE.txt". However,
# you may obtain a copy of the License on our GitHub here:
# https://github.com/Pypperoni/pypperoni
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied. See the License for the specific
# language governing permissions and limitations under the
# License.

from pypperoni.codeobj import MutableCodeObject
from pypperoni.config import IMPORT_ALIASES, SPLIT_INTERVAL
from pypperoni.context import Context
from pypperoni.util import *

from opcode import *
globals().update(opmap)

import hashlib
import struct
import dis


class ModuleBase:
    def __init__(self, name, code):
        self.name = name
        self.code = MutableCodeObject(code)

        self._is_main = False
        self._id = -1

    def set_as_main(self):
        self._is_main = True

    def is_external(self):
        return False

    def get_id(self):
        if self._is_main:
            return 0

        if self._id == -1:
            self._id = struct.unpack('<I', hashlib.sha1(self.name).digest()[:4])[0]

        return self._id

    def get_parent(self, modules):
        return None

    def generate_c_code(self, f, modules):
        pass


class Module(ModuleBase):
    def __init__(self, name, code):
        ModuleBase.__init__(self, name, code)

    def get_parent(self, modules):
        if '.' in self.name:
            return modules.get(self.name.rsplit('.', 1)[0])

        return None

    def __handle_one_instr(self, codeobj, context, label, op, oparg, line):
        context.insert_label(label)

        if context.try_blocks and context.try_blocks[-1] == label:
            context.try_blocks.pop()

            context.insert_line('Py_XDECREF(exc);')
            context.insert_line('Py_XDECREF(val);')
            context.insert_line('Py_XDECREF(tb);')
            context.insert_line('PyErr_Fetch(&exc, &val, &tb);')
            context.insert_line('PyErr_NormalizeException(&exc, &val, &tb);')
            context.insert_line('if (exc == NULL) {exc = Py_None; Py_INCREF(exc);}')
            context.insert_line('if (val == NULL) {val = Py_None; Py_INCREF(val);}')
            context.insert_line('if (tb == NULL) {Py_INCREF(Py_None); PUSH(Py_None);}')
            context.insert_line('else {PUSH(tb);}')
            context.insert_line('PUSH(val);')
            context.insert_line('PUSH(exc);')
            context.insert_line('Py_INCREF(exc);')
            context.insert_line('Py_INCREF(val);')
            context.insert_line('Py_XINCREF(tb);')

        if label in context.loop_blocks:
            context.loop_blocks.remove(label)

        if label in context.finally_blocks:
            context.finally_blocks.remove(label)

        self.handle_op(codeobj, context, label, op, oparg, line)

    def handle_op(self, codeobj, context, label, op, oparg, line):
        if op == NOP:
            context.insert_line('// NOP')

        elif op == POP_TOP:
            context.begin_block()
            context.insert_line('v = POP();')
            context.insert_line('Py_DECREF(v);')
            context.end_block()

        elif op == DUP_TOP:
            context.begin_block()
            context.insert_line('v = TOP();')
            context.insert_line('Py_INCREF(v);')
            context.insert_line('PUSH(v);')
            context.end_block()

        elif op == DUP_TOPX:
            context.begin_block()

            context.insert_line('x = TOP();')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('w = SECOND();')
            context.insert_line('Py_INCREF(w);')

            if oparg == 3:
                context.insert_line('v = THIRD();')
                context.insert_line('Py_INCREF(v);')
                context.insert_line('STACKADJ(3);')
                context.insert_line('SET_THIRD(v);')

            else:
                context.insert_line('STACKADJ(2);')

            context.insert_line('SET_TOP(x);')
            context.insert_line('SET_SECOND(w);')

            context.end_block()

        elif op == ROT_TWO:
            context.begin_block()
            context.insert_line('v = TOP();')
            context.insert_line('w = SECOND();')
            context.insert_line('SET_TOP(w);')
            context.insert_line('SET_SECOND(v);')
            context.end_block()

        elif op == ROT_THREE:
            context.begin_block()
            context.insert_line('v = TOP();')
            context.insert_line('w = SECOND();')
            context.insert_line('x = THIRD();')
            context.insert_line('SET_TOP(w);')
            context.insert_line('SET_SECOND(x);')
            context.insert_line('SET_THIRD(v);')
            context.end_block()

        elif op == ROT_FOUR:
            context.begin_block()
            context.insert_line('u = TOP();')
            context.insert_line('v = SECOND();')
            context.insert_line('w = THIRD();')
            context.insert_line('x = FOURTH();')
            context.insert_line('SET_TOP(v);')
            context.insert_line('SET_SECOND(w);')
            context.insert_line('SET_THIRD(x);')
            context.insert_line('SET_FOURTH(U);')
            context.end_block()

        elif op == LOAD_CONST:
            context.begin_block()

            value = codeobj.co_consts[oparg]
            if isinstance(value, MutableCodeObject):
                context.insert_line('// LOADED CODE OBJECT')
                context.codeobjs.append(value)
                context.end_block()

            elif value in (-1, 1) and len(context.buf) > context.i + 1 \
                     and context.buf[context.i + 1][1] == IMPORT_NAME:
                context.end_block()
                context.insert_line('// DETECTED IMPORT')
                self.__handle_import(codeobj, context, value)

            else:
                if value is None:
                    context.insert_line('x = Py_None;')
                    context.insert_line('Py_INCREF(x);')

                else:
                    getter = context.register_const(value)
                    context.insert_line('x = %s; // %s' % (getter, safeRepr(value)))
                    context.insert_line('if (x == NULL) {')
                    context.insert_handle_error(line, label)
                    context.insert_line('}')

                context.insert_line('PUSH(x);')
                context.end_block()

        elif op == LOAD_NAME:
            context.begin_block()
            name = codeobj.co_names[oparg]
            context.insert_line('x = __pypperoni_IMPL_load_name(f, %s);' % context.register_const(name))
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_FAST:
            context.begin_block()
            context.insert_line('x = f->f_fastlocals[%d];' % oparg)
            context.insert_line('if (x == NULL) {')
            context.insert_line('__pypperoni_IMPL_raise(PyExc_UnboundLocalError, "failed to load local %d");' % oparg)
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_GLOBAL:
            context.begin_block()
            name = codeobj.co_names[oparg]
            context.insert_line('x = __pypperoni_IMPL_load_global(f, %s);' % context.register_const(name))
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_LOCALS:
            context.begin_block()
            context.insert_line('x = f->f_locals;')
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_DEREF:
            is_pseudo_fast = False
            if oparg < len(codeobj.co_varnames) and oparg < len(codeobj.co_cellvars):
                if codeobj.co_varnames[oparg] == codeobj.co_cellvars[oparg]:
                    # Treat this as STORE_FAST
                    is_pseudo_fast = True

            context.begin_block()
            if is_pseudo_fast:
                context.insert_line('x = f->f_fastlocals[%d];' % oparg)
            else:
                context.insert_line('x = __pypperoni_IMPL_load_deref(f, %d);' % oparg)
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_CLOSURE:
            context.begin_block()
            context.insert_line('x = __pypperoni_IMPL_load_closure(f, %d);' % oparg)
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == STORE_NAME:
            context.begin_block()

            name = codeobj.co_names[oparg]
            context.insert_line('x = POP();')
            context.insert_line('err = __pypperoni_IMPL_store_name(f, %s, x);' %
                                          context.register_const(name))
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == STORE_GLOBAL:
            context.begin_block()

            name = codeobj.co_names[oparg]
            context.insert_line('x = POP();')
            context.insert_line('err = __pypperoni_IMPL_store_global(f, %s, x);' %
                                            context.register_const(name))
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == STORE_FAST:
            context.begin_block()

            context.insert_line('x = POP();')
            context.insert_line('tmp = f->f_fastlocals[%d];' % oparg)
            context.insert_line('f->f_fastlocals[%d] = x;' % oparg)
            context.insert_line('Py_XDECREF(tmp);')

            context.end_block()

        elif op == STORE_DEREF:
            context.begin_block()

            context.insert_line('x = POP();')
            context.insert_line('err = __pypperoni_IMPL_store_deref(f, x, %d);' % oparg)
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == LOAD_ATTR:
            context.begin_block()

            attr = codeobj.co_names[oparg]
            context.insert_line('v = TOP();')
            context.insert_line('x = PyObject_GetAttr(v, %s);' % context.register_const(attr))
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('SET_TOP(x);')

            context.end_block()

        elif op in (PRINT_ITEM, PRINT_ITEM_TO, PRINT_NEWLINE, PRINT_NEWLINE_TO):
            context.begin_block()

            if op in (PRINT_ITEM_TO, PRINT_NEWLINE_TO):
                context.insert_line('v = POP();')

            else:
                context.insert_line('v = NULL;')

            if op in (PRINT_ITEM, PRINT_ITEM_TO):
                context.insert_line('x = POP();')

            else:
                context.insert_line('x = NULL;')

            context.insert_line('err = __pypperoni_IMPL_do_print(v, x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_XDECREF(v);')
            context.insert_line('Py_XDECREF(x);')
            context.end_block()

        elif op in (CALL_FUNCTION, CALL_FUNCTION_VAR, CALL_FUNCTION_KW, CALL_FUNCTION_VAR_KW):
            context.begin_block()

            num_args = oparg & 0xFF
            num_kwargs = (oparg >> 8) & 0xFF

            context.add_decl_once('func', 'PyObject*', 'NULL', False)
            context.add_decl_once('pargs', 'PyObject*', 'NULL', False)
            context.add_decl_once('args', 'PyObject*', 'NULL', False)
            context.add_decl_once('kw', 'PyObject*', 'NULL', False)

            context.insert_line('pargs = NULL;')
            context.insert_line('args = NULL;')
            context.insert_line('kw = NULL;')

            if op in (CALL_FUNCTION_KW, CALL_FUNCTION_VAR_KW):
                context.insert_line('kw = POP();')

            elif num_kwargs > 0:
                context.insert_line('kw = PyDict_New();')

            if op in (CALL_FUNCTION_VAR, CALL_FUNCTION_VAR_KW):
                context.insert_line('args = POP();')

            while num_kwargs:
                context.insert_line('v = POP();')
                context.insert_line('w = POP();')
                context.insert_line('PyDict_SetItem(kw, w, v);')
                context.insert_line('Py_DECREF(v);')
                context.insert_line('Py_DECREF(w);')
                num_kwargs -= 1

            for i in reversed(range(num_args)):
                context.add_decl_once('_arg_%d' % i, 'PyObject*', 'NULL', False)
                context.insert_line('_arg_%d = POP();' % i)

            context.insert_line('pargs = PyList_New(%d);' % num_args)
            for i in xrange(num_args):
                context.insert_line('PyList_SET_ITEM(pargs, %d, _arg_%d);' % (i, i))

            if op in (CALL_FUNCTION_VAR, CALL_FUNCTION_VAR_KW):
                context.insert_line('_PyList_Extend((PyListObject*)pargs, args);')
                context.insert_line('Py_DECREF(args);')

            context.insert_line('func = POP();')
            context.insert_line('err = __pypperoni_IMPL_call_func(func, &x, pargs, kw);')
            context.insert_line('Py_DECREF(func);')
            context.insert_line('Py_DECREF(pargs);')
            context.insert_line('Py_XDECREF(kw);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PUSH(x);')

            context.end_block()

        elif op == RETURN_VALUE:
            context.begin_block()

            context.insert_line('retval = POP();')

            if context.finally_blocks:
                context.insert_line('Py_INCREF(Py_None);')
                context.insert_line('PUSH(Py_None);')
                context.insert_line('goto label_%d;' % context.finally_blocks[-1])

            else:
                context.insert_line('goto end;')

            context.end_block()

        elif op in (BUILD_LIST, BUILD_SET, BUILD_TUPLE):
            context.begin_block()

            context.add_decl_once('i', 'Py_ssize_t', '0', False)

            if op == BUILD_LIST:
                context.insert_line('x = PyList_New(%d);' % oparg)

            elif op == BUILD_TUPLE:
                context.insert_line('x = PyTuple_New(%d);' % oparg)

            elif op == BUILD_SET:
                context.insert_line('x = PySet_New(NULL);')

            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.insert_line('for (i = %d - 1; i >= 0; i--)' % oparg)
            context.begin_block()
            context.insert_line('w = POP();')
            if op == BUILD_LIST:
                context.insert_line('PyList_SET_ITEM(x, i, w);')
            elif op == BUILD_TUPLE:
                context.insert_line('PyTuple_SET_ITEM(x, i, w);')
            elif op == BUILD_SET:
                context.insert_line('PySet_Add(x, w);')
            context.end_block()

            context.insert_line('PUSH(x);')

            context.end_block()

        elif op in (MAKE_FUNCTION, MAKE_CLOSURE):
            context.begin_block()

            funccode = context.codeobjs.pop()

            context.add_decl_once('closure', 'PyObject*', 'NULL', False)
            context.add_decl_once('func_defaults', 'PyObject*', 'NULL', False)
            context.add_decl_once('fname', 'PyObject*', 'NULL', False)
            context.add_decl_once('varnames', 'PyObject*', 'NULL', False)
            context.add_decl_once('cellvars', 'PyObject*', 'NULL', False)

            if op == MAKE_CLOSURE:
                context.insert_line('closure = POP();')

            else:
                context.insert_line('closure = NULL;')

            if oparg:
                context.insert_line('func_defaults = PyTuple_New(%d);' % oparg)
                while oparg:
                    oparg -= 1
                    context.insert_line('v = POP();')
                    context.insert_line('PyTuple_SET_ITEM(func_defaults, %d, v);' % oparg)

            else:
                context.insert_line('func_defaults = NULL;')

            fname = context.register_const(funccode.co_privname)
            context.insert_line('fname = %s;' % fname)

            varnames = context.register_const(funccode.co_varnames)
            context.insert_line('varnames = %s;' % varnames)

            varnames = context.register_const(funccode.co_cellvars)
            context.insert_line('cellvars = %s;' % varnames)

            funcname = ('_%s_%s__' % (self.name, funccode.get_signature(label)))
            funcname = funcname.replace('.', '_')
            funcname = funcname.replace('<', '')
            funcname = funcname.replace('>', '')
            context.insert_line('err = __pypperoni_IMPL_make_func((void*)%s, &x, func_defaults,'
                                ' closure, f->f_globals, fname, varnames, cellvars,'
                                ' %d, %d, %d, %d, %d);' % (funcname, funccode.co_flags,
                                     funccode.co_argcount, funccode.co_stacksize,
                                     len(funccode.co_freevars) + len(funccode.co_cellvars),
                                     funccode.co_nlocals))
            context.insert_line('Py_DECREF(fname);')
            context.insert_line('Py_DECREF(varnames);')
            context.insert_line('Py_XDECREF(func_defaults);')
            context.insert_line('Py_XDECREF(closure);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PUSH(x);')

            self.__gen_code(context.file, funcname, context.modules, funccode,
                            context._consts)

            context.end_block()

        elif op in (POP_JUMP_IF_TRUE, POP_JUMP_IF_FALSE):
            context.add_decl_once('result', 'int', None, False)
            context.insert_line('x = POP();')
            context.insert_line('err = __pypperoni_IMPL_check_cond(x, &result);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('if (%sresult)' %
                                ('!' if op == POP_JUMP_IF_FALSE else ''))
            context.begin_block()
            context.insert_line('goto label_%d;' % oparg)
            context.end_block()

        elif op in (JUMP_IF_TRUE_OR_POP, JUMP_IF_FALSE_OR_POP):
            context.add_decl_once('result', 'int', None, False)
            context.insert_line('x = TOP();')
            context.insert_line('err = __pypperoni_IMPL_check_cond(x, &result);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('if (%sresult)' %
                                ('!' if op == JUMP_IF_FALSE_OR_POP else ''))
            context.begin_block()
            context.insert_line('goto label_%d;' % oparg)
            context.end_block()

            context.insert_line('STACKADJ(-1);')
            context.insert_line('Py_DECREF(x);')

        elif op == JUMP_FORWARD:
            if oparg:
                context.begin_block()
                context.insert_line('goto label_%d;' % (oparg + label + 3))
                context.end_block()

        elif op in (JUMP_ABSOLUTE, CONTINUE_LOOP):
            context.begin_block()
            context.insert_line('goto label_%d;' % oparg)
            context.end_block()

        elif op == STORE_ATTR:
            context.begin_block()

            attr = codeobj.co_names[oparg]
            context.insert_line('v = TOP();')
            context.insert_line('u = SECOND();')
            context.insert_line('STACKADJ(-2);')
            context.insert_line('err = PyObject_SetAttr(v, %s, u);' %
                                       context.register_const(attr))
            context.insert_line('Py_DECREF(u);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == BUILD_MAP:
            context.begin_block()

            context.insert_line('x = _PyDict_NewPresized((Py_ssize_t)%d);' % oparg)
            context.insert_line('PUSH(x);')

            context.end_block()

        elif op == COMPARE_OP:
            context.begin_block()

            context.insert_line('w = POP();')
            context.insert_line('v = TOP();')
            context.insert_line('err = __pypperoni_IMPL_compare(w, v, %d, &x);' % oparg)
            context.insert_line('Py_DECREF(w);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('SET_TOP(x);')

            context.end_block()

        elif op == STORE_SUBSCR:
            context.begin_block()

            context.insert_line('w = POP();')
            context.insert_line('v = POP();')
            context.insert_line('u = POP();')

            context.insert_line('err = PyObject_SetItem(v, w, u);')
            context.insert_line('Py_XDECREF(w);')
            context.insert_line('Py_XDECREF(v);')
            context.insert_line('Py_XDECREF(u);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif opname[op].startswith('UNARY_'):
            opstr = opname[op].lower()
            context.begin_block()

            context.insert_line('v = TOP();')
            context.insert_line('err = __pypperoni_IMPL_%s(v, &x);' % opstr)
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_line('STACKADJ(-1);')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('SET_TOP(x);')

            context.end_block()

        elif opname[op].startswith('BINARY_'):
            opstr = opname[op].lower()
            context.begin_block()

            context.insert_line('w = POP();')
            context.insert_line('v = TOP();')
            context.insert_line('err = __pypperoni_IMPL_%s(v, w, &x);' % opstr)
            context.insert_line('Py_DECREF(v);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('if (err != 0) {')
            context.insert_line('STACKADJ(-1);')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('SET_TOP(x);')

            context.end_block()

        elif op == SETUP_LOOP:
            context.insert_line('// SETUP_LOOP (%d -> %d)' % (label, oparg + label + 3))
            context.loop_blocks.append(oparg + label + 3)
            context.setup_stack_block(label)

        elif op == SETUP_FINALLY:
            context.insert_line('// SETUP_FINALLY (%d -> %d)' % (label, oparg + label + 3))
            context.finally_blocks.append(oparg + label + 3)
            context.setup_stack_block(label)

        elif op == GET_ITER:
            context.begin_block()

            context.insert_line('v = TOP();')
            context.insert_line('x = PyObject_GetIter(v);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (x == NULL) {')
            context.insert_line('STACKADJ(-1);')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('SET_TOP(x);')

            context.end_block()

        elif op == FOR_ITER:
            context.begin_block()

            context.insert_line('v = TOP();')
            context.insert_line('err = __pypperoni_IMPL_for_iter(v, &x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.insert_line('if (x == NULL) // StopIteration')
            context.begin_block()
            context.insert_line('Py_DECREF(v);')
            context.insert_line('STACKADJ(-1);')
            context.insert_line('goto label_%d;' % (label + oparg + 3))
            context.end_block()

            context.insert_line('PUSH(x);')

            context.end_block()

        elif opname[op].startswith('INPLACE_'):
            opstr = opname[op].lower()
            context.begin_block()

            context.insert_line('w = POP();')
            context.insert_line('v = TOP();')
            context.insert_line('err = __pypperoni_IMPL_%s(v, w, &x);' % opstr)
            context.insert_line('Py_DECREF(v);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.insert_line('SET_TOP(x);')

            context.end_block()

        elif op == POP_BLOCK:
            context.insert_line('// POP_BLOCK')
            context.pop_stack_block()

        elif op == BUILD_CLASS:
            context.begin_block()

            context.add_decl_once('methods', 'PyObject*', 'NULL', False)
            context.add_decl_once('bases', 'PyObject*', 'NULL', False)
            context.add_decl_once('classname', 'PyObject*', 'NULL', False)

            context.insert_line('methods = POP();')
            context.insert_line('bases = POP();')
            context.insert_line('classname = POP();')
            context.insert_line('err = __pypperoni_IMPL_build_class(methods, bases, classname, &x);')
            context.insert_line('Py_DECREF(methods);')
            context.insert_line('Py_DECREF(bases);')
            context.insert_line('Py_DECREF(classname);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.insert_line('PUSH(x);')

            context.end_block()

        elif op == UNPACK_SEQUENCE:
            context.begin_block()

            context.insert_line('v = POP();')
            context.add_decl('unpack_array_at_%d[%d]' % (label, oparg), 'PyObject*', None, False)

            context.insert_line('err = __pypperoni_IMPL_unpack_sequence(v, unpack_array_at_%d, %d);' % (label, oparg))
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            while oparg:
                oparg -= 1
                context.insert_line('w = unpack_array_at_%d[%d];' % (label, oparg))
                context.insert_line('PUSH(w);')

            context.end_block()

        elif op == SETUP_EXCEPT:
            context.try_blocks.append(oparg + label + 3)
            context.exc_blocks += 1
            context.setup_stack_block(label)

        elif op == END_FINALLY:
            context.insert_line('// END_FINALLY')
            context.begin_block()

            if context.exc_blocks:
                context.insert_line('// re-raise unhandled exception, if any:')
                context.insert_line('if (exc != NULL)')
                context.begin_block()
                context.insert_line('PyErr_Restore(exc, val, tb);')
                context.insert_line('exc = NULL;')
                context.insert_line('val = NULL;')
                context.insert_line('tb = NULL;')
                context.insert_handle_error(line, label)
                context.end_block()
                context.exc_blocks -= 1

            else:
                context.insert_line('// no exception in stack')
                context.insert_line('v = POP();')
                context.insert_line('Py_DECREF(v);')

            context.insert_line('PypperoniTraceback_Clear(); // the exception was handled')
            context.insert_line('f->f_excline = -1;')
            context.insert_line('if (retval != NULL) goto end;')

            context.end_block()

        elif op == DELETE_ATTR:
            context.begin_block()

            context.insert_line('v = POP();')

            name = codeobj.co_names[oparg]
            context.insert_line('err = PyObject_SetAttr(v, %s, NULL);' %
                                     context.register_const(name))
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == DELETE_SUBSCR:
            context.begin_block()

            context.insert_line('w = POP();')
            context.insert_line('v = POP();')

            context.insert_line('err = PyObject_DelItem(v, w);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif opname[op] in ('SLICE+0', 'SLICE+1', 'SLICE+2', 'SLICE+3'):
            context.begin_block()

            context.insert_line('w = NULL;')
            context.insert_line('v = NULL;')

            if (op - 30) & 2:
                context.insert_line('w = POP();')

            if (op - 30) & 1:
                context.insert_line('v = POP();')

            context.insert_line('u = TOP();')
            context.insert_line('err = __pypperoni_IMPL_apply_slice(u, v, w, &x);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('Py_XDECREF(w);')
            context.insert_line('Py_XDECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_line('STACKADJ(-1);')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('SET_TOP(x);')

            context.end_block()

        elif opname[op] in ('STORE_SLICE+0', 'STORE_SLICE+1', 'STORE_SLICE+2', 'STORE_SLICE+3'):
            context.begin_block()

            context.insert_line('w = NULL;')
            context.insert_line('v = NULL;')

            if (op - 40) & 2:
                context.insert_line('w = POP();')

            if (op - 40) & 1:
                context.insert_line('v = POP();')

            context.insert_line('u = POP();')
            context.insert_line('x = POP();')

            context.insert_line('err = __pypperoni_IMPL_assign_slice(u, v, w, x);')
            context.insert_line('Py_XDECREF(w);')
            context.insert_line('Py_XDECREF(v);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif opname[op] in ('DELETE_SLICE+0', 'DELETE_SLICE+1', 'DELETE_SLICE+2', 'DELETE_SLICE+3'):
            context.begin_block()

            context.insert_line('w = NULL;')
            context.insert_line('v = NULL;')

            if (op - 50) & 2:
                context.insert_line('w = POP();')

            if (op - 50) & 1:
                context.insert_line('v = POP();')

            context.insert_line('u = POP();')

            context.insert_line('err = __pypperoni_IMPL_assign_slice(u, v, w, NULL);')
            context.insert_line('Py_XDECREF(w);')
            context.insert_line('Py_XDECREF(v);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == RAISE_VARARGS:
            if not oparg:
                context.insert_line('if (exc == NULL) {')
                context.insert_line('PyErr_Fetch(&exc, &val, &tb);')
                context.insert_line('PyErr_NormalizeException(&exc, &val, &tb);')
                context.insert_line('}')
                context.insert_line('u = tb;')
                context.insert_line('v = val;')
                context.insert_line('w = exc;')
                context.insert_line('Py_XINCREF(w);')
                context.insert_line('Py_XINCREF(v);')
                context.insert_line('Py_XINCREF(u);')

            else:
                context.insert_line('u = NULL;')
                context.insert_line('v = NULL;')
                context.insert_line('w = NULL;')
                if oparg > 2:
                    context.insert_line('u = POP();')

                if oparg > 1:
                    context.insert_line('v = POP();')

                context.insert_line('w = POP();')

            context.insert_line('__pypperoni_IMPL_do_raise(w, v, u);')
            context.insert_handle_error(line, label)

        elif op == EXEC_STMT:
            context.begin_block()
            context.insert_line('__pypperoni_IMPL_raise(PyExc_RuntimeError, "exec is disabled");')
            context.insert_handle_error(line, label)
            context.end_block()

        elif op == DELETE_FAST:
            context.begin_block()
            context.insert_line('tmp = f->f_fastlocals[%d];' % oparg)
            context.insert_line('if (tmp == NULL) {')
            context.insert_line('__pypperoni_IMPL_raise(PyExc_UnboundLocalError, "DELETE_FAST failed");')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.insert_line('f->f_fastlocals[%d] = NULL;' % oparg)
            context.insert_line('Py_DECREF(tmp);')
            context.end_block()

        elif op == DELETE_NAME:
            context.begin_block()

            name = codeobj.co_names[oparg]
            context.insert_line('err = __pypperoni_IMPL_delete_name(f, %s);' %
                                       context.register_const(name))
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == DELETE_GLOBAL:
            context.begin_block()

            name = codeobj.co_names[oparg]
            context.insert_line('err = PyDict_DelItem(f->f_globals, %s);' %
                                       context.register_const(name))
            context.insert_line('if (err != 0) {')
            context.insert_line('__pypperoni_IMPL_raise(PyExc_NameError, "DELETE_GLOBAL failed");')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == BREAK_LOOP:
            context.insert_line('// BREAK_LOOP')

            label = context.stack_level_blocks[-1]
            context.insert_restore_stack_label(label)
            context.insert_line('goto label_%d;' % context.loop_blocks[-1])

        elif op == STORE_MAP:
            context.begin_block()

            context.insert_line('w = TOP();')
            context.insert_line('u = SECOND();')
            context.insert_line('v = THIRD();')
            context.insert_line('STACKADJ(-2);')
            context.insert_line('err = PyDict_SetItem(v, w, u);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op in (LIST_APPEND, SET_ADD):
            context.begin_block()

            context.insert_line('w = POP();')
            context.insert_line('v = PEEK(%d);' % oparg)

            if op == LIST_APPEND:
                context.insert_line('err = PyList_Append(v, w);')
            else:
                context.insert_line('err = PySet_Add(v, w);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == SETUP_WITH:
            context.begin_block()

            context.insert_line('w = TOP();')
            context.insert_line('err = __pypperoni_IMPL_setup_with(w, &u, &x);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('SET_TOP(u);') # exitptr
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PUSH(x);')

            context.setup_stack_block(label)

            context.end_block()

        elif op == WITH_CLEANUP:
            context.begin_block()

            context.insert_line('Py_DECREF(POP()); // None')
            context.insert_line('v = POP();')
            context.insert_line('err = __pypperoni_IMPL_exit_with(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

            if context.buf[context.i][1] == END_FINALLY:
                # Skip this END_FINALLY:
                context.i += 1

        elif op == BUILD_SLICE:
            context.begin_block()

            if oparg == 3:
                context.insert_line('w = POP();')

            else:
                context.insert_line('w = NULL;')

            context.insert_line('v = POP();')
            context.insert_line('u = POP();')

            context.insert_line('x = PySlice_New(u, v, w);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('Py_XDECREF(w);')
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.insert_line('PUSH(x);')

            context.end_block()

        elif op == MAP_ADD:
            context.begin_block()

            context.insert_line('w = POP();')
            context.insert_line('u = POP();')
            context.insert_line('v = PEEK(%d);' % oparg)
            context.insert_line('err = PyDict_SetItem(v, w, u);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == YIELD_VALUE:
            context.begin_block()

            context.insert_line('retval = POP();')
            context.insert_line('f->f_lasti = %d;' % label)
            context.insert_line('f->f_stacktop = stack_pointer;')
            context.insert_line('return retval;')

            context.end_block()

        else:
            context.codebuffer.seek(0)
            with Lock():
                safePrint(context.codebuffer.read())
                dis.disassemble(codeobj)
            raise ValueError('%d (%s) @ %s/%s/%d' % (op, opname[op], self.name, codeobj.get_full_name(), label))

    def __gen_code(self, f, name, modules, codeobj, consts, flushconsts=False):
        buf = list(codeobj.read_code())
        chunki = 0
        codeobjs = []
        for chunk in self.__split_buf(buf, codeobj):
            chunki += 1
            chunkname = '%s_%d' % (name, chunki)
            context = self.get_context(f, chunkname, modules, codeobj.co_flags)
            context._consts = consts
            context.codeobjs = codeobjs

            context.buf = tuple(chunk)
            context.i = 0
            while context.i < len(context.buf):
                label, op, oparg, line = context.buf[context.i]
                context.i += 1

                self.__handle_one_instr(codeobj, context, label, op, oparg, line)

            context.finish()
            codeobjs = context.codeobjs

        f.add_common_header('PyObject* %s(PypperoniFrame* f);' % name)
        f.write('\nPyObject* %s(PypperoniFrame* f) {\n' % name)
        f.write('  PyObject* retval = NULL;\n\n')
        f.write('  if (Py_EnterRecursiveCall("")) return NULL;\n\n')
        f.write('  if (f->f_lasti == -2) goto clear_stack;\n')
        for i in xrange(1, chunki + 1):
            chunkname = '%s_%d' % (name, i)
            f.write('  {\n')
            f.write('    PyObject* ret = %s(f);\n' % chunkname)
            f.write('    if (ret != NULL) {\n')
            f.write('      retval = ret;\n')
            f.write('      if (f->f_lasti == -2) goto clear_stack;\n')
            f.write('      else goto end;\n')
            f.write('    }\n')
            f.write('    else if (f->f_exci != -1) goto error;\n')
            f.write('  }\n')
        f.write('  goto clear_stack;\n')
        f.write('  error:\n')
        f.write('  PypperoniTraceback_AddFrame(%s, f);\n' % context.register_literal(name))
        f.write('  clear_stack: // Clear stack\n')
        f.write('  {\n')
        f.write('    PyObject** stack_pointer = f->f_stacktop;\n')
        f.write('    while (STACK_LEVEL() > 0) {\n')
        f.write('      Py_DECREF(TOP());\n')
        f.write('      STACKADJ(-1);\n')
        f.write('    }\n')
        f.write('  }\n')
        f.write('  end:\n')
        f.write('  Py_LeaveRecursiveCall();\n')
        f.write('  return retval;\n')
        f.write('}\n\n')

        if flushconsts:
            context.flushconsts()

    def get_context(self, f, name, modules, flags):
        return Context(f, name, modules, flags)

    def __split_buf(self, buf, codeobj):
        if codeobj.co_flags & CO_GENERATOR:
            yield buf
            return

        split_interval = SPLIT_INTERVAL
        yield_at = split_interval
        _cur = []

        for i, instr in enumerate(buf):
            if instr[0] >= yield_at and len(_cur) >= split_interval:
                yield _cur
                _cur = []
                yield_at = instr[0] + split_interval

            _cur.append(instr)
            if instr[1] in (SETUP_WITH, SETUP_LOOP, SETUP_EXCEPT, SETUP_FINALLY,
                            JUMP_FORWARD):
                yield_at = max(yield_at, instr[0] + instr[2] + 4)

            elif instr[1] in (POP_JUMP_IF_TRUE, POP_JUMP_IF_FALSE,
                              JUMP_IF_TRUE_OR_POP, JUMP_IF_FALSE_OR_POP,
                              JUMP_ABSOLUTE):
                yield_at = max(yield_at, instr[2] + 1)

            elif instr[1] == LOAD_CONST and codeobj.co_consts[instr[2]] == -1:
                if len(buf) > i + 2 and buf[i + 2][1] == IMPORT_NAME:
                    # Skip until next line:
                    import_instr_size = 0
                    while buf[i + import_instr_size][3] == instr[3]:
                         import_instr_size += 1
                         if i + import_instr_size >= len(buf):
                             import_instr_size -= 1
                             break

                    yield_at = max(yield_at, buf[i + import_instr_size][0])

        if _cur:
            yield _cur

    def generate_c_code(self, f, modules):
        modname = '_%s_MODULE__' % self.name.replace('.', '_')
        self.__gen_code(f, modname, modules, self.code, [], True)

    def __handle_import(self, codeobj, context, level):
        # Get fromlist
        fromlist = codeobj.co_consts[context.buf[context.i][2]]
        context.i += 1

        # Get import_name
        orig_name = codeobj.co_names[context.buf[context.i][2]]
        context.i += 1
        if not orig_name:
            # from . import <whatever>
            orig_name = self.name.rsplit('.', 1)[0]

        import_name = self.__lookup_import(orig_name, context.modules, level=level)
        mod = context.modules[import_name]
        label = context.buf[context.i][0]
        line = context.buf[context.i][3]

        context.begin_block()

        if not fromlist:
            # Case 1: Import and store
            import_handled = False
            if import_name == orig_name and '.' in orig_name:
                module, tail_list = import_name.split('.', 1)
                if module in context.modules:
                    # Special case: "import <module>.<submodule>" (eg. "import os.path")
                    # First, import <module>, which is what actually gets stored (x)
                    # unless this is "imported as" (ie. "import module.submodule as M")
                    # In that case, the import will be followed by LOAD_ATTR
                    store_tail = False
                    while context.buf[context.i][1] == LOAD_ATTR:
                        store_tail = True
                        context.i += 1

                    tail_list = tail_list.split('.')

                    rootmod = context.modules[module]
                    context.insert_line('w = x = __pypperoni_IMPL_import((Py_ssize_t)%dU); /* %s */' % (rootmod.get_id(), rootmod.name))
                    context.insert_line('Py_INCREF(x);')
                    context.insert_line('if (x == NULL) {')
                    context.insert_handle_error(line, label)
                    context.insert_line('}')

                    modname = module + '.'
                    while tail_list:
                        # Now import <tail> and setattr
                        tail = tail_list.pop(0)
                        modname += tail + '.'
                        mod = context.modules[modname[:-1]]
                        context.insert_line('u = __pypperoni_IMPL_import((Py_ssize_t)%dU); /* %s */' % (mod.get_id(), modname[:-1]))
                        context.insert_line('if (u == NULL) {')
                        context.insert_line('Py_DECREF(x);')
                        context.insert_line('Py_DECREF(w);')
                        context.insert_handle_error(line, label)
                        context.insert_line('}')
                        context.insert_line('PyObject_SetAttr(x, %s, u);' % context.register_const(tail))
                        context.insert_line('Py_DECREF(x);')
                        context.insert_line('x = u;')

                    if store_tail:
                        context.insert_line('Py_DECREF(w);')

                    else:
                        context.insert_line('Py_DECREF(x);')
                        context.insert_line('x = w;')

                    import_handled = True

            if not import_handled:
                context.insert_line('x = __pypperoni_IMPL_import((Py_ssize_t)%dU); /* %s */' % (mod.get_id(), mod.name))
                context.insert_line('if (x == NULL) {')
                context.insert_handle_error(line, label)
                context.insert_line('}')

            context.insert_line('PUSH(x);')

            # Let __handle_one_instr handle STORE_*

        elif fromlist == ('*',):
            # Case 2: Import all
            context.insert_line('x = __pypperoni_IMPL_import((Py_ssize_t)%dU); /* %s */' % (mod.get_id(), mod.name))
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('err = __pypperoni_IMPL_import_star(f, x);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.i += 1

        else:
            # Case 3: Importing N names
            context.add_decl_once('mod', 'PyObject*', 'NULL', False)
            context.insert_line('mod = __pypperoni_IMPL_import((Py_ssize_t)%dU); /* %s */' % (mod.get_id(), mod.name))
            context.insert_line('if (mod == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in xrange(len(fromlist)):
                label, op, oparg, line = context.buf[context.i]
                context.i += 1

                name = codeobj.co_names[oparg]
                fullname = mod.name + '.' + name
                fullname = self.__lookup_import(fullname, context.modules, importable=False)
                if fullname in context.modules:
                    # We're either importing a name or a module
                    _mod = context.modules[fullname]
                    context.insert_line('v = __pypperoni_IMPL_import_from_or_module(mod, %s, (Py_ssize_t)%dU); /* %s */' % (context.register_const(name), _mod.get_id(), _mod.name))

                else:
                    # IMPORT_FROM
                    context.insert_line('v = __pypperoni_IMPL_import_from(mod, %s);' % context.register_literal(name))

                context.insert_line('if (v == NULL) {')
                context.insert_line('Py_DECREF(mod);')
                context.insert_handle_error(line, label)
                context.insert_line('}')
                context.insert_line('PUSH(v);')

                storelabel, storeop, storeoparg, storeline = context.buf[context.i]
                context.i += 1

                self.__handle_one_instr(codeobj, context, storelabel,
                                        storeop, storeoparg, storeline)

            context.insert_line('Py_DECREF(mod);')
            context.i += 1

        context.end_block()

    def __lookup_import(self, name, modules, importable=True, level=-1):
        # Check if it's a relative import
        _name = self.name.rsplit('.', 1)[0] + '.' + name
        if _name in modules:
            return _name

        elif _name in IMPORT_ALIASES:
            return IMPORT_ALIASES[_name]

        elif level != -1:
            if name == self.name.rsplit('.', 1)[0]:
                return name

            raise ImportError('bogus relative import: %s %s %s (%d)' % (_name, self.name, name, level))

        if name in IMPORT_ALIASES:
            name = IMPORT_ALIASES[name]

        # Usually, it's in modules
        if name in modules:
            return name

        # Builtin?
        if importable:
            try:
                __import__(name)

                # Register it:
                modules[name] = BuiltinModule(name)
                return name

            except ImportError:
                # OK, treat it as an external module
                safePrint('Found unknown module %s imported by %s' % (name, self.name))
                modules[name] = ExternalModule(name)
                return name


class NullModule(Module):
    def __init__(self, name):
        code = MutableCodeObject(compile('', name, 'exec'))
        Module.__init__(self, name, code)


class ExternalModule(ModuleBase):
    def __init__(self, name):
        code = MutableCodeObject(compile('', name, 'exec'))
        ModuleBase.__init__(self, name, code)

    def is_external(self):
        return True


class BuiltinModule(ExternalModule):
    pass


def write_modules_file(f, modules):
    s = '  PypperoniModule* m;\n'
    for module in modules.values():
        is_ext = module.is_external()
        parent = module.get_parent(modules)

        s += '\n'
        s += '  m = new PypperoniModule;\n'
        s += '  m->index = %dL;\n' % module.get_id()
        s += '  m->type = %s;\n' % ('MODULE_BUILTIN' if is_ext else 'MODULE_DEFINED')
        s += '  m->parent = %dL;\n' % (parent.get_id() if parent else -1)
        s += '  m->name = "%s";\n' % module.name

        if is_ext:
            s += '  m->val_1 = 0;\n'
            s += '  m->val_2 = 0;\n'
            s += '  m->val_3 = 0;\n'

        else:
            modname = '_%s_MODULE__' % module.name.replace('.', '_')
            f.write('extern "C" PyObject* %s(PypperoniFrame* f); // fwd decl\n' % modname)
            s += '  m->ptr = (void*)%s;\n' % modname
            s += '  m->val_1 = %d;\n' % module.code.co_stacksize
            s += '  m->val_2 = %d;\n' % (len(module.code.co_freevars) + len(module.code.co_cellvars))
            s += '  m->val_3 = %d;\n' % module.code.co_nlocals

        s += '  m->obj = NULL;\n'
        s += '  result.push_back(m);\n'

    f.write('\nstatic void __load_modules(std::vector<PypperoniModule*>& result)\n')
    f.write('{\n')
    f.write(s)
    f.write('}\n')

    f.write('\nstatic std::vector<PypperoniModule*> get_pypperoni_modules()\n')
    f.write('{\n')
    f.write('  static std::vector<PypperoniModule*> _pypperoni_modules;\n')
    f.write('  if(!_pypperoni_modules.size()) __load_modules(_pypperoni_modules);\n')
    f.write('  return _pypperoni_modules;\n')
    f.write('}\n')

    f.write('\n')
