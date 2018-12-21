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

#include <opcode.h> // PyCmp_*
#include <structmember.h>

#include <algorithm>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <map>

#ifdef __GNUC__
#pragma GCC diagnostic ignored "-Wwrite-strings"
#pragma GCC diagnostic ignored "-Wformat"
#endif

// Modules
#define MODULE_BUILTIN 1
#define MODULE_DEFINED 2

#include "modules.I"


// Frames
static PypperoniFrame* _current_frame = NULL;
static std::vector<PypperoniFrame*> _frames;

// Num of frames to alloc at a time
#define FRAME_ARENA_SIZE 15
#include "frames.I"

static void PypperoniFrame_Allocate()
{
    Py_ssize_t i, j;
    for (i = 0; i < FRAME_ARENA_SIZE; i++)
    {
        PypperoniFrame* f = new PypperoniFrame;

        // Allocate stack
        f->f_stackptr = new PyObject*[MAX_STACKSIZE];
        f->f_stacktop = f->f_stackptr;
        for (j = 0; j < MAX_STACKSIZE; j++)
            f->f_stacktop[j] = NULL;

        f->f_stacklevel = PyDict_New();

        // Allocate cells
        f->f_cells = new PyObject*[MAX_NCELLS];
        for (j = 0; j < MAX_NCELLS; j++)
            f->f_cells[j] = PyCell_New(NULL);

        // Allocate fastlocals
        f->f_fastlocals = new PyObject*[MAX_NLOCALS];
        for (j = 0; j < MAX_NLOCALS; j++)
            f->f_fastlocals[j] = NULL;

        _frames.push_back(f);
    }
}

static PypperoniFrame* PypperoniFrame_New(PyObject* globals, PyObject* locals,
                                  PyObject* builtins, Py_ssize_t stacksize,
                                  Py_ssize_t numcells, Py_ssize_t numfast)
{
    Py_ssize_t i;

    if (builtins == NULL)
    {
        builtins = PyThreadState_GET()->interp->builtins;
        if (builtins == NULL)
        {
            Py_FatalError("no builtins");
            return NULL;
        }
    }

    if (locals == NULL)
        locals = PyDict_New();

    else
        Py_INCREF(locals);

    Py_INCREF(builtins);
    Py_INCREF(globals);

    if (!_frames.size())
        PypperoniFrame_Allocate();

    PypperoniFrame* f = _frames.back();
    _frames.pop_back();
    f->f_globals = globals;
    f->f_locals = locals;
    f->f_builtins = builtins;

    f->f_stacktop = f->f_stackptr;
    f->f_lasti = -1;
    f->f_exci = -1;
    f->f_excline = -1;
    f->f_back = NULL;

    f->f_stacksize = stacksize;
    f->f_numcells = numcells;
    f->f_numfast = numfast;

    return f;
}

static void PypperoniFrame_Clear(PypperoniFrame* f)
{
    Py_ssize_t i;

    Py_DECREF(f->f_builtins);
    Py_DECREF(f->f_globals);
    Py_DECREF(f->f_locals);

    f->f_builtins = NULL;
    f->f_globals = NULL;
    f->f_locals = NULL;

    // Clear stack
    for (i = 0; i < f->f_stacksize; i++)
    {
        f->f_stackptr[i] = NULL;
    }

    PyDict_Clear(f->f_stacklevel);

    // Clear fastlocals
    for (i = 0; i < f->f_numfast; i++)
    {
        Py_XDECREF(f->f_fastlocals[i]);
        f->f_fastlocals[i] = NULL;
    }

    // Clear cells
    for (i = 0; i < f->f_numcells; i++)
    {
        if (PyCell_GET(f->f_cells[i]) != NULL)
        {
            Py_DECREF(f->f_cells[i]);
            f->f_cells[i] = PyCell_New(NULL);
        }
    }

    _frames.push_back(f);
}

#define CO_VARARGS 0x0004
#define CO_VARKEYWORDS 0x0008
#define CO_GENERATOR 0x0020

typedef PyObject* (*func_ptr_t)(PypperoniFrame* f);


// Tracebacks
typedef struct {
    const char* name;
    int instr;
    int line;
    int depth;
} _tbentry;
static std::vector<_tbentry> _traceback;

void PypperoniTraceback_AddFrame(const char* name, PypperoniFrame* f)
{
    _traceback.erase(std::remove_if(_traceback.begin(), _traceback.end(),
                     [f](const _tbentry& a) { return a.depth == f->f_depth; }),
                     _traceback.end());

    _tbentry e;
    e.name = name;
    e.instr = f->f_exci;
    e.line = f->f_excline;
    e.depth = f->f_depth;
    _traceback.push_back(e);

    // Sort by depth
    std::sort(_traceback.begin(), _traceback.end(),
              [](const _tbentry& a, const _tbentry& b) {
        return a.depth > b.depth;
    });
}

void PypperoniTraceback_Clear()
{
    _traceback.clear();
    PyErr_Clear();
}

static std::string PypperoniTraceback_Format()
{
    // Normalize the traceback:
    int lastdepth = 0;
    std::vector<_tbentry> fixedtb;
    int i = 0;
    for (auto it = _traceback.rbegin(); it != _traceback.rend(); ++it)
    {
       _tbentry e = *it;
       if (e.depth > i + 1) break;
       e.depth = i++;
       fixedtb.push_back(e);
    }
    _traceback = std::vector<_tbentry>(fixedtb.rbegin(), fixedtb.rend());

    std::stringstream ss;
    for (auto& it : _traceback)
    {
        ss << "#" << it.depth << " In \"" << it.name;
        ss << "\", instr " << it.instr << ", line ";
        ss << it.line << std::endl;
    }

    return ss.str();
}

void PypperoniTraceback_Print()
{
    std::cerr << PypperoniTraceback_Format();
    PyErr_Print();
}

static PyObject* Py_PypperoniTraceback_Format(PyObject* self, PyObject* args)
{
    return PyString_FromString(PypperoniTraceback_Format().c_str());
}

// Generators
typedef struct _generator {
    PyObject_HEAD

    func_ptr_t gen_ptr;
    PypperoniFrame* gen_frame;
    const char* gen_name;
    int gen_exhausted;

    PyObject* gen_weakreflist;
    int gen_running;
} PypperoniGenObject;

static void gen_dealloc(PypperoniGenObject* gen)
{
    PyObject* self = (PyObject *) gen;

    _PyObject_GC_UNTRACK(gen);

    if (gen->gen_weakreflist != NULL)
        PyObject_ClearWeakRefs(self);

    gen->gen_exhausted = 1;
    gen->gen_running = 0;
    gen->gen_ptr = NULL;
    gen->gen_name = NULL;

    PypperoniFrame_Clear(gen->gen_frame);
    gen->gen_frame = NULL;

    PyObject_GC_Del(gen);
}

static int gen_traverse(PypperoniGenObject* gen, visitproc visit, void* arg)
{
    return 0;
}

