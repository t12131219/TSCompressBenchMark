"""Generate exactly the two profile-only native translation units from verified input."""
from pathlib import Path
import sys

ALP = ('generated::falp::x86_64::avx2::falp(in,w.output.data(),bw,bp,fac,exp);'
       '++stats.falp_avx2_vectors;')
JOB = 'static void ZSTDMT_compressionJob(void* jobDescription)\n{'
JOB_END = ('    ZSTD_pthread_mutex_unlock(&job->job_mutex);\n}\n\n\n'
           '/* ------------------------------------------ */\n/* =====   Multi-threaded compression   ===== */')
JOB_CLOSURE, JOB_SECTION = JOB_END.split('\n\n\n', 1)


def replace_once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise ValueError('trace overlay anchor changed: ' + anchor)
    return text.replace(anchor, replacement, 1)


def overlay(kind, src):
    if kind == 'alp':
        src = replace_once(src, ALP, 'const auto bmk_span = bmk_trace_begin(BMK_TRACE_ALP_FUSED_AVX2);'
                           + ALP + 'bmk_trace_end(bmk_span);')
    elif kind == 'zstd':
        src = replace_once(src, JOB, JOB.replace('ZSTDMT_compressionJob', 'bmk_original_compressionJob'))
        src = replace_once(src, JOB_END, JOB_CLOSURE + '\n\nstatic void ZSTDMT_compressionJob(void* jobDescription)\n{\n'
                           '    uint64_t span = bmk_trace_begin(BMK_TRACE_ZSTD_MT_JOB);\n'
                           '    bmk_original_compressionJob(jobDescription);\n'
                           '    bmk_trace_end(span);\n}\n\n' + JOB_SECTION)
    else:
        raise ValueError('unknown profile overlay')
    return '#include "tsbench/trace_api.h"\n' + src


if __name__ == '__main__':
    _, kind, source, target = sys.argv
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = overlay(kind, Path(source).read_text())
    if not path.exists() or path.read_text() != contents:
        path.write_text(contents)
