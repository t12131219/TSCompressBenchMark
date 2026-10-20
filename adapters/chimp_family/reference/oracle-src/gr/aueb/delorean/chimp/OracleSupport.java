package gr.aueb.delorean.chimp;
// Infrastructure only. Actual fixed-width read/write methods are frozen original source.
interface BooleanIterator { boolean hasNext(); boolean nextBoolean(); default Boolean next(){return nextBoolean();} default int skip(int n){throw new UnsupportedOperationException();} }
interface RepositionableStream { void position(long p) throws java.io.IOException; }
class Fast { static int mostSignificantBit(int x){return 31-Integer.numberOfLeadingZeros(x);} static int mostSignificantBit(long x){return 63-Long.numberOfLeadingZeros(x);} }
