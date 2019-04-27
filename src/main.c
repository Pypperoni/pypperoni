/* Copyright (c) Pypperoni

   Pypperoni is licensed under the MIT License; you may
   not use it except in compliance with the License.

   You should have received a copy of the License with
   this source code under the name "LICENSE.txt". However,
   you may obtain a copy of the License on our GitHub here:
   https://github.com/Pypperoni/pypperoni

   Unless required by applicable law or agreed to in writing,
   software distributed under the License is distributed on an
   "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
   either express or implied. See the License for the specific
   language governing permissions and limitations under the
   License.
*/

#include "pypperoni_impl.h"

int main(int argc, char* argv[])
{
    int ret;

    setup_pypperoni();
    ret = __pypperoni_IMPL_main();
    if (ret != 0)
    {
        PyErr_Print();
    }

    return ret;
}
