/* Direct C11 lifecycle exercise, without the scan/copy interposer. */
#include "gorilla.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ROWS 512
#define CUT 23
#define CAP 9600
_Static_assert(sizeof(g_sample)==16, "expected the frozen Linux TV layout");

static void check(int ok, const char *why) {
    if (!ok) { fprintf(stderr,"Gorilla lifecycle: %s\n",why); exit(6); }
}
static size_t load(const char *path,void *out,size_t cap) {
    FILE *f = fopen(path,"rb");
    check(f!=NULL,"open bounded input");
    const size_t n = fread(out,1,cap,f);
    const int ok = fgetc(f)==EOF && !ferror(f);
    check(fclose(f)==0 && ok,"input extent/read");
    return n;
}
static void save(const char *path,const void *data,size_t n) {
    FILE *f = fopen(path,"wbx");
    check(f!=NULL,"create output");
    const int ok = fwrite(data,1,n,f)==n;
    check(fclose(f)==0 && ok,"write output");
}
typedef struct { size_t rows,bits,workspace; } Progress;
static Progress progress(const g_encoder *e) {
    Progress p;
    check(g_encoder_progress(e,&p.rows,&p.bits,&p.workspace)==G_OK,"encoder progress");
    return p;
}
static void show(Progress p) {
    printf("{\"rows\":%zu,\"chunk_bits\":%zu,\"workspace_bytes\":%zu}",p.rows,p.bits,p.workspace);
}
static int same(g_buffer a,g_buffer b) {
    return a.size==b.size && a.data && b.data && !memcmp(a.data,b.data,a.size);
}
static void append(void) {
    g_sample input[ROWS];
    check(load("/inputs/raw",input,sizeof input)==sizeof input,"traffic row extent");
    g_encoder *e = NULL;
    g_buffer snapshot={0}, prefix={0}, whole={0}, again={0}, batch={0}, reset={0};
    check(g_encoder_create(ROWS,&e)==G_OK && e,"create encoder");
    check(g_encoder_append(e,input,CUT)==G_OK,"append prefix");
    const Progress before=progress(e);
    check(g_encoder_snapshot(e,&snapshot)==G_OK && g_compress(input,CUT,&prefix)==G_OK && same(snapshot,prefix),
          "snapshot/direct prefix differ");
    const g_status invalid=g_encoder_append(e,NULL,ROWS), overflow=g_encoder_append(e,input,ROWS);
    const Progress after=progress(e);
    check(invalid==G_INVALID && overflow==G_LIMIT && before.rows==after.rows && before.bits==after.bits &&
          before.workspace==after.workspace,"invalid append changed progress");
    check(g_encoder_append(e,input+CUT,ROWS-CUT)==G_OK && g_encoder_finish(e,&whole)==G_OK &&
          g_encoder_finish(e,&again)==G_OK && g_compress(input,ROWS,&batch)==G_OK && same(whole,again) &&
          same(whole,batch),"append/finish/direct batch differ");
    const g_status closed=g_encoder_append(e,NULL,0);
    check(closed==G_INVALID && g_encoder_reset(e)==G_OK && g_encoder_snapshot(e,&reset)==G_OK &&
          reset.size==2 && reset.data[0]==0 && reset.data[1]==0,"finish/reset contract");
    save("snapshot",snapshot.data,snapshot.size); save("uninterrupted",whole.data,whole.size);
    printf("{\"prefix\":"); show(before); printf(",\"after_overflow\":"); show(after);
    printf(",\"invalid_span\":%d,\"overflow\":%d,\"closed_append\":%d,"
           "\"prefix_equals_batch\":true,\"finish_equals_batch\":true,\"finish_idempotent\":true,"
           "\"reset_snapshot_hex\":\"0000\"}\n",invalid,overflow,closed);
    g_encoder_destroy(e);
    g_free(snapshot.data); g_free(prefix.data); g_free(whole.data); g_free(again.data); g_free(batch.data); g_free(reset.data);
}
static void resume(void) {
    uint8_t snap[CAP];
    g_sample tail[ROWS-CUT];
    const size_t n=load("/inputs/snapshot",snap,sizeof snap-1);
    check(n>=2 && snap[0]==0 && snap[1]==CUT && load("/inputs/tail",tail,sizeof tail)==sizeof tail,"resume input extent");
    g_encoder *e = NULL;
    check(g_encoder_create(ROWS,&e)==G_OK && e,"create resume encoder");
    snap[n]=0;
    const g_status bad=g_encoder_resume(e,snap,n+1);
    check(bad==G_CORRUPT && g_encoder_reset(e)==G_OK && g_encoder_resume(e,snap,n)==G_OK,"resume after bad snapshot/reset");
    const Progress p=progress(e);
    memset(snap,0xff,n);
    g_buffer result={0};
    check(g_encoder_append(e,tail,ROWS-CUT)==G_OK && g_encoder_finish(e,&result)==G_OK,"resume tail and finish");
    save("resumed",result.data,result.size);
    printf("{\"resumed_prefix\":"); show(p); printf(",\"bad_snapshot\":%d}\n",bad);
    g_free(result.data); g_encoder_destroy(e);
}
static void drain(void) {
    uint8_t wire[CAP];
    const size_t n = load("/inputs/backing",wire,sizeof wire-1);
    check(n>=2,"iterator frame missing header");
    const size_t rows=(size_t)wire[0]*256+wire[1];
    g_iterator *it=NULL;
    check(rows>0 && rows<=ROWS && g_iterator_create(wire,n,ROWS,&it)==G_OK && it,"iterator open");
    int64_t t[ROWS]; uint64_t v[ROWS];
    g_sample a={0}; int present=0;
    for (size_t i=0; i<rows; i++) {
        check(g_iterator_next(it,&a,&present)==G_OK && present,"iterator row");
        t[i]=a.timestamp; v[i]=a.bits;
    }
    const g_status eof=g_iterator_next(it,&a,&present);
    wire[n]=0;
    check(eof==G_OK && !present && g_iterator_reset(it,wire,n+1,ROWS)==G_OK,"iterator EOF/reset");
    for (size_t i=0; i<rows; i++) {
        check(g_iterator_next(it,&a,&present)==G_OK && present && a.timestamp==t[i] && a.bits==v[i],"valid prefix before bad trailer");
    }
    const g_status bad=g_iterator_next(it,&a,&present);
    check(bad==G_CORRUPT && !present,"damaged trailer not rejected at drain");
    const g_status poisoned=g_iterator_next(it,&a,&present);
    check(poisoned==G_CORRUPT && !present && g_iterator_reset(it,wire,n,ROWS)==G_OK &&
          g_iterator_next(it,&a,&present)==G_OK && present && a.timestamp==t[0] && a.bits==v[0],"iterator poison/reset");
    save("t",t,rows*sizeof t[0]); save("v",v,rows*sizeof v[0]);
    printf("{\"rows\":%zu,\"eof\":[%d,null],\"bad_trailer\":[[%d,null],[%d,null]],\"reset_verified\":true}\n",
           rows,eof,bad,poisoned);
    g_iterator_destroy(it);
}
int gorilla_lifecycle(const char *op) {
    if (!strcmp(op,"state-append")) append();
    else if (!strcmp(op,"state-resume")) resume();
    else if (!strcmp(op,"iterator-drain")) drain();
    else return 2;
    return fflush(stdout)==0 && !ferror(stdout)?0:5;
}
