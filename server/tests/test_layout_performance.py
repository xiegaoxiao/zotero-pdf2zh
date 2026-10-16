import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

import numpy as np
from babeldoc.docvision.base_doclayout import YoloResult
from utils.layout_performance import cached_layout_predict,cpu_session_options,prune_layout_cache


class FakeModel:
    def __init__(self,path):
        self.model_path=path
        self.model=Mock()
        self.model.get_providers.return_value=['CPUExecutionProvider']
        self.model.get_session_options.return_value=NS(intra_op_num_threads=0)
        self._names={0:'plain text'}
        self.calls=0
        self.fail=False
        self.empty=False

    @cached_layout_predict
    def predict(self,image,**kwargs):
        self.calls+=1
        if self.fail:
            raise RuntimeError('inference failed')
        boxes=np.empty((0,6),dtype=np.float32) if self.empty else np.array([[1.5,2.5,20.5,30.5,.95,0]],dtype=np.float32)
        return [YoloResult(boxes_data=boxes,names=self._names)]


class LayoutCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.weights=self.root/'model.onnx'
        self.weights.write_bytes(b'synthetic model')
        self.cache=self.root/'cache'
        self.env=patch.dict(os.environ,{'ZOTERO_PDF2ZH_LAYOUT_CACHE_DIR':str(self.cache),'ZOTERO_PDF2ZH_LAYOUT_CACHE':'1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.image=np.zeros((40,60,3),dtype=np.uint8)
        self.model=FakeModel(self.weights)

    def test_hit_reuses_exact_coordinates_and_confidence_across_instances(self):
        expected=self.model.predict(self.image)[0]
        other=FakeModel(self.weights)
        actual=other.predict(self.image)[0]
        self.assertEqual(other.calls,0)
        self.assertEqual(len(actual.boxes),len(expected.boxes))
        np.testing.assert_array_equal(actual.boxes[0].xyxy,expected.boxes[0].xyxy)
        self.assertEqual(actual.boxes[0].conf,expected.boxes[0].conf)

    def test_changed_pixels_miss(self):
        self.model.predict(self.image)
        self.image[0,0,0]=1
        self.model.predict(self.image)
        self.assertEqual(self.model.calls,2)

    def test_model_upgrade_invalidates_cache(self):
        self.model.predict(self.image)
        self.weights.write_bytes(b'changed weights')
        other=FakeModel(self.weights)
        other.predict(self.image)
        self.assertEqual(other.calls,1)

    def test_runtime_options_invalidate_cache(self):
        self.model.predict(self.image)
        other=FakeModel(self.weights)
        other.model.get_session_options.return_value=NS(intra_op_num_threads=4)
        other.predict(self.image)
        self.assertEqual(other.calls,1)

    def test_non_default_call_bypasses_cache(self):
        self.model.predict(self.image,imgsz=512)
        self.model.predict(self.image,imgsz=512)
        self.assertEqual(self.model.calls,2)
        self.assertFalse(self.cache.exists())

    def test_disabled_cache_does_not_write(self):
        with patch.dict(os.environ,{'ZOTERO_PDF2ZH_LAYOUT_CACHE':'0'}):
            self.model.predict(self.image)
            self.model.predict(self.image)
        self.assertEqual(self.model.calls,2)
        self.assertFalse(self.cache.exists())

    def test_corrupt_or_invalid_cache_is_recomputed(self):
        self.model.predict(self.image)
        path=next(self.cache.glob('*.json'))
        for contents in ['broken json',json.dumps({'schema':1,'boxes':[[0,0,2,2,.8,99]]})]:
            path.write_text(contents,encoding='utf8')
            before=self.model.calls
            self.model.predict(self.image)
            self.assertEqual(self.model.calls,before+1)
            self.assertEqual(json.loads(path.read_text())['schema'],1)

    def test_unwritable_cache_does_not_fail_translation(self):
        with patch('utils.layout_performance._cache_root',side_effect=PermissionError):
            self.assertEqual(len(self.model.predict(self.image)),1)

    def test_expired_hit_is_recomputed(self):
        self.model.predict(self.image)
        path=next(self.cache.glob('*.json'))
        os.utime(path,(0,0))
        self.model.predict(self.image)
        self.assertEqual(self.model.calls,2)

    def test_failed_inference_is_not_hidden_or_cached(self):
        self.model.fail=True
        with self.assertRaisesRegex(RuntimeError,'inference failed'):
            self.model.predict(self.image)
        self.assertEqual(list(self.cache.glob('*.json')),[])

    def test_empty_detections_round_trip(self):
        self.model.empty=True
        self.assertEqual(len(self.model.predict(self.image)[0].boxes),0)
        self.assertEqual(len(self.model.predict(self.image)[0].boxes),0)
        self.assertEqual(self.model.calls,1)

    def test_cache_contains_only_boxes_and_schema(self):
        self.model.predict(self.image)
        data=json.loads(next(self.cache.glob('*.json')).read_text())
        self.assertEqual(set(data),{'schema','boxes'})

    def test_pruning_limits_size_age_and_preserves_unrelated_files(self):
        self.cache.mkdir()
        old=self.cache/('a'*64+'.json')
        new=self.cache/('b'*64+'.json')
        unrelated=self.cache/'notes.json'
        for path in [old,new,unrelated]:path.write_text('{}')
        os.utime(old,(100,100))
        with patch('utils.layout_performance.MAX_CACHE_FILES',0):
            prune_layout_cache(self.cache,now=40*24*3600)
        self.assertFalse(old.exists())
        self.assertFalse(new.exists())
        self.assertTrue(unrelated.exists())


class CpuOptionsTests(unittest.TestCase):
    def test_default_keeps_automatic_parallelism(self):
        self.assertIsNone(cpu_session_options(Mock(),['CPUExecutionProvider'],{}))

    def test_accelerator_options_are_unchanged(self):
        self.assertIsNone(cpu_session_options(Mock(),['CoreMLExecutionProvider','CPUExecutionProvider']))

    def test_explicit_thread_limit_and_idle_spinning(self):
        runtime=Mock()
        with patch('utils.layout_performance.os.cpu_count',return_value=16):
            options=cpu_session_options(runtime,['CPUExecutionProvider'],{'ZOTERO_PDF2ZH_CPU_THREADS':'4','ZOTERO_PDF2ZH_DISABLE_SPINNING':'1'})
        self.assertEqual(options.intra_op_num_threads,4)
        self.assertEqual(options.inter_op_num_threads,1)
        options.add_session_config_entry.assert_any_call('session.intra_op.allow_spinning','0')


if __name__=='__main__':
    unittest.main()
