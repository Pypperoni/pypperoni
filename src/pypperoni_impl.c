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

#include <opcode.h> /* PyCmp_* */
#include <structmember.h>

/* Implementations */
PyObject* __pypperoni_IMPL_load_name(PyFrameObject* f, PyObject* name)
{
    if (f->f_locals == NULL) {
        PyErr_Format(PyExc_SystemError,
                     "no locals when loading %R",
                     name);
        return NULL;
    }

    PyObject* x = NULL;
    PyObject* v = f->f_locals;
    if (PyDict_CheckExact(v)) {
        x = PyDict_GetItem(v, name);
    }
    else {
        x = PyObject_GetItem(v, name);
        if (x == NULL && PyErr_Occurred()) {
            if (!PyErr_ExceptionMatches(PyExc_KeyError))
            {
                return NULL;
            }
            PyErr_Clear();
        }
    }

    if (x == NULL) {
        x = PyDict_GetItem(f->f_globals, name);
        if (x == NULL) {
            x = PyDict_GetItem(f->f_builtins, name);
            if (x == NULL) {
                PyErr_Format(PyExc_NameError, "name '%R' is not defined", name);
                return NULL;
            }
        }
    }

    return x;
}

PyObject* __pypperoni_IMPL_load_global(PyFrameObject* f, PyObject* name)
{
    PyObject *v;
    if (PyDict_CheckExact(f->f_globals)
        && PyDict_CheckExact(f->f_builtins))
    {
        v = _PyDict_LoadGlobal((PyDictObject *)f->f_globals,
                               (PyDictObject *)f->f_builtins,
                               name);
        if (v == NULL) {
            if (!_PyErr_OCCURRED()) {
                /* _PyDict_LoadGlobal() returns NULL without raising
                 * an exception if the key doesn't exist */
                PyErr_Format(PyExc_NameError, "name %R is not defined", name);
            }
            return NULL;
        }
        Py_INCREF(v);
    }
    else {
        /* Slow-path if globals or builtins is not a dict */

        /* namespace 1: globals */
        v = PyObject_GetItem(f->f_globals, name);
        if (v == NULL) {
            if (!PyErr_ExceptionMatches(PyExc_KeyError))
                return NULL;
            PyErr_Clear();

            /* namespace 2: builtins */
            v = PyObject_GetItem(f->f_builtins, name);
            if (v == NULL) {
                if (PyErr_ExceptionMatches(PyExc_KeyError))
                    PyErr_Format(PyExc_NameError, "name '%R' is not defined", name);
                return NULL;
            }
        }
    }

    return v;
}

#define CANNOT_CATCH_MSG "catching classes that do not inherit from "\
                         "BaseException is not allowed"

int __pypperoni_IMPL_compare(PyObject* v, PyObject* w, int op, PyObject** result)
{
    int res = 0;
    switch (op) {
    case PyCmp_IS:
        res = (v == w);
        break;
    case PyCmp_IS_NOT:
        res = (v != w);
        break;
    case PyCmp_IN:
        res = PySequence_Contains(w, v);
        if (res < 0)
            return 1;
        break;
    case PyCmp_NOT_IN:
        res = PySequence_Contains(w, v);
        if (res < 0)
            return 1;
        res = !res;
        break;
    case PyCmp_EXC_MATCH:
        if (PyTuple_Check(w)) {
            Py_ssize_t i, length;
            length = PyTuple_Size(w);
            for (i = 0; i < length; i += 1) {
                PyObject *exc = PyTuple_GET_ITEM(w, i);
                if (!PyExceptionClass_Check(exc)) {
                    PyErr_SetString(PyExc_TypeError,
                                    CANNOT_CATCH_MSG);
                    return 1;
                }
            }
        }
        else {
            if (!PyExceptionClass_Check(w)) {
                PyErr_SetString(PyExc_TypeError,
                                CANNOT_CATCH_MSG);
                return 1;
            }
        }
        res = PyErr_GivenExceptionMatches(v, w);
        break;
    default:
        *result = PyObject_RichCompare(v, w, op);
        return (*result == NULL) ? 1 : 0;
    }
    *result = res ? Py_True : Py_False;
    Py_INCREF(*result);
    return 0;
}

static int
unpack_iterable(PyObject *v, int argcnt, int argcntafter, PyObject **sp)
{
    int i = 0, j = 0;
    Py_ssize_t ll = 0;
    PyObject *it;  /* iter(v) */
    PyObject *w;
    PyObject *l = NULL; /* variable list */

    assert(v != NULL);

    it = PyObject_GetIter(v);
    if (it == NULL)
        goto Error;

    for (; i < argcnt; i++) {
        w = PyIter_Next(it);
        if (w == NULL) {
            /* Iterator done, via error or exhaustion. */
            if (!PyErr_Occurred()) {
                if (argcntafter == -1) {
                    PyErr_Format(PyExc_ValueError,
                        "not enough values to unpack (expected %d, got %d)",
                        argcnt, i);
                }
                else {
                    PyErr_Format(PyExc_ValueError,
                        "not enough values to unpack "
                        "(expected at least %d, got %d)",
                        argcnt + argcntafter, i);
                }
            }
            goto Error;
        }
        *--sp = w;
    }

    if (argcntafter == -1) {
        /* We better have exhausted the iterator now. */
        w = PyIter_Next(it);
        if (w == NULL) {
            if (PyErr_Occurred())
                goto Error;
            Py_DECREF(it);
            return 1;
        }
        Py_DECREF(w);
        PyErr_Format(PyExc_ValueError,
            "too many values to unpack (expected %d)",
            argcnt);
        goto Error;
    }

    l = PySequence_List(it);
    if (l == NULL)
        goto Error;
    *--sp = l;
    i++;

    ll = PyList_GET_SIZE(l);
    if (ll < argcntafter) {
        PyErr_Format(PyExc_ValueError,
            "not enough values to unpack (expected at least %d, got %zd)",
            argcnt + argcntafter, argcnt + ll);
        goto Error;
    }

    /* Pop the "after-variable" args off the list. */
    for (j = argcntafter; j > 0; j--, i++) {
        *--sp = PyList_GET_ITEM(l, ll - j);
    }
    /* Resize the list. */
    Py_SIZE(l) = ll - argcntafter;
    Py_DECREF(it);
    return 1;

Error:
    for (; i > 0; i--, sp++)
        Py_DECREF(*sp);
    Py_XDECREF(it);
    return 0;
}

