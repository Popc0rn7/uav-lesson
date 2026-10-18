# 来源与迁移边界

任务读取、方向提示、动作量程和大偏航动作规则依据相邻 AeroVLA 当前工作区：
https://github.com/XuPeng23/AeroVLA ，上游 HEAD `2c5ae0987a484ab92f00dd9d9ed493cb3e98e492`，含本机未提交的 demo/实时控制修改。原项目 Apache-2.0；本目录保留其许可证为 LICENSE.AeroVLA。模型权重和 Town05 场景单独准备，其分发条件不由代码许可证代替。

本目录不复制模型加载、训练、旧仿真管理服务或批量评估框架。HTTP 服务由旧仓库 `scripts/serve_inference.py` 提供并独立启动。Stage 4 依赖任务给定目标坐标生成动态方向提示，不宣称无坐标目标搜索；原 SimpleFlight、暂停推理结果不等于本链路 PX4 验收。

评估规则依据同工作区 src/vlnce_src/closeloop_util.py、env_uav.py、assist.py 迁入 stage4/evaluation.py：保留阈值与观测步计数，去除模型框架依赖。webui.css 直接复用 src/demo/dashboard.css，HTML 按源 UI 布局适配原生浏览器，原 Apache-2.0 许可证同上。STOP 服从服务接口契约：远距离 STOP 提前结束并降落，不复现旧评估器后续继续请求的行为。
