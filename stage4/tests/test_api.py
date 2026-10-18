from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest

from stage4.api_client import AeroVLAClient


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ready"}')
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.payload=payload
        if self.path=='/error':
            self.send_response(500); self.end_headers(); self.wfile.write(b'{"error":"inference failed"}'); return
        data=dict(action=dict(fwd=1.,down=0.,yaw=0.),
                  stop=False,raw_output='20 49 49',elapsed_seconds=.01,prompt='actual prompt')
        if self.path=='/invalid-stop': data['stop']='false'
        if self.path=='/bad-generation': data['raw_output']='unparseable'; data['stop']=True
        if self.path=='/invalid': data['action']['fwd']='oops'
        if self.path=='/timeout': time.sleep(.2)
        self.send_response(200); self.end_headers()
        try: self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError: pass


class APITests(unittest.TestCase):
    def infer(self,client):
        return client.infer('step',3.,[0,0,-2],[0,0,0,1],[10,0,-2],
                            '0 degrees from you. table Please control drone',b'front',b'down')
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_real_http_payload_and_response(self):
        client=AeroVLAClient(self.url+'/infer',timeout=1)
        self.assertEqual(client.health(),{'status':'ready'})
        response=self.infer(client)
        self.assertEqual(response['action']['fwd'],1.)
        self.assertEqual(self.server.payload['front_image'],'ZnJvbnQ=')
        self.assertEqual(self.server.payload['position'],[0,0,-2])
        self.assertNotIn('prompt',self.server.payload)
        self.assertNotIn('request_id',self.server.payload)
        self.assertEqual(response['request_id'],'step')
        self.assertEqual(response['prompt'],'actual prompt')

    def test_malformed_responses_rejected(self):
        for suffix in ('/invalid-stop','/invalid','/bad-generation'):
            with self.assertRaises(ValueError): self.infer(AeroVLAClient(self.url+suffix,1))

    def test_timeout(self):
        with self.assertRaises(TimeoutError): self.infer(AeroVLAClient(self.url+'/timeout',.05))

    def test_server_error_explanation_is_preserved(self):
        with self.assertRaisesRegex(RuntimeError,'HTTP 500: inference failed'):
            self.infer(AeroVLAClient(self.url+'/error',1))


if __name__=='__main__': unittest.main()
