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

from cStringIO import StringIO
import os


class ConditionalFile:
    def __init__(self, filename, hashfunc):
        self.filename = filename
        self.hashfunc = hashfunc

        self._buf = StringIO()

    def write(self, data):
        self._buf.write(data)

    def read(self):
        return self._buf.read()

    def seek(self, *args):
        self._buf.seek(*args)

    def tell(self):
        return self._buf.tell()

    def close(self):
        self._buf.seek(0)
        newhash = self.hashfunc(self._buf)
        if not os.path.isfile(self.filename):
            self.__write()
            return (self.filename, newhash, False)

        f = open(self.filename, 'rb')
        oldhash = self.hashfunc(f)
        self.seek(0)
        f.close()

        modified = oldhash != newhash
        if modified:
            self.__write()

        return (self.filename, newhash, modified)

    def __write(self):
        self.seek(0)
        f = open(self.filename, 'wb')
        f.write(self._buf.read())
        f.close()


class FileContainer:
    def __init__(self, prefix, hashfunc):
        self.prefix = prefix
        self.hashfunc = hashfunc

        self.uid = os.path.basename(prefix).replace('.', '_')

        self.headers = ['#include "pypperoni_impl.h"']
        self.files = []
        self.filenames = []
        self.__next()

    def __next(self):
        self.filenames.append('%s_%d.c' % (self.prefix, len(self.filenames) + 1))
        f = ConditionalFile(self.filenames[-1], self.hashfunc)
        self.files.append(f)

    def write(self, *args):
        self.files[-1].write(*args)

    def consider_next(self):
        if self.files[-1].tell() > config.MAX_FILE_SIZE:
            self.__next()

    def add_common_header(self, header):
        self.headers.append(header)

    def close(self):
        for fname, f in zip(self.filenames, self.files):
            f.seek(0)
            data = f.read()
            f.seek(0)

            for header in self.headers:
                f.write(header + '\n')

            f.write('\n')
            f.write(data)
            yield f.close()
