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

from pypperoni import config

from threading import Lock
from opcode import HAVE_ARGUMENT, EXTENDED_ARG, opmap
import types
import dis

NOP = opmap['NOP']


class MutableCodeObject:
    MAX_STACKSIZE = 0
    MAX_NCELLS = 0
    MAX_NLOCALS = 0

    def __init__(self, code):
        for attr in dir(code):
            if attr.startswith('co_'):
                v = getattr(code, attr)
                if type(v) == tuple:
                    v = list(self.__recurse_tuple(v, self))

                setattr(self, attr, v)

        self.parent = None

        self.co_privname = self.co_name

        with Lock():
            MutableCodeObject.MAX_STACKSIZE = max(MutableCodeObject.MAX_STACKSIZE,
                                                  self.co_stacksize)
            MutableCodeObject.MAX_NCELLS = max(MutableCodeObject.MAX_NCELLS,
                                                len(self.co_freevars) +
                                                len(self.co_cellvars))
            MutableCodeObject.MAX_NLOCALS = max(MutableCodeObject.MAX_NLOCALS,
                                                self.co_nlocals)

    def __recurse_tuple(self, v, parent):
        r = []
        for x in v:
            if type(x) == types.CodeType:
                x = MutableCodeObject(x)
                x.parent = parent

            elif type(x) == tuple:
                x = self.__recurse_tuple(x, parent)

            r.append(x)

        return type(v)(r)

    def __recurse_list(self, v):
        r = []
        for x in v:
            if isinstance(x, self.__class__):
                x = x.get_code_obj()

            elif type(x) == tuple:
                x = self.__recurse_list(x)

            r.append(x)

        return type(v)(r)

    def get_full_name(self):
        parts = [self.co_name]
        parent = self.parent
        while parent:
            if parent.co_privname != '<module>':
                parts.append(parent.co_name)

            parent = parent.parent

        return '.'.join(parts[::-1])

    def get_signature(self, label):
        sig = self.get_full_name()
        sig += '_%d_%d_%d' % (len(self.co_code), self.co_stacksize, label)
        return sig

    def get_code_obj(self):
        args = map(lambda x: getattr(self, 'co_' + x),
                                       ('argcount', 'nlocals', 'stacksize',
                                       'flags', 'code', 'consts', 'names',
                                       'varnames', 'filename', 'name',
                                       'firstlineno', 'lnotab', 'freevars',
                                       'cellvars'))
        args = [x if type(x) != list else tuple(self.__recurse_list(x))
                for x in args]
        return types.CodeType(*args)

    def read_code(self):
        extended_arg = 0
        code = self.co_code
        n = len(code)
        i = 0
        label = 0
        lbuffer = []
        line = 0
        linestarts = dict(dis.findlinestarts(self))

        while i < n:
            if i in linestarts:
                line = linestarts[i]

            op = ord(code[i])
            i += 1
            oparg = None
            if op >= HAVE_ARGUMENT:
                oparg = ord(code[i]) + ord(code[i + 1]) * 256 + extended_arg
                extended_arg = 0
                i += 2
                if op == EXTENDED_ARG:
                    extended_arg = oparg * 65536

            if op != EXTENDED_ARG:
                yield (label, op, oparg, line)

            else:
                # Yield a NOP just in case there's a jump to this label
                yield (label, NOP, None, line)

            label += 1
            if op >= HAVE_ARGUMENT:
                label += 2


def write_frames_file(f):
    extra = config.EXTRA_STACK_SIZE
    f.write('#define MAX_STACKSIZE %d\n' % (MutableCodeObject.MAX_STACKSIZE + extra))
    f.write('#define MAX_NCELLS %d\n' % (MutableCodeObject.MAX_NCELLS + 1))
    f.write('#define MAX_NLOCALS %d\n' % (MutableCodeObject.MAX_NLOCALS + 1))
