// Copyright (c) Pypperoni
//
// Pypperoni is licensed under the MIT License; you may
// not use it except in compliance with the License.
//
// You should have received a copy of the License with
// this source code under the name "LICENSE.txt". However,
// you may obtain a copy of the License on our GitHub here:
// https://github.com/Pypperoni/pypperoni
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
// either express or implied. See the License for the specific
// language governing permissions and limitations under the
// License.

#include "pypperoni_impl.h"

int main(int argc, char* argv[])
{
    Py_IgnoreEnvironmentFlag++;
    Py_NoSiteFlag++;
    Py_FrozenFlag++;

    Py_SetProgramName(argv[0]);
    Py_Initialize();
    PyEval_InitThreads();
    PySys_SetArgv(argc, argv);

    setup_pypperoni();

    if (__pypperoni_IMPL_main() != 0)
    {
        if (PyErr_Occurred() && !PyErr_ExceptionMatches(PyExc_SystemExit))
            PypperoniTraceback_Print();
    }

    return 0;
}
