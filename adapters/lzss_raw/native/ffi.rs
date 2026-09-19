use lzss::{Lzss, SliceReader, SliceWriter, SliceWriterExact};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ffi::c_void;
type Codec = Lzss<10, 4, 0x20, 1024, 2048>;
extern "C" {
    fn tscb_lzss_clock(timer: *mut c_void) -> u64;
    fn tscb_lzss_interval(timer: *mut c_void, decode: u32, start: u64, end: u64);
}

// Pointer validity and non-overlap are enforced by the C ABI caller.
#[no_mangle]
pub unsafe extern "C" fn lzss_encode(src: *const u8, n: usize, dst: *mut u8,
                                     capacity: usize, written: *mut usize,
                                     timer: *mut c_void) -> u32 {
    if src.is_null() || dst.is_null() || written.is_null() || timer.is_null() { return 1; }
    let result = catch_unwind(AssertUnwindSafe(|| {
        let input = std::slice::from_raw_parts(src, n);
        let output = std::slice::from_raw_parts_mut(dst, capacity);
        let reader = SliceReader::new(input);
        let writer = SliceWriter::new(output);
        let start = tscb_lzss_clock(timer);
        let result = Codec::compress_stack(reader, writer);
        let end = tscb_lzss_clock(timer);
        tscb_lzss_interval(timer, 0, start, end);
        result
    }));
    match result {
        Ok(Ok(count)) => { *written = count; 0 },
        Ok(Err(_)) => 3,
        Err(_) => 7, // Internal panic signal; the C ABI maps it to CODEC_ERROR.
    }
}

#[no_mangle]
pub unsafe extern "C" fn lzss_decode(src: *const u8, n: usize, dst: *mut u8,
                                     capacity: usize, timer: *mut c_void) -> u32 {
    if src.is_null() || dst.is_null() || timer.is_null() { return 1; }
    let result = catch_unwind(AssertUnwindSafe(|| {
        let input = std::slice::from_raw_parts(src, n);
        let output = std::slice::from_raw_parts_mut(dst, capacity);
        let reader = SliceReader::new(input);
        let writer = SliceWriterExact::new(output);
        let start = tscb_lzss_clock(timer);
        let result = Codec::decompress_stack(reader, writer);
        let end = tscb_lzss_clock(timer);
        tscb_lzss_interval(timer, 1, start, end);
        result
    }));
    match result { Ok(Ok(())) => 0, Ok(Err(_)) => 4, Err(_) => 7 }
}