int __pypperoni_IMPL_unpack_sequence(PyObject* seq, PyObject*** sp, int num)
{
    PyObject *item, **items;
    PyObject **stack_pointer = *sp;
    int res = 0;

    if (PyTuple_CheckExact(seq) && PyTuple_GET_SIZE(seq) == num)
    {
        items = ((PyTupleObject *)seq)->ob_item;
        while (num--)
        {
            item = items[num];
            Py_INCREF(item);
            PUSH(item);
        }
    }

    else if (PyList_CheckExact(seq) && PyList_GET_SIZE(seq) == num)
    {
        items = ((PyListObject *)seq)->ob_item;
        while (num--)
        {
            item = items[num];
            Py_INCREF(item);
            PUSH(item);
        }
    }

    else if (unpack_iterable(seq, num, -1, stack_pointer + num))
    {
        STACKADJ(num);
    }

    else
    {
        /* unpack_iterable() raised an exception */
        Py_DECREF(seq);
        res = 1;
    }

    Py_DECREF(seq);
    *sp = stack_pointer;
    return res;
}

int __pypperoni_IMPL_unpack_ex(PyObject* seq, PyObject*** sp, int num)
{
    int totalargs = 1 + (num & 0xFF) + (num >> 8);
    PyObject **stack_pointer = *sp;
    int res = 0;

    if (unpack_iterable(seq, num & 0xFF, num >> 8,
                        stack_pointer + totalargs))
        stack_pointer += totalargs;

    else
        res = 1;

    Py_DECREF(seq);
    *sp = stack_pointer;
    return res;
}

void __pypperoni_IMPL_handle_bmuwc_error(PyObject* arg, PyObject* func)
{
    if (PyErr_ExceptionMatches(PyExc_AttributeError))
    {
        PyErr_Format(PyExc_TypeError,
                     "%.200s%.200s argument after ** "
                     "must be a mapping, not %.200s",
                     PyEval_GetFuncName(func),
                     PyEval_GetFuncDesc(func),
                     arg->ob_type->tp_name);
    }

    else if (PyErr_ExceptionMatches(PyExc_KeyError))
    {
        PyObject *exc, *val, *tb;
        PyErr_Fetch(&exc, &val, &tb);
        if (val && PyTuple_Check(val) && PyTuple_GET_SIZE(val) == 1)
        {
            PyObject *key = PyTuple_GET_ITEM(val, 0);
            if (!PyUnicode_Check(key)) {
                PyErr_Format(PyExc_TypeError,
                        "%.200s%.200s keywords must be strings",
                        PyEval_GetFuncName(func),
                        PyEval_GetFuncDesc(func));
            } else {
                PyErr_Format(PyExc_TypeError,
                        "%.200s%.200s got multiple "
                        "values for keyword argument '%U'",
                        PyEval_GetFuncName(func),
                        PyEval_GetFuncDesc(func),
                        key);
            }
            Py_XDECREF(exc);
            Py_XDECREF(val);
            Py_XDECREF(tb);
        }
        else
        {
            PyErr_Restore(exc, val, tb);
        }
    }
}

PyObject* __pypperoni_IMPL_ensure_args_iterable(PyObject* args, PyObject* func)
{
    if (!PyTuple_CheckExact(args)) {
        if (args->ob_type->tp_iter == NULL && !PySequence_Check(args)) {
            PyErr_Format(PyExc_TypeError,
                         "%.200s%.200s argument after * "
                         "must be an iterable, not %.200s",
                         PyEval_GetFuncName(func),
                         PyEval_GetFuncDesc(func),
                         args->ob_type->tp_name);
            Py_CLEAR(args);
        }
        else {
            Py_SETREF(args, PySequence_Tuple(args));
        }
    }

    return args;
}

PyObject* __pypperoni_IMPL_ensure_kwdict(PyObject* kwdict, PyObject* func)
{
    if (!PyDict_CheckExact(kwdict)) {
        PyObject *d = PyDict_New();
        if (d != NULL && PyDict_Update(d, kwdict) != 0) {
           Py_DECREF(d);
           d = NULL;
           if (PyErr_ExceptionMatches(PyExc_AttributeError)) {
               PyErr_Format(PyExc_TypeError,
                            "%.200s%.200s argument after ** "
                            "must be a mapping, not %.200s",
                            PyEval_GetFuncName(func),
                            PyEval_GetFuncDesc(func),
                            kwdict->ob_type->tp_name);
           }
       }

       Py_SETREF(kwdict, d);
   }

   return kwdict;
}

