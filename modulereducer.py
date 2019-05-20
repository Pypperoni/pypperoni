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

from collections import defaultdict
import ast

TAG_UNSET = object()


class ModuleGraph:
    def __init__(self):
        self.connections = defaultdict(lambda: set())
        self.tags = defaultdict(lambda: TAG_UNSET)

    def add_connection(self, a, b):
        # a imports b
        if a is not b:
            self.connections[a.name].add(b)

    def dfs(self, v, tag, level=0):
        self.tags[v] = tag
        for v in self.connections[v]:
            if self.tags[v.name] is TAG_UNSET:
                self.dfs(v.name, tag, level + 1)

    def dfs_all(self, modules, tag):
        for name, m in modules.items():
            if self.tags[name] is TAG_UNSET:
                self.dfs(name, tag)

    def get_tag(self, key):
        return self.tags[key]


class ModuleFinderVisitor(ast.NodeVisitor):
    def __init__(self, graph, modules):
        self.graph = graph
        self.modules = modules

    def visit_Import(self, node):
        modlist = self._module.resolve_imports_from_node(self.modules, node)
        for m in modlist:
            self.graph.add_connection(self._module, m)

    def visit_ImportFrom(self, node):
        self.visit_Import(node)

    def visit_module(self, module):
        self._module = module
        self.visit(module.astmod)
        del self._module


def reduce_modules(modules):
    graph = ModuleGraph()
    v = ModuleFinderVisitor(graph, modules)

    modlist = list(modules.values()) # dict size may change
    for m in modlist:
        v.visit_module(m)

    # DFS main module
    for m in modlist:
        if m._is_main:
            graph.dfs(m.name, True)

    # DFS required modules
    graph.dfs('codecs_index', True)
    graph.dfs_all(modules, False)

    modlist = list(modules.items())
    for name, m in modlist:
        if not graph.get_tag(name):
            del modules[name]