static PyObject* gen_send_ex(PypperoniGenObject* gen, PyObject* arg)
{
    PyThreadState *tstate = PyThreadState_GET();
    PypperoniFrame *f = gen->gen_frame;
    PyObject *result;

    if (gen->gen_running) {
        PyErr_SetString(PyExc_ValueError,
                        "generator already executing");
        return NULL;
    }

    if (gen->gen_exhausted) {
        if (arg != NULL)
            PyErr_SetNone(PyExc_StopIteration);

        return NULL;
    }

    if (f->f_lasti == -1) {
        if (arg && arg != Py_None) {
            PyErr_SetString(PyExc_TypeError,
                            "can't send non-None value to a "
                            "just-started generator");
            return NULL;
        }
    } else {
        /* Push arg onto the frame's value stack */
        result = arg ? arg : Py_None;
        Py_INCREF(result);
        *(f->f_stacktop++) = result;
    }

    f->f_back = _current_frame;
    _current_frame = f;
    f->f_depth = f->f_back ? f->f_back->f_depth + 1 : 0;
    gen->gen_running = 1;
    result = gen->gen_ptr(f);
    gen->gen_running = 0;
    _current_frame = f->f_back;

    /* If the generator just returned (as opposed to yielding), signal
     * that the generator is exhausted. */
    if (result == Py_None && f->f_lasti == -2) {
        Py_DECREF(result);
        result = NULL;
        gen->gen_exhausted = 1;
        /* Set exception if not called by gen_iternext() */
        if (arg)
            PyErr_SetNone(PyExc_StopIteration);
    }

    return result;
}

static PyObject* gen_iternext(PypperoniGenObject* gen)
{
    return gen_send_ex(gen, NULL);
}

static PyObject* gen_send(PypperoniGenObject* gen, PyObject* arg)
{
    return gen_send_ex(gen, arg);
}

static PyObject* gen_repr(PypperoniGenObject* gen)
{
    return PyString_FromFormat("<generator object %.200s at %p>",
                               gen->gen_name, gen);
}

static PyObject* gen_get_name(PypperoniGenObject* gen)
{
    return PyString_FromString(gen->gen_name);
}

static PyObject* gen_close(PypperoniGenObject* gen, PyObject* args)
{
    // This call cannot fail
    gen->gen_frame->f_lasti = -2;
    gen->gen_ptr(gen->gen_frame);

    gen->gen_exhausted = 1;
    Py_INCREF(Py_None);
    return Py_None;
}

static PyGetSetDef gen_getsetlist[] = {
    {"__name__", (getter)gen_get_name, NULL, ""},
    {NULL}
};

static PyMemberDef gen_memberlist[] = {
    {"gi_running", T_INT, offsetof(PypperoniGenObject, gen_running), RO},
    {NULL}      /* Sentinel */
};

static PyMethodDef gen_methods[] = {
    {"send", (PyCFunction)gen_send, METH_O, ""},
    {"close", (PyCFunction)gen_close, METH_NOARGS, ""},
    {NULL, NULL}        /* Sentinel */
};

PyTypeObject PyGen_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    "generator",                                /* tp_name */
    sizeof(PypperoniGenObject),                     /* tp_basicsize */
    0,                                          /* tp_itemsize */
    /* methods */
    (destructor)gen_dealloc,                    /* tp_dealloc */
    0,                                          /* tp_print */
    0,                                          /* tp_getattr */
    0,                                          /* tp_setattr */
    0,                                          /* tp_compare */
    (reprfunc)gen_repr,                         /* tp_repr */
    0,                                          /* tp_as_number */
    0,                                          /* tp_as_sequence */
    0,                                          /* tp_as_mapping */
    0,                                          /* tp_hash */
    0,                                          /* tp_call */
    0,                                          /* tp_str */
    PyObject_GenericGetAttr,                    /* tp_getattro */
    0,                                          /* tp_setattro */
    0,                                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,    /* tp_flags */
    0,                                          /* tp_doc */
    (traverseproc)gen_traverse,                 /* tp_traverse */
    0,                                          /* tp_clear */
    0,                                          /* tp_richcompare */
    offsetof(PypperoniGenObject, gen_weakreflist),  /* tp_weaklistoffset */
    PyObject_SelfIter,                          /* tp_iter */
    (iternextfunc)gen_iternext,                 /* tp_iternext */
    gen_methods,                                /* tp_methods */
    gen_memberlist,                             /* tp_members */
    gen_getsetlist,                             /* tp_getset */
    0,                                          /* tp_base */
    0,                                          /* tp_dict */
    0,                                          /* tp_descr_get */
    0,                                          /* tp_descr_set */
    0,                                          /* tp_dictoffset */
    0,                                          /* tp_init */
    0,                                          /* tp_alloc */
    0,                                          /* tp_new */
    0,                                          /* tp_free */
    0,                                          /* tp_is_gc */
    0,                                          /* tp_bases */
    0,                                          /* tp_mro */
    0,                                          /* tp_cache */
    0,                                          /* tp_subclasses */
    0,                                          /* tp_weaklist */
    0,                                          /* tp_del */
};

PyObject* PypperoniGen_New(PypperoniFrame* f, func_ptr_t func, const char* name)
{
    PypperoniGenObject* gen = PyObject_GC_New(PypperoniGenObject, &PyGen_Type);
    if (gen == NULL) {
        PypperoniFrame_Clear(f);
        return NULL;
    }

    gen->gen_frame = f;
    gen->gen_ptr = func;
    gen->gen_name = name;
    gen->gen_running = 0;
    gen->gen_exhausted = 0;
    gen->gen_weakreflist = NULL;
    _PyObject_GC_TRACK(gen);
    return (PyObject *)gen;
}


// Functions
typedef struct _func {
    PyObject_HEAD

    func_ptr_t func_ptr;

    PyObject* func_globals;
    PyObject* func_defaults;
    PyObject* func_closure;
    PyObject* func_name;
    PyObject* func_varnames;
    PyObject* func_cellvars;

    PyObject* func_dict;

    int func_flags;
    int func_argcount;
    int func_stacksize;
    int func_numcells;
    int func_numfast;
} PypperoniFunctionObject;

static PyMemberDef func_memberlist[] = {
    {"func_name", T_OBJECT, offsetof(PypperoniFunctionObject, func_name), READONLY},
    {NULL}      /* Sentinel */
};

static int func_set_dict(PypperoniFunctionObject* op, PyObject* dict)
{
    if (!dict || !PyDict_Check(dict))
    {
        PyErr_SetString(PyExc_TypeError, "expected a dict");
        return -1;
    }

    Py_DECREF(op->func_dict);
    op->func_dict = dict;
    Py_INCREF(op->func_dict);
    return 0;
}

static PyObject* func_get_dict(PypperoniFunctionObject* op)
{
    Py_INCREF(op->func_dict);
    return op->func_dict;
}

static int func_set_name(PypperoniFunctionObject* op, PyObject* name)
{
    if (!name || !PyString_Check(name))
    {
        PyErr_SetString(PyExc_TypeError, "expected a string");
        return -1;
    }

    Py_DECREF(op->func_name);
    op->func_name = name;
    Py_INCREF(op->func_name);
    return 0;
}

static PyObject* func_get_name(PypperoniFunctionObject* op)
{
    Py_INCREF(op->func_name);
    return op->func_name;
}

static int func_set_module(PypperoniFunctionObject*, PyObject*)
{
    return 0;
}