#define GETLOCAL(i)     (fastlocals[i])
#define SETLOCAL(i, value)      do { PyObject *tmp = GETLOCAL(i); \
                                     GETLOCAL(i) = value; \
                                     Py_XDECREF(tmp); } while (0)


static void
format_missing(const char *kind, PyCodeObject *co, PyObject *names)
{
    int err;
    Py_ssize_t len = PyList_GET_SIZE(names);
    PyObject *name_str, *comma, *tail, *tmp;

    assert(PyList_CheckExact(names));
    assert(len >= 1);
    /* Deal with the joys of natural language. */
    switch (len) {
    case 1:
        name_str = PyList_GET_ITEM(names, 0);
        Py_INCREF(name_str);
        break;
    case 2:
        name_str = PyUnicode_FromFormat("%U and %U",
                                        PyList_GET_ITEM(names, len - 2),
                                        PyList_GET_ITEM(names, len - 1));
        break;
    default:
        tail = PyUnicode_FromFormat(", %U, and %U",
                                    PyList_GET_ITEM(names, len - 2),
                                    PyList_GET_ITEM(names, len - 1));
        if (tail == NULL)
            return;
        /* Chop off the last two objects in the list. This shouldn't actually
           fail, but we can't be too careful. */
        err = PyList_SetSlice(names, len - 2, len, NULL);
        if (err == -1) {
            Py_DECREF(tail);
            return;
        }
        /* Stitch everything up into a nice comma-separated list. */
        comma = PyUnicode_FromString(", ");
        if (comma == NULL) {
            Py_DECREF(tail);
            return;
        }
        tmp = PyUnicode_Join(comma, names);
        Py_DECREF(comma);
        if (tmp == NULL) {
            Py_DECREF(tail);
            return;
        }
        name_str = PyUnicode_Concat(tmp, tail);
        Py_DECREF(tmp);
        Py_DECREF(tail);
        break;
    }
    if (name_str == NULL)
        return;
    PyErr_Format(PyExc_TypeError,
                 "%U() missing %i required %s argument%s: %U",
                 co->co_name,
                 len,
                 kind,
                 len == 1 ? "" : "s",
                 name_str);
    Py_DECREF(name_str);
}

static void
missing_arguments(PyCodeObject *co, Py_ssize_t missing, Py_ssize_t defcount,
                  PyObject **fastlocals)
{
    Py_ssize_t i, j = 0;
    Py_ssize_t start, end;
    int positional = (defcount != -1);
    const char *kind = positional ? "positional" : "keyword-only";
    PyObject *missing_names;

    /* Compute the names of the arguments that are missing. */
    missing_names = PyList_New(missing);
    if (missing_names == NULL)
        return;
    if (positional) {
        start = 0;
        end = co->co_argcount - defcount;
    }
    else {
        start = co->co_argcount;
        end = start + co->co_kwonlyargcount;
    }
    for (i = start; i < end; i++) {
        if (GETLOCAL(i) == NULL) {
            PyObject *raw = PyTuple_GET_ITEM(co->co_varnames, i);
            PyObject *name = PyObject_Repr(raw);
            if (name == NULL) {
                Py_DECREF(missing_names);
                return;
            }
            PyList_SET_ITEM(missing_names, j++, name);
        }
    }
    assert(j == missing);
    format_missing(kind, co, missing_names);
    Py_DECREF(missing_names);
}

static void
too_many_positional(PyCodeObject *co, Py_ssize_t given, Py_ssize_t defcount,
                    PyObject **fastlocals)
{
    int plural;
    Py_ssize_t kwonly_given = 0;
    Py_ssize_t i;
    PyObject *sig, *kwonly_sig;
    Py_ssize_t co_argcount = co->co_argcount;

    assert((co->co_flags & CO_VARARGS) == 0);
    /* Count missing keyword-only args. */
    for (i = co_argcount; i < co_argcount + co->co_kwonlyargcount; i++) {
        if (GETLOCAL(i) != NULL) {
            kwonly_given++;
        }
    }
    if (defcount) {
        Py_ssize_t atleast = co_argcount - defcount;
        plural = 1;
        sig = PyUnicode_FromFormat("from %zd to %zd", atleast, co_argcount);
    }
    else {
        plural = (co_argcount != 1);
        sig = PyUnicode_FromFormat("%zd", co_argcount);
    }
    if (sig == NULL)
        return;
    if (kwonly_given) {
        const char *format = " positional argument%s (and %zd keyword-only argument%s)";
        kwonly_sig = PyUnicode_FromFormat(format,
                                          given != 1 ? "s" : "",
                                          kwonly_given,
                                          kwonly_given != 1 ? "s" : "");
        if (kwonly_sig == NULL) {
            Py_DECREF(sig);
            return;
        }
    }
    else {
        /* This will not fail. */
        kwonly_sig = PyUnicode_FromString("");
        assert(kwonly_sig != NULL);
    }
    PyErr_Format(PyExc_TypeError,
                 "%U() takes %U positional argument%s but %zd%U %s given",
                 co->co_name,
                 sig,
                 plural ? "s" : "",
                 given,
                 kwonly_sig,
                 given == 1 && !kwonly_given ? "was" : "were");
    Py_DECREF(sig);
    Py_DECREF(kwonly_sig);
}

