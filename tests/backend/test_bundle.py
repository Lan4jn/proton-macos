import json
import tempfile
import unittest
from pathlib import Path
from scripts.backend.bundle import build_plan,verify_bundle,prepare_tool
from scripts.backend.process import LAB

class BundleTests(unittest.TestCase):
    def setUp(self):
        self.base=LAB/'logs/backend/tests';self.base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=self.base);self.r=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_missing_manifest_blocks(self):
        self.assertEqual(build_plan(self.r/'missing',LAB/'fixtures/runtime/sysroot',self.r/'prefix',[],engine='wine')['status'],'BLOCKED')
    def test_real_bundle_checksums(self):
        info=verify_bundle(LAB/'artifacts/public-proton/bundle.json')
        self.assertEqual(info['status'],'CHECKSUM_VERIFIED')
        self.assertFalse(info['independent_valve_signature_verified'])
    def test_changed_digest_rejected(self):
        manifest=json.loads((LAB/'artifacts/public-proton/bundle.json').read_text())
        key=next(iter(manifest['critical_files']));manifest['critical_files'][key]='0'*64
        p=self.r/'bad.json';p.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):verify_bundle(p)
    def test_wine_plan_no_execution(self):
        p=build_plan(LAB/'artifacts/public-proton/bundle.json',LAB/'fixtures/runtime/sysroot',self.r/'prefix',['--version'],engine='wine')
        self.assertEqual(p['status'],'PLAN_READY');self.assertIn('--user',p['argv'])
        self.assertFalse((self.r/'prefix').exists())
        self.assertIn('WINEPREFIX',p['env'])
    def test_full_proton_needs_linux_python(self):
        p=build_plan(LAB/'artifacts/public-proton/bundle.json',LAB/'fixtures/runtime/sysroot',self.r/'prefix',['run','game.exe'],engine='proton')
        self.assertEqual(p['status'],'BLOCKED');self.assertIn('python',p['reason'].lower())
    def test_prefix_escape(self):
        with self.assertRaises(ValueError):build_plan(LAB/'artifacts/public-proton/bundle.json',LAB/'fixtures/runtime/sysroot',Path('/tmp/prefix'),[],engine='wine')
    def test_prepare_does_not_install(self):
        target=self.r/'pretend Steam/compatibilitytools.d';candidate=prepare_tool(self.r/'prepared',target)
        self.assertFalse(target.exists())
        self.assertTrue((Path(candidate['candidate'])/'toolmanifest.vdf').is_file())
        self.assertEqual(candidate['applied'],False)
        self.assertIn('-- %verb%',(Path(candidate['candidate'])/'toolmanifest.vdf').read_text())

if __name__=='__main__':unittest.main()
