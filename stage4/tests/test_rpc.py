"""Guard the upstream image transport fix without adding another RPC client."""
import unittest
from unittest.mock import patch
import msgpack
from stage3.super.airsim.rpc_client import rpc


class ImageRPCTests(unittest.TestCase):
    def test_fragmented_binary_image_is_not_utf8_decoded(self):
        png=b'\x89PNG\r\n\x1a\n\x00\xff\xfe\x80'
        payload=msgpack.packb([1,1,None,[dict(image_data_uint8=png,camera_name='前视')]],use_bin_type=True)
        chunks=iter([payload[:9],payload[9:21],payload[21:]])
        class Connection:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def settimeout(self,value): pass
            def sendall(self,value):
                request=msgpack.unpackb(value,raw=False)
                self.request=request
            def recv(self,size): return next(chunks,b'')
        connection=Connection()
        with patch('stage3.super.airsim.rpc_client.socket.create_connection',return_value=connection):
            result=rpc('simGetImages',[],'PX4',False)
        self.assertEqual(result[0]['image_data_uint8'],png)
        self.assertIsInstance(result[0]['image_data_uint8'],bytes)
        self.assertEqual(result[0]['camera_name'],'前视')
        self.assertEqual(connection.request[2],'simGetImages')
