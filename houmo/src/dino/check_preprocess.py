"""Verify seven native input tensors against bundled samples, without an NPU."""
import argparse
import json
from pathlib import Path
import tempfile
import cv2
import numpy as np
from pipeline import Pipeline


def main():
    here = Path(__file__).resolve().parent
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--bundle', type=Path, default=here/'bundle')
    cli.add_argument('--tokenizer', type=Path, default=here/'tokenizer')
    args = cli.parse_args()
    with tempfile.TemporaryDirectory(prefix='dino-preprocess-') as temp:
        root = Path(temp)
        config = json.loads((args.bundle/'bundle.json').read_text())['config']
        height, width = config['height'], config['width']
        (root/'inputs.tsv').write_text(f'pixel_values\t6\t1\t3\t{height}\t{width}\npixel_mask\t0\t1\t{height}\t{width}\ninput_ids\t4\t1\t256\ntoken_type_ids\t4\t1\t256\nattention_mask\t0\t1\t256\nposition_ids\t4\t1\t256\ntext_self_attention_mask\t0\t1\t256\t256\n')
        (root/'outputs.tsv').write_text('pred_logits\t6\t1\t900\t256\npred_boxes\t6\t1\t900\t4\n')
        pipeline = Pipeline(root, args.tokenizer)
        for index,prompt in enumerate(('shoe', 'shoe. person.', 'elephant')):
            with np.load(args.bundle/f'case{index:04}.npz',allow_pickle=False) as data:
                mask = data['pixel_mask'][0]
                h,w = int(mask.any(1).sum()),int(mask.any(0).sum())
                pixels = data['pixel_values'][0,:,:h,:w].transpose(1,2,0)
                rgb = np.rint((pixels*np.array([.229,.224,.225])+np.array([.485,.456,.406]))*255).clip(0,255).astype(np.uint8)
                pipeline.prepare(root, cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR), prompt)
                for i,(name,dtype,shape) in enumerate(pipeline.inputs):
                    actual = np.fromfile(root/f'input_{i}.bin',dtype=dtype).reshape(shape)
                    if not np.array_equal(actual,data[name].astype(dtype)):
                        raise AssertionError(f'Case {index}: input mismatch: {name}')
            print(f'case{index:04}: all seven inputs exactly equal after native dtype conversion')
        for shape in ((113,37,3),(1,4000,3)):
            pipeline.prepare(root,np.zeros(shape,np.uint8),'car')
            mask=np.fromfile(root/'input_1.bin',dtype=np.int8).reshape(height,width)
            assert mask.any()
        try:
            pipeline.prepare(root,np.zeros((10,10,3),np.uint8),'shoe '*300)
        except ValueError:
            pass
        else:
            raise AssertionError('Oversized text should be rejected')
        print('Portrait/thin images and overlong prompt: PASS')


if __name__ == '__main__':
    main()
