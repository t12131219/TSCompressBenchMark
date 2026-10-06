/* SPDX-License-Identifier: PSF-2.0 */
/* Native float-key specialization of CPython3.11.5 stable powersort.
 * No Python object/runtime/API calls. Original sorting closure is retained.
 * n<=256 bounds all arrays and makes dynamic merge allocation unreachable.
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>
#include <limits.h>
typedef ptrdiff_t Py_ssize_t;
typedef struct {double value;uint32_t id;} PyObject;
#define Py_LOCAL_INLINE(T) static inline T
#define SIZEOF_SIZE_T sizeof(size_t)
#define PY_SSIZE_T_MAX PTRDIFF_MAX
#define Py_MIN(A,B) ((A)<(B)?(A):(B))
#define PyMem_Malloc malloc
#define PyMem_Free free
#define PyErr_NoMemory() ((void)0)
static void reverse_slice(PyObject** lo,PyObject** hi){
    while(lo<--hi){PyObject* p=*lo;*lo++=*hi;*hi=p;}
}
