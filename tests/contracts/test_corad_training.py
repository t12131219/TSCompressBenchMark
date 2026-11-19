from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.assets import ContractError
from tsbench.planner.corad_training import plan_corad_training, retained_paths, source_argv
from tsbench.qualification.corad_training import _normalization, npy_values


def npy(header, values):
    data = header.encode('ascii')+b'\n'
    return b'\x93NUMPY\x01\0'+struct.pack('<H',len(data))+data+struct.pack(f'<{len(values)}d',*values)


class CoradTrainingContracts(unittest.TestCase):
    def test_training_fit_assets_and_eval_seed_mask(self):
        bundle, data = plan_corad_training(ROOT)
        self.assertEqual(11,len(bundle['cases']))
        self.assertEqual(17,len(retained_paths(bundle)))
        self.assertEqual(96,bundle['c_options']['max_training_samples'])
        self.assertLess(bundle['data']['train']['last_timestamp'],bundle['data']['evaluation']['first_timestamp'])
        self.assertEqual(129*3*8,len(data['train'][1]))
        self.assertEqual(67*3*8,len(data['evaluation'][1]))
        first, second = [source_argv(bundle,label) for label in bundle['source_labels']]
        self.assertNotEqual(first[6],second[6])
        self.assertEqual(first[:-8],second[:-8])

    def test_normalization_masks_and_drops_short_training_tail(self):
        series = [struct.pack('<3d',1,3,2),struct.pack('<3d',7,7,7)]
        means,scales,vectors = _normalization(series,2,2)
        self.assertEqual([2.,7.],means)
        self.assertAlmostEqual((2/3)**0.5,scales[0])
        self.assertEqual((1.,[0.,0.]),(scales[1],vectors))

    def test_no_pickle_or_misaligned_matrix(self):
        header = "{'descr':'<f8','fortran_order':False,'shape':(1,2)}"
        correct = npy(header,[1.,2.])
        self.assertEqual((1.,2.),npy_values(correct,1,2))
        for bad in (correct[:-1],correct+b'\0',npy(header,[1.,float('nan')]),
                    npy(header.replace('<f8','|O'),[1.,2.]),npy(header.replace('False','True'),[1.,2.]),
                    npy(header.replace('(1,2)','(2,1)'),[1.,2.])):
            with self.assertRaises(ContractError):
                npy_values(bad,1,2)
