import hashlib,unittest
SHA='2f69987b28f18023bd1dec8c7b23b925fbd20cf62df652fff100c57f20842050'
def verify(source,capture,width,height):
    if (width,height)!=(64,64) or len(source)!=16384 or len(capture)!=16384:
        raise ValueError('Expected native 64x64 RGBA8 with pitch 256, no resampling')
    bad=[i for i in range(4096) if source[i*4:i*4+4]!=capture[i*4:i*4+4]]
    return {'exact':not bad,'pixels_compared':4096,'mismatched_pixels':len(bad),
        'mismatch_coordinates':[[i%64,i//64] for i in bad[:8]],
        'source_sha256':hashlib.sha256(source).hexdigest(),'capture_sha256':hashlib.sha256(capture).hexdigest()}
class PixelTests(unittest.TestCase):
    def test_exact_all_pixels(self):
        source=bytes([0,0,128,255])*4096
        self.assertTrue(verify(source,source,64,64)['exact'])
    def test_one_bad_byte_fails(self):
        source=bytes([0,0,128,255])*4096;wrong=bytearray(source);wrong[600]=255
        self.assertFalse(verify(source,bytes(wrong),64,64)['exact'])
    def test_wrong_size_fails(self):
        with self.assertRaises(ValueError):verify(b'x',b'x',64,64)
    def test_scaled_image_fails(self):
        with self.assertRaises(ValueError):verify(bytes(65536),bytes(65536),128,128)
if __name__=='__main__':unittest.main(verbosity=2)
