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

from . import config

from threading import Lock
from opcode import HAVE_ARGUMENT, EXTENDED_ARG, opmap
import dis

NOP = opmap['NOP']


class CodeObject:
    def __init__(self, code):
        for attr in dir(code):
            if attr.startswith('co_'):
                v = getattr(code, attr)
                setattr(self, attr, v)

        self.co_path = ''

    def get_full_name(self):
        return '%s.%s' % (self.co_path, self.co_name)

    def get_signature(self, label):
        sig = self.get_full_name()
        sig += '_%d_%d_%d' % (len(self.co_code), self.co_stacksize, label)
        return sig

    def read_code(self):
        code = self.co_code
        extended_arg = 0
        line = self.co_firstlineno
        linestarts = dict(dis.findlinestarts(self))

        for i in range(0, len(code), 2):
            if i in linestarts:
                line = linestarts[i]

            op = code[i]
            if op >= HAVE_ARGUMENT:
                oparg = code[i + 1] | extended_arg
                extended_arg = (oparg << 8) if op == EXTENDED_ARG else 0
            else:
                oparg = None

            if op != EXTENDED_ARG:
                yield (i, op, oparg, line)