static PyObject*
_PyFunction_FastCall(PyCodeObject *co, PyObject **args, Py_ssize_t nargs,
                     PyObject *globals)
{
    PyFrameObject *f;
    PyThreadState *tstate = PyThreadState_GET();
    PyObject **fastlocals;
    Py_ssize_t i;
    PyObject *result;

    assert(globals != NULL);
    /* XXX Perhaps we should create a specialized
       PyFrame_New() that doesn't take locals, but does
       take builtins without sanity checking them.
       */
    assert(tstate != NULL);
    f = PyFrame_New(tstate, co, globals, NULL);
    if (f == NULL) {
        return NULL;
    }

    fastlocals = f->f_localsplus;

    for (i = 0; i < nargs; i++) {
        Py_INCREF(*args);
        fastlocals[i] = *args++;
    }
    result = PyEval_EvalFrameEx(f,0);

    ++tstate->recursion_depth;
    Py_DECREF(f);
    --tstate->recursion_depth;

    return result;
}

static PyObject *
_PyEval_EvalCodeWithName(PyObject *_co, PyObject *globals, PyObject *locals,
           PyObject **args, Py_ssize_t argcount,
           PyObject **kwnames, PyObject **kwargs,
           Py_ssize_t kwcount, int kwstep,
           PyObject **defs, Py_ssize_t defcount,
           PyObject *kwdefs, PyObject *closure,
           PyObject *name, PyObject *qualname)
{
    PyCodeObject* co = (PyCodeObject*)_co;
    PyFrameObject *f;
    PyObject *retval = NULL;
    PyObject **fastlocals, **freevars;
    PyThreadState *tstate;
    PyObject *x, *u;
    const Py_ssize_t total_args = co->co_argcount + co->co_kwonlyargcount;
    Py_ssize_t i, n;
    PyObject *kwdict;

    if (globals == NULL) {
        PyErr_SetString(PyExc_SystemError,
                        "PyEval_EvalCodeEx: NULL globals");
        return NULL;
    }

    /* Create the frame */
    tstate = PyThreadState_GET();
    assert(tstate != NULL);
    f = PyFrame_New(tstate, co, globals, locals);
    if (f == NULL) {
        return NULL;
    }
    fastlocals = f->f_localsplus;
    freevars = f->f_localsplus + co->co_nlocals;

    /* Create a dictionary for keyword parameters (**kwags) */
    if (co->co_flags & CO_VARKEYWORDS) {
        kwdict = PyDict_New();
        if (kwdict == NULL)
            goto fail;
        i = total_args;
        if (co->co_flags & CO_VARARGS) {
            i++;
        }
        SETLOCAL(i, kwdict);
    }
    else {
        kwdict = NULL;
    }

    /* Copy positional arguments into local variables */
    if (argcount > co->co_argcount) {
        n = co->co_argcount;
    }
    else {
        n = argcount;
    }
    for (i = 0; i < n; i++) {
        x = args[i];
        Py_INCREF(x);
        SETLOCAL(i, x);
    }

    /* Pack other positional arguments into the *args argument */
    if (co->co_flags & CO_VARARGS) {
        u = PyTuple_New(argcount - n);
        if (u == NULL) {
            goto fail;
        }
        SETLOCAL(total_args, u);
        for (i = n; i < argcount; i++) {
            x = args[i];
            Py_INCREF(x);
            PyTuple_SET_ITEM(u, i-n, x);
        }
    }

    /* Handle keyword arguments passed as two strided arrays */
    kwcount *= kwstep;
    for (i = 0; i < kwcount; i += kwstep) {
        PyObject **co_varnames;
        PyObject *keyword = kwnames[i];
        PyObject *value = kwargs[i];
        Py_ssize_t j;

        if (keyword == NULL || !PyUnicode_Check(keyword)) {
            PyErr_Format(PyExc_TypeError,
                         "%U() keywords must be strings",
                         co->co_name);
            goto fail;
        }

        /* Speed hack: do raw pointer compares. As names are
           normally interned this should almost always hit. */
        co_varnames = ((PyTupleObject *)(co->co_varnames))->ob_item;
        for (j = 0; j < total_args; j++) {
            PyObject *name = co_varnames[j];
            if (name == keyword) {
                goto kw_found;
            }
        }

        /* Slow fallback, just in case */
        for (j = 0; j < total_args; j++) {
            PyObject *name = co_varnames[j];
            int cmp = PyObject_RichCompareBool( keyword, name, Py_EQ);
            if (cmp > 0) {
                goto kw_found;
            }
            else if (cmp < 0) {
                goto fail;
            }
        }

        if (j >= total_args && kwdict == NULL) {
            PyErr_Format(PyExc_TypeError,
                         "%U() got an unexpected keyword argument '%S'",
                         co->co_name, keyword);
            goto fail;
        }

        if (PyDict_SetItem(kwdict, keyword, value) == -1) {
            goto fail;
        }
        continue;

      kw_found:
        if (GETLOCAL(j) != NULL) {
            PyErr_Format(PyExc_TypeError,
                         "%U() got multiple values for argument '%S'",
                         co->co_name, keyword);
            goto fail;
        }
        Py_INCREF(value);
        SETLOCAL(j, value);
    }

    /* Check the number of positional arguments */
    if (argcount > co->co_argcount && !(co->co_flags & CO_VARARGS)) {
        too_many_positional(co, argcount, defcount, fastlocals);
        goto fail;
    }

    /* Add missing positional arguments (copy default values from defs) */
    if (argcount < co->co_argcount) {
        Py_ssize_t m = co->co_argcount - defcount;
        Py_ssize_t missing = 0;
        for (i = argcount; i < m; i++) {
            if (GETLOCAL(i) == NULL) {
                missing++;
            }
        }
        if (missing) {
            missing_arguments(co, missing, defcount, fastlocals);
            goto fail;
        }
        if (n > m)
            i = n - m;
        else
            i = 0;
        for (; i < defcount; i++) {
            if (GETLOCAL(m+i) == NULL) {
                PyObject *def = defs[i];
                Py_INCREF(def);
                SETLOCAL(m+i, def);
            }
        }
    }

    /* Add missing keyword arguments (copy default values from kwdefs) */
    if (co->co_kwonlyargcount > 0) {
        Py_ssize_t missing = 0;
        for (i = co->co_argcount; i < total_args; i++) {
            PyObject *name;
            if (GETLOCAL(i) != NULL)
                continue;
            name = PyTuple_GET_ITEM(co->co_varnames, i);
            if (kwdefs != NULL) {
                PyObject *def = PyDict_GetItem(kwdefs, name);
                if (def) {
                    Py_INCREF(def);
                    SETLOCAL(i, def);
                    continue;
                }
            }
            missing++;
        }
        if (missing) {
            missing_arguments(co, missing, -1, fastlocals);
            goto fail;
        }
    }

    /* Allocate and initialize storage for cell vars, and copy free
       vars into frame. */
    for (i = 0; i < PyTuple_GET_SIZE(co->co_cellvars); ++i) {
        PyObject *c;
        int arg;
        /* Possibly account for the cell variable being an argument. */
        if (co->co_cell2arg != NULL &&
            (arg = co->co_cell2arg[i]) != CO_CELL_NOT_AN_ARG) {
            c = PyCell_New(GETLOCAL(arg));
            /* Clear the local copy. */
            SETLOCAL(arg, NULL);
        }
        else {
            c = PyCell_New(NULL);
        }
        if (c == NULL)
            goto fail;
        SETLOCAL(co->co_nlocals + i, c);
    }

    /* Copy closure variables to free variables */
    for (i = 0; i < PyTuple_GET_SIZE(co->co_freevars); ++i) {
        PyObject *o = PyTuple_GET_ITEM(closure, i);
        Py_INCREF(o);
        freevars[PyTuple_GET_SIZE(co->co_cellvars) + i] = o;
    }

    /* Handle generator/coroutine/asynchronous generator */
    if (co->co_flags & (CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR)) {
        PyObject *gen;
        PyObject *coro_wrapper = tstate->coroutine_wrapper;
        int is_coro = co->co_flags & CO_COROUTINE;

        if (is_coro && tstate->in_coroutine_wrapper) {
            assert(coro_wrapper != NULL);
            PyErr_Format(PyExc_RuntimeError,
                         "coroutine wrapper %.200R attempted "
                         "to recursively wrap %.200R",
                         coro_wrapper,
                         co);
            goto fail;
        }

        /* Don't need to keep the reference to f_back, it will be set
         * when the generator is resumed. */
        Py_CLEAR(f->f_back);

        /* Create a new generator that owns the ready to run frame
         * and return that as the value. */
        if (is_coro) {
            gen = PyCoro_New(f, name, qualname);
        } else if (co->co_flags & CO_ASYNC_GENERATOR) {
            gen = PyAsyncGen_New(f, name, qualname);
        } else {
            gen = PyGen_NewWithQualName(f, name, qualname);
        }
        if (gen == NULL)
            return NULL;

        if (is_coro && coro_wrapper != NULL) {
            PyObject *wrapped;
            tstate->in_coroutine_wrapper = 1;
            wrapped = PyObject_CallFunction(coro_wrapper, "N", gen);
            tstate->in_coroutine_wrapper = 0;
            return wrapped;
        }

        return gen;
    }

    retval = PyEval_EvalFrameEx(f,0);

fail: /* Jump here from prelude on failure */

    /* decref'ing the frame can cause __del__ methods to get invoked,
       which can call back into Python.  While we're done with the
       current Python frame (f), the associated C stack is still in use,
       so recursion_depth must be boosted for the duration.
    */
    assert(tstate != NULL);
    ++tstate->recursion_depth;
    Py_DECREF(f);
    --tstate->recursion_depth;
    return retval;
}

