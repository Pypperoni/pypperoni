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

from .codeobj import CodeObject
from .config import IMPORT_ALIASES, SPLIT_INTERVAL
from .context import Context
from .util import *

from opcode import *
globals().update(opmap)

import hashlib
import struct
import types
import dis
import ast


IDX_LABEL = 0
IDX_OP = 1
IDX_OPARG = 2
IDX_LINE = 3

FVC_MASK = 0x3
FVC_NONE = 0x0
FVC_STR = 0x1
FVC_REPR = 0x2
FVC_ASCII = 0x3
FVS_MASK = 0x4
FVS_HAVE_SPEC = 0x4


class ModuleBase:
    '''
    Base class for all module types.
    '''
    def __init__(self, name, code):
        self.name = name
        self.astmod = ast.parse(code)

        self._is_main = False
        self._id = -1

    def set_as_main(self):
        self._is_main = True

    def is_external(self):
        return False

    def is_package(self):
        return False

    def get_id(self):
        if self._is_main:
            return 0

        if self._id == -1:
            self._id = struct.unpack('<I', hashlib.sha1(self.name.encode('utf-8')).digest()[:4])[0]

        return self._id

    def get_parent(self, modules):
        return None

    def generate_c_code(self, f, modules):
        pass


class Module(ModuleBase):
    '''
    The simplest module class.
    '''
    def __init__(self, name, code):
        ModuleBase.__init__(self, name, code)

    def get_parent(self, modules):
        if '.' in self.name:
            return modules.get(self.name.rsplit('.', 1)[0])

        return None

    def __handle_one_instr(self, codeobj, context, label, op, oparg, line):
        context.insert_label(label)
        self.handle_op(codeobj, context, label, op, oparg, line)

    def handle_op(self, codeobj, context, label, op, oparg, line):
        if op == NOP:
            context.insert_line('/* NOP */')

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

        elif op == DUP_TOP_TWO:
            context.begin_block()
            context.insert_line('v = TOP();')
            context.insert_line('u = SECOND();')
            context.insert_line('Py_INCREF(u);')
            context.insert_line('Py_INCREF(v);')
            context.insert_line('PUSH(u);')
            context.insert_line('PUSH(v);')
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

        elif op == LOAD_CONST:
            context.begin_block()

            value = codeobj.co_consts[oparg]
            if isinstance(value, types.CodeType):
                context.insert_line('/* LOADED CODE OBJECT */')
                context.codeobjs.append(CodeObject(value))
                context.end_block()

            elif len(context.buf) > context.i + 1 and \
                 context.buf[context.i + 1][IDX_OP] == IMPORT_NAME:
                context.end_block()
                context.insert_line('/* DETECTED IMPORT */')
                self.__handle_import(codeobj, context, value)

            else:
                if value is None:
                    context.insert_line('x = Py_None;')

                else:
                    getter = context.register_const(value)
                    context.insert_line('x = %s; /* %s */' % (getter, safeRepr(value)))
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
            context.insert_line('v = f->f_locals;')
            context.insert_line('if (v == NULL) {')
            context.insert_line('PyErr_SetString(PyExc_SystemError, "no locals");')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('u = %s;' % context.register_const(name))
            context.insert_line('err = PyDict_CheckExact(v) ?')
            context.insert_line('  PyDict_SetItem(v, u, x) : PyObject_SetItem(v, u, x);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == STORE_GLOBAL:
            context.begin_block()

            name = codeobj.co_names[oparg]
            context.insert_line('x = POP();')
            context.insert_line('err = PyDict_SetItem(f->f_globals, %s, x);' %
                                            context.register_const(name))
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.end_block()

        elif op == STORE_FAST:
            context.begin_block()

            context.insert_line('x = POP();')
            context.insert_line('tmp = fastlocals[%d];' % oparg)
            context.insert_line('fastlocals[%d] = x;' % oparg)
            context.insert_line('Py_XDECREF(tmp);')

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

        elif op == STORE_SUBSCR:
            context.begin_block()
            context.insert_line('w = POP();')
            context.insert_line('v = POP();')
            context.insert_line('u = POP();')
            context.insert_line('err = PyObject_SetItem(v, w, u);')
            context.insert_line('Py_DECREF(w);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op == STORE_DEREF:
            context.begin_block()
            context.insert_line('v = POP();')
            context.insert_line('x = freevars[%d]; /* cell */' % oparg)
            context.insert_line('tmp = PyCell_GET(x);')
            context.insert_line('PyCell_SET(x, v);')
            context.insert_line('Py_XDECREF(tmp);')
            context.end_block()

        elif op == DELETE_FAST:
            context.begin_block()
            context.insert_line('tmp = fastlocals[%d];' % oparg)
            context.insert_line('if (tmp == NULL) {')
            context.insert_line('PyErr_SetString(PyExc_UnboundLocalError, "DELETE_FAST failed");')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('fastlocals[%d] = NULL;' % oparg)
            context.insert_line('Py_DECREF(tmp);')
            context.end_block()

        elif op == DELETE_NAME:
            context.begin_block()

            name = codeobj.co_names[oparg]
            context.insert_line('x = POP();')
            context.insert_line('v = f->f_locals;')
            context.insert_line('if (v == NULL) {')
            context.insert_line('PyErr_SetString(PyExc_SystemError, "no locals");')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('err = PyObject_DelItem(v, %s);' % context.register_const(name))
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
            context.insert_line('PyErr_Format(PyExc_NameError, "DELETE_GLOBAL failed");')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op == DELETE_ATTR:
            context.begin_block()

            name = codeobj.co_names[oparg]
            context.insert_line('v = POP();')
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

        elif op == DELETE_DEREF:
            context.begin_block()
            context.insert_line('tmp = freevars[%d]; /* cell */' % oparg)
            context.insert_line('if (PyCell_GET(tmp) == NULL) {')
            context.insert_line('PyErr_SetString(PyExc_UnboundLocalError, "DELETE_DEREF failed");')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PyCell_Set(tmp, NULL);')
            context.end_block()

        elif op == COMPARE_OP:
            context.begin_block()

            context.insert_line('w = POP(); /* right */')
            context.insert_line('v = TOP(); /* left */')
            context.insert_line('err = __pypperoni_IMPL_compare(v, w, %d, &x);' % oparg)
            context.insert_line('Py_DECREF(w);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('SET_TOP(x);')
            context.end_block()

        elif op == BUILD_STRING:
            context.begin_block()
            context.insert_line('u = PyUnicode_New(0, 0); /* empty */')
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('x = _PyUnicode_JoinArray(u, stack_pointer - %d, %d);' % (oparg, oparg))
            context.insert_line('Py_DECREF(u);')
            context.insert_line('if (x == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg):
                context.insert_line('v = POP();')
                context.insert_line('Py_DECREF(v);')

            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == BUILD_LIST:
            context.begin_block()
            context.insert_line('u = PyList_New(%d);' % oparg)
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg, 0, -1):
                context.insert_line('v = POP();')
                context.insert_line('PyList_SET_ITEM(u, %d, v);' % (i - 1))

            context.insert_line('PUSH(u);')
            context.end_block()

        elif op in (BUILD_TUPLE_UNPACK_WITH_CALL, BUILD_TUPLE_UNPACK, BUILD_LIST_UNPACK):
            context.begin_block()
            context.insert_line('u = PyList_New(0); /* sum */')
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg, 0, -1):
                context.insert_line('v = _PyList_Extend((PyListObject *)u, PEEK(%d));' % i)
                context.insert_line('if (v == NULL) {')
                context.insert_line('Py_DECREF(u);')
                context.insert_handle_error(line, label)
                context.insert_line('}')
                context.insert_line('Py_DECREF(v);')

            if op != BUILD_LIST_UNPACK:
                context.insert_line('x = PyList_AsTuple(u);')
                context.insert_line('Py_DECREF(u);')
                context.insert_line('if (x == NULL) {')
                context.insert_handle_error(line, label)
                context.insert_line('}')

            else:
                context.insert_line('x = u;')

            for i in range(oparg):
                context.insert_line('Py_DECREF(POP());')

            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == BUILD_MAP_UNPACK_WITH_CALL:
            context.begin_block()
            context.insert_line('u = PyDict_New(); /* sum */')
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg, 0, -1):
                context.insert_line('v = PEEK(%d);' % i)
                context.insert_line('if (_PyDict_MergeEx(u, v, 2) < 0) {')
                context.insert_line('__pypperoni_IMPL_handle_bmuwc_error(v, PEEK(%d));' % (oparg + 2))
                context.insert_line('Py_DECREF(u);')
                context.insert_handle_error(line, label)
                context.insert_line('}')
                context.insert_line('Py_DECREF(v);')

            for i in range(oparg):
                context.insert_line('Py_DECREF(POP());')

            context.insert_line('PUSH(u);')
            context.end_block()

        elif op == BUILD_MAP_UNPACK:
            context.begin_block()
            context.insert_line('u = PyDict_New(); /* sum */')
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg, 0, -1):
                context.insert_line('v = PEEK(%d);' % i)
                context.insert_line('if (PyDict_Update(u, v) < 0) {')
                context.insert_line('if (PyErr_ExceptionMatches(PyExc_AttributeError)) {')
                context.insert_line('PyErr_Format(PyExc_TypeError, "\'%.200s\' object is not a mapping", v->ob_type->tp_name);')
                context.insert_line('}')
                context.insert_line('Py_DECREF(u);')
                context.insert_handle_error(line, label)
                context.insert_line('}')
                context.insert_line('Py_DECREF(v);')

            for i in range(oparg):
                context.insert_line('Py_DECREF(POP());')

            context.insert_line('PUSH(u);')
            context.end_block()

        elif op == LIST_APPEND:
            context.begin_block()
            context.insert_line('v = POP();')
            context.insert_line('x = PEEK(%d);' % oparg)
            context.insert_line('err = PyList_Append(x, v);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op == BUILD_TUPLE:
            context.begin_block()
            context.insert_line('u = PyTuple_New(%d);' % oparg)
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg, 0, -1):
                context.insert_line('v = POP();')
                context.insert_line('PyTuple_SET_ITEM(u, %d, v);' % (i - 1))

            context.insert_line('PUSH(u);')
            context.end_block()

        elif op == BUILD_SET:
            context.begin_block()
            context.insert_line('u = PySet_New(NULL);')
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg, 0, -1):
                context.insert_line('v = PEEK(%d);' % i)
                context.insert_line('if (err == 0) err = PySet_Add(u, v);')
                context.insert_line('Py_DECREF(v);')

            context.insert_line('STACKADJ(-%d);' % oparg)
            context.insert_line('if (err != 0) {')
            context.insert_line('Py_DECREF(u);')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PUSH(u);')
            context.end_block()

        elif op == SET_ADD:
            context.begin_block()
            context.insert_line('v = POP();')
            context.insert_line('x = PEEK(%d);' % oparg)
            context.insert_line('err = PySet_Add(x, v);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op == BUILD_MAP:
            context.begin_block()
            context.insert_line('u = _PyDict_NewPresized(%d);' % oparg)
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(oparg, 0, -1):
                context.insert_line('x = PEEK(%d);' % (2 * i))
                context.insert_line('v = PEEK(%d);' % (2 * i - 1))
                context.insert_line('err = PyDict_SetItem(u, x, v);')
                context.insert_line('if (err != 0)')
                context.begin_block()
                context.insert_line('Py_DECREF(u);')
                context.insert_handle_error(line, label)
                context.end_block()

            for i in range(2 * oparg):
                context.insert_line('x = POP();')
                context.insert_line('Py_DECREF(x);')

            context.insert_line('PUSH(u);')
            context.end_block()

        elif op == MAP_ADD:
            context.begin_block()
            context.insert_line('x = POP();')
            context.insert_line('v = POP();')
            context.insert_line('u = PEEK(%d);' % oparg)
            context.insert_line('err = PyDict_SetItem(u, x, v);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op == BUILD_CONST_KEY_MAP:
            context.begin_block()

            context.insert_line('x = POP(); /* keys */')
            context.insert_line('u = _PyDict_NewPresized(%d);' % oparg)

            context.insert_line('if (u == NULL)')
            context.begin_block()
            context.insert_line('Py_DECREF(x);')
            context.insert_handle_error(line, label)
            context.end_block()

            for i in range(oparg):
                context.insert_line('v = PyTuple_GET_ITEM(x, %d);' % i)
                context.insert_line('w = POP();')
                context.insert_line('err = PyDict_SetItem(u, v, w);')
                context.insert_line('Py_DECREF(w);')
                context.insert_line('if (err != 0)')
                context.begin_block()
                context.insert_line('Py_DECREF(u);')
                context.insert_handle_error(line, label)
                context.end_block()

            context.insert_line('PUSH(u);')

            context.end_block()

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

        elif op == LOAD_FAST:
            context.begin_block()
            name = codeobj.co_varnames[oparg]
            context.insert_line('x = fastlocals[%d];' % oparg)
            context.insert_line('if (x == NULL) {')
            errormsg = "local variable '%.200s' referenced before assignment" % name
            context.insert_line('PyErr_SetString(PyExc_UnboundLocalError, %s);' % context.register_literal(errormsg))
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_DEREF:
            context.begin_block()
            context.insert_line('x = freevars[%d]; /* cell */' % oparg)
            context.insert_line('u = PyCell_GET(x);')
            context.insert_line('if (u == NULL) {')

            if oparg < len(codeobj.co_cellvars):
                name = codeobj.co_cellvars[oparg]

            else:
                name = codeobj.co_freevars[oparg - len(codeobj.co_cellvars)]

            errormsg = "free variable '%.200s' referenced before assignment in enclosing scope" % name
            context.insert_line('PyErr_SetString(PyExc_NameError, %s);' % context.register_literal(errormsg))
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(u);')
            context.insert_line('PUSH(u);')
            context.end_block()

        elif op == LOAD_CLOSURE:
            context.begin_block()
            context.insert_line('x = freevars[%d];' % oparg)
            context.insert_line('Py_INCREF(x);')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_BUILD_CLASS:
            context.begin_block()
            context.insert_line('err = __pypperoni_IMPL_load_build_class(f, &x);')
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == LOAD_CLASSDEREF:
            context.begin_block()

            name = codeobj.co_freevars[oparg - len(codeobj.co_cellvars)]
            name = context.register_const(name)
            context.insert_line('if (PyDict_CheckExact(f->f_locals)) {')
            context.insert_line('v = PyDict_GetItem(f->f_locals, %s);' % name)
            context.insert_line('Py_XINCREF(v);')
            context.insert_line('}')
            context.insert_line('else {')
            context.insert_line('v = PyObject_GetItem(f->f_locals, %s);' % name)
            context.insert_line('if (v == NULL) {')
            context.insert_line('if (!PyErr_ExceptionMatches(PyExc_KeyError)) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PyErr_Clear();')
            context.insert_line('}')
            context.insert_line('}')
            context.insert_line('if (v == NULL) {')
            context.insert_line('v = PyCell_GET(freevars[%d]);' % oparg)
            context.insert_line('if (v == NULL) {')
            context.insert_line('PyErr_SetString(PyExc_UnboundLocalError, "LOAD_CLASSDEREF failed");')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(v);')
            context.insert_line('}')
            context.insert_line('PUSH(v);')
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
                context.insert_line('goto label_%d;' % (oparg + label + 2))
                context.end_block()

        elif op == JUMP_ABSOLUTE:
            context.begin_block()
            context.insert_line('goto label_%d;' % oparg)
            context.end_block()

        elif op == GET_AWAITABLE:
            context.add_decl_once('type', 'PyTypeObject*', None, False)
            context.begin_block()
            context.insert_line('u = TOP(); /* iterable */')
            context.insert_line('v = _PyCoro_GetAwaitableIter(u); /* iter */')

            prevopcode = context.buf[context.i - 2][IDX_OP]
            prevopcode2msg = {
                BEFORE_ASYNC_WITH: 'enter',
                WITH_CLEANUP_START: 'exit'
            }
            if prevopcode in prevopcode2msg:
                msg = "'async with' received an object from __a%s__ that does not implement __await__: %%.100s"
                msg %= prevopcode2msg[prevopcode]
                context.insert_line('if (v == NULL)')
                context.begin_block()
                context.insert_line('type = Py_TYPE(u);')
                context.insert_line('if (type->tp_as_async == NULL || type->tp_as_async->am_await == NULL) {')
                context.insert_line('PyErr_Format(PyExc_TypeError, %s, type->tp_name);' % msg)
                context.insert_line('}')
                context.end_block()

            context.insert_line('Py_DECREF(u);')
            context.insert_line('if (v != NULL && PyCoro_CheckExact(v))')
            context.begin_block()
            context.insert_line('tmp = _PyGen_yf((PyGenObject*)v);')
            context.insert_line('if (tmp != NULL) {')
            context.insert_line('Py_DECREF(tmp);')
            context.insert_line('Py_CLEAR(v);')
            context.insert_line('PyErr_SetString(PyExc_RuntimeError, "coroutine is being awaited already");')
            context.insert_line('}')
            context.end_block()

            context.insert_line('SET_TOP(v);')
            context.insert_line('if (v == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op == GET_ITER:
            context.begin_block()
            context.insert_line('u = TOP();')
            context.insert_line('v = PyObject_GetIter(u);')
            context.insert_line('if (v == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('SET_TOP(v);')
            context.end_block()

        elif op == FOR_ITER:
            context.begin_block()
            context.insert_line('u = TOP();')
            context.insert_line('x = (*u->ob_type->tp_iternext)(u);')

            context.insert_line('if (x == NULL)')
            context.begin_block()

            context.insert_line('if (PyErr_Occurred())')
            context.begin_block()
            context.insert_line('if (!PyErr_ExceptionMatches(PyExc_StopIteration)) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PyErr_Clear();')
            context.end_block()

            context.insert_line('Py_DECREF(u);')
            context.insert_line('STACKADJ(-1);')
            context.insert_line('goto label_%d;' % (label + oparg + 2))

            context.end_block()

            context.insert_line('PUSH(x);')

            context.end_block()

        elif op == UNPACK_SEQUENCE:
            context.begin_block()
            context.insert_line('u = POP();')
            context.insert_line('err = __pypperoni_IMPL_unpack_sequence(u, &stack_pointer, %d);' % oparg)
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op == UNPACK_EX:
            context.begin_block()
            context.insert_line('u = POP();')
            context.insert_line('err = __pypperoni_IMPL_unpack_ex(u, &stack_pointer, %d);' % oparg)
            context.insert_line('if (err != 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

        elif op in (CALL_FUNCTION, CALL_FUNCTION_KW):
            context.begin_block()

            if op == CALL_FUNCTION_KW:
                context.insert_line('v = POP();')

            else:
                context.insert_line('v = NULL;')

            context.insert_line('u = __pypperoni_IMPL_call_func(&stack_pointer, %d, v);' % oparg)

            if op == CALL_FUNCTION_KW:
                context.insert_line('Py_DECREF(v);')

            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('PUSH(u);')
            context.end_block()

        elif op == CALL_FUNCTION_EX:
            context.begin_block()

            if oparg & 0x01:
                context.insert_line('w = POP(); /* kwargs */')
                context.insert_line('w = __pypperoni_IMPL_ensure_kwdict(w, SECOND());')
                context.insert_line('if (w == NULL) {')
                context.insert_handle_error(line, label)
                context.insert_line('}')

            else:
                context.insert_line('w = NULL;')

            context.insert_line('v = POP(); /* callargs */')
            context.insert_line('v = __pypperoni_IMPL_ensure_args_iterable(v, TOP());')
            context.insert_line('if (v == NULL) {')
            if oparg & 0x01:
                context.insert_line('Py_DECREF(w);')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            context.insert_line('x = TOP(); /* func */')

            context.insert_line('if (PyCFunction_Check(x)) u = PyCFunction_Call(x, v, w);')
            context.insert_line('else u = PyObject_Call(x, v, w);')
            if oparg & 0x01:
                context.insert_line('Py_DECREF(w);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('SET_TOP(u);')
            context.insert_line('if (u == NULL) {')
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

        elif op == MAKE_FUNCTION:
            context.add_decl_once('codeobj', 'PyCodeObject*', None, False)
            context.add_decl_once('func', 'PyFunctionObject*', None, False)
            context.begin_block()

            context.insert_line('u = POP(); /* qualname */')

            funccode = context.codeobjs.pop()
            funccode.co_path = '%s_%d' % (codeobj.get_full_name(), label)

            context.insert_line('tmp = PyBytes_FromString("");')
            context.insert_line('codeobj = PyCode_New(')
            context.insert_line('  %d, /* argcount */' % funccode.co_argcount)
            context.insert_line('  %d, /* kwonlyargcount */' % funccode.co_kwonlyargcount)
            context.insert_line('  %d, /* nlocals */' % funccode.co_nlocals)
            context.insert_line('  %d, /* stacksize */' % funccode.co_stacksize)
            context.insert_line('  %d, /* flags */' % funccode.co_flags)
            context.insert_line('  NULL, /* code */')
            context.insert_line('  NULL, /* consts */')
            context.insert_line('  NULL, /* names */')
            context.insert_line('  %s, /* varnames */' % context.register_const(funccode.co_varnames))
            context.insert_line('  %s, /* freevars */' % context.register_const(funccode.co_freevars))
            context.insert_line('  %s, /* cellvars */' % context.register_const(funccode.co_cellvars))
            context.insert_line('  %s, /* filename */' % context.register_const(self.name))
            context.insert_line('  %s, /* name */' % context.register_const(funccode.co_name))
            context.insert_line('  %d, /* firstlineno */' % funccode.co_firstlineno)
            context.insert_line('  tmp /* lnotab */')
            context.insert_line(');')
            context.insert_line('if (codeobj == NULL) {')
            context.insert_line('Py_DECREF(u);')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('func = (PyFunctionObject*) PyFunction_NewWithQualName'
                                '((PyObject*)codeobj, f->f_globals, u);')
            context.insert_line('Py_DECREF(u);')
            context.insert_line('if (func == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            if oparg & 0x08:
                context.insert_line('func->func_closure = POP();')

            if oparg & 0x04:
                context.insert_line('func->func_annotations = POP();')

            if oparg & 0x02:
                context.insert_line('func->func_kwdefaults = POP();')

            if oparg & 0x01:
                context.insert_line('func->func_defaults = POP();')

            funcname = ('_%s_%s__' % (self.name, funccode.get_signature(label)))
            funcname = funcname.replace('.', '_')
            funcname = funcname.replace('<', '')
            funcname = funcname.replace('>', '')
            self.__gen_code(context.file, funcname, context.modules, funccode,
                            context._consts)

            context.insert_line('codeobj->co_meth_ptr = &%s;' % funcname)

            context.insert_line('PUSH((PyObject*)func);')
            context.end_block()

        elif op in (SETUP_LOOP, SETUP_EXCEPT, SETUP_FINALLY):
            context.begin_block()
            context.insert_line('void* __addr;')
            context.insert_line('GET_ADDRESS(__addr, label_%d);' % (label + oparg + 2))
            context.insert_line('PyFrame_BlockSetup(f, %d, __addr, STACK_LEVEL());' % op)
            context.end_block()

        elif op == RAISE_VARARGS:
            context.begin_block()
            context.insert_line('u = NULL;')
            context.insert_line('v = NULL;')

            if oparg >= 2:
                context.insert_line('v = POP();')

            if oparg >= 1:
                context.insert_line('u = POP();')

            context.insert_line('if (__pypperoni_IMPL_do_raise(u, v) == 0) {')
            context.insert_line('  *why = WHY_EXCEPTION; goto fast_block_end;')
            context.insert_line('}')
            context.insert_handle_error(line, label)
            context.end_block()

        elif op == YIELD_VALUE:
            context.begin_block()
            context.insert_line('retval = POP();')

            if codeobj.co_flags & CO_ASYNC_GENERATOR:
                context.insert_line('w = _PyAsyncGenValueWrapperNew(retval);')
                context.insert_line('Py_DECREF(retval);')
                context.insert_line('if (w == NULL) {')
                context.insert_line('retval = NULL;')
                context.insert_handle_error(line, label)
                context.insert_line('}')
                context.insert_line('retval = w;')

            context.insert_yield(line, label + 2)
            context.end_block()

        elif op == RETURN_VALUE:
            context.begin_block()
            context.insert_line('retval = POP();')
            context.insert_line('*why = WHY_RETURN; goto fast_block_end;')
            context.end_block()

        elif op == CONTINUE_LOOP:
            context.begin_block()
            context.insert_line('retval = PyLong_FromLong(%d);' % oparg)
            context.insert_line('*why = WHY_CONTINUE; goto fast_block_end;')
            context.end_block()

        elif op == BREAK_LOOP:
            context.begin_block()
            context.insert_line('*why = WHY_BREAK; goto fast_block_end;')
            context.end_block()

        elif op == POP_BLOCK:
            context.add_decl_once('block', 'PyTryBlock*', None, False)
            context.begin_block()
            context.insert_line('block = PyFrame_BlockPop(f);')
            context.insert_line('UNWIND_BLOCK(block)')
            context.end_block()

        elif op == POP_EXCEPT:
            context.add_decl_once('block', 'PyTryBlock*', None, False)
            context.begin_block()
            context.insert_line('block = PyFrame_BlockPop(f);')
            context.insert_line('UNWIND_EXCEPT_HANDLER(block);')
            context.end_block()

        elif op == END_FINALLY:
            context.add_decl_once('block', 'PyTryBlock*', None, False)
            context.begin_block()
            context.insert_line('x = POP(); /* status */')

            context.insert_line('if PyLong_Check(x)')
            context.begin_block()
            context.insert_line('*why = PyLong_AS_LONG(x);')
            context.insert_line('if (*why == WHY_RETURN || *why == WHY_CONTINUE)')
            context.insert_line('  retval = POP();')
            context.insert_line('if (*why == WHY_SILENCED)')
            context.begin_block()
            context.insert_line('block = PyFrame_BlockPop(f);')
            context.insert_line('UNWIND_EXCEPT_HANDLER(block);')
            context.insert_line('*why = WHY_NOT;')
            context.end_block()
            context.insert_line('else')
            context.begin_block()
            context.insert_line('Py_DECREF(x);')
            context.insert_line('goto fast_block_end;')
            context.end_block()
            context.end_block()

            context.insert_line('else if PyExceptionClass_Check(x)')
            context.begin_block()
            context.insert_line('exc = POP(); tb = POP();')
            context.insert_line('PyErr_Restore(x, exc, tb);')
            context.insert_line('*why = WHY_EXCEPTION; goto fast_block_end;')
            context.end_block()

            context.insert_line('Py_DECREF(x);')

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
            context.insert_line('void* __addr;')
            context.insert_line('GET_ADDRESS(__addr, label_%d);' % (label + oparg + 2))
            context.insert_line('PyFrame_BlockSetup(f, SETUP_FINALLY, __addr, STACK_LEVEL());')
            context.insert_line('PUSH(x);')
            context.end_block()

        elif op == WITH_CLEANUP_START:
            context.add_decl_once('block', 'PyTryBlock*', None, False)
            context.begin_block()
            context.insert_line('exc = TOP();')
            context.insert_line('val = Py_None;')
            context.insert_line('tb = Py_None;')

            context.insert_line('if (exc == Py_None)')
            context.begin_block()
            context.insert_line('POP();')
            context.insert_line('x = TOP(); /* exit_func */')
            context.insert_line('SET_TOP(exc);')
            context.end_block()

            context.insert_line('else if (PyLong_Check(exc))')
            context.begin_block()
            context.insert_line('STACKADJ(-1);')
            context.insert_line('switch (PyLong_AS_LONG(exc))')
            context.begin_block()
            context.insert_line('case WHY_RETURN:')
            context.insert_line('case WHY_CONTINUE:')
            context.insert_line('  x = SECOND(); /* exit_func */')
            context.insert_line('  SET_SECOND(TOP());')
            context.insert_line('  SET_TOP(exc);')
            context.insert_line('  break;')
            context.insert_line('default:')
            context.insert_line('  x = TOP();')
            context.insert_line('  SET_TOP(exc);')
            context.insert_line('  break;')
            context.end_block()
            context.insert_line('exc = Py_None;')
            context.end_block()

            context.insert_line('else')
            context.begin_block()
            context.insert_line('val = SECOND();')
            context.insert_line('tb = THIRD();')
            context.insert_line('u = FOURTH(); /* tp2 */')
            context.insert_line('v = PEEK(5); /* exc2 */')
            context.insert_line('w = PEEK(6); /* tb2 */')
            context.insert_line('x = PEEK(7); /* exit_func */')
            context.insert_line('SET_VALUE(7, w);')
            context.insert_line('SET_VALUE(6, v);')
            context.insert_line('SET_VALUE(5, u);')
            context.insert_line('SET_FOURTH(NULL);')
            context.insert_line('block = &f->f_blockstack[f->f_iblock - 1];')
            context.insert_line('block->b_level--;')
            context.end_block()

            context.insert_line('tmp = PyObject_CallFunctionObjArgs(x, exc, val, tb, NULL);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('if (tmp == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_INCREF(exc);')
            context.insert_line('PUSH(exc);')
            context.insert_line('PUSH(tmp);')

            context.end_block()

        elif op == WITH_CLEANUP_FINISH:
            context.begin_block()
            context.insert_line('x = POP();')
            context.insert_line('exc = POP();')
            context.insert_line('err = (exc != Py_None) ? PyObject_IsTrue(x) : 0;')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('Py_DECREF(exc);')
            context.insert_line('if (err < 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('else if (err > 0)')
            context.begin_block()
            context.insert_line('err = 0;')
            context.insert_line('PUSH(PyLong_FromLong((long) WHY_SILENCED));')
            context.end_block()
            context.end_block()

        elif op == GET_YIELD_FROM_ITER:
            context.begin_block()
            context.insert_line('x = TOP(); /* iterable */')

            context.insert_line('if (PyCoro_CheckExact(x))')
            context.begin_block()
            if not codeobj.co_flags & (CO_COROUTINE | CO_ITERABLE_COROUTINE):
                context.insert_line('Py_DECREF(x);')
                context.insert_line('SET_TOP(NULL);')
                context.insert_line('PyErr_SetString(PyExc_TypeError,')
                context.insert_line('   "cannot \'yield from\' a coroutine object "')
                context.insert_line('   "in a non-coroutine generator");')
                context.insert_handle_error(line, label)
            context.end_block()

            context.insert_line('else if (!PyGen_CheckExact(x))')
            context.begin_block()
            context.insert_line('u = PyObject_GetIter(x);')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('SET_TOP(u);')
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()

            context.end_block()

        elif op == YIELD_FROM:
            context.begin_block()
            context.insert_line('v = POP();')
            context.insert_line('x = TOP(); /* receiver */')

            context.insert_line('if (PyGen_CheckExact(x) || PyCoro_CheckExact(x))')
            context.begin_block()
            context.insert_line('retval = _PyGen_Send((PyGenObject *)x, v);')
            context.end_block()

            context.insert_line('else')
            context.begin_block()
            context.insert_line('_Py_IDENTIFIER(send);')
            context.insert_line('if (v == Py_None) retval = Py_TYPE(x)->tp_iternext(x);')
            context.insert_line('else retval = _PyObject_CallMethodIdObjArgs(x, &PyId_send, v, NULL);')
            context.end_block()

            context.insert_line('Py_DECREF(v);')
            context.insert_line('if (retval == NULL)')
            context.begin_block()
            context.insert_line('err = _PyGen_FetchStopIterationValue(&val);')
            context.insert_line('if (err < 0) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.insert_line('Py_DECREF(x);')
            context.insert_line('SET_TOP(val);')
            context.end_block()

            context.insert_line('else')
            context.begin_block()
            context.insert_yield(line, label)
            context.end_block()

            context.end_block()

        elif op == FORMAT_VALUE:
            context.begin_block()

            if (oparg & FVS_MASK) == FVS_HAVE_SPEC:
                context.insert_line('x = POP(); /* fmt_spec */')

            else:
                context.insert_line('x = NULL; /* fmt_spec */')

            context.insert_line('v = POP();')

            conv_fn = {
                FVC_STR: 'PyObject_Str',
                FVC_REPR: 'PyObject_Repr',
                FVC_ASCII: 'PyObject_ASCII'
            }.get(oparg & FVC_MASK)
            if conv_fn:
                context.insert_line('u = %s(v);' % conv_fn)
                context.insert_line('Py_DECREF(v);')
                context.insert_line('if (u == NULL) {')
                context.insert_line('Py_XDECREF(x);')
                context.insert_handle_error(line, label)
                context.insert_line('}')
                context.insert_line('v = u;')

            context.insert_line('if (PyUnicode_CheckExact(v) && x == NULL) u = v;')
            context.insert_line('else')
            context.begin_block()
            context.insert_line('u = PyObject_Format(v, x);')
            context.insert_line('Py_DECREF(v);')
            context.insert_line('Py_XDECREF(x);')
            context.insert_line('if (u == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')
            context.end_block()
            context.insert_line('PUSH(u);')
            context.end_block()

        else:
            context.codebuffer.seek(0)
            with Lock():
                safePrint(context.codebuffer.read())
                dis.disassemble(codeobj)
            raise ValueError('%d (%s) @ %s/%s/%d' % (op, opname[op], self.name,
                                                     codeobj.get_full_name(),
                                                     label))

    def __gen_code(self, f, name, modules, codeobj, consts, flushconsts=False):
        buf = list(codeobj.read_code())
        chunki = 0
        chunks = list(self.__split_buf(buf, codeobj))

        f.add_common_header('PyObject* %s(PyFrameObject* f);' % name)

        if len(chunks) > 1:
            context = self.__handle_chunks(chunks, f, name, modules, codeobj, consts,)

        else:
            context = self.__handle_chunk(chunks[0], f, name, modules, codeobj, consts, [])
            context.finish(False)

        if flushconsts:
            context.flushconsts()

    def __handle_chunk(self, chunk, f, chunkname, modules, codeobj, consts, codeobjs):
        '''
        Handles a single chunk of code and returns a Context object.
        '''
        context = self.get_context(f, chunkname, modules,
                                   codeobj.co_flags,
                                   codeobj.co_nlocals)
        context._consts = consts
        context.codeobjs = codeobjs

        context.buf = tuple(chunk)
        context.i = 0
        while context.i < len(context.buf):
            label, op, oparg, line = context.buf[context.i]
            context.i += 1

            self.__handle_one_instr(codeobj, context, label, op, oparg, line)

        return context

    def __handle_chunks(self, chunks, f, name, modules, codeobj, consts):
        '''
        Handles and encapsulates multiple chunks of code.
        '''
        codeobjs = []
        chunki = 0
        for chunk in chunks:
            chunki += 1
            chunkname = '%s_%d' % (name, chunki)
            context = self.__handle_chunk(chunk, f, chunkname, modules,
                                          codeobj, consts, codeobjs)
            context.finish(True)
            codeobjs = context.codeobjs

        f.write('\nPyObject* %s(PyFrameObject* f) {\n' % name)
        f.write('  PyObject* retval = NULL;\n')
        f.write('  int why;\n\n')
        f.write('  __%s_load_consts();\n' % f.uid)
        for i in range(1, chunki + 1):
            chunkname = '%s_%d' % (name, i)
            f.write('  {\n')
            f.write('    retval = %s(f, &why);\n' % chunkname)
            f.write('    if (why == WHY_EXCEPTION) goto error;\n')
            f.write('    else if (why == WHY_YIELD) goto end;\n')
            f.write('    else if (retval != NULL) goto clear_stack;\n')
            f.write('  }\n')
        f.write('  goto clear_stack;\n')
        f.write('  error:\n')
        f.write('  PyTraceBack_Here(f);\n')
        f.write('  clear_stack: /* Clear stack */\n')
        f.write('  {\n')
        f.write('    PyObject** stack_pointer = f->f_stacktop;\n')
        f.write('    while (STACK_LEVEL() > 0) {\n')
        f.write('      Py_XDECREF(TOP());\n')
        f.write('      STACKADJ(-1);\n')
        f.write('    }\n')
        f.write('    f->f_stacktop = NULL;\n')
        f.write('  }\n')
        f.write('  end:\n')
        f.write('  return _Py_CheckFunctionResult(NULL, retval, "%s");\n' % name)
        f.write('}\n\n')

        return context

    def get_context(self, f, name, modules, flags, nlocals):
        return Context(f, name, modules, flags, nlocals)

    def __split_buf(self, buf, codeobj):
        if codeobj.co_flags & CO_GENERATOR:
            # No splitting generators
            yield buf
            return

        split_interval = SPLIT_INTERVAL
        yield_at = split_interval
        _cur = []

        for i, instr in enumerate(buf):
            if instr[IDX_LABEL] >= yield_at and len(_cur) >= split_interval:
                yield _cur
                _cur = []
                yield_at = instr[IDX_LABEL] + split_interval

            _cur.append(instr)
            if instr[IDX_OP] in hasjrel:
                yield_at = max(yield_at, instr[IDX_LABEL] + instr[IDX_OPARG] + 4)

            elif instr[IDX_OP] in hasjabs:
                yield_at = max(yield_at, instr[IDX_OPARG] + 1)

            elif instr[IDX_OP] == LOAD_CONST and codeobj.co_consts[instr[IDX_OPARG]] == -1:
                if len(buf) > i + 2 and buf[i + 2][IDX_OP] == IMPORT_NAME:
                    # Skip until next line:
                    import_instr_size = 0
                    while buf[i + import_instr_size][IDX_LINE] == instr[IDX_LINE]:
                         import_instr_size += 1
                         if i + import_instr_size >= len(buf):
                             import_instr_size -= 1
                             break

                    yield_at = max(yield_at, buf[i + import_instr_size][IDX_LABEL])

        if _cur:
            yield _cur

    def generate_c_code(self, f, modules):
        self.code = CodeObject(compile(self.astmod, self.name, 'exec', optimize=2))
        modname = '_%s_MODULE__' % self.name.replace('.', '_')
        self.__gen_code(f, modname, modules, self.code, [], True)

    def __handle_import(self, codeobj, context, level):
        # Get fromlist
        fromlist = codeobj.co_consts[context.buf[context.i][IDX_OPARG]]
        context.i += 1

        # Get import_name
        orig_name = codeobj.co_names[context.buf[context.i][IDX_OPARG]]
        context.i += 1

        orig_name = self.__convert_relative_import(orig_name, level)
        import_name = self.__lookup_import(orig_name, context.modules)
        mod = context.modules[import_name]
        label = context.buf[context.i][IDX_LABEL]
        line = context.buf[context.i][IDX_LINE]

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
                    while context.buf[context.i][IDX_OP] == LOAD_ATTR:
                        store_tail = True
                        context.i += 1

                    tail_list = tail_list.split('.')

                    rootmod = context.modules[module]
                    context.insert_line('w = x = __pypperoni_IMPL_import((uint64_t)%dU);'
                                        ' /* %s */' % (rootmod.get_id(), rootmod.name))
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
                        context.insert_line('u = __pypperoni_IMPL_import((uint64_t)%dU);'
                                            ' /* %s */' % (mod.get_id(), modname[:-1]))
                        context.insert_line('if (u == NULL) {')
                        context.insert_line('Py_DECREF(x);')
                        context.insert_line('Py_DECREF(w);')
                        context.insert_handle_error(line, label)
                        context.insert_line('}')
                        context.insert_line('PyObject_SetAttr(x, %s, u);' %
                                            context.register_const(tail))
                        context.insert_line('Py_DECREF(x);')
                        context.insert_line('x = u;')

                    if store_tail:
                        context.insert_line('Py_DECREF(w);')

                    else:
                        context.insert_line('Py_DECREF(x);')
                        context.insert_line('x = w;')

                    import_handled = True

            if not import_handled:
                context.insert_line('x = __pypperoni_IMPL_import((uint64_t)%dU);'
                                    ' /* %s */' % (mod.get_id(), mod.name))
                context.insert_line('if (x == NULL) {')
                context.insert_handle_error(line, label)
                context.insert_line('}')

            context.insert_line('PUSH(x);')

            # Let __handle_one_instr handle STORE_*

        elif fromlist == ('*',):
            # Case 2: Import all
            context.insert_line('x = __pypperoni_IMPL_import((uint64_t)%dU);'
                                ' /* %s */' % (mod.get_id(), mod.name))
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
            context.insert_line('mod = __pypperoni_IMPL_import((uint64_t)%dU);'
                                ' /* %s */' % (mod.get_id(), mod.name))
            context.insert_line('if (mod == NULL) {')
            context.insert_handle_error(line, label)
            context.insert_line('}')

            for i in range(len(fromlist)):
                label, op, oparg, line = context.buf[context.i]
                context.i += 1

                name = codeobj.co_names[oparg]
                fullname = mod.name + '.' + name
                fullname = self.__lookup_import(fullname, context.modules,
                                                can_be_external=False)
                if fullname in context.modules:
                    # We're either importing a name or a module
                    _mod = context.modules[fullname]
                    context.insert_line('v = __pypperoni_IMPL_import_from_or_module'
                                        '(mod, %s, (uint64_t)%dU); /* %s */' %
                                        (context.register_const(name), _mod.get_id(), _mod.name))

                else:
                    # IMPORT_FROM
                    context.insert_line('v = __pypperoni_IMPL_import_from(mod, %s);' %
                                        context.register_literal(name))

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

    def __convert_relative_import(self, name, level):
        '''
        Converts relative to absolute imports.
        '''
        if level > 0:
            if self.is_package():
                level -= 1

            if self.name.count('.') < (level - 1):
                raise ImportError('bogus relative import: %s %s (%d)' % (self.name, name, level))

            prefix = self.name.rsplit('.', level)[0]
            if name:
                # from [...]name import <etc>
                name = prefix + '.' + name

            else:
                # from [...] import <etc>
                name = prefix

        return name

    def resolve_import_from_name(self, modules, name, level=0, can_be_external=True):
        '''
        Resolves a module from name and level. This returns None
        if the module doesn't exist.
        '''
        name = self.__convert_relative_import(name, level)
        name = self.__lookup_import(name, modules, can_be_external)
        if not name:
            return None

        return modules[name]

    def resolve_imports_from_node(self, modules, node):
        '''
        Yields a list of module parsed from an AST node.
        'node' must be of type Import or ImportFrom.
        '''
        if isinstance(node, ast.ImportFrom):
            module = self.__convert_relative_import(node.module, node.level)
            mod = self.resolve_import_from_name(modules, module)
            yield mod

            for alias in node.names:
                name = module + '.' + alias.name
                mod = self.resolve_import_from_name(modules, name, can_be_external=False)
                if mod:
                    yield mod

        else:
            for alias in node.names:
                mod = self.resolve_import_from_name(modules, alias.name)
                yield mod

    def __lookup_import(self, name, modules, can_be_external=True):
        '''
        Lookups modules dict to find a module by name.
        This will either return a name that is guaranteed
        to exist in modules or None. If can_be_external is
        True, it will register a builtin or external module
        as required (in which case it will never return None).
        '''
        if name in IMPORT_ALIASES:
            name = IMPORT_ALIASES[name]

        # Usually, it's in modules
        if name in modules:
            return name

        # Builtin?
        if can_be_external:
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


class PackageModule(Module):
    '''
    Use this for modules that were originally __init__.py files.
    '''
    def is_package(self):
        return True


class NullModule(Module):
    '''
    Use this for empty modules.
    '''

    def __init__(self, name):
        Module.__init__(self, name, '')


class ExternalModule(ModuleBase):
    '''
    This is used to represent a module that could not be found
    at compile time (e.g. nt doesn't exist on Unix systems).
    '''
    def __init__(self, name):
        ModuleBase.__init__(self, name, '')

    def is_external(self):
        return True


class BuiltinModule(ExternalModule):
    '''
    This is used to represent a builtin module.
    '''
    pass


def write_modules_file(f, modules):
    s = '  PypperoniModule* m;\n'
    for i, module in enumerate(modules.values()):
        is_ext = module.is_external()
        parent = module.get_parent(modules)

        s += '\n'
        s += '  m = malloc(sizeof(PypperoniModule));\n'
        s += '  m->index = %dL;\n' % module.get_id()
        s += '  m->type = %s;\n' % ('MODULE_BUILTIN' if is_ext else 'MODULE_DEFINED')
        s += '  m->parent = %dL;\n' % (parent.get_id() if parent else -1)
        s += '  m->name = "%s";\n' % module.name

        if is_ext:
            s += '  m->stacksize = 0;\n'
            s += '  m->nlocals = 0;\n'

        else:
            modname = '_%s_MODULE__' % module.name.replace('.', '_')
            f.write('PyObject* %s(PyFrameObject* f); /* fwd decl */\n' % modname)
            s += '  m->ptr = %s;\n' % modname
            s += '  m->stacksize = %d;\n' % module.code.co_stacksize
            s += '  m->nlocals = %d;\n' % module.code.co_nlocals

        s += '  m->obj = NULL;\n'
        s += '  modlist[%d] = m;\n' % i

    s += '  modlist[%d] = NULL;' % len(modules)

    f.write('\nstatic void get_pypperoni_modules(PypperoniModule*** modlist_ptr)\n')
    f.write('{\n')
    f.write('  static int loaded = 0;\n')
    f.write('  static PypperoniModule *modlist[%d];\n' % (len(modules) + 1))
    f.write('  *modlist_ptr = modlist;\n')
    f.write('  if (loaded) return;\n')
    f.write('  loaded = 1;\n')
    f.write(s)
    f.write('}\n')

    f.write('\nstatic PyObject* load_encodings(void)\n')
    f.write('{\n')
    f.write('  PyObject *encodings_mod, *_io_mod, *codecs_index_mod;')
    f.write('  encodings_mod = __pypperoni_IMPL_import(%d);\n' % modules['encodings'].get_id())
    f.write('  if (!encodings_mod) goto error;\n')
    f.write('  _io_mod = PyImport_ImportModule("_io");\n')
    f.write('  if (!_io_mod) goto error;\n')
    f.write('  _PyImport_FixupBuiltin(_io_mod, "_io");\n')
    f.write('  codecs_index_mod =  __pypperoni_IMPL_import(%d);\n' % modules['codecs_index'].get_id())
    f.write('  if (!codecs_index_mod) goto error;\n')
    f.write('  return encodings_mod;\n')
    f.write('error:\n')
    f.write('  PyErr_Print();\n')
    f.write('  return NULL;\n')
    f.write('}\n')

    f.write('\n')
