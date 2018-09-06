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

from pypperoni.util import *

from cStringIO import StringIO
import marshal


class Context:
    def __init__(self, file, name, modules, flags=0):
        self.file = file
        self.name = name
        self.modules = modules
        self.flags = flags

        self.indent = 2
        self.__indentstr = '  '

        self.codeobjs = []
        self.try_blocks = []
        self.exc_blocks = 0
        self.loop_blocks = []
        self.finally_blocks = []
        self.labels = []

        self.stack_level_blocks = []

        self.buf = []
        self.i = 0

        self.codebuffer = StringIO()
        self.__decls = [
            # (type, name, default value, deref)
            ('err', 'Py_ssize_t', '0', False),
            ('retval', 'PyObject*', 'NULL', False),
            ('tmp', 'PyObject*', 'NULL', False),
            ('u', 'PyObject*', 'NULL', False),
            ('v', 'PyObject*', 'NULL', False),
            ('w', 'PyObject*', 'NULL', False),
            ('x', 'PyObject*', 'NULL', False),
            ('tb', 'PyObject*', 'NULL', True),
            ('val', 'PyObject*', 'NULL', True),
            ('exc', 'PyObject*', 'NULL', True)
        ]

        self._consts = []

    def finish(self):
        self.insert_line('f->f_exci = -1;')
        self.insert_line('goto end;')
        self.insert_line('error:')
        self.insert_line('  retval = NULL;')

        self.labels.append('end')
        self.insert_line('end:')
        for d in self.__decls:
            if d[3]:
                self.insert_line('  Py_XDECREF(%s);' % d[0])

        self.insert_line('f->f_stacktop = stack_pointer;')
        self.insert_line('f->f_lasti = -2;')
        self.insert_line('return retval;')

        self.file.add_common_header('PyObject* %s(PypperoniFrame* f);' % self.name)
        self.file.write('PyObject* %s(PypperoniFrame* f) {\n' % self.name)
        for d in self.__decls:
            if d[2] is not None:
                self.file.write('  %s %s = %s;\n' % (d[1], d[0], d[2]))

            else:
                self.file.write('  %s %s;\n' % (d[1], d[0]))

        self.file.write('  register PyObject** stack_pointer = f->f_stacktop;\n')

        if self.flags & CO_GENERATOR:
            for i in xrange(len(self.labels) - 1):
                _this = int(self.labels[i])
                _next = self.labels[i + 1]
                if _next != 'end':
                    _next = 'label_%d' % _next

                self.file.write('  if (f->f_lasti == %d) '
                                'goto %s;\n' % (_this, _next))

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

    def insert_handle_error(self, line, label):
        self.insert_line('f->f_exci = %d;' % label)
        self.insert_line('f->f_excline = %d;' % line)
        if self.try_blocks:
            self.insert_line('goto label_%d;' % self.try_blocks[-1])

        else:
            self.insert_line('goto error;')

    def add_decl(self, name, type='PyObject*', val='NULL', deref=True):
        self.__decls.append((name, type, val, deref))

    def add_decl_once(self, name, type='PyObject*', val='NULL', deref=True):
        for n, _, _, _ in self.__decls:
            if n == name:
                return

        self.__decls.append((name, type, val, deref))

    def setup_stack_block(self, label):
        self.stack_level_blocks.append(label)
        self.insert_line('PyDict_SetItem(f->f_stacklevel, __pypperoni_pyint(%d), '
                         '__pypperoni_pyint(STACK_LEVEL()));' % label)

    def pop_stack_block(self):
        label = self.stack_level_blocks.pop()
        self.insert_restore_stack_label(label)

    def insert_restore_stack_label(self, label):
        levelstr = 'PyInt_AS_LONG(PyDict_GetItem(f->f_stacklevel, __pypperoni_pyint(%d)))' % label
        self.insert_restore_stack(levelstr)

    def insert_restore_stack(self, levelstr):
        self.insert_line('while (STACK_LEVEL() > %s)' % levelstr)
        self.begin_block()
        self.insert_line('v = POP();')
        self.insert_line('Py_DECREF(v);')
        self.end_block()

    def insert_label(self, label):
        self.insert_line('label_%d:' % label)
        self.labels.append(label)

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
            self.file.write('%d, ' % ord(c))
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