static PyObject* func_get_module(PypperoniFunctionObject*)
{
    return Py_BuildValue("s", "PypperoniFunction");
}

static PyGetSetDef func_getsetlist[] = {
    {"__dict__", (getter)func_get_dict, (setter)func_set_dict},
    {"__name__", (getter)func_get_name, (setter)func_set_name},
    {"__module__", (getter)func_get_module, (setter)func_set_module},
    {NULL} /* Sentinel */
};

static PyObject* func_call(PypperoniFunctionObject* func, PyObject* args, PyObject* kw)
{
    Py_ssize_t i, num_given, kwidx, num_cellvars;
    PyObject** co_varnames;
    PyObject* result = NULL;

    PypperoniFrame* f = PypperoniFrame_New(func->func_globals, NULL, NULL,
                                   func->func_stacksize,
                                   func->func_numcells,
                                   func->func_numfast);
    // Fill with default args:
    Py_ssize_t ndef = PySequence_Size(func->func_defaults);
    for (i = 0; i < ndef; ++i)
    {
        PyObject* x = PyTuple_GET_ITEM(func->func_defaults, i);
        Py_INCREF(x);
        f->f_fastlocals[func->func_argcount - ndef + i] = x;
    }

    // Unpack args:
    num_given = 0;
    if (args)
        num_given = PySequence_Size(args);

    if (num_given > func->func_argcount)
    {
        // Remaining args: either *args or error
        if (func->func_flags & CO_VARARGS)
        {
            f->f_fastlocals[func->func_argcount] = PyTuple_GetSlice(args,
                   func->func_argcount, num_given);
            num_given = func->func_argcount;
        }

        else
        {
            PyErr_Format(PyExc_TypeError,
                "%.200s() takes %s %d "
                "argument%s (%d given)",
                PyString_AsString(func->func_name),
                ndef ? "at most" : "exactly",
                func->func_argcount,
                func->func_argcount == 1 ? "" : "s",
                num_given);
            goto fail;
        }
    }

    else if (func->func_flags & CO_VARARGS)
    {
        f->f_fastlocals[func->func_argcount] = PyTuple_New(0);
    }

    for (i = 0; i < num_given; i++)
    {
        PyObject* x = PyTuple_GET_ITEM(args, i);
        Py_INCREF(x);
        f->f_fastlocals[i] = x;
    }

    // Deal with kw:
    kwidx = (func->func_flags & CO_VARARGS) ? 1 : 0;
    if (func->func_flags & CO_VARKEYWORDS)
        f->f_fastlocals[func->func_argcount + kwidx] = PyDict_New();

    if (kw != NULL)
    {
        PyObject *key, *value;
        Py_ssize_t pos = 0;
        while (PyDict_Next(kw, &pos, &key, &value)) {
            int j;
            // Check if key is an arg or belongs in kwdict
            if (key == NULL || !(PyString_Check(key) || PyUnicode_Check(key)))
            {
                PyErr_Format(PyExc_TypeError,
                    "%.200s() keywords must be strings",
                    PyString_AsString(func->func_name));
                goto fail;
            }
            /* Speed hack: do raw pointer compares. As names are
               normally interned this should almost always hit. */
            co_varnames = ((PyListObject *)(func->func_varnames))->ob_item;
            for (j = 0; j < func->func_argcount; j++) {
                PyObject *nm = co_varnames[j];
                if (nm == key)
                    goto kw_found;
            }
            /* Slow fallback, just in case */
            for (j = 0; j < func->func_argcount; j++) {
                PyObject *nm = co_varnames[j];
                int cmp = PyObject_RichCompareBool(
                    key, nm, Py_EQ);
                if (cmp > 0)
                    goto kw_found;
                else if (cmp < 0)
                    goto fail;
            }
            if (f->f_fastlocals[func->func_argcount + kwidx] == NULL) {
                PyErr_Format(PyExc_TypeError,
                             "%.200s() got an unexpected "
                             "keyword argument '%.400s'",
                             PyString_AsString(func->func_name),
                             PyString_AsString(key));
                goto fail;
            }
            PyDict_SetItem(f->f_fastlocals[func->func_argcount + kwidx], key, value);
            continue;

          kw_found:
            Py_INCREF(value);
            f->f_fastlocals[j] = value;
        }
    }

    // Look for missing args
    for (i = 0; i < func->func_argcount; ++i)
    {
        if (f->f_fastlocals[i] == NULL)
        {
            PyErr_Format(PyExc_TypeError,
                "%.200s() takes %s %d "
                "argument%s (%d given)",
                PyString_AsString(func->func_name),
                ((func->func_flags & CO_VARARGS) ||
                 ndef) ? "at least" : "exactly",
                func->func_argcount - ndef,
                (func->func_argcount - ndef) == 1 ? "" : "s",
                i);
            goto fail;
        }
    }

    // Closures:
    num_cellvars = PyList_GET_SIZE(func->func_cellvars);
    for (i = 0; i < num_cellvars; ++i)
    {
        if (PyCell_Get(f->f_cells[i]) != NULL)
            continue;

        int j;
        const char* cellname = PyString_AS_STRING(PyList_GET_ITEM(func->func_cellvars, i));
        co_varnames = ((PyListObject *)(func->func_varnames))->ob_item;
        for (j = 0; j < func->func_argcount; j++) {
            const char* nm = PyString_AS_STRING(co_varnames[j]);
            if (strcmp(nm, cellname) == 0)
            {
                PyCell_Set(f->f_cells[i], f->f_fastlocals[j]);
                goto found;
            }
        }

        found: continue;
    }

    for (i = 0; i < PyTuple_GET_SIZE(func->func_closure); ++i)
    {
        PyObject* o = PyTuple_GET_ITEM(func->func_closure, i);
        Py_INCREF(o);
        Py_DECREF(f->f_cells[i + num_cellvars]);
        f->f_cells[i + num_cellvars] = o;

        if (PyCell_Get(o) == NULL)
        {
            PyErr_Format(PyExc_RuntimeError, "cell %d of %s should not be empty!", i + num_cellvars, PyString_AsString(func->func_name));
            goto fail;
        }
    }

    if (func->func_flags & CO_GENERATOR)
        return PypperoniGen_New(f, func->func_ptr, PyString_AS_STRING(func->func_name));

    f->f_back = _current_frame;
    _current_frame = f;
    f->f_depth = f->f_back ? f->f_back->f_depth + 1 : 0;
    result = func->func_ptr(f);
    _current_frame = f->f_back;

 fail:
    PypperoniFrame_Clear(f);
    return result;
}

static PyObject* func_repr(PypperoniFunctionObject* func)
{
    return PyString_FromFormat("<PypperoniFunctionObject %.200s>",
                               PyString_AS_STRING(func->func_name));
}

static void func_dealloc(PypperoniFunctionObject* func)
{
    PyObject_GC_UnTrack(func);
    Py_TRASHCAN_SAFE_BEGIN(func)
    Py_XDECREF(func->func_globals);
    Py_XDECREF(func->func_defaults);
    Py_XDECREF(func->func_closure);
    Py_XDECREF(func->func_name);
    Py_XDECREF(func->func_varnames);
    Py_XDECREF(func->func_cellvars);
    Py_XDECREF(func->func_dict);
    PyObject_GC_Del(func);
    Py_TRASHCAN_SAFE_END(func)
}

