#ifndef LANG2_ARGV_RUNTIME_H
#define LANG2_ARGV_RUNTIME_H

#include "array_runtime.h"
#include "string_runtime.h"

typedef DriftArrayHeader DriftArrayString;

// Build an Array<String> header from argc/argv using existing string/array runtimes.
DriftArrayString drift_build_argv(int argc, char **argv);

#endif // LANG2_ARGV_RUNTIME_H
