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

from .util import *

from io import StringIO
import marshal


class Context:
    def __init__(self, file, name, modules, flags, nlocals):
        self.file = file
        self.name = name
        self.modules = modules
        self.flags = flags
        self.nlocals = nlocals

        self.indent = 2
        self.__indentstr = '  '

        self.codeobjs = []
        self.yield_labels = []

        self.buf = []
        self.i = 0

        self.codebuffer = StringIO()
        self.__decls = [
            # (type, name, default value, deref)
            ('err', 'int', '0', False),
            ('_jmpto', 'void*', 'NULL', False),
            ('retval', 'PyObject*', 'NULL', False),
            ('tmp', 'PyObject*', 'NULL', False),
            ('u', 'PyObject*', 'NULL', False),
            ('v', 'PyObject*', 'NULL', False),
            ('w', 'PyObject*', 'NULL', False),
            ('x', 'PyObject*', 'NULL', False),
            ('exc', 'PyObject*', 'NULL', False),
            ('tb', 'PyObject*', 'NULL', False),
            ('val', 'PyObject*', 'NULL', False),
        ]

        self._consts = []

    def finish(self):
        self.insert_line('goto end;')
        self.insert_line('error:')
        self.insert_line('  *why = WHY_EXCEPTION;')
        self.insert_line('  retval = NULL;')

        self.insert_line('fast_block_end:')
        self.insert_line('while (*why != WHY_NOT && f->f_iblock > 0)')
        self.begin_block()

        self.insert_line('PyTryBlock *b = &f->f_blockstack[f->f_iblock - 1];')
        self.insert_line('if (b->b_type == SETUP_LOOP && *why == WHY_CONTINUE)')
        self.begin_block()
        self.insert_line('*why = WHY_NOT;')
        self.insert_line('_jmpto = (void*)(PyLong_AS_LONG(retval));')
        self.insert_line('Py_DECREF(retval);')
        self.insert_line('JUMP_TO_ADDR(_jmpto);')
        self.end_block()

        self.insert_line('f->f_iblock--;')
        self.insert_line('if (b->b_type == EXCEPT_HANDLER)')
        self.begin_block()
        self.insert_line('UNWIND_EXCEPT_HANDLER(b);')
        self.insert_line('continue;')
        self.end_block()

        self.insert_line('UNWIND_BLOCK(b);')
        self.insert_line('if (b->b_type == SETUP_LOOP && *why == WHY_BREAK)')
        self.begin_block()
        self.insert_line('*why = WHY_NOT;')
        self.insert_line('JUMP_TO_ADDR(b->b_handler);')
        self.end_block()

        self.insert_line('if (*why == WHY_EXCEPTION && (b->b_type == SETUP_EXCEPT || b->b_type == SETUP_FINALLY))')
        self.begin_block()
        self.insert_line('PyObject *exc, *val, *tb;')
        self.insert_line('_jmpto = b->b_handler;')
        self.insert_line('PyFrame_BlockSetup(f, EXCEPT_HANDLER, NULL, STACK_LEVEL());')
        self.insert_line('PUSH(tstate->exc_traceback);')
        self.insert_line('PUSH(tstate->exc_value);')
        self.insert_line('if (tstate->exc_type != NULL) {PUSH(tstate->exc_type);}')
        self.insert_line('else {Py_INCREF(Py_None); PUSH(Py_None);}')
        self.insert_line('PyErr_Fetch(&exc, &val, &tb);')
        self.insert_line('PyErr_NormalizeException(&exc, &val, &tb);')
        self.insert_line('if (tb != NULL) PyException_SetTraceback(val, tb);')
        self.insert_line('else PyException_SetTraceback(val, Py_None);')
        self.insert_line('Py_INCREF(exc);')
        self.insert_line('tstate->exc_type = exc;')
        self.insert_line('Py_INCREF(val);')
        self.insert_line('tstate->exc_value = val;')
        self.insert_line('tstate->exc_traceback = tb;')
        self.insert_line('if (tb == NULL) tb = Py_None;')
        self.insert_line('Py_INCREF(tb);')
        self.insert_line('PUSH(tb); PUSH(val); PUSH(exc);')
        self.insert_line('*why = WHY_NOT;')
        self.insert_line('JUMP_TO_ADDR(_jmpto);')
        self.end_block()

        self.insert_line('if (b->b_type == SETUP_FINALLY)')
        self.begin_block()
        self.insert_line('if (*why & (WHY_RETURN | WHY_CONTINUE)) PUSH(retval);')
        self.insert_line('PUSH(PyLong_FromLong((long)*why));')
        self.insert_line('*why = WHY_NOT;')
        self.insert_line('JUMP_TO_ADDR(b->b_handler);')
        self.end_block()

        self.end_block()

        self.insert_line('end:')
        for d in self.__decls:
            if d[3]:
                self.insert_line('  Py_XDECREF(%s);' % d[0])

        self.insert_line('f->f_stacktop = stack_pointer;')
        self.insert_line('return retval;')

        self.file.add_common_header('PyObject* %s(PyFrameObject* f, int* why);' % self.name)
        self.file.write('PyObject* %s(PyFrameObject* f, int* why) {\n' % self.name)
        for d in self.__decls:
            if d[2] is not None:
                self.file.write('  %s %s = %s;\n' % (d[1], d[0], d[2]))

            else:
                self.file.write('  %s %s;\n' % (d[1], d[0]))

        self.file.write('  PyThreadState *tstate = PyThreadState_GET();\n')
        self.file.write('  PyObject **stack_pointer = f->f_stacktop;\n')
        self.file.write('  PyObject **fastlocals = f->f_localsplus;\n')
        self.file.write('  PyObject **freevars = f->f_localsplus + %d;\n' % self.nlocals)
        self.file.write('  *why = WHY_NOT;\n')

        if self.flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR):
            self.file.write('  if (PyErr_Occurred()) goto error; /* generator.throw() */\n')
            self.file.write('  f->f_lineno = 0;')
            self.file.write('  switch (f->f_lasti) {\n')
            for l in self.yield_labels:
                self.file.write('    case %d: goto label_%d; break;\n' % (l, l))
            self.file.write('    default: break;\n')
            self.file.write('  }\n')

        else:
            self.file.write('  assert(!PyErr_Occurred());\n')

        self.codebuffer.seek(0)
        self.file.write(self.codebuffer.read() + '}\n')
        self.file.consider_next()

    def flushconsts(self):
        self.flushconsts()

    def begin_block(self):
        self.insert_line('{')
        self.indent += 2
        self.__indentstr += '  '

    def end_block(self):
        self.indent -= 2
        self.__indentstr = self.__indentstr[:-2]
        self.insert_line('}')

    def insert_line(self, line):
        self.codebuffer.write(self.__indentstr)
        self.codebuffer.write(line)
        self.codebuffer.write('\n')

    def insert_yield(self, line, label):
        self.yield_labels.append(label)
        self.insert_line('*why = WHY_YIELD;')
        self.insert_line('f->f_lasti = %d;' % label)
        self.insert_line('f->f_lineno = %d; /* in case of throw() */' % line)
        self.insert_line('goto end;')

    def insert_handle_error(self, line, label):
        self.insert_line('f->f_lineno = %d;' % line)
        self.insert_line('goto error;')

    def add_decl(self, name, type='PyObject*', val='NULL', deref=True):
        self.__decls.append((name, type, val, deref))

    def add_decl_once(self, name, type='PyObject*', val='NULL', deref=True):
        for n, _, _, _ in self.__decls:
            if n == name:
                return

        self.__decls.append((name, type, val, deref))

    def insert_label(self, label):
        self.insert_line('label_%d:' % label)

    def register_const(self, value):
        with Lock():
            self._consts.append(value)
            ret = '__%s_get_const(%d)' % (self.file.uid, len(self._consts) - 1)

        return ret

    def register_literal(self, value):
        getter = self.register_const(value)
        return '__pypperoni_const2str(%s) /* %s */' % (getter, value)

    def dumpconsts(self):
        return marshal.dumps(tuple(self._consts))

    def flushconsts(self):
        blob = self.dumpconsts()
        blobsize = len(blob)
        blobptr = '__data_blob_%s' % self.name

        self.file.write('const char %s[%d] = {\n  ' % (blobptr, blobsize))

        i = 0
        for c in blob:
            self.file.write('%d, ' % c)
            i += 1
            if not i % 16:
                self.file.write('\n  ')

        self.file.write('};\n\n')
        self.file.add_common_header('PyObject* __%s_get_const(Py_ssize_t index);\n' % self.file.uid)
        self.file.write('PyObject* __%s_get_const(Py_ssize_t index) {\n' % self.file.uid)
        self.file.write('  PyObject* it;\n')
        self.file.write('  static PyObject* page = NULL;\n')
        self.file.write('  if (page == NULL) {\n')
        self.file.write('     page = PyMarshal_ReadObjectFromString((char*)%s, %d);\n' % (blobptr, blobsize))
        self.file.write('  }\n')
        self.file.write('  it = PyTuple_GET_ITEM(page, index);\n')
        self.file.write('  Py_INCREF(it);\n')
        self.file.write('  return it;\n')
        self.file.write('}\n\n')
