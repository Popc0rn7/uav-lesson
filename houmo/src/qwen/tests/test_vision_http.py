import asyncio,base64,json
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import prepare_request
import test_server

IMAGE='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()

class VisionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_server.ServiceTests.asyncSetUp
    asyncTearDown=test_server.ServiceTests.asyncTearDown
    http=test_server.ServiceTests.http
    async def test_openai_text_and_models(self):
        status,value=await self.http('GET','/v1/models')
        self.assertEqual(value['data'][0]['id'],'qwen')
        request={'model':'qwen','messages':[{'role':'user','content':'hello'}],'max_tokens':8}
        status,value=await self.http('POST','/v1/chat/completions',json.dumps(request).encode())
        self.assertEqual(status,200)
        self.assertEqual(value['choices'][0]['message']['content'],'hello')
        request['model']='unknown'
        self.assertEqual((await self.http('POST','/v1/chat/completions',json.dumps(request).encode()))[0],400)

    async def test_image_staged_then_cleaned_and_cancelled_request_still_cleans(self):
        self.worker.metadata['vision_enabled']=True
        paths=[];original=self.worker.infer
        async def inspect(body):
            paths.extend(body['image_paths'])
            self.assertTrue(all(Path(p).read_bytes().startswith(b'\x89PNG') for p in paths))
            return await original(body)
        self.worker.infer=inspect
        task=asyncio.create_task(self.http('POST','/infer',json.dumps({'prompt':'slow','images':[IMAGE]}).encode()))
        while not self.worker.lock.locked():await asyncio.sleep(.001)
        self.assertTrue(all(Path(p).exists() for p in paths))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        await asyncio.gather(*tuple(self.worker.pending))
        self.assertTrue(paths)
        self.assertTrue(all(not Path(p).exists() for p in paths))

    async def test_visual_validation_and_no_arbitrary_file_paths(self):
        for payload in [{'prompt':'x','images':[IMAGE]}, {'prompt':'x','image_paths':['/etc/passwd']},
                        {'prompt':'x','images':['https://example.com/image.png']},
                        {'prompt':'x','images':['data:image/png;base64,bm90LWltYWdl']},
                        {'prompt':'x','images':[IMAGE]*5}]:
            self.assertEqual((await self.http('POST','/infer',json.dumps(payload).encode()))[0],400)
        self.worker.metadata['vision_enabled']=True
        request={'model':'qwen','messages':[{'role':'user','content':[{'type':'text','text':'describe'},
            {'type':'image_url','image_url':{'url':IMAGE}}]}]}
        status,value=await self.http('POST','/v1/chat/completions',json.dumps(request).encode())
        self.assertEqual(status,200)
        self.assertEqual(value['choices'][0]['message']['content'],'describe\n<|vision_start|><|image_pad|><|vision_end|>')


    async def test_openai_error_envelope_and_explicit_unsupported_options(self):
        for extra in ({'temperature':.5},{'n':2},{'stream':True},{'response_format':{'type':'json_object'}},
                      {'max_tokens':8,'max_completion_tokens':8}):
            payload={'model':'qwen','messages':[{'role':'user','content':'hello'}],**extra}
            status,value=await self.http('POST','/v1/chat/completions',json.dumps(payload).encode())
            self.assertEqual(status,400)
            self.assertIsInstance(value['error']['message'],str)
            self.assertEqual(value['error']['type'],'invalid_request_error')

    async def test_interleaved_text_and_images_keep_their_order(self):
        body,images=prepare_request({'messages':[{'role':'user','content':[
            {'type':'text','text':'first image:'},{'type':'image_url','image_url':{'url':IMAGE}},
            {'type':'text','text':'second image:'},{'type':'image_url','image_url':{'url':IMAGE}},
            {'type':'text','text':'compare them'}]}]},True,'qwen')
        marker='<|vision_start|><|image_pad|><|vision_end|>'
        self.assertEqual(body['prompt'],'first image:\n'+marker+'\nsecond image:\n'+marker+'\ncompare them')
        self.assertTrue(body['images_in_prompt'])
        self.assertEqual(len(images),2)

if __name__=='__main__':unittest.main()