static int func_traverse(PypperoniFunctionObject* func, visitproc visit, void* arg)
{
    Py_VISIT(func->func_globals);
    Py_VISIT(func->func_defaults);
    Py_VISIT(func->func_closure);
    Py_VISIT(func->func_name);
    Py_VISIT(func->func_varnames);
    Py_VISIT(func->func_cellvars);
    Py_VISIT(func->func_dict);
    return 0;
}

static void func_clear(PypperoniFunctionObject* func)
{
    Py_CLEAR(func->func_globals);
    Py_CLEAR(func->func_defaults);
    Py_CLEAR(func->func_closure);
    Py_CLEAR(func->func_name);
    Py_CLEAR(func->func_varnames);
    Py_CLEAR(func->func_cellvars);
    Py_CLEAR(func->func_dict);
}

static PyObject* func_descr_get(PyObject* func, PyObject* obj, PyObject* type)
{
    if (obj == Py_None)
        obj = NULL;
    return PyMethod_New(func, obj, type);
}

PyTypeObject PypperoniFunc_Type = {
    PyVarObject_HEAD_INIT(&PyType_Type, 0)
    "PypperoniFunction",
    sizeof(PypperoniFunctionObject),
    0,
    (destructor)func_dealloc,                   /*tp_dealloc*/
    0,                                          /*tp_print*/
    0,                                          /*tp_getattr*/
    0,                                          /*tp_setattr*/
    0,                                          /*tp_compare*/
    (reprfunc)func_repr,                        /*tp_repr*/
    0,                                          /*tp_as_number*/
    0,                                          /*tp_as_sequence*/
    0,                                          /*tp_as_mapping*/
    0,                                          /* tp_hash */
    (ternaryfunc)func_call,                     /* tp_call */
    0,                                          /* tp_str */
    0,                                          /* tp_getattro */
    0,                                          /* tp_setattro */
    0,                                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,    /* tp_flags */
    0,                                          /* tp_doc */
    (traverseproc)func_traverse,                /* tp_traverse */
    (inquiry)func_clear,                        /* tp_clear */
    0,                                          /* tp_richcompare */
    0,                                          /* tp_weaklistoffset */
    0,                                          /* tp_iter */
    0,                                          /* tp_iternext */
    0,                                          /* tp_methods */
    func_memberlist,                            /* tp_members */
    func_getsetlist,                            /* tp_getset */
    0,                                          /* tp_base */
    0,                                          /* tp_dict */
    func_descr_get,                             /* tp_descr_get */
    0,                                          /* tp_descr_set */
    offsetof(PypperoniFunctionObject, func_dict),   /* tp_dictoffset */
};

extern "C"
int PyFunction_Check(PyObject* op)
{
    return (Py_TYPE(op) == &PypperoniFunc_Type);
}

static PyObject* PypperoniFunction_New(void* ptr, PyObject* func_globals,
    PyObject* func_defaults, PyObject* func_closure,
    PyObject* func_name, PyObject* func_varnames, PyObject* func_cellvars,
    int func_flags, int func_argcount, int func_stacksize, int func_numcells,
    int func_numfast)
{
    PypperoniFunctionObject* func = PyObject_GC_New(PypperoniFunctionObject, &PypperoniFunc_Type);
    if (func == NULL)
        return NULL;

    func->func_ptr = (func_ptr_t)ptr;

    Py_INCREF(func_globals);
    func->func_globals = func_globals;
    Py_INCREF(func_defaults);
    func->func_defaults = func_defaults;
    Py_INCREF(func_closure);
    func->func_closure = func_closure;
    Py_INCREF(func_name);
    func->func_name = func_name;
    Py_INCREF(func_varnames);
    func->func_varnames = func_varnames;
    Py_INCREF(func_cellvars);
    func->func_cellvars = func_cellvars;

    func->func_dict = PyDict_New();

    func->func_flags = func_flags;
    func->func_argcount = func_argcount;
    func->func_stacksize = func_stacksize;
    func->func_numcells = func_numcells;
    func->func_numfast = func_numfast;

    return (PyObject*) func;
}


const char* __pypperoni_const2str(PyObject* strobj)
{
    Py_DECREF(strobj);
    return PyString_AS_STRING(strobj);
}

static PyObject*
string_concatenate(PyObject* v, PyObject* w)
{
    Py_ssize_t v_len = PyString_GET_SIZE(v);
    Py_ssize_t w_len = PyString_GET_SIZE(w);
    Py_ssize_t new_len = v_len + w_len;
    if (new_len < 0) {
        PyErr_SetString(PyExc_OverflowError,
                        "strings are too large to concat");
        return NULL;
    }

    Py_INCREF(v); // PyString_Concat steals the ref
    PyString_Concat(&v, w);
    return v;
}

static PyObject*
cmp_outcome(int op, register PyObject* v, register PyObject* w)
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
            return NULL;
        break;
    case PyCmp_NOT_IN:
        res = PySequence_Contains(w, v);
        if (res < 0)
            return NULL;
        res = !res;
        break;
    case PyCmp_EXC_MATCH:
        if (PyTuple_Check(w)) {
            Py_ssize_t i, length;
            length = PyTuple_Size(w);
            for (i = 0; i < length; i += 1) {
                PyObject *exc = PyTuple_GET_ITEM(w, i);
                if (PyString_Check(exc)) {
                    int ret_val;
                    ret_val = PyErr_WarnEx(
                        PyExc_DeprecationWarning,
                        "catching of string "
                        "exceptions is deprecated", 1);
                    if (ret_val < 0)
                        return NULL;
                }
            }
        }
        else {
            if (PyString_Check(w)) {
                int ret_val;
                ret_val = PyErr_WarnEx(
                                PyExc_DeprecationWarning,
                                "catching of string "
                                "exceptions is deprecated", 1);
                if (ret_val < 0)
                    return NULL;
            }
        }
        res = PyErr_GivenExceptionMatches(v, w);
        break;
    default:
        return PyObject_RichCompare(v, w, op);
    }
    v = res ? Py_True : Py_False;
    Py_INCREF(v);
    return v;
}

PyObject* __pypperoni_IMPL_load_name(PypperoniFrame* f, PyObject* name)
{
    if (f->f_locals == NULL)
    {
        PyErr_Format(PyExc_SystemError,
                     "no locals when loading %.200s",
                     name);
        return NULL;
    }

    PyObject* x = NULL;
    PyObject* v = f->f_locals;
    if (PyDict_CheckExact(v)) {
        x = PyDict_GetItem(v, name);
        Py_XINCREF(x);
    }
    else {
        x = PyObject_GetItem(v, name);
        if (x == NULL && PyErr_Occurred()) {
            if (!PyErr_ExceptionMatches(PyExc_KeyError))
            {
                Py_DECREF(name);
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
                PyErr_Format(PyExc_NameError, "name '%.200s' is not defined", PyString_AS_STRING(name));
                Py_DECREF(name);
                return NULL;
            }
        }
        Py_INCREF(x);
    }

    Py_DECREF(name);
    return x;
}