static PyObject *
fast_function(PyObject *func, PyObject **stack,
              Py_ssize_t nargs, PyObject *kwnames)
{
    PyCodeObject *co = (PyCodeObject *)PyFunction_GET_CODE(func);
    PyObject *globals = PyFunction_GET_GLOBALS(func);
    PyObject *argdefs = PyFunction_GET_DEFAULTS(func);
    PyObject *kwdefs, *closure, *name, *qualname;
    PyObject **d;
    Py_ssize_t nkwargs = (kwnames == NULL) ? 0 : PyTuple_GET_SIZE(kwnames);
    Py_ssize_t nd;

    assert(PyFunction_Check(func));
    assert(nargs >= 0);
    assert(kwnames == NULL || PyTuple_CheckExact(kwnames));
    assert((nargs == 0 && nkwargs == 0) || stack != NULL);
    /* kwnames must only contains str strings, no subclass, and all keys must
       be unique */

    if (co->co_kwonlyargcount == 0 && nkwargs == 0 &&
        co->co_flags == (CO_OPTIMIZED | CO_NEWLOCALS | CO_NOFREE))
    {
        if (argdefs == NULL && co->co_argcount == nargs) {
            return _PyFunction_FastCall(co, stack, nargs, globals);
        }
        else if (nargs == 0 && argdefs != NULL
                 && co->co_argcount == Py_SIZE(argdefs)) {
            /* function called with no arguments, but all parameters have
               a default value: use default values as arguments .*/
            stack = &PyTuple_GET_ITEM(argdefs, 0);
            return _PyFunction_FastCall(co, stack, Py_SIZE(argdefs), globals);
        }
    }

    kwdefs = PyFunction_GET_KW_DEFAULTS(func);
    closure = PyFunction_GET_CLOSURE(func);
    name = ((PyFunctionObject *)func) -> func_name;
    qualname = ((PyFunctionObject *)func) -> func_qualname;

    if (argdefs != NULL) {
        d = &PyTuple_GET_ITEM(argdefs, 0);
        nd = Py_SIZE(argdefs);
    }
    else {
        d = NULL;
        nd = 0;
    }
    return _PyEval_EvalCodeWithName((PyObject*)co, globals, (PyObject *)NULL,
                                    stack, nargs,
                                    nkwargs ? &PyTuple_GET_ITEM(kwnames, 0) : NULL,
                                    stack + nargs,
                                    nkwargs, 1,
                                    d, (int)nd, kwdefs,
                                    closure, name, qualname);
}

