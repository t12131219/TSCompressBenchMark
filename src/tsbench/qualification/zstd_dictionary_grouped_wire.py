"""ZDG1 harness framing sizes; native Zstd frames remain unchanged."""
from struct import Struct

from ..planner.m3_zstd_dictionary import LIMIT

HEAD, FRAME = Struct('<4sI'), Struct('<II')
MAGIC = b'ZDG1'
MAX_WIRE = LIMIT + 1024
