import math

from tsbench.study import cluster_interval, pareto_indices, primary_rows


def test_source_weighting_is_not_dominated_by_many_dependent_windows():
    result=cluster_interval({'one_source_many_windows':[math.log(4)]*100,
                             'another_source_one_window':[math.log(1)]},repetitions=200)
    assert result['source_count']==2 and result['estimate']==2
    assert result['interval'][0]==1 and result['interval'][1]==4
    assert cluster_interval({'only_one':[0]})['interval'] is None


def test_pair_analysis_preserves_original_failure_and_only_skips_not_run():
    common={'phase':'measurement','event':'terminal','case_id':'same','session':0,'round':0}
    rows=[{**common,'status':'error','attempt':0},{**common,'status':'ok','attempt':1}]
    assert primary_rows(rows)[('same',0,0)]['status']=='error'
    rows[0]['status']='not_run'
    assert primary_rows(rows)[('same',0,0)]['attempt']==1


def test_quality_size_and_both_completion_times_all_affect_oracle_frontier():
    points=[(0.01,100,10,20),(0.02,200,20,30),(0.001,500,40,50),(0.02,90,9,19)]
    assert pareto_indices(points)==[0,2,3]