PyObject* __pypperoni_IMPL_call_func(PyObject*** sp, int oparg, PyObject* kwargs)
{
    PyObject **pfunc = (*sp) - oparg - 1;
    PyObject *func = *pfunc;
    PyObject *x, *w;
    Py_ssize_t nkwargs = (kwargs == NULL) ? 0 : PyTuple_GET_SIZE(kwargs);
    Py_ssize_t nargs = oparg - nkwargs;
    PyObject **stack;

    /* Always dispatch PyCFunction first, because these are
       presumed to be the most frequent callable object.
    */
    if (PyCFunction_Check(func)) {
        stack = (*sp) - nargs - nkwargs;
        x = _PyCFunction_FastCallKeywords(func, stack, nargs, kwargs);
    }
    else {
        if (PyMethod_Check(func) && PyMethod_GET_SELF(func) != NULL) {
            /* optimize access to bound methods */
            PyObject *self = PyMethod_GET_SELF(func);
            Py_INCREF(self);
            func = PyMethod_GET_FUNCTION(func);
            Py_INCREF(func);
            Py_SETREF(*pfunc, self);
            nargs++;
        }
        else {
            Py_INCREF(func);
        }

        stack = (*sp) - nargs - nkwargs;

        if (PyFunction_Check(func)) {
            x = fast_function(func, stack, nargs, kwargs);
        }
        else {
            x = _PyObject_FastCallKeywords(func, stack, nargs, kwargs);
        }

        Py_DECREF(func);
    }

    assert((x != NULL) ^ (PyErr_Occurred() != NULL));

    /* Clear the stack of the function object.  Also removes
       the arguments in case they weren't consumed already
       (fast_function() and err_args() leave them on the stack).
     */
    while ((*sp) > pfunc) {
        w = *--(*sp);
        Py_DECREF(w);
    }

    return x;
}

int __pypperoni_IMPL_load_build_class(PyFrameObject* f, PyObject** result)
{
    _Py_IDENTIFIER(__build_class__);

    PyObject *bc;
    if (PyDict_CheckExact(f->f_builtins)) {
        bc = _PyDict_GetItemId(f->f_builtins, &PyId___build_class__);
        if (bc == NULL) {
            PyErr_SetString(PyExc_NameError,
                            "__build_class__ not found");
            goto error;
        }
        Py_INCREF(bc);
    }
    else {
        PyObject *build_class_str = _PyUnicode_FromId(&PyId___build_class__);
        if (build_class_str == NULL)
            goto error;
        bc = PyObject_GetItem(f->f_builtins, build_class_str);
        if (bc == NULL) {
            if (PyErr_ExceptionMatches(PyExc_KeyError))
                PyErr_SetString(PyExc_NameError,
                                "__build_class__ not found");
            goto error;
        }
    }
    *result = bc;
    return 0;

error:
    *result = NULL;
    return 1;
}

static PyObject *
special_lookup(PyObject *o, _Py_Identifier *id)
{
    PyObject *res;
    res = _PyObject_LookupSpecial(o, id);
    if (res == NULL && !PyErr_Occurred()) {
        PyErr_SetObject(PyExc_AttributeError, id->object);
        return NULL;
    }
    return res;
}

int __pypperoni_IMPL_setup_with(PyObject* v, PyObject** exitptr, PyObject** result)
{
    _Py_IDENTIFIER(__exit__);
    _Py_IDENTIFIER(__enter__);
    PyObject *enter = special_lookup(v, &PyId___enter__);
    if (enter == NULL)
        goto error;

    *exitptr = special_lookup(v, &PyId___exit__);
    if (*exitptr == NULL) {
        Py_DECREF(enter);
        goto error;
    }

    *result = PyObject_CallFunctionObjArgs(enter, NULL);
    Py_DECREF(enter);

    if (*result == NULL)
        goto error;

    return 0;

error:
    *exitptr = NULL;
    return 1;
}

