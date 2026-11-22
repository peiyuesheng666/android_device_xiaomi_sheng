#!/usr/bin/env python3
"""Check specific paths against the FULL candidate file-contexts database.

Unlike checkfc -t, this does not demand test paths covering unrelated thousands
of existing regexes. It does not ignore lookup or expected-label mismatches.
checkfc and sefcontext_compile separately validate all entries against policy.
"""
import argparse
import ctypes
import ctypes.util
import json
from pathlib import Path


def check(contexts, cases):
    library = ctypes.util.find_library('selinux')
    if not library:
        raise RuntimeError('Host libselinux is required; no skipped acceptance')
    lib = ctypes.CDLL(library, use_errno=True)

    class Option(ctypes.Structure):
        _fields_ = [('type', ctypes.c_int), ('value', ctypes.c_char_p)]

    lib.selabel_open.argtypes = [ctypes.c_uint, ctypes.POINTER(Option), ctypes.c_uint]
    lib.selabel_open.restype = ctypes.c_void_p
    lib.selabel_lookup_raw.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p),
                                      ctypes.c_char_p, ctypes.c_int]
    lib.selabel_lookup_raw.restype = ctypes.c_int
    lib.freecon.argtypes = [ctypes.c_void_p]
    lib.freecon.restype = None
    lib.selabel_close.argtypes = [ctypes.c_void_p]
    lib.selabel_close.restype = None
    # libselinux/include/selinux/label.h: FILE backend=0, OPT_PATH=3.
    option = Option(3, str(Path(contexts).resolve()).encode('utf-8'))
    handle = lib.selabel_open(0, ctypes.byref(option), 1)
    if not handle:
        raise OSError(ctypes.get_errno(), 'selabel_open failed')
    results = []
    try:
        for path, expected in cases:
            value = ctypes.c_char_p()
            if lib.selabel_lookup_raw(handle, ctypes.byref(value), path.encode('utf-8'), 0):
                raise OSError(ctypes.get_errno(), 'selabel_lookup failed: ' + path)
            try:
                context = value.value.decode('utf-8')
            finally:
                lib.freecon(value)
            if context.split(':')[2] != expected:
                raise RuntimeError(f'{path}: expected {expected}, got {context}')
            results.append(dict(path=path, expected_type=expected, context=context, passed=True))
    finally:
        lib.selabel_close(handle)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('contexts', type=Path)
    parser.add_argument('tests', type=Path)
    args = parser.parse_args()
    cases = [line.rsplit(' ', 1) for line in args.tests.read_text().splitlines() if line.strip()]
    if not cases:
        raise ValueError('Empty lookup tests')
    print(json.dumps(check(args.contexts, cases), indent=2))


if __name__ == '__main__':
    main()
