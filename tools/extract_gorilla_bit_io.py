#!/usr/bin/env python3
"""Extract bit primitives from the exact frozen Unique Gorilla C11 source."""
import hashlib
from pathlib import Path
import sys

SOURCE_SHA256 = 'de517e725407dd947ac4e6f1d31fdd27d2024d1236064616d2a624fa747cd677'


def main(source, output):
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SOURCE_SHA256:
        raise ValueError('Gorilla derivation requires the pinned Unique gorilla.c')
    text = payload.decode('ascii')
    writer = text[text.index('static unsigned leading('):text.index('#ifndef G_STREAM_ONLY')]
    begin = text.index('typedef struct { const uint8_t *p; size_t bytes,remaining;')
    reader = text[begin:text.index('#ifndef G_STREAM_ONLY', begin)]
    result = ('/* Generated from Unique gorilla-native/unique-v1 src/gorilla.c; do not edit. */\n'
              + writer + reader)
    if not output.exists() or output.read_text(encoding='ascii') != result:
        output.write_text(result, encoding='ascii')


if __name__ == '__main__':
    main(*map(Path, sys.argv[1:]))
