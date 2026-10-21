from pathlib import Path
import json,hashlib,sys,platform,importlib,shutil
P=Path(__file__).resolve().parents[1];R=P.parents[1]
capabilities={
'abba':['segmentation.norm1.norm2','digitization.ckmeans_scl0_sclinf','digitization.sklearn_fallback_finite_scl','digitization.incremental_weighted_symmetric','symbols.population_remap','inverse.quantize_reconstruct','model.explicit_codebook','native_ckmeans.linear_loglinear_quadratic'],
'fabba':['segmentation.scalar_cython_equivalent','digitization.lexi_norm1_norm2_norm_pca','missing.ffill_bfill_zero_mean_median','alphabet.builtin_custom','model.fit_export_import','inverse.edited_symbols','parallel.partition_partitionrate','image.flatten_adjust_restore'],
'qabba':['segmentation.scalar_cython_equivalent','digitization.agg_norm_pca','digitization.kmeans','digitization.sampled_fkmeans','quantizers.affine_signed_bits','symbols.frequency_remap','model.fit_transform_reconstruct','missing.ffill_bfill_zero_mean_median','batch.shared_codebook_threads','symbol.none_fixed_huffman_huffman1_lzw','symbol.zlib_gzip_bz2_lzma_zstd','storage.source_estimates_vs_physical','representation.independent_quantizer_state']}
for a,caps in capabilities.items():
 p=R/'ReWrite'/a;p.mkdir(exist_ok=True)
 source=json.loads((R/'Source'/a/'SOURCE_MANIFEST.json').read_text())
 matrix={'algorithm_id':a,'source_commit':source['commit'],'overall_result':'FAIL','capabilities':[{'id':c,'classification':'REQUIRED_PARITY','owner':'abba-family C++ implementation','status':'PLANNED','test':'direct-source stage/model/negative differential'} for c in caps], 'absent_capabilities':[{'id':x,'classification':'NOT_APPLICABLE','reason':'No API or kernel in selected upstream class','evidence':'public source/API inventory in docs/CONTRACT.md'} for x in ['continuous_stream','seek_random_access','explicit_simd_isa','gpu_device_codec']]}
 (p/'NATIVE_CAPABILITY_MATRIX.json').write_text(json.dumps(matrix,indent=2)+'\n')
 manifest={'algorithm_id':a,'implementation_route':'SOURCE_REWRITE','port_method':'TRANSLATED','object_level':'P2_PIPELINE','compatibility_target':'SEMANTIC','source_commit':source['commit'],'status':'IN_PROGRESS','gates':{'G0':'PASS','G1':'PASS','G2':'PASS','G3':'PENDING','G4':'PENDING','G5':'PENDING','G6':'PENDING'},'contract':'../abba-family/docs/CONTRACT.md','oracle':'../abba-family/tools/oracle.py','contract_sha256':hashlib.sha256((P/'docs/CONTRACT.md').read_bytes()).hexdigest(),'notes':['Direct GitHub acquisition. Older vendor implementations discarded before implementation.','ABBA CKmeans native dependency explicitly retained.','No Benchmark integration is part of this request.']}
 (p/'PORT_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
 (p/'README.md').write_text(f'# {a}\n\nFresh direct-upstream rewrite in progress; implementation shared in ../abba-family.\nNo completed qualification is claimed yet.\n')
# Freeze compatible real inputs with origin hash; label column excluded without scaling.
datasets=Path('/home/fzg/PycharmProjects/材料/New_Source_Code/CORAD/datasets/UCRArchive_2018')
out=P/'tests/data';out.mkdir(exist_ok=True);rows=[]
for name in ['ECG5000','Chinatown','Coffee']:
 f=datasets/name/(name+'_TEST.tsv');values=[[float(x) for x in line.split()[1:]] for line in f.read_text().splitlines()[:12]]
 payload=json.dumps(values,separators=(',',':')).encode();target=out/(name+'.json');target.write_bytes(payload)
 rows.append({'id':name,'source':str(f),'source_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'series':12,'samples':sum(map(len,values)),'frozen':str(target.relative_to(P)),'payload_sha256':hashlib.sha256(payload).hexdigest(),'preprocessing':'Exclude first classification label; parse remaining original finite binary64; no normalization'})
(P/'docs/DATASET_TEST_PLAN.json').write_text(json.dumps({'algorithms':list(capabilities),'datasets':rows,'parameters':'default plus all required alternative path configurations','comparison':'source/C++ stages, symbols, model, reconstruction and source-relative lossy metrics'},indent=2)+'\n')
env={'python':sys.version,'executable':sys.executable,'platform':platform.platform(),'dependencies':{n:importlib.import_module(n).__version__ for n in ['numpy','scipy','sklearn','joblib']},'swig':'4.3.1; local installation; wheel SHA in validation/oracle-build.json'}
(P/'docs/TOOLCHAIN_MANIFEST.json').write_text(json.dumps(env,indent=2)+'\n')
print('G0-G2 records and dataset plan frozen; no canonical code written yet')
