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

from threading import Lock
import sys


CO_OPTIMIZED = 0x0001
CO_NEWLOCALS = 0x0002
CO_VARARGS = 0x0004
CO_VARKEYWORDS = 0x0008
CO_NESTED = 0x0010
CO_GENERATOR = 0x0020
CO_NOFREE = 0x0040
CO_COROUTINE = 0x0080
CO_ITERABLE_COROUTINE = 0x0100
CO_ASYNC_GENERATOR = 0x0200

def safePrint(string):
    with Lock():
        sys.stdout.write('%s\n' % string)
        sys.stdout.flush()

def safeRepr(obj):
    r = repr(obj)
    r = r.replace('\n', '\\n')
    r = r.replace('\r', '\\r')
    r = r.replace('\t', '\\t')
    r = r.replace('*', '')
    r = r[:40]
    return r.rstrip('\\')
