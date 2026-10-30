import unittest
from scripts.runtime.private_map_coherence.probe import classify, PATTERN

class CoherenceTests(unittest.TestCase):
    def setUp(self):
        self.obs={'before':{'shared_rw':0,'private_ro':0,'shared_ro':0}, 'after':{'shared_rw':PATTERN,'private_ro':PATTERN,'shared_ro':PATTERN}, 'file_value':PATTERN,'cleanup_errors':[]}
    def test_coherent(self): self.assertEqual(classify(self.obs),'OBSERVED_COHERENT')
    def test_private_stale(self):
        self.obs['after']['private_ro']=0
        self.assertEqual(classify(self.obs),'PRIVATE_STALE_BUT_SHARED_OK')
    def test_bad_shared(self):
        self.obs['after']['shared_ro']=0
        self.assertEqual(classify(self.obs),'SHARED_OR_FILE_UPDATE_FAILED')
    def test_file_not_updated(self):
        self.obs['file_value']=0
        self.assertEqual(classify(self.obs),'SHARED_OR_FILE_UPDATE_FAILED')
    def test_invalid_initial(self):
        self.obs['before']['private_ro']=PATTERN
        self.assertEqual(classify(self.obs),'INVALID_INITIAL_STATE')
    def test_cleanup(self):
        self.obs['cleanup_errors']=['munmap']
        self.assertEqual(classify(self.obs),'PROBE_ERROR')
    def test_error(self):
        self.obs['error']='mmap failure'
        self.assertEqual(classify(self.obs),'PROBE_ERROR')

if __name__ == '__main__': unittest.main()
