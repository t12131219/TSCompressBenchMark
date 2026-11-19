/* Process-isolated control over frozen native CORAD model/solver APIs. */
#include "corad.h"
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CAP 16384u
#define COLS 3u
static const corad_config train_config = {129, COLS, 4, 4, 2, 0.9};
static int read_blob(const char *p, void *data, size_t cap, size_t *n) {
    FILE *f = fopen(p,"rb");
    if (!f) return 0;
    *n = fread(data,1,cap,f);
    int ok = fgetc(f)==EOF && !ferror(f);
    return fclose(f)==0 && ok;
}
static int write_blob(const char *p,const void *data,size_t n) {
    if (n>CAP) return 0;
    FILE *f = fopen(p,"wb");
    if (!f) return 0;
    int ok = fwrite(data,1,n,f)==n;
    return fclose(f)==0 && ok;
}
static uint64_t integer(const char *str,uint64_t max) {
    char *end;
    errno=0;
    uint64_t v=strtoull(str,&end,10);
    if (errno || str==end || *end || *str<'0' || *str>'9' || v>max) exit(2);
    return v;
}
static double real(const char *str,double lo,double hi) {
    char *end;
    errno=0;
    double v=strtod(str,&end);
    if (errno || str==end || *end || !isfinite(v) || v<lo || v>hi) exit(2);
    return v;
}
static corad_train_options options(char **a) {
    corad_train_options o;
    corad_train_options_init(&o);
    o.seed=integer(a[0],UINT64_MAX);
    o.training_columns=integer(a[1],7);
    o.max_training_samples=integer(a[2],96);
    o.max_iter=(uint32_t)integer(a[3],10);
    o.solver_max_iter=(uint32_t)integer(a[4],4000);
    o.alpha=real(a[5],0.0,1.0);
    o.tolerance=real(a[6],0.0,1e-6);
    o.solver_tolerance=real(a[7],0.0,1e-8);
    o.solver=0;
    o.normalize=1;
    return o;
}
static void stats(const corad_train_stats *s) {
    printf("{\"training_samples\":%zu,\"resampled_atoms\":%zu,\"iterations\":%u,\"converged\":%d,"
           "\"objective\":%#.17g,\"max_kkt_violation\":%#.17g}",s->training_samples,s->resampled_atoms,
           s->iterations,s->converged,s->objective,s->max_kkt_violation);
}
static void report_options(const corad_train_options *o) {
    printf("{\"size\":%u,\"version\":%u,\"solver\":%u,\"normalize\":%u,\"seed\":%" PRIu64
           ",\"training_columns\":%" PRIu64 ",\"max_training_samples\":%zu,\"max_iter\":%u,\"solver_max_iter\":%u,"
           "\"alpha\":%#.17g,\"tolerance\":%#.17g,\"solver_tolerance\":%#.17g}",o->size,o->version,o->solver,
           o->normalize,o->seed,o->training_columns,o->max_training_samples,o->max_iter,o->solver_max_iter,
           o->alpha,o->tolerance,o->solver_tolerance);
}
static int fit(const char *verb,const char *path,corad_train_options o) {
    double data[129*COLS];
    size_t n;
    if (!read_blob(path,data,sizeof(data),&n) || n!=sizeof(data)) return 3;
    if (!strcmp(verb,"fit-cap")) --o.max_training_samples;
    if (!strcmp(verb,"fit-mask")) o.training_columns=1u<<COLS;
    corad_train_stats s={0};
    corad_model *model=NULL;
    int rc=corad_model_train(&train_config,data,&o,&model,&s);
    if ((rc==CORAD_OK)!=!!model) { corad_model_free(model); return 4; }
    printf("{\"options\":"); report_options(&o);
    printf(",\"status\":%d,\"stats\":",rc);
    if (model) {
        uint8_t output[CAP];
        int saved=corad_model_save(model,output,sizeof(output),&n)==CORAD_OK;
        corad_model_free(model);
        if (!saved || !write_blob("model",output,n)) return 5;
        stats(&s);
    } else printf("null");
    puts("}");
    return 0;
}
static int controls(corad_train_options o) {
    const double initial[]={1.,0.,0.,1.}, sample[]={2.,-1.}, data[]={2.,0.,0.,-1.};
    printf("{\"analytical_controls\":[");
    for (unsigned i=0;i<2;++i) {
        double z[2], kkt, d[4];
        corad_train_stats s={0};
        o.solver=i;
        if (corad_sparse_code(initial,2,2,sample,&o,z,&kkt)!=CORAD_OK ||
            corad_dictionary_fit(data,2,2,2,&o,initial,d,&s)!=CORAD_OK) return 4;
        printf("%s{\"solver\":%u,\"coefficients\":[%#.17g,%#.17g],\"kkt\":%#.17g,"
               "\"fixed_dictionary\":[%#.17g,%#.17g,%#.17g,%#.17g],\"expected_objective\":%#.17g,\"stats\":",
               i ? "," : "",i,z[0],z[1],kkt,d[0],d[1],d[2],d[3],s.objective);
        stats(&s); putchar('}');
    }
    double z[2],kkt;
    o.solver_max_iter=1;
    int rc=corad_sparse_code((double[]){1.,0.,0.8,0.6},2,2,(double[]){2.,2.},&o,z,&kkt);
    printf("],\"sparse_nonconvergence\":%d}\n",rc);
    return 0;
}
static int pack(const char *path) {
    double d[22];
    uint8_t model[CAP];
    size_t n;
    corad_config c=train_config;
    c.rows=0;
    if (!read_blob(path,d,sizeof(d),&n) || n!=sizeof(d) ||
        corad_model_pack(&c,d,d+16,d+19,model,sizeof(model),&n)!=CORAD_OK || !write_blob("model",model,n)) return 3;
    return 0;
}
static int decode(const char *path, const char *bound) {
    uint8_t frame[CAP];
    double values[CAP/sizeof(double)];
    size_t n,count=123;
    corad_config c={0};
    size_t max=(size_t)integer(bound,CAP/sizeof(double));
    if (!read_blob(path,frame,sizeof(frame),&n)) return 3;
    int rc=corad_decode(frame,n,values,max,max,&count,&c);
    if ((rc==CORAD_OK && !write_blob("values",values,count*sizeof(double))) || (rc!=CORAD_OK && count)) return 4;
    printf("{\"status\":%d,\"values\":%zu}\n",rc,count);
    return 0;
}
int main(int argc,char **argv) {
    if (argc<2) return 2;
    const char *verb=argv[1];
    if (argc==11 && (!strcmp(verb,"fit") || !strcmp(verb,"fit-cap") || !strcmp(verb,"fit-mask")))
        return fit(verb,argv[2],options(argv+3));
    if (argc==10 && !strcmp(verb,"controls")) return controls(options(argv+2));
    if (argc==3 && !strcmp(verb,"pack")) return pack(argv[2]);
    if (argc==4 && !strcmp(verb,"decode")) return decode(argv[2],argv[3]);
    if (argc==3 && !strcmp(verb,"model-load")) {
        uint8_t frame[CAP]; size_t n;
        corad_model *model=NULL;
        if (!read_blob(argv[2],frame,sizeof(frame),&n)) return 3;
        int rc=corad_model_load(frame,n,&model);
        if (model) { corad_model_free(model); return 4; }
        printf("{\"status\":%d}\n",rc);
        return 0;
    }
    return 2;
}