int __pypperoni_IMPL_do_raise(PyObject* exc, PyObject* cause)
{
    PyObject *type = NULL, *value = NULL;

    if (exc == NULL) {
        /* Reraise */
        PyThreadState *tstate = PyThreadState_GET();
        PyObject *tb;
        type = tstate->exc_type;
        value = tstate->exc_value;
        tb = tstate->exc_traceback;
        if (type == Py_None || type == NULL) {
            PyErr_SetString(PyExc_RuntimeError,
                            "No active exception to reraise");
            return 0;
        }
        Py_XINCREF(type);
        Py_XINCREF(value);
        Py_XINCREF(tb);
        PyErr_Restore(type, value, tb);
        return 1;
    }

    /* We support the following forms of raise:
       raise
       raise <instance>
       raise <type> */

    if (PyExceptionClass_Check(exc)) {
        type = exc;
        value = PyObject_CallObject(exc, NULL);
        if (value == NULL)
            goto raise_error;
        if (!PyExceptionInstance_Check(value)) {
            PyErr_Format(PyExc_TypeError,
                         "calling %R should have returned an instance of "
                         "BaseException, not %R",
                         type, Py_TYPE(value));
            goto raise_error;
        }
    }
    else if (PyExceptionInstance_Check(exc)) {
        value = exc;
        type = PyExceptionInstance_Class(exc);
        Py_INCREF(type);
    }
    else {
        /* Not something you can raise.  You get an exception
           anyway, just not what you specified :-) */
        Py_DECREF(exc);
        PyErr_SetString(PyExc_TypeError,
                        "exceptions must derive from BaseException");
        goto raise_error;
    }

    if (cause) {
        PyObject *fixed_cause;
        if (PyExceptionClass_Check(cause)) {
            fixed_cause = PyObject_CallObject(cause, NULL);
            if (fixed_cause == NULL)
                goto raise_error;
            Py_DECREF(cause);
        }
        else if (PyExceptionInstance_Check(cause)) {
            fixed_cause = cause;
        }
        else if (cause == Py_None) {
            Py_DECREF(cause);
            fixed_cause = NULL;
        }
        else {
            PyErr_SetString(PyExc_TypeError,
                            "exception causes must derive from "
                            "BaseException");
            goto raise_error;
        }
        PyException_SetCause(value, fixed_cause);
    }

    PyErr_SetObject(type, value);
    /* PyErr_SetObject incref's its arguments */
    Py_XDECREF(value);
    Py_XDECREF(type);
    return 0;

raise_error:
    Py_XDECREF(value);
    Py_XDECREF(type);
    Py_XDECREF(cause);
    return 0;
}

/* Modules */
#define MODULE_BUILTIN 1
#define MODULE_DEFINED 2

#include "modules.I"

static int __init_module_obj(PypperoniModule* mod)
{
    PyObject *m, *d, *result;
    PyCodeObject* co;
    PyFrameObject* f;

    if (mod->type == MODULE_BUILTIN)
    {
        mod->obj = PyImport_ImportModule(mod->name);
        if (mod->obj == NULL)
            PyErr_Format(PyExc_ImportError, "unknown module %.200s", mod->name);

        return (mod->obj != NULL);
    }

    m = PyImport_AddModule(mod->name);
    Py_INCREF(m);
    mod->obj = m;
    d = PyModule_GetDict(m);

    /* Get code object */
    co = PyCode_NewEmpty(mod->name, "<module>", 0);
    if (co == NULL)
        return 0;

    co->co_nlocals = mod->nlocals;
    co->co_stacksize = mod->stacksize;
    co->co_meth_ptr = mod->ptr;

    /* Set a few attributes */
    PyDict_SetItemString(d, "__file__", PyUnicode_FromString(mod->name));
    PyDict_SetItemString(d, "__builtins__", PyThreadState_GET()->interp->builtins);

    /* Execute the function */
    result = PyEval_EvalCode((PyObject*)co, d, NULL);
    Py_XDECREF(result);
    return (result == NULL) ? 0 : 1;
}

static PypperoniModule* __get_module(int64_t index)
{
    PypperoniModule *mod, **modlist;
    get_pypperoni_modules(&modlist); /* provided by modules.I */

    while (mod = *modlist++)
        if (mod->index == index)
            return mod;

    return NULL;
}

static int __init_module(int64_t index)
{
    /* Returns 1 on success and 0 on failure */
    PypperoniModule* mod = __get_module(index);
    if (mod == NULL)
        return 0;

    if (mod->obj != NULL)
        return 1; /* already initialized */

    return __init_module_obj(mod);
}

PyObject* __pypperoni_IMPL_import(int64_t index)
{
    PypperoniModule* mod = __get_module(index);
    if (mod == NULL)
    {
        PyErr_Format(PyExc_ImportError, "unknown module %lld", index);
        return NULL;
    }

    if (mod->obj != NULL)
    {
        Py_INCREF(mod->obj);
        return mod->obj;
    }

    if (mod->parent != -1 && !__init_module(mod->parent))
        return NULL;

    if (!__init_module_obj(mod))
        return NULL;

    Py_INCREF(mod->obj);
    return mod->obj;
}

PyObject* __pypperoni_IMPL_import_from(PyObject* mod, const char* name)
{
    PyObject* x = PyObject_GetAttrString(mod, name);
    if (x == NULL && PyErr_ExceptionMatches(PyExc_AttributeError)) {
        PyErr_Format(PyExc_ImportError, "cannot import name %.230s", name);
    }
    return x;
}

PyObject* __pypperoni_IMPL_import_from_or_module(PyObject* mod, PyObject* name, int64_t index)
{
    PyObject* x = PyObject_GetAttr(mod, name);
    if (x == NULL && PyErr_ExceptionMatches(PyExc_AttributeError)) {
        PyErr_Clear();
        x = __pypperoni_IMPL_import(index);
    }
    return x;
}

