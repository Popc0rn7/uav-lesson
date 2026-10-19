"""Board-local Grounding DINO tiny preprocessing and box decoding."""
import base64
import time
from pathlib import Path
import cv2
import numpy as np
from image_resize import resize_rgb
from bert_tokenizer import BertTokenizer
from tensor_io import schema


class Pipeline:
    def __init__(self, metadata_dir, tokenizer_dir):
        self.inputs = schema(Path(metadata_dir) / 'inputs.tsv')
        self.outputs = schema(Path(metadata_dir) / 'outputs.tsv')
        shapes = {n: s for n, _, s in self.inputs}
        image_shape = shapes.get('pixel_values', ())
        if len(image_shape) != 4 or image_shape[:2] != (1, 3):
            raise ValueError('Expected batch=1 NCHW image input')
        self.height, self.width = image_shape[2:]
        self.shortest_edge = min(self.height, self.width)
        self.longest_edge = 1333 if (self.height, self.width) == (800, 1344) else max(self.height, self.width)
        expected = {'pixel_values': image_shape, 'pixel_mask': (1, self.height, self.width),
                    'input_ids': (1, 256), 'token_type_ids': (1, 256),
                    'attention_mask': (1, 256), 'position_ids': (1, 256),
                    'text_self_attention_mask': (1, 256, 256)}
        if shapes != expected:
            raise ValueError(f'Unsupported Grounding DINO export interface: {shapes}')
        if {n: s for n, _, s in self.outputs} != {'pred_logits': (1, 900, 256), 'pred_boxes': (1, 900, 4)}:
            raise ValueError('Unsupported Grounding DINO outputs')
        self.tokenizer = BertTokenizer(tokenizer_dir, 256)

    def prepare(self, directory, image, prompt, timings=None, image_mode='resize'):
        timings = {} if timings is None else timings
        start = time.perf_counter()
        h, w = image.shape[:2]
        # Derive the resize canvas from the native model interface.
        # Keep the original 800x1344 export's 1333-pixel longest-edge convention.
        if image_mode == 'resize':
            short = max(1, min(self.shortest_edge, int(round(self.longest_edge * min(h, w) / max(h, w)))))
            rh, rw = (short, int(short*w/h)) if h <= w else (int(short*h/w), short)
            rh, rw = max(1, rh), max(1, rw)
            scale = min(1.0, self.height/rh, self.width/rw)
            rh, rw = max(1, int(rh*scale)), max(1, int(rw*scale))
        elif image_mode == 'pad':
            if h > self.height or w > self.width:
                raise ValueError('Direct padding image exceeds the static model canvas')
            rh, rw = h, w
        else:
            raise ValueError('image_mode must be resize or pad')
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        timings['image_color_and_geometry_ms'] = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        resized = resize_rgb(rgb, rw, rh)
        timings['image_resize_ms'] = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        resized = resized.astype(np.float32)/255.
        normalized = (resized - np.array([.485, .456, .406], np.float32))/np.array([.229, .224, .225], np.float32)
        pixels = np.zeros((1, 3, self.height, self.width), np.float32)
        pixels[0, :, :rh, :rw] = normalized.transpose(2, 0, 1)
        mask = np.zeros((1, self.height, self.width), bool)
        mask[0, :rh, :rw] = True
        timings['image_normalize_pad_ms'] = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        encoded = self.tokenizer.encode(prompt)
        timings['text_tokenize_ms'] = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        ids = np.asarray(encoded.ids)
        # Grounding DINO resets positions and isolates attention at phrase punctuation.
        attention = np.eye(256, dtype=bool)[None]
        positions = np.zeros((1, 256), dtype=np.int64)
        previous = 0
        for column, token in enumerate(ids):
            if token not in self.tokenizer.special:
                continue
            if column not in (0, 255):
                attention[0, previous+1:column+1, previous+1:column+1] = True
                positions[0, previous+1:column+1] = np.arange(column-previous)
            previous = column
        values = {'pixel_values': pixels, 'pixel_mask': mask, 'input_ids': ids[None],
                  'token_type_ids': np.asarray(encoded.type_ids)[None],
                  'attention_mask': np.asarray(encoded.attention_mask)[None],
                  'position_ids': positions, 'text_self_attention_mask': attention}
        timings['text_masks_ms'] = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        # Keep request-specific tokens on disk so no mutable prompt state is shared.
        np.save(Path(directory)/'tokens.npy', ids, allow_pickle=False)
        for i, (name, dtype, shape) in enumerate(self.inputs):
            value = np.asarray(values[name], dtype=dtype)
            if value.shape != shape:
                raise ValueError(f'Wrong shape for {name}: {value.shape}')
            value.tofile(Path(directory)/f'input_{i}.bin')
        timings['input_cast_write_ms'] = (time.perf_counter()-start)*1000

    def finish(self, directory, image, threshold, overlay, timings=None):
        timings = {} if timings is None else timings
        start = time.perf_counter()
        outputs = {n: np.fromfile(Path(directory)/f'output_{i}.bin', dtype=d).reshape(s).astype(np.float32)
                   for i, (n, d, s) in enumerate(self.outputs)}
        timings['output_read_cast_ms'] = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        logits, boxes = outputs['pred_logits'][0], outputs['pred_boxes'][0]
        if np.isnan(logits).any() or not np.isfinite(boxes).all():
            raise RuntimeError('Invalid model outputs')
        probabilities = 1/(1+np.exp(-np.clip(logits, -80, 80)))
        scores = probabilities.max(axis=-1)
        ids = np.load(Path(directory)/'tokens.npy', allow_pickle=False)
        h, w = image.shape[:2]
        detections = []
        draw_ms = 0.
        for i in np.flatnonzero(scores > threshold):
            cx, cy, bw, bh = boxes[i]
            box = np.array([cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2])*[w,h,w,h]
            box = np.clip(box, [0,0,0,0], [w,h,w,h])
            selected = (probabilities[i] > .25)
            selected[[0, 255]] = False
            selected &= ~np.isin(ids, list(self.tokenizer.special | {0}))
            label = self.tokenizer.decode(ids[selected].tolist())
            detections.append({'query_id': int(i), 'score': float(scores[i]), 'label': label, 'box_xyxy': box.tolist()})
            if overlay:
                draw_start = time.perf_counter()
                xy = np.rint(box).astype(int)
                cv2.rectangle(image, tuple(xy[:2]), tuple(xy[2:]), (0,255,0), 2)
                cv2.putText(image, label, tuple(xy[:2]), cv2.FONT_HERSHEY_SIMPLEX, .5, (0,255,0), 1)
                draw_ms += (time.perf_counter()-draw_start)*1000
        timings['box_score_label_ms'] = (time.perf_counter()-start)*1000-draw_ms
        timings['overlay_draw_ms'] = draw_ms
        result = {'width': w, 'height': h, 'detections': detections}
        if overlay:
            start = time.perf_counter()
            ok, png = cv2.imencode('.png', image)
            timings['overlay_png_encode_ms'] = (time.perf_counter()-start)*1000
            if not ok:
                raise RuntimeError('Overlay encoding failed')
            start = time.perf_counter()
            result['overlay_png_base64'] = base64.b64encode(png).decode('ascii')
            timings['overlay_base64_encode_ms'] = (time.perf_counter()-start)*1000
        return result
