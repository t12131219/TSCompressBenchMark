import java.io.*;
import java.nio.*;
import java.util.*;
import gr.aueb.delorean.chimp.*;
import com.github.kutschkem.fpc.*;
public class Oracle {
 static FpcCompressor streamEncoder=new FpcCompressor(),streamDecoder=new FpcCompressor();
 static int rd(InputStream s)throws IOException {byte[] b=s.readNBytes(4);if(b.length!=4)throw new EOFException();return ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getInt();}
 static void wr(OutputStream s,int n)throws IOException{s.write(ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(n).array());}
 static byte[] words(List<Long> w){ByteBuffer b=ByteBuffer.allocate(w.size()*8).order(ByteOrder.LITTLE_ENDIAN);for(long x:w)b.putLong(x);return b.array();}
 static byte[] decode(int method,int n,int count,byte[] raw){List<Long> values=new ArrayList<>();
  if(method==6){double[] d=new double[count];new FpcCompressor().decompress(ByteBuffer.wrap(raw),d);for(double v:d)values.add(Double.doubleToRawLongBits(v));}
  else if(method==1){ChimpDecompressor d=new ChimpDecompressor(raw);Double v;while((v=d.readValue())!=null){values.add(Double.doubleToRawLongBits(v));if(values.size()>1048576)throw new IllegalStateException("limit");}}
  else if(method==2){ChimpDecompressor32 d=new ChimpDecompressor32(raw);Value v;while((v=d.readPair())!=null){values.add(Integer.toUnsignedLong(v.getIntValue()));if(values.size()>1048576)throw new IllegalStateException("limit");}}
  else if(method==3||method==4){ChimpNDecompressor d=new ChimpNDecompressor(raw,n);Double v;while((v=d.readValue())!=null){values.add(Double.doubleToRawLongBits(v));if(values.size()>1048576)throw new IllegalStateException("limit");}}
  else if(method==5){ChimpNDecompressor32 d=new ChimpNDecompressor32(raw,n);Float v;while((v=d.readValue())!=null){values.add(Integer.toUnsignedLong(Float.floatToRawIntBits(v)));if(values.size()>1048576)throw new IllegalStateException("limit");}}
  return words(values);
 }
 static byte[] run(int mode,int method,int n,float eps,int count,byte[] bytes)throws Exception {
  ByteBuffer b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
  if(mode==10)return words(Arrays.asList(new FpcCompressor().toLong(bytes)));
  if(mode==11)return new FpcCompressor().toByteArray(b.getLong());
  if(mode==9){streamEncoder=new FpcCompressor();streamDecoder=new FpcCompressor();return new byte[0];}
  if(mode==7){double[] ds=new double[count];for(int i=0;i<count;++i)ds[i]=Double.longBitsToDouble(b.getLong());ByteBuffer out=ByteBuffer.allocate(17*((count+1)/2));streamEncoder.compress(out,ds);return Arrays.copyOf(out.array(),out.position());}
  if(mode==8){double[] ds=new double[count];streamDecoder.decompress(ByteBuffer.wrap(bytes),ds);List<Long> w=new ArrayList<>();for(double d:ds)w.add(Double.doubleToRawLongBits(d));return words(w);}

  if(mode==2)return decode(method,n,count,bytes);
  if(method<=6){if(method==6){double[] ds=new double[count];for(int i=0;i<count;++i)ds[i]=Double.longBitsToDouble(b.getLong());ByteBuffer out=ByteBuffer.allocate(17*((count+1)/2));new FpcCompressor().compress(out,ds);return Arrays.copyOf(out.array(),out.position());}
   Object c=method==1?new Chimp():method==2?new Chimp32():method==3?new ChimpN(n):method==4?new ChimpNNoIndex(n):new ChimpN32(n);
   for(int i=0;i<count;++i){long w=b.getLong();if(method==1)((Chimp)c).addValue(w);else if(method==2)((Chimp32)c).addValue((int)w);else if(method==3)((ChimpN)c).addValue(w);else if(method==4)((ChimpNNoIndex)c).addValue(w);else ((ChimpN32)c).addValue((int)w);}
   c.getClass().getMethod("close").invoke(c);int bits=(int)c.getClass().getMethod("getSize").invoke(c)+1;return Arrays.copyOf((byte[])c.getClass().getMethod("getOut").invoke(c),(bits+7)/8);
  }
  List<Point> points=new ArrayList<>();for(int i=0;i<count;++i)points.add(new Point(b.getLong(),b.getFloat()));
  List<SwingSegment> segments=new ArrayList<>();List<PmcMR.Constant> constants=null;
  if(method==7)constants=new PmcMR().filter(points,eps);
  else if(method==8)segments=new SwingFilter().filter(points,eps);
  else if(method==9)segments=new SwingFilterDisjoint().filter(points,eps);
  else if(method==10)segments=new SwingFilterDisjointQuantized().filter(points,eps);
  else if(method==11)segments=new SwingFilterDisjointQuantized().filter2(points,eps);
  if(mode==5){ByteArrayOutputStream os=new ByteArrayOutputStream();if(method==7){DecompressorPmcMr d=new DecompressorPmcMr(constants);for(PmcMR.Constant s:constants)for(long t=s.getInitialTimestamp();t<=s.getFinalTimestamp();++t){Float f=d.readValue();os.write(ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN).putLong(t).putFloat(f).array());}}
    else {DecompressorSwingFilter d=new DecompressorSwingFilter(segments);for(SwingSegment s:segments)for(long t=s.getInitialTimestamp();t<=s.getFinalTimestamp();++t){Float f=d.readValue();os.write(ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN).putLong(t).putFloat(f).array());}}
    return os.toByteArray();}
  ByteBuffer out=ByteBuffer.allocate((method==7?constants.size():segments.size())*52).order(ByteOrder.LITTLE_ENDIAN);
  if(method==7)for(PmcMR.Constant s:constants)out.putLong(s.getInitialTimestamp()).putLong(s.getFinalTimestamp()).putDouble(0).putDouble(s.getValue()).putDouble(0).putDouble(0).putFloat(0);
  else for(SwingSegment s:segments){out.putLong(s.getInitialTimestamp()).putLong(s.getFinalTimestamp()).putDouble(s.getLine().a).putDouble(s.getLine().b);if(s instanceof SwingSegmentDisjointQuantized){SwingSegmentDisjointQuantized q=(SwingSegmentDisjointQuantized)s;out.putDouble(q.getaMin()).putDouble(q.getaMax()).putFloat(q.getB());}else out.putDouble(0).putDouble(0).putFloat(0);}
  return out.array();
 }
 public static void main(String[] args)throws Exception{InputStream in=new BufferedInputStream(System.in);OutputStream out=new BufferedOutputStream(System.out);while(true){int mode;try{mode=rd(in);}catch(EOFException e){break;}int method=rd(in),n=rd(in);float eps=Float.intBitsToFloat(rd(in));int count=rd(in),len=rd(in);byte[] bytes=in.readNBytes(len);try{byte[] result=run(mode,method,n,eps,count,bytes);wr(out,0);wr(out,result.length);out.write(result);}catch(Throwable e){byte[] msg=(e.toString()+" "+e.getCause()).getBytes(java.nio.charset.StandardCharsets.UTF_8);wr(out,1);wr(out,msg.length);out.write(msg);}out.flush();}}
}
