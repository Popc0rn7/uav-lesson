# Copyright (c) 2026 HOUMO AI
#
# File: tensor_io.py
# Description:
#   Read input and output tensor metadata from the native TCIM worker.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0
"""Read the tensor interface emitted by the native DINO worker."""
import numpy as np

DTYPES = {0: 'i1', 1: 'u1', 2: '<i2', 3: '<u2', 4: '<i4', 5: '<u4', 6: '<f2', 7: '<f4'}


def schema(path):
    result = []
    names = set()
    for line in path.read_text().splitlines():
        name, dtype, *shape = line.split('\t')
        shape = tuple(map(int, shape))
        if not name or name in names or any(d <= 0 for d in shape):
            raise ValueError(f'Invalid tensor interface: {name} {shape}')
        names.add(name)
        result.append((name, np.dtype(DTYPES[int(dtype)]), shape))
    if not result:
        raise ValueError(f'Empty tensor interface: {path}')
    return result