PyObject* __pypperoni_IMPL_load_global(PypperoniFrame* f, PyObject* name)
{
    PyObject* x = NULL;

    /* Inline the PyDict_GetItem() calls.
       WARNING: this is an extreme speed hack.
       Do not try this at home. */
    long hash = ((PyStringObject *)name)->ob_shash;
    if (hash != -1) {
        PyDictObject *d;
        PyDictEntry *e;
        d = (PyDictObject *)(f->f_globals);
        e = d->ma_lookup(d, name, hash);
        if (e == NULL) {
            Py_DECREF(name);
            return NULL;
        }
        x = e->me_value;
        if (x != NULL) {
            Py_INCREF(x);
            Py_DECREF(name);
            return x;
        }
        d = (PyDictObject *)(f->f_builtins);
        e = d->ma_lookup(d, name, hash);
        if (e == NULL) {
            Py_DECREF(name);
            return NULL;
        }
        x = e->me_value;
        if (x != NULL) {
            Py_INCREF(x);
            Py_DECREF(name);
            return x;
        }
        goto load_global_error;
    }
    /* This is the un-inlined version of the code above */
    x = PyDict_GetItem(f->f_globals, name);
    if (x == NULL) {
        x = PyDict_GetItem(f->f_builtins, name);
        if (x == NULL) {
          load_global_error:
            PyErr_Format(PyExc_NameError, "name '%.200s' is not defined", PyString_AS_STRING(name));
            x = NULL;
        }
    }

    Py_DECREF(name);
    return x;
}

PyObject* __pypperoni_IMPL_load_deref(PypperoniFrame* f, Py_ssize_t index)
{
    PyObject* w = PyCell_Get(f->f_cells[index]);
    if (w == NULL) {
        PyErr_Format(PyExc_UnboundLocalError, "failed to load deref %d", index);
    }
    return w;
}

PyObject* __pypperoni_IMPL_load_closure(PypperoniFrame* f, Py_ssize_t index)
{
    PyObject* w = f->f_cells[index];
    if (w == NULL) {
        PyErr_Format(PyExc_UnboundLocalError, "failed to load closure %d", index);
    }
    return w;
}

Py_ssize_t __pypperoni_IMPL_store_name(PypperoniFrame* f, PyObject* name, PyObject* obj)
{
    Py_ssize_t err;
    if (f->f_locals == NULL)
    {
        PyErr_Format(PyExc_SystemError,
                     "no locals when storing %.200s",
                     PyString_AS_STRING(name));
        err = 1;
    }

    else
    {
        if (PyDict_CheckExact(f->f_locals))
            err = PyDict_SetItem(f->f_locals, name, obj);
        else
        {
            err = PyObject_SetItem(f->f_locals, name, obj);
            Py_DECREF(name);
        }
    }

    return err;
}

Py_ssize_t __pypperoni_IMPL_store_global(PypperoniFrame* f, PyObject* name, PyObject* obj)
{
    Py_ssize_t result = PyDict_SetItem(f->f_globals, name, obj);
    Py_DECREF(name);
    return result;
}

Py_ssize_t __pypperoni_IMPL_store_deref(PypperoniFrame* f, PyObject* obj,
                                    Py_ssize_t index)
{
    PyCell_Set(f->f_cells[index], obj);
    return 0;
}

static int __init_module_obj(PypperoniModule* mod)
{
    PyObject *m, *d, *result;
    PypperoniFrame* f;

    if (mod->type == MODULE_BUILTIN)
    {
        mod->obj = Py_ImportBuiltin(mod->name);
        if (mod->obj == NULL)
            PyErr_Format(PyExc_ImportError, "unknown module %.200s", mod->name);

        return (mod->obj != NULL);
    }

    func_ptr_t ptr = (func_ptr_t)(mod->ptr);

    m = PyImport_AddModule(mod->name);
    Py_INCREF(m);
    mod->obj = m;
    d = PyModule_GetDict(m);

    // Get a frame
    f = PypperoniFrame_New(d, d, NULL, mod->val_1, mod->val_2, mod->val_3);
    if (f == NULL)
        return 0;

    // Set a few attributes
    PyDict_SetItemString(d, "__file__", PyString_FromString(mod->name));
    PyDict_SetItemString(d, "__builtins__", f->f_builtins);

    // Execute the function
    f->f_back = _current_frame;
    _current_frame = f;
    f->f_depth = f->f_back ? f->f_back->f_depth + 1 : 0;
    result = ptr(f);
    _current_frame = f->f_back;

    PypperoniFrame_Clear(f);

    return (result == NULL) ? 0 : 1;
}

static PypperoniModule* __get_module(Py_ssize_t index)
{
    for (auto mod : get_pypperoni_modules())
    {
        if (mod->index == index)
            return mod;
    }

    return NULL;
}

static int __init_module(Py_ssize_t index)
{
    /* Returns 1 on success and 0 on failure */
    PypperoniModule* mod = __get_module(index);
    if (mod == NULL)
        return 0;

    if (mod->obj != NULL)
        return 1; // already initialized

    return __init_module_obj(mod);
}

