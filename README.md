# Pypperoni Compiler

<img align="left" width="100" height="100" src="https://i.imgur.com/zSG7wSw.png" alt="Pypperoni Logo">

Pypperoni is a free and open source Python compiler and bytecode preprocessor designed and maintained by the developers of [The Legend of Pirates Online](https://tlopo.com/), a fan-made recreation of Disney's Pirates of the Caribbean Online.

This is the main source code repository.

## Overview

Python, by design, is an interpreted programming language. This means that a Python program's source code is first compiled to a bytecode format and then interpreted at runtime. This can lead to certain security issues, such as bytecode dumping and injection.

Pypperoni's main objective is to eliminate the interpreter by preprocessing your bytecode and expanding it to Python C API calls at compile time.


## Getting Started
### Downloading Sample Projects
To best get a feel of how Pypperoni works, try downloading one of our many [sample projects](http://github.com/pypperoni/sample-projects). To get started, please follow each project's included guide on how to set them up. These samples are a good example of how to properly structure your own Pypperoni project.


## Why use Pypperoni?
Pypperoni was designed with security as a central focus. Our compiler provides you with the necessary tools to run a secure and high quality Python application.

With the removal of the interpreter, it is practically impossible to inject Python code into your program and/or recover the original source code.

Additionally, by preprocessing the bytecode there may be a performance boost in your application.

## How does Pypperoni work?
When Pypperoni is ran, it will compile all of your Python application's source code (`*.py`) into Python bytecode (`*.pyc`). An example of Python bytecode is shown below:

```
15 SETUP_LOOP              41 (to 59)
18 LOAD_NAME                1 (enumerate)
```

Next, Pypperoni will read through the bytecode, interpreting the Python OP codes into the equivalent Python C API calls; this is what we call "preprocessing the bytecode." The following example is the output from preprocessing the above bytecode:

```
label_15:
// SETUP_LOOP (15 -> 59)
PyDict_SetItem(f->f_stacklevel, __pypperoni_pyint(15), __pypperoni_pyint(STACK_LEVEL()));

label_18:
{
  x = __pypperoni_IMPL_load_name(f, __pypperoni_const2str(__example_get_const(4)) /* enumerate */);
  if (x == NULL) {
    f->f_exci = 18;
    f->f_excline = 2;
    goto error;
  }
  Py_INCREF(x);
  PUSH(x);
}
```

This C code is then compiled as a normal C application, and an executable is generated.

## Documentation
Pypperoni is still in its infancy. We will be writing and publishing documentation over time [here](http://pypperoni.github.io/).

## Development
### Background
Pypperoni was developed initially as an in-house compiler for the free online game, The Legend of Pirates Online ("TLOPO"). TLOPO, which is almost entirely written in Python, had to come up with many creative solutions for security problems intrinsic to the Python programming language, such as Python injection.

They recognized the numerous security and performance issues associated with running a production application written in Python, and thus sought out to reinvent the way we traditionally think about Python compilers. Pypperoni is the result of this vision.

Previously, TLOPO maintained their own custom and open source compiler named [Nirai](https://github.com/nirai-compiler). Unlike Pypperoni, Nirai was designed to be specifically used alongside the Panda3D game engine. Pypperoni is the successor to Nirai and is designed to be compatible with any application written in Python 2.7.


### Maintainers
- **[@loblao](https://github.com/loblao) Nacib Neme** is Pypperoni's lead architect and designer.
- **[@mfwass](https://github.com/mfwass) Michael Wass** is a maintainer of Pypperoni.


## License
Pypperoni is licensed under the MIT License; you may not use it except in compliance with the License.

You may obtain a copy of the License [here](LICENSE.txt).

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.


## Contributors
We welcome any potential contributors! But before hacking away and sending off a bunch of new pull requests, please check out the current issues and pull requests. If you would like to add a new feature or fix a bug, please submit an issue describing the bug or feature. This way we can always make sure we're all on the same page.
