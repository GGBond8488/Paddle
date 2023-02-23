# Copyright (c) 2022 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

import numpy as np
import parameterized as param

import paddle
from paddle.fluid import core

core._set_prim_backward_enabled(True)

limit = {
    'float16': {'atol': 1e-3, 'rtol': 1e-3},
    'float32': {'atol': 1e-6, 'rtol': 1e-6},
    'float64': {'atol': 1e-15, 'rtol': 1e-15},
}


def apply_to_static(net, use_cinn):
    build_strategy = paddle.static.BuildStrategy()
    build_strategy.build_cinn_pass = use_cinn
    return paddle.jit.to_static(net, build_strategy=build_strategy)


class PrimeNet(paddle.nn.Layer):
    def __init__(self):
        super(PrimeNet, self).__init__()
        self.fc = paddle.nn.Linear(4, 4)

    def forward(self, x):
        tmp = self.fc(x)
        out = paddle.cumsum(tmp, axis=-1)
        return out


@param.parameterized_class(
    ('primal', 'cotangent', 'dtype'),
    [
        (np.random.rand(10, 10, 10), np.random.rand(10, 10, 10), np.float16),
        (np.random.rand(10, 10, 10), np.random.rand(10, 10, 10), np.float32),
        (
            np.random.rand(4, 8, 16, 16),
            np.random.rand(4, 8, 16, 16),
            np.float64,
        ),
    ],
)
class TestCumsumGradComp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core._set_prim_backward_enabled(True)
        cls.primal = cls.primal.astype(cls.dtype)
        if cls.cotangent is not None:
            cls.cotangent = cls.cotangent.astype(cls.dtype)

    @classmethod
    def tearDownClass(cls):
        core._set_prim_backward_enabled(False)

    def setUp(self):
        paddle.enable_static()

    def tearDown(self):
        paddle.disable_static()

    # TODO(GGBond8488):After the CINN cumsum operator is enhanced,
    # the CINN test needs to be supplemented

    def test_cumsum_grad_comp(self):
        def actual(primal, cotangent):
            core._set_prim_backward_enabled(True)
            mp, sp = paddle.static.Program(), paddle.static.Program()
            with paddle.static.program_guard(mp, sp):
                x = paddle.static.data('primal', primal.shape, primal.dtype)
                x.stop_gradient = False
                v = paddle.static.data(
                    'cotangent', cotangent.shape, cotangent.dtype
                )
                y = paddle.cumsum(x, -1)
                x_cotangent = paddle.static.gradients(y, x, v)
            exe = paddle.static.Executor()
            exe.run(sp)
            return exe.run(
                program=mp,
                feed={'primal': primal, 'cotangent': cotangent},
                fetch_list=x_cotangent,
            )[0]

        def desired(primal, cotangent):
            core._set_prim_backward_enabled(False)
            mp, sp = paddle.static.Program(), paddle.static.Program()
            with paddle.static.program_guard(mp, sp):
                x = paddle.static.data('primal', primal.shape, primal.dtype)
                x.stop_gradient = False
                v = paddle.static.data(
                    'cotangent', cotangent.shape, cotangent.dtype
                )
                y = paddle.cumsum(x, -1)
                x_cotangent = paddle.static.gradients(y, x, v)
            exe = paddle.static.Executor()
            exe.run(sp)
            return exe.run(
                program=mp,
                feed={'primal': primal, 'cotangent': cotangent},
                fetch_list=x_cotangent,
            )[0]

        if (
            paddle.device.get_device() == "cpu"
            and self.primal.dtype == np.float16
        ):
            print("pass cpu+float16 case")
        else:
            np.testing.assert_allclose(
                actual=actual(self.primal, self.cotangent),
                desired=desired(self.primal, self.cotangent),
                rtol=limit[str(self.primal.dtype)]['rtol'],
                atol=limit[str(self.primal.dtype)]['atol'],
            )
        core._set_prim_backward_enabled(False)


if __name__ == '__main__':
    unittest.main()