int __pypperoni_IMPL_import_star(PyFrameObject* f, PyObject* mod)
{
    _Py_IDENTIFIER(__all__);
    _Py_IDENTIFIER(__dict__);
    PyObject *all = _PyObject_GetAttrId(mod, &PyId___all__);
    PyObject *dict, *name, *value;
    int skip_leading_underscores = 0;
    int pos, err;

    if (all == NULL) {
        if (!PyErr_ExceptionMatches(PyExc_AttributeError))
            return -1; /* Unexpected error */
        PyErr_Clear();
        dict = _PyObject_GetAttrId(mod, &PyId___dict__);
        if (dict == NULL) {
            if (!PyErr_ExceptionMatches(PyExc_AttributeError))
                return -1;
            PyErr_SetString(PyExc_ImportError,
            "from-import-* object has no __dict__ and no __all__");
            return -1;
        }
        all = PyMapping_Keys(dict);
        Py_DECREF(dict);
        if (all == NULL)
            return -1;
        skip_leading_underscores = 1;
    }

    for (pos = 0, err = 0; ; pos++) {
        name = PySequence_GetItem(all, pos);
        if (name == NULL) {
            if (!PyErr_ExceptionMatches(PyExc_IndexError))
                err = -1;
            else
                PyErr_Clear();
            break;
        }
        if (skip_leading_underscores && PyUnicode_Check(name)) {
            if (PyUnicode_READY(name) == -1) {
                Py_DECREF(name);
                err = -1;
                break;
            }
            if (PyUnicode_READ_CHAR(name, 0) == '_') {
                Py_DECREF(name);
                continue;
            }
        }
        value = PyObject_GetAttr(mod, name);
        if (value == NULL)
            err = -1;
        else if (PyDict_CheckExact(f->f_locals))
            err = PyDict_SetItem(f->f_locals, name, value);
        else
            err = PyObject_SetItem(f->f_locals, name, value);
        Py_DECREF(name);
        Py_XDECREF(value);
        if (err != 0)
            break;
    }
    Py_DECREF(all);
    return err;
}

static PyMethodDef describeException_def;

#define PyTraceBack_LIMIT 1000

static PyObject* describeException(PyObject* self, PyObject* args)
{
    _Py_IDENTIFIER(__name__);

    PyThreadState* tstate = PyThreadState_GET();
    PyTracebackObject* tb = (PyTracebackObject*)tstate->exc_traceback;
    PyFrameObject* exc_frame;
    PyObject* result;
    int depth = 0;

    result = PyUnicode_FromString("");
    if ((PyObject*)tb == Py_None || result == NULL)
        tb = NULL;

    while (tb != NULL && depth < PyTraceBack_LIMIT)
    {
        exc_frame = tb->tb_frame;
        PyObject* modname = _PyDict_GetItemId(exc_frame->f_globals,
                                              &PyId___name__);
        PyObject* formatted = PyUnicode_FromFormat("#%d In \"%U\", instr %d, line %d\n",
                                                   depth++, modname,
                                                   exc_frame->f_lasti,
                                                   exc_frame->f_lineno);
        PyUnicode_Append(&result, formatted);
        tb = tb->tb_next;
    }

    return result;
}

/* Setup and main */
void setup_pypperoni()
{
    const char* _def_encoding = "UTF-8";

    /* Register encodings module */
    PyImport_AppendInittab("encodings", load_encodings); /* provided by modules.I */

    /* Initialize Python */
    Py_IsolatedFlag++;
    Py_IgnoreEnvironmentFlag++;
    Py_NoSiteFlag++;
    Py_FrozenFlag++;

    /* Py_FileSystemDefaultEncoding must be malloc'ed */
    Py_FileSystemDefaultEncoding = malloc(sizeof(_def_encoding));
    strcpy((char*)Py_FileSystemDefaultEncoding, _def_encoding);

    Py_Initialize();
    PyEval_InitThreads();

    /* Setup __pypperoni__ */
    PyObject* pypperonimod = PyImport_AddModule("__pypperoni__");
    PyObject* bt = PyEval_GetBuiltins();
    PyDict_SetItemString(bt, "__pypperoni__", pypperonimod);

    describeException_def.ml_name = "describeException";
    describeException_def.ml_meth = (PyCFunction)describeException;
    describeException_def.ml_flags = METH_NOARGS;
    PyObject_SetAttrString(pypperonimod, "describeException",
                           PyCFunction_New(&describeException_def, NULL));

    PyObject_SetAttrString(pypperonimod, "platform", PyUnicode_FromString(
#ifdef _WIN32
      "windows"
#elif ANDROID
      "android"
#elif __APPLE__
      "mac"
#elif __linux
      "linux"
#endif
    ));

    Py_DECREF(pypperonimod);
}

int __pypperoni_IMPL_main(int argc, char* argv[])
{
    /* XXX TODO: Handle unicode properly */
    int i;
    PyObject* av = PyList_New(argc);
    if (av == NULL)
        goto argv_error;

    for (i = 0; i < argc; i++)
    {
        PyObject* v = PyUnicode_FromString(argv[i]);
        if (v == NULL)
            goto argv_error;

        PyList_SetItem(av, i, v);
    }

    if (PySys_SetObject("argv", av) != 0)
        goto argv_error;

    if (__pypperoni_IMPL_import(0) != NULL)
        return 0;

    return 1;

argv_error:
    Py_XDECREF(av);
    Py_FatalError("can't assign sys.argv");
}
