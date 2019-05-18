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

#pragma once

#include <Python.h>
#include <frameobject.h>
#include <opcode.h>
#include <marshal.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct _pypperoni_module {
    int64_t index;
    int type;
    int parent;
    PyObject*(*ptr)(PyFrameObject*);
    const char* name;
    int stacksize;
    int nlocals;
    PyObject* obj;
} PypperoniModule;

#define STACK_LEVEL()     ((int)(stack_pointer - f->f_stacktop))
#define TOP()             (stack_pointer[-1])
#define SECOND()          (stack_pointer[-2])
#define THIRD()           (stack_pointer[-3])
#define FOURTH()          (stack_pointer[-4])
#define PEEK(n)           (stack_pointer[-(n)])
#define SET_TOP(v)        (stack_pointer[-1] = (v))
#define SET_SECOND(v)     (stack_pointer[-2] = (v))
#define SET_THIRD(v)      (stack_pointer[-3] = (v))
#define SET_FOURTH(v)     (stack_pointer[-4] = (v))
#define SET_VALUE(n, v)   (stack_pointer[-(n)] = (v))
#define STACKADJ(n)       (stack_pointer += n)
#define PUSH(v)           (*stack_pointer++ = (v))
#define POP()             (*--stack_pointer)

#define UNWIND_BLOCK(b) \
    while (STACK_LEVEL() > (b)->b_level) { \
        PyObject *v = POP(); \
        Py_XDECREF(v); \
    }

#define UNWIND_EXCEPT_HANDLER(b) \
    do { \
        PyObject *type, *value, *traceback; \
        assert(STACK_LEVEL() >= (b)->b_level + 3); \
        while (STACK_LEVEL() > (b)->b_level + 3) { \
            value = POP(); \
            Py_XDECREF(value); \
        } \
        type = tstate->exc_type; \
        value = tstate->exc_value; \
        traceback = tstate->exc_traceback; \
        tstate->exc_type = POP(); \
        tstate->exc_value = POP(); \
        tstate->exc_traceback = POP(); \
        Py_XDECREF(type); \
        Py_XDECREF(value); \
        Py_XDECREF(traceback); \
    } while(0)

#define WHY_NOT 0x0001
#define WHY_EXCEPTION 0x0002
#define WHY_RETURN 0x0008
#define WHY_BREAK 0x0010
#define WHY_CONTINUE 0x0020
#define WHY_YIELD 0x0040
#define WHY_SILENCED 0x0080

#ifdef HAVE_COMPUTED_GOTOS
    #define GET_ADDRESS(var, label) var = &&label;
    #define JUMP_TO_ADDR(addr) goto *(addr);
#else
    #if UINTPTR_MAX > 0xFFFFFFFF // x64: use rax
        #define GET_ADDRESS(var, label) do { \
            __asm lea rax, label \
            __asm mov var, rax \
        } while(0)
    #else // not x64: use eax
        #define GET_ADDRESS(var, label) do { \
            __asm lea eax, label \
            __asm mov var, eax \
        } while(0)
        #endif
    #define JUMP_TO_ADDR(addr) do { \
       	void* __addr = addr; \
       	__asm jmp __addr \
    } while (0)
#endif

PyObject* __pypperoni_IMPL_load_name(PyFrameObject* f, PyObject* name);
PyObject* __pypperoni_IMPL_load_global(PyFrameObject* f, PyObject* name);
int __pypperoni_IMPL_compare(PyObject* w, PyObject* v, int op, PyObject** result);
int __pypperoni_IMPL_unpack_sequence(PyObject* seq, PyObject*** sp, int num);
int __pypperoni_IMPL_unpack_ex(PyObject* seq, PyObject*** sp, int num);
void __pypperoni_IMPL_handle_bmuwc_error(PyObject* arg, PyObject* func);
PyObject* __pypperoni_IMPL_ensure_args_iterable(PyObject* args, PyObject* func);
PyObject* __pypperoni_IMPL_ensure_kwdict(PyObject* kwdict, PyObject* func);
PyObject* __pypperoni_IMPL_call_func(PyObject*** sp, int oparg, PyObject* kwargs);
int __pypperoni_IMPL_load_build_class(PyFrameObject* f, PyObject** result);
int __pypperoni_IMPL_setup_with(PyObject* v, PyObject** exitptr, PyObject** result);
int __pypperoni_IMPL_do_raise(PyObject* exc, PyObject* cause);

PyObject* __pypperoni_IMPL_import(int64_t index);
PyObject* __pypperoni_IMPL_import_from(PyObject* mod, const char* name);
PyObject* __pypperoni_IMPL_import_from_or_module(PyObject* mod, PyObject* name, int64_t index);
int __pypperoni_IMPL_import_star(PyFrameObject* f, PyObject* mod);

static inline int __pypperoni_IMPL_check_cond(PyObject* obj, int* result)
{
    int err;

    if (obj == Py_True) {
        *result = 1;
        return 0;
    }

    if (obj == Py_False) {
        *result = 0;
        return 0;
    }

    *result = PyObject_IsTrue(obj);
    if (*result < 0)
        return 1;

    return 0;
}

static inline int __pypperoni_IMPL_binary_power(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Power(v, w, Py_None);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_multiply(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Multiply(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_matrix_multiply(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_MatrixMultiply(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_modulo(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyUnicode_CheckExact(v) && (!PyUnicode_Check(w) || PyUnicode_CheckExact(w)))
        *x = PyUnicode_Format(v, w);
    else
        *x = PyNumber_Remainder(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_add(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyUnicode_CheckExact(v) && PyUnicode_CheckExact(w))
    {
        Py_INCREF(v); // PyUnicode_Append steals a ref
        PyUnicode_Append(&v, w);
        *x = v;
    }

    else
        *x = PyNumber_Add(v, w);

    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_subtract(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Subtract(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_subscr(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyObject_GetItem(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_floor_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_FloorDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_true_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_TrueDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_lshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Lshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_rshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Rshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_and(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_And(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_xor(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Xor(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_binary_or(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Or(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_floor_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceFloorDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_true_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceTrueDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_add(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyUnicode_CheckExact(v) && PyUnicode_CheckExact(w))
    {
        Py_INCREF(v); // PyUnicode_Append steals a ref
        PyUnicode_Append(&v, w);
        *x = v;
    }

    else
        *x = PyNumber_InPlaceAdd(v, w);

    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_subtract(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceSubtract(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_multiply(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceMultiply(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_matrix_multiply(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceMatrixMultiply(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_modulo(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceRemainder(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_power(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlacePower(v, w, Py_None);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_lshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceLshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_rshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceRshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_and(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceAnd(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_xor(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceXor(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_inplace_or(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceOr(v, w);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_unary_invert(PyObject* v, PyObject** x)
{
    *x = PyNumber_Invert(v);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_unary_positive(PyObject* v, PyObject** x)
{
    *x = PyNumber_Positive(v);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_unary_negative(PyObject* v, PyObject** x)
{
    *x = PyNumber_Negative(v);
    return (*x == NULL) ? 1 : 0;
}

static inline int __pypperoni_IMPL_unary_not(PyObject* v, PyObject** x)
{
    int err;

    err = PyObject_IsTrue(v);

    if (err == 0)
    {
        Py_INCREF(Py_True);
        *x = Py_True;
    }

    else if (err > 0)
    {
        Py_INCREF(Py_False);
        *x = Py_False;
        err = 0;
    }

    return err;
}

void setup_pypperoni();
int __pypperoni_IMPL_main(int argc, char* argv[]);

#ifdef __cplusplus
}
#endif
