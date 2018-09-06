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

#pragma once

#include <Python.h>
#include <marshal.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct _pypperoni_frame {
    struct _pypperoni_frame* f_back;

    PyObject* f_builtins;   /* builtin symbol table (PyDictObject) */
    PyObject* f_globals;    /* global symbol table (PyDictObject) */
    PyObject* f_locals;     /* local symbol table (any mapping) */
    PyObject** f_stackptr;
    PyObject** f_stacktop;

    PyObject* f_stacklevel; /* stack level dict {label: level} */

    int f_lasti;                /* Last instruction if called */
    int f_exci;                 /* Where the exception occurred (instruction) */
    int f_excline;              /* Where the exception occurred (line number) */
    PyObject** f_fastlocals;    /* fast locals */
    PyObject** f_cells;         /* cells */

    int f_stacksize, f_numcells, f_numfast;
    int f_depth;
} PypperoniFrame;

typedef struct _pypperoni_module {
    Py_ssize_t index;
    int type;
    Py_ssize_t parent;
    void* ptr;
    const char* name;
    int val_1;
    int val_2;
    int val_3;
    PyObject* obj;
} PypperoniModule;

void PypperoniTraceback_AddFrame(const char* name, PypperoniFrame* f);
void PypperoniTraceback_Clear();
void PypperoniTraceback_Print();

#define STACK_LEVEL()     ((int)(stack_pointer - f->f_stackptr))
#define TOP()             (stack_pointer[-1])
#define SECOND()          (stack_pointer[-2])
#define THIRD()           (stack_pointer[-3])
#define FOURTH()          (stack_pointer[-4])
#define PEEK(n)           (stack_pointer[-(n)])
#define SET_TOP(v)        (stack_pointer[-1] = (v))
#define SET_SECOND(v)     (stack_pointer[-2] = (v))
#define SET_THIRD(v)      (stack_pointer[-3] = (v))
#define SET_FOURTH(v)     (stack_pointer[-4] = (v))
#define STACKADJ(n)       (stack_pointer += n)
#define PUSH(v)           (*stack_pointer++ = (v))
#define POP()             (*--stack_pointer)

const char* __pypperoni_const2str(PyObject* strobj);

PyObject* __pypperoni_IMPL_load_name(PypperoniFrame* f, PyObject* name);
PyObject* __pypperoni_IMPL_load_global(PypperoniFrame* f, PyObject* name);
PyObject* __pypperoni_IMPL_load_deref(PypperoniFrame* f, Py_ssize_t index);
PyObject* __pypperoni_IMPL_load_closure(PypperoniFrame* f, Py_ssize_t index);

Py_ssize_t __pypperoni_IMPL_store_name(PypperoniFrame* f, PyObject* name, PyObject* obj);
Py_ssize_t __pypperoni_IMPL_store_global(PypperoniFrame* f, PyObject* name, PyObject* obj);
Py_ssize_t __pypperoni_IMPL_store_deref(PypperoniFrame* f, PyObject* obj,
                                    Py_ssize_t index);

PyObject* __pypperoni_IMPL_import(Py_ssize_t index);
PyObject* __pypperoni_IMPL_import_from(PyObject* mod, const char* name);
PyObject* __pypperoni_IMPL_import_from_or_module(PyObject* mod, PyObject* name, Py_ssize_t index);

Py_ssize_t __pypperoni_IMPL_import_star(PypperoniFrame* f, PyObject* mod);

Py_ssize_t __pypperoni_IMPL_do_print(PyObject* stream, PyObject* obj);

Py_ssize_t __pypperoni_IMPL_make_func(void* ptr, PyObject** result,
                                  PyObject* func_defaults,
                                  PyObject* closure,
                                  PyObject* globals,
                                  PyObject* name,
                                  PyObject* varnames,
                                  PyObject* cellvars,
                                  int func_flags,
                                  int func_argcount,
                                  int func_stacksize,
                                  int func_numcells,
                                  int func_numfast);
Py_ssize_t __pypperoni_IMPL_call_func(PyObject* func, PyObject** result,
                                   PyObject* pargs, PyObject* kwargs);
Py_ssize_t __pypperoni_IMPL_check_cond(PyObject* obj, int* result);

Py_ssize_t __pypperoni_IMPL_compare(PyObject* w, PyObject* v, Py_ssize_t op, PyObject** result);
Py_ssize_t __pypperoni_IMPL_for_iter(PyObject* v, PyObject** result);
Py_ssize_t __pypperoni_IMPL_build_class(PyObject* methods, PyObject* bases, PyObject* classname, PyObject** result);
Py_ssize_t __pypperoni_IMPL_unpack_sequence(PyObject* v, PyObject** array, Py_ssize_t num);
Py_ssize_t __pypperoni_IMPL_apply_slice(PyObject* u, PyObject* v, PyObject* w, PyObject** result);
Py_ssize_t __pypperoni_IMPL_assign_slice(PyObject* u, PyObject* v, PyObject* w, PyObject* x);
void __pypperoni_IMPL_do_raise(PyObject* type, PyObject* value, PyObject* tb);
void __pypperoni_IMPL_raise(PyObject* exc, const char* msg);
Py_ssize_t __pypperoni_IMPL_delete_name(PypperoniFrame* f, PyObject* name);
Py_ssize_t __pypperoni_IMPL_setup_with(PyObject* v, PyObject** exitptr, PyObject** result);
Py_ssize_t __pypperoni_IMPL_exit_with(PyObject* v);

Py_ssize_t __pypperoni_IMPL_binary_power(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_multiply(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_divide(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_modulo(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_add(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_subtract(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_subscr(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_floor_divide(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_true_divide(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_lshift(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_rshift(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_and(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_xor(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_binary_or(PyObject* v, PyObject* w, PyObject** x);

Py_ssize_t __pypperoni_IMPL_inplace_floor_divide(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_true_divide(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_add(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_subtract(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_multiply(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_divide(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_modulo(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_power(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_lshift(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_rshift(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_and(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_xor(PyObject* v, PyObject* w, PyObject** x);
Py_ssize_t __pypperoni_IMPL_inplace_or(PyObject* v, PyObject* w, PyObject** x);

Py_ssize_t __pypperoni_IMPL_unary_positive(PyObject* v, PyObject** x);
Py_ssize_t __pypperoni_IMPL_unary_negative(PyObject* v, PyObject** x);
Py_ssize_t __pypperoni_IMPL_unary_not(PyObject* v, PyObject** x);
Py_ssize_t __pypperoni_IMPL_unary_convert(PyObject* v, PyObject** x);
Py_ssize_t __pypperoni_IMPL_unary_invert(PyObject* v, PyObject** x);

PyObject* __pypperoni_pyint(long value);

void setup_pypperoni();
int __pypperoni_IMPL_main();

#ifdef __cplusplus
}
#endif
