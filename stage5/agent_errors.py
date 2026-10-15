"""任务运行器、飞行执行器与仿真控制共用的故障类型。"""


class FatalControl(RuntimeError):
    """不能由模型验收覆盖的飞控、遥测或仿真控制故障。"""
