from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tsbench.supervisor.process import invoke
from tsbench.supervisor.resource import admission, resource_binding, sample, verify_resources
from tsbench.assets import ContractError

ROOT = Path(__file__).resolve().parents[2]


class ResourceCandidateTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'contract_bindings':{'resource':resource_binding(ROOT)},
                     'inputs':{'input':{'bytes':1024}},'suite':{'max_serialized_bytes_per_slot':8192}}
        self.slot = {'input_id':'input','slot_id':'c'*64}

    def test_recompute_thresholds_for_this_mount_and_this_slot(self):
        reading = {'disk':{'device':1,'available_bytes':0,'available_inodes':0},'host_memavailable_bytes':0}
        guard = admission(self.plan,self.slot,reading)
        self.assertEqual(33554432+1024+8192,guard['minimum']['available_bytes'])
        self.assertEqual(3,len(guard['reasons']))
        for k in ('available_bytes','available_inodes'):
            reading['disk'][k] = guard['minimum'][k]
        reading['host_memavailable_bytes'] = guard['minimum']['host_memavailable_bytes']
        self.assertEqual([],admission(self.plan,self.slot,reading)['reasons'])
        reading['disk']['available_inodes'] = None
        self.assertEqual(['results_mount_capacity_unavailable'],admission(self.plan,self.slot,reading)['reasons'])

    def test_resource_block_with_no_execution_and_verified_reclamation(self):
        reading = {'disk':None,'host_memavailable_bytes':10**9}
        guard = admission(self.plan,self.slot,reading)
        row = {'slot_id':self.slot['slot_id'],'status':'resource_blocked','reason':'; '.join(guard['reasons']),
               'operations':[],'artifact':None,'workspace':[],'resource_guard':guard}
        verify_resources(self.plan,self.slot,row,{'workspace_action':'no_files'},None,{})
        with self.assertRaisesRegex(ContractError,'cannot have launched work'):
            verify_resources(self.plan,self.slot,{**row,'operations':[{}]},{'workspace_action':'no_files'},None,{})
        reading['disk'] = {'device':1,'available_bytes':10**9,'available_inodes':10**6}
        guard = admission(self.plan,self.slot,reading)
        files = [{'name':'restored.bin','bytes':1024,'sha256':'a'*64},
                 {'name':'restored.json','bytes':65,'sha256':'b'*64}]
        row.update(status='verified',workspace=files,resource_guard=guard)
        validation = {'decoded':{'values_sha256':'a'*64,'schema_sha256':'b'*64}}
        verify_resources(self.plan,self.slot,row,{'workspace_action':'verified_released'},validation,{})
        with self.assertRaisesRegex(ContractError,'workspace disposition'):
            verify_resources(self.plan,self.slot,row,{'workspace_action':'failure_retained'},validation,{})
        row['workspace'][0]['sha256'] = 'd'*64
        with self.assertRaisesRegex(ContractError,'differs from the verified restoration'):
            verify_resources(self.plan,self.slot,row,{'workspace_action':'verified_released'},validation,{})

    def test_wait4_usage_includes_failure_but_never_unlaunched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good = invoke([sys.executable,'-B','-c','x=sum(range(5000000))'],root,root,'good',5,lambda:False,
                          observe_process=True,capture_usage=True)
            self.assertEqual('completed',good['status'])
            self.assertGreater(good['child_usage']['user_cpu_ns'],0)
            self.assertGreater(good['child_usage']['maxrss_bytes'],0)
            self.assertEqual(0,good['child_usage']['maxrss_bytes']%1024)
            failed = invoke([sys.executable,'-B','-c','raise SystemExit(7)'],root,root,'failed',5,lambda:False,
                            observe_process=True,capture_usage=True)
            self.assertEqual(7,failed['returncode'])
            self.assertIn('child_usage',failed)
            unlaunched = invoke([sys.executable],root,root,'cancel',5,lambda:True,observe_process=True,capture_usage=True)
            self.assertNotIn('child_usage',unlaunched)
            absent = invoke([str(root/'missing')],root,root,'missing',5,lambda:False,observe_process=True,capture_usage=True)
            self.assertEqual('dependency_failed',absent['status'])
            self.assertNotIn('child_usage',absent)

    def test_snapshot_reads_filesystem_of_the_output(self):
        class Fs:
            f_files = 123
            f_favail = 91
            f_bavail = 23
            f_frsize = 512
        with patch('tsbench.supervisor.resource.os.statvfs',return_value=Fs()) as statvfs, \
             patch('tsbench.supervisor.resource._memavailable',return_value=456):
            self.assertEqual({'disk':{'device':ROOT.stat().st_dev,'available_bytes':11776,'available_inodes':91},
                              'host_memavailable_bytes':456},sample(ROOT))
            statvfs.assert_called_once_with(ROOT)