PyObject* __pypperoni_IMPL_import(Py_ssize_t index)
{
    PypperoniModule* mod = __get_module(index);
    if (mod == NULL)
    {
        PyErr_Format(PyExc_ImportError, "unknown module %d", index);
        return NULL;
    }

    if (mod->obj != NULL)
    {
        Py_INCREF(mod->obj);
        return mod->obj;
    }

    if (mod->parent != -1)
        if (!__init_module(mod->parent))
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

PyObject* __pypperoni_IMPL_import_from_or_module(PyObject* mod, PyObject* name, Py_ssize_t index)
{
    PyObject* x = PyObject_GetAttr(mod, name);
    if (x == NULL && PyErr_ExceptionMatches(PyExc_AttributeError)) {
        PyErr_Clear();
        x = __pypperoni_IMPL_import(index);
    }
    return x;
}

Py_ssize_t __pypperoni_IMPL_import_star(PypperoniFrame* f, PyObject* mod)
{
    PyObject *all = PyObject_GetAttrString(mod, "__all__");
    PyObject *dict, *name, *value;
    int skip_leading_underscores = 0;
    int pos, err;

    if (all == NULL) {
        if (!PyErr_ExceptionMatches(PyExc_AttributeError))
            return -1; /* Unexpected error */
        PyErr_Clear();
        dict = PyObject_GetAttrString(mod, "__dict__");
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
        if (skip_leading_underscores &&
            PyString_Check(name) &&
            PyString_AS_STRING(name)[0] == '_')
        {
            Py_DECREF(name);
            continue;
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

Py_ssize_t __pypperoni_IMPL_do_print(PyObject* stream, PyObject* obj)
{
    Py_ssize_t err = 0;
    if (stream == NULL || stream == Py_None)
    {
        stream = PySys_GetObject("stdout");
        if (stream == NULL) {
            PyErr_SetString(PyExc_RuntimeError,
                            "lost sys.stdout");
            return 1;
        }
    }

    if (obj == NULL) // newline
    {
        Py_INCREF(stream);
        err = PyFile_WriteString("\n", stream);
        if (err == 0)
            PyFile_SoftSpace(stream, 0);
        Py_DECREF(stream);
        return err;
    }

    /* PyFile_SoftSpace() can execute arbitrary code
       if sys.stdout is an instance with a __getattr__.
       If __getattr__ raises an exception, stream will
       be freed, so we need to prevent that temporarily. */
    Py_INCREF(stream);
    if (PyFile_SoftSpace(stream, 0))
        PyFile_WriteString(" ", stream);
    if (err == 0) {
        err = PyFile_WriteObject(obj, stream, Py_PRINT_RAW);
    }
    if (err == 0) {
        if (PyString_Check(obj)) {
            char *s = PyString_AS_STRING(obj);
            Py_ssize_t len = PyString_GET_SIZE(obj);
            if (len == 0 ||
                !isspace(Py_CHARMASK(s[len-1])) ||
                s[len-1] == ' ')
                PyFile_SoftSpace(stream, 1);
        }
 #ifdef Py_USING_UNICODE
        else if (PyUnicode_Check(obj)) {
            Py_UNICODE *s = PyUnicode_AS_UNICODE(obj);
            Py_ssize_t len = PyUnicode_GET_SIZE(obj);
            if (len == 0 ||
                !Py_UNICODE_ISSPACE(s[len-1]) ||
                s[len-1] == ' ')
                PyFile_SoftSpace(stream, 1);
        }
 #endif
        else
            PyFile_SoftSpace(stream, 1);
    }
    Py_DECREF(stream);
    return err;
}

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
                                  int func_numfast)
{
    if (func_defaults == NULL)
        func_defaults = PyTuple_New(0);

    if (closure == NULL)
        closure = PyTuple_New(0);

    *result = PypperoniFunction_New(ptr, globals,
        func_defaults, closure, name, varnames,
        cellvars, func_flags, func_argcount, func_stacksize,
        func_numcells, func_numfast);

    return 0;
}

Py_ssize_t __pypperoni_IMPL_call_func(PyObject* func, PyObject** result,
                                   PyObject* pargs, PyObject* kwargs)
{
    if (PyMethod_Check(func) && PyMethod_GET_SELF(func) != NULL) {
        PyObject* self = PyMethod_GET_SELF(func);
        PyList_Insert(pargs, 0, self);
        func = PyMethod_GET_FUNCTION(func);
    }

    PyObject* pargstuple = (pargs == NULL) ? NULL : PySequence_Tuple(pargs);

    if (PyCFunction_Check(func)) {
        *result = PyCFunction_Call(func, pargstuple, kwargs);
    }
    else
        *result = PyObject_Call(func, pargstuple, kwargs);

    Py_XDECREF(pargstuple);
    return (*result == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_check_cond(PyObject* obj, int* result)
{
    Py_ssize_t err;

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

Py_ssize_t __pypperoni_IMPL_compare(PyObject* w, PyObject* v, Py_ssize_t op, PyObject** result)
{
    if (PyInt_CheckExact(w) && PyInt_CheckExact(v)) {
        /* INLINE: cmp(int, int) */
        register long a, b;
        register int res;
        a = PyInt_AS_LONG(v);
        b = PyInt_AS_LONG(w);
        switch (op) {
        case PyCmp_LT: res = a <  b; break;
        case PyCmp_LE: res = a <= b; break;
        case PyCmp_EQ: res = a == b; break;
        case PyCmp_NE: res = a != b; break;
        case PyCmp_GT: res = a >  b; break;
        case PyCmp_GE: res = a >= b; break;
        case PyCmp_IS: res = v == w; break;
        case PyCmp_IS_NOT: res = v != w; break;
        default: goto slow_compare;
        }
        *result = res ? Py_True : Py_False;
        Py_INCREF(*result);
    }
    else {
      slow_compare:
        *result = cmp_outcome(op, v, w);
    }

    return (*result == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_for_iter(PyObject* v, PyObject** result)
{
    if (v->ob_type->tp_iternext == NULL)
    {
        PyErr_Format(PyExc_TypeError, "'%.200s' type is not iterable", v->ob_type->tp_name);
        return 1;
    }

    *result = (*v->ob_type->tp_iternext)(v);
    if (*result != NULL)
        return 0;

    if (PyErr_Occurred()) {
        if (!PyErr_ExceptionMatches(PyExc_StopIteration))
            return 1;

        PyErr_Clear();
    }

    return 0;
}

Py_ssize_t __pypperoni_IMPL_build_class(PyObject* methods, PyObject* bases, PyObject* classname, PyObject** result)
{
    PyObject *metaclass = NULL, *base;

    if (PyDict_Check(methods))
        metaclass = PyDict_GetItemString(methods, "__metaclass__");
    if (metaclass != NULL)
        Py_INCREF(metaclass);
    else if (PyTuple_Check(bases) && PyTuple_GET_SIZE(bases) > 0) {
        base = PyTuple_GET_ITEM(bases, 0);
        metaclass = PyObject_GetAttrString(base, "__class__");
        if (metaclass == NULL) {
            PyErr_Clear();
            metaclass = (PyObject *)base->ob_type;
            Py_INCREF(metaclass);
        }
    }
    else {
        PyObject *g = PyEval_GetGlobals();
        if (g != NULL && PyDict_Check(g))
            metaclass = PyDict_GetItemString(g, "__metaclass__");
        if (metaclass == NULL)
            metaclass = (PyObject *) &PyClass_Type;
        Py_INCREF(metaclass);
    }

    *result = PyObject_CallFunctionObjArgs(metaclass, classname, bases, methods,
                                           NULL);
    Py_DECREF(metaclass);

    return (*result == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_unpack_sequence(PyObject* v, PyObject** array, Py_ssize_t num)
{
    int i;
    PyObject *it;
    PyObject *w;

    if (PyTuple_CheckExact(v) &&
        PyTuple_GET_SIZE(v) == num) {
        PyObject **items = \
            ((PyTupleObject *)v)->ob_item;
        while (num--) {
            w = items[num];
            Py_INCREF(w);
            array[num] = w;
        }
        Py_DECREF(v);
        return 0;
    }

    if (PyList_CheckExact(v) &&
        PyList_GET_SIZE(v) == num) {
        PyObject **items = \
            ((PyListObject *)v)->ob_item;
        while (num--) {
            w = items[num];
            Py_INCREF(w);
            array[num] = w;
        }
        return 0;
    }

    it = PyObject_GetIter(v);
    if (it == NULL)
        goto unpack_error;

    // Initialize the array with NULLs
    for (i = 0; i < num; i++)
        array[i] = NULL;

    // Fill it
    for (i = 0; i < num; i++)
    {
        w = PyIter_Next(it);
        if (w == NULL)
        {
            /* Iterator done, via error or exhaustion. */
            if (!PyErr_Occurred())
            {
                PyErr_Format(PyExc_ValueError,
                    "need more than %d value%s to unpack",
                    i, i == 1 ? "" : "s");
            }
            goto unpack_error;
        }
        array[i] = w;
    }

    /* We better have exhausted the iterator now. */
    w = PyIter_Next(it);
    if (w == NULL)
    {
        if (PyErr_Occurred())
            goto unpack_error;
        Py_DECREF(it);
        return 0;
    }
    Py_DECREF(w);
    PyErr_SetString(PyExc_ValueError, "too many values to unpack");

 unpack_error:
    for (i = 0; i < num; i++) {
        Py_XDECREF(array[i]);
        array[i] = NULL;
    }

    Py_XDECREF(it);
    return 1;
}

Py_ssize_t __pypperoni_IMPL_apply_slice(PyObject* u, PyObject* v, PyObject* w, PyObject** result)
{
#define ISINDEX(x) ((x) == NULL || PyInt_Check(x) || PyLong_Check(x) || PyIndex_Check(x))

    PyTypeObject *tp = u->ob_type;
    PySequenceMethods *sq = tp->tp_as_sequence;

    if (sq && sq->sq_slice && ISINDEX(v) && ISINDEX(w))
    {
        Py_ssize_t ilow = 0, ihigh = PY_SSIZE_T_MAX;
        if (!_PyEval_SliceIndex(v, &ilow))
        {
            *result = NULL;
            return 1;
        }
        if (!_PyEval_SliceIndex(w, &ihigh))
        {
            *result = NULL;
            return 1;
        }
        *result = PySequence_GetSlice(u, ilow, ihigh);
        return (*result == NULL) ? 1 : 0;
    }
    else
    {
        PyObject *slice = PySlice_New(v, w, NULL);
        if (slice != NULL) {
            *result = PyObject_GetItem(u, slice);
            Py_DECREF(slice);
            return (*result == NULL) ? 1 : 0;
        }
        else
        {
            *result = NULL;
            return 1;
        }
    }
}

Py_ssize_t __pypperoni_IMPL_assign_slice(PyObject* u, PyObject* v, PyObject* w, PyObject* x)
{
    PyTypeObject *tp = u->ob_type;
    PySequenceMethods *sq = tp->tp_as_sequence;

    if (sq && sq->sq_ass_slice && ISINDEX(v) && ISINDEX(w))
    {
        Py_ssize_t ilow = 0, ihigh = PY_SSIZE_T_MAX;
        if (!_PyEval_SliceIndex(v, &ilow))
            return -1;
        if (!_PyEval_SliceIndex(w, &ihigh))
            return -1;
        if (x == NULL)
            return PySequence_DelSlice(u, ilow, ihigh);
        else
            return PySequence_SetSlice(u, ilow, ihigh, x);
    }
    else
    {
        PyObject *slice = PySlice_New(v, w, NULL);
        if (slice != NULL)
        {
            int res;
            if (x != NULL)
                res = PyObject_SetItem(u, slice, x);
            else
                res = PyObject_DelItem(u, slice);
            Py_DECREF(slice);
            return res;
        }
        else
            return -1;
    }
}

void __pypperoni_IMPL_do_raise(PyObject* type, PyObject* value, PyObject* tb)
{
    if (type == NULL) {
        /* Reraise */
        PyErr_Fetch(&type, &value, &tb);
        if (type == NULL)
            type = Py_None;

        Py_INCREF(type);
        Py_XINCREF(value);
        Py_XINCREF(tb);
    }

    /* First, check the traceback argument, replacing None with
       NULL. */
    if (tb == Py_None) {
        Py_DECREF(tb);
        tb = NULL;
    }

    /* Next, replace a missing value with None */
    if (value == NULL) {
        value = Py_None;
        Py_INCREF(value);
    }

    /* Next, repeatedly, replace a tuple exception with its first item */
    while (PyTuple_Check(type) && PyTuple_Size(type) > 0) {
        PyObject *tmp = type;
        type = PyTuple_GET_ITEM(type, 0);
        Py_INCREF(type);
        Py_DECREF(tmp);
    }

    if (PyExceptionClass_Check(type)) {
        PyErr_NormalizeException(&type, &value, &tb);
        if (!PyExceptionInstance_Check(value)) {
            PyErr_Format(PyExc_TypeError,
                         "calling %s() should have returned an instance of "
                         "BaseException, not '%s'",
                         ((PyTypeObject *)type)->tp_name,
                         Py_TYPE(value)->tp_name);
            goto raise_error;
        }
    }
    else if (PyExceptionInstance_Check(type)) {
        /* Raising an instance.  The value should be a dummy. */
        if (value != Py_None) {
            PyErr_SetString(PyExc_TypeError,
              "instance exception may not have a separate value");
            goto raise_error;
        }
        else {
            /* Normalize to raise <class>, <instance> */
            Py_DECREF(value);
            value = type;
            type = PyExceptionInstance_Class(type);
            Py_INCREF(type);
        }
    }
    else {
        /* Not something you can raise.  You get an exception
           anyway, just not what you specified :-) */

        PyErr_Format(PyExc_TypeError,
                     "exceptions must be old-style classes or "
                     "derived from BaseException, not %s",
                     type->ob_type->tp_name);
        goto raise_error;
    }

    PyErr_Restore(type, value, tb);
    return;

 raise_error:
    Py_XDECREF(value);
    Py_XDECREF(type);
    Py_XDECREF(tb);
}

void __pypperoni_IMPL_raise(PyObject* exc, const char* msg)
{
    PyErr_SetString(exc, msg);
}

Py_ssize_t __pypperoni_IMPL_delete_name(PypperoniFrame* f, PyObject* name)
{
    Py_ssize_t err;

    if (f->f_locals != NULL)
    {
        err = PyObject_DelItem(f->f_locals, name);
        if (err != 0)
        {
            PyErr_Format(PyExc_NameError, "name '%.200s' is not defined", PyString_AS_STRING(name));
        }
    }

    else
    {
        PyErr_Format(PyExc_SystemError, "no locals when deleting %.200s", PyString_AS_STRING(name));
        err = 1;
    }

    Py_DECREF(name);
    return err;
}

Py_ssize_t __pypperoni_IMPL_setup_with(PyObject* v, PyObject** exitptr, PyObject** result)
{
    PyObject* enterptr;

    *exitptr = PyObject_GetAttrString(v, "__exit__");
    if (*exitptr == NULL)
    {
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_AttributeError, "__exit__ not found");
        *result = NULL;
        return 1;
    }

    enterptr = PyObject_GetAttrString(v, "__enter__");
    if (enterptr == NULL)
    {
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_AttributeError, "__enter__ not found");
        Py_DECREF(*exitptr);
        *exitptr = NULL;
        *result = NULL;
        return 1;
    }

    *result = PyObject_CallFunctionObjArgs(enterptr, NULL);
    Py_DECREF(enterptr);
    if (*result == NULL)
    {
        Py_DECREF(*exitptr);
        *exitptr = NULL;
        return 1;
    }

    return 0;
}

Py_ssize_t __pypperoni_IMPL_exit_with(PyObject* v)
{
    PyObject* x = PyObject_CallFunctionObjArgs(v, Py_None, Py_None, Py_None, NULL);
    Py_XDECREF(x);
    return (x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_power(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Power(v, w, Py_None);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_multiply(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Multiply(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_divide(PyObject* v, PyObject* w, PyObject** x)
{
    if (_Py_QnewFlag) return __pypperoni_IMPL_binary_true_divide(v, w, x);
    *x = PyNumber_Divide(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_modulo(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyString_CheckExact(v))
        *x = PyString_Format(v, w);
    else
        *x = PyNumber_Remainder(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_add(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyInt_CheckExact(v) && PyInt_CheckExact(w)) {
        /* INLINE: int + int */
        register long a, b, i;
        a = PyInt_AS_LONG(v);
        b = PyInt_AS_LONG(w);
        /* cast to avoid undefined behaviour
           on overflow */
        i = (long)((unsigned long)a + b);
        if ((i^a) < 0 && (i^b) < 0)
            goto slow_add;
        *x = PyInt_FromLong(i);
    }
    else if (PyString_CheckExact(v) &&
             PyString_CheckExact(w)) {
        *x = string_concatenate(v, w);
    }
    else {
      slow_add:
        *x = PyNumber_Add(v, w);
    }
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_subtract(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyInt_CheckExact(v) && PyInt_CheckExact(w)) {
        /* INLINE: int - int */
        register long a, b, i;
        a = PyInt_AS_LONG(v);
        b = PyInt_AS_LONG(w);
        /* cast to avoid undefined behaviour
           on overflow */
        i = (long)((unsigned long)a - b);
        if ((i^a) < 0 && (i^~b) < 0)
            goto slow_sub;
        *x = PyInt_FromLong(i);
    }
    else {
      slow_sub:
        *x = PyNumber_Subtract(v, w);
    }

    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_subscr(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyList_CheckExact(v) && PyInt_CheckExact(w)) {
        /* INLINE: list[int] */
        Py_ssize_t i = PyInt_AsSsize_t(w);
        if (i < 0)
            i += PyList_GET_SIZE(v);
        if (i >= 0 && i < PyList_GET_SIZE(v)) {
            *x = PyList_GET_ITEM(v, i);
            Py_INCREF(*x);
        }
        else
            goto slow_get;
    }
    else
      slow_get:
        *x = PyObject_GetItem(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_floor_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceFloorDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_true_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_TrueDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_lshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Lshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_rshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Rshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_and(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_And(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_xor(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Xor(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_binary_or(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_Or(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_floor_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceFloorDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_true_divide(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceTrueDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_add(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyInt_CheckExact(v) && PyInt_CheckExact(w)) {
        /* INLINE: int + int */
        register long a, b, i;
        a = PyInt_AS_LONG(v);
        b = PyInt_AS_LONG(w);
        i = a + b;
        if ((i^a) < 0 && (i^b) < 0)
            goto slow_iadd;
        *x = PyInt_FromLong(i);
    }
    else if (PyString_CheckExact(v) &&
             PyString_CheckExact(w)) {
        *x = string_concatenate(v, w);
    }
    else {
      slow_iadd:
        *x = PyNumber_InPlaceAdd(v, w);
    }
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_subtract(PyObject* v, PyObject* w, PyObject** x)
{
    if (PyInt_CheckExact(v) && PyInt_CheckExact(w)) {
        /* INLINE: int - int */
        register long a, b, i;
        a = PyInt_AS_LONG(v);
        b = PyInt_AS_LONG(w);
        i = a - b;
        if ((i^a) < 0 && (i^~b) < 0)
            goto slow_isub;
        *x = PyInt_FromLong(i);
    }
    else {
      slow_isub:
        *x = PyNumber_InPlaceSubtract(v, w);
    }
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_multiply(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceMultiply(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_divide(PyObject* v, PyObject* w, PyObject** x)
{
    if (_Py_QnewFlag) return __pypperoni_IMPL_inplace_true_divide(v, w, x);
    *x = PyNumber_InPlaceDivide(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_modulo(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceRemainder(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_power(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlacePower(v, w, Py_None);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_lshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceLshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_rshift(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceRshift(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_and(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceAnd(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_xor(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceXor(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_inplace_or(PyObject* v, PyObject* w, PyObject** x)
{
    *x = PyNumber_InPlaceOr(v, w);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_unary_positive(PyObject* v, PyObject** x)
{
    *x = PyNumber_Positive(v);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_unary_negative(PyObject* v, PyObject** x)
{
    *x = PyNumber_Negative(v);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_unary_not(PyObject* v, PyObject** x)
{
    Py_ssize_t err;
    err = PyObject_IsTrue(v);
    if (err == 0) {
        Py_INCREF(Py_True);
        *x = Py_True;
    }
    else if (err > 0) {
        Py_INCREF(Py_False);
        *x = Py_False;
        err = 0;
    }
    return err;
}

PyObject* __pypperoni_pyint(long value)
{
    static std::map<long, PyObject*> __pyints;
    if (__pyints.find(value) != __pyints.end())
        return __pyints[value];

    PyObject* v = PyInt_FromLong(value);
    return __pyints[value] = v;
}

Py_ssize_t __pypperoni_IMPL_unary_convert(PyObject* v, PyObject** x)
{
    *x = PyObject_Repr(v);
    return (*x == NULL) ? 1 : 0;
}

Py_ssize_t __pypperoni_IMPL_unary_invert(PyObject* v, PyObject** x)
{
    *x = PyNumber_Invert(v);
    return (*x == NULL) ? 1 : 0;
}

PyObject *
PyEval_GetBuiltins(void)
{
    if (_current_frame == NULL)
        return PyThreadState_GET()->interp->builtins;
    return _current_frame->f_builtins;
}

PyObject *
PyEval_GetLocals(void)
{
    if (_current_frame == NULL)
        return NULL;
    return _current_frame->f_locals;
}

PyObject *
PyEval_GetGlobals(void)
{
    if (_current_frame == NULL)
        return NULL;
    return _current_frame->f_globals;
}

static PyMethodDef PypperoniMethods[] = {{NULL, NULL, 0}};

void setup_pypperoni()
{
    // Setup __pypperoni__
    PyObject* pypperonimod = Py_InitModule("__pypperoni__", PypperoniMethods);
    PyObject* bt = Py_GetBuiltinModule();
    PyObject_SetAttrString(bt, "__pypperoni__", pypperonimod);
    Py_INCREF(pypperonimod);
    Py_DECREF(bt);

    PyObject_SetAttrString(pypperonimod, "platform", PyString_FromString(
#ifdef WIN32
      "windows"
#elif ANDROID
      "android"
#elif __APPLE__
      "mac"
#elif __linux
      "linux"
#endif
    ));
}

static PyMethodDef def;

int __pypperoni_IMPL_main()
{
    if (PyType_Ready(&PypperoniFunc_Type) < 0)
        return -1;

    if (PyType_Ready(&PyGen_Type) < 0)
        return -2;

    PyObject* m = Py_ImportBuiltin("__pypperoni__");
    def.ml_name = "describeException";
    def.ml_meth = (PyCFunction)Py_PypperoniTraceback_Format;
    def.ml_flags = METH_NOARGS;
    PyObject* _format = PyCFunction_New(&def, NULL);
    PyObject_SetAttrString(m, "describeException", _format);
    Py_DECREF(m);

    if (__pypperoni_IMPL_import(0) != NULL)
        return 0;

    return 1;
}
