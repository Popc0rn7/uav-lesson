"""AirSim 执行器：沿用任务账本与 PX4 控制，车队由 task 统一管理。"""
import math
from pathlib import Path

from agent_runtime import FlightRuntime
from agent_errors import FatalControl
from qwen_agent import SYSTEM, QwenAgent
from stage5.airsim.perception import AirSimPerception

SUPPORTED_MODES = ('rear_above',)


def supported_stage(stage, task=None):
    if stage.get('skill') not in ('observe_target', 'follow_vehicle'):
        raise ValueError('AirSim只支持observe_target/follow_vehicle；不能调用红色专用技能')
    if stage['skill'] == 'follow_vehicle' and stage.get('following_mode') not in SUPPORTED_MODES:
        raise ValueError('当前前向相机只开放 rear_above 候选')
    if stage['skill'] == 'follow_vehicle':
        for key, low, high in (('horizontal_distance_m', 3, 12), ('above_m', 1, 4)):
            value = stage.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'当前AirSim候选要求{key}为{low}～{high}')
        if task:
            for key, expected in (('horizontal_distance_m', task['behind_m']), ('above_m', task['above_roof_m']), *(() if task.get('continuous') else (('duration_s', task['duration_s']),))):
                value = stage.get(key)
                if type(value) not in (int, float) or not math.isclose(value, expected):
                    raise ValueError(f'固定任务要求{key}={expected}，不能改写用户要求')
    if task and task.get('continuous') and stage['skill'] == 'follow_vehicle' and stage.get('continuous') is not True:
        raise ValueError('当前任务要求continuous=true持续跟随，不设置固定秒数完成条件')
    if task and 'pickup' not in str(stage.get('dino_text', '')).lower():
        raise ValueError('当前任务目标是pickup，不得换成其他车辆')


class AirSimQwenAgent(QwenAgent):
    def request(self, purpose, payload, images, timeout):
        result = super().request(purpose, payload, images, timeout)
        if purpose == 'review':
            stages_now = payload['plan']['stages']
            expected_id = stages_now[payload['current_index']]['id']
            expected_attempt = payload['stage_reports'][-1]['attempt']
            if (('reviewed_stage_id' in result and result['reviewed_stage_id'] != expected_id) or
                    ('reviewed_attempt' in result and result['reviewed_attempt'] != expected_attempt)):
                raise ValueError(f'验收对象不匹配：当前reviewed_stage_id={expected_id}, reviewed_attempt={expected_attempt}；不得引用旧阶段结果')
            result = {**result, 'reviewed_stage_id': expected_id, 'reviewed_attempt': expected_attempt}
        stages = result.get('stages', []) if purpose == 'plan' or result.get('action') == 'modify_plan' else []
        if result.get('action') == 'modify_stage':
            stages = [result.get('stage', {})]
        if isinstance(stages, list):
            for stage in stages:
                if isinstance(stage, dict):
                    supported_stage(stage, self.config.get('AIRSIM_TASK'))
        return result

SYSTEM_AIRSIM = '''你是 AirSim 三车场景的无人机任务负责人。只返回JSON。
任务距离单位为米，时长单位为秒。前后左右均相对目标车辆的行驶方向，高度以目标车顶为基准。
持续跟随任务使用continuous=true，无需duration_s；不要创建累计10秒等固定时长完成条件。Jev依据当前任务与观测判断running/done/failed，总预算和总timeout限制运行。valid_follow_s仅作诊断，不作为验收门槛。
用户任务字段只包含原始自然语言要求；不得把系统约定、JSON协议或内部配置追加到mission描述。
当前可执行技能只有 observe_target（观察/寻找与可选超量程接近）和 follow_vehicle（指定车辆后上方跟随）。
follow_vehicle 使用新鲜DINO候选、RGBD表面深度和当前帧候选，没有颜色掩膜、平移搜索、绕障或通用重识别。
无人机出生朝向已在场景设置中改为180度；起飞后直接使用当前实时画面规划，不再固定转半圈。
由你先根据画面和用户任务决定策略，并通过stage.goal、completion_criteria、failure_criteria向Jev下达语言指示。
先检查当前图像和新鲜感知证据是否已可靠确认指定目标；未确认或不在视野时，先规划独立observe_target阶段寻找并确认，再规划follow_vehicle。
寻找阶段用goal给出语言指示，例如“保持高度环视寻找指定pickup；明确超量程时可按方位低速接近以获取实测深度”，并按需开放scan_yaw。
只有当前已有可靠目标确认时才可直接进入跟随；不能把“未看到目标”当成“可以直接跟随”，也不能只在跟随阶段隐含补做寻找。
寻找完成不等于原任务完成，必须继续后续跟随；Jev只判断当前寻找阶段，Qwen负责验收和推进。
scan_yaw只是可选的原地偏航基础动作（20度/秒，不授权平移），是否开放由你设置allowed_skills。
Jev依据当前语言指示和实时观测决定转向、继续、停止及当前阶段完成/失败；没有固定一圈、见候选即停或独立搜索时限。
初始起飞高度已经由任务入口提高以扩大寻找视野，无需再添加升高阶段；找到后仍须下降/调整至用户要求的车顶上方高度，不得改写above_m。
寻找需留出环视、可靠确认和Qwen验收时间；本轮可给寻找约60秒/36次Jev，跟随约75秒/41次Jev，按剩余总时间调整，不机械照抄。
执行器不会用旧框关联或候选分差否决当前检测；target_selection报告候选分数及身份尚未由关联验证的事实，由Jev结合当前信息与记忆判断。Jev的done/failed直接交给你验收，不由执行器重复驳回；持续跟随不以有效秒数作门槛。成功阶段验收期间执行器仍用实时感知和Jev继续上一阶段，不悬停等待；失败、额度或超时耗尽则保持。
阶段allocation和任务总timeout约束执行时间；你负责验收、继续、重试或修改策略。
当前只有内置前向相机，因此本轮不支持左侧伴随或正上方跟随；不支持则返回 {"unsupported_reason":"原因"}。
目标明确超量程too_far表示已找到且>20米，用20米截断代理和检测方位支持approach_target低速水平接近；由Jev按当前阶段指示选择，不另请求Qwen逐步决定接近。进入量程后approach_target继续按实测距离接近至所需水平间距，跟随阶段有实测运动几何时approach_target和hold_course均执行含运动方向的相对目标控制，不因选接近而停在水平间距边界。代理不是实测值，不计跟随达标。框内最大深度层用于控制，其他层保留遮挡证据；NaN和无采集时刻PX4位姿不能生成几何。
高度参考是检测框上部光线与表面深度推算的近似车顶，不是实测车顶中心；必须在验收中说明此局限。
用户任务按原文执行：领车yellow pickup、中车grey-green armored vehicle、尾车white van；dino_text保留对应颜色和车型，不得改成红车或更换目标。方向取自视觉估计的车辆运动，不使用仿真车辆真值。
初始计划 version=2，以下示例用于目标尚未确认的现场，额度需按实际剩余时间调整：
{"version":2,"mission":"用户原始任务","stages":[{"id":"find","goal":"保持高度环视寻找指定pickup，明确超量程时可低速接近",
"skill":"observe_target","dino_text":"a yellow pickup truck.","completion_criteria":"指定pickup已由新鲜DINO可靠确认，too_far也算找到，但不等于已可精确跟随",
"failure_criteria":"根据当前观测无法继续寻找指定目标","allowed_skills":["brake","reacquire","scan_yaw","approach_target"],
"allocation":{"budget":36,"timeout":60}},{"id":"follow","goal":"持续跟随指定pickup",
"skill":"follow_vehicle","following_mode":"rear_above","dino_text":"a yellow pickup truck.",
"horizontal_distance_m":8,"above_m":2,"continuous":true,"completion_criteria":"已建立指定相对位置的持续跟随，由Jev判断阶段结果",
"failure_criteria":"搜索预算用尽仍无法跟踪或实际受阻","allowed_skills":["hold_course","brake","reacquire","scan_yaw","approach_target"],
"allocation":{"budget":41,"timeout":75}}]}。
observe_target也需id、goal、dino_text、完成/失败标准、allocation，allowed_skills可选brake/reacquire/scan_yaw/approach_target，不强制包含偏航动作。
水平距离3～12米、上方1～4米。任务所要求的距离必须保留；持续跟随不设固定秒数。
''' + 'allocation.budget' + SYSTEM.split('allocation.budget', 1)[1]


class AirSimFlightRuntime(FlightRuntime):
    def __init__(self, config, output, deadline, *, flight, lease, stop_convoy):
        self.stop_convoy = stop_convoy
        super().__init__(config, output, deadline, flight=flight, lease=lease, perception_class=AirSimPerception)

    def snapshot(self):
        value = super().snapshot()
        value['review_execution'] = ('continue live perception and Jev within current allocation; stop on failure/budget/timeout'
                                     if getattr(self, 'review_continuing', False) else 'not continuing')
        return value

    def start(self, stage, progress, tag, directory):
        supported_stage(stage, self.config.get('AIRSIM_TASK'))
        return super().start(stage, progress, tag, directory)

    def service(self):
        if self.config.get('AIRSIM_RUN_DIR') and (Path(self.config['AIRSIM_RUN_DIR'])/'land.request.json').exists():
            raise FatalControl('本轮已请求人工降落或仿真急停，取消任务控制')
        super().service()
        if getattr(self, 'review_continuing', False):
            result = self.step(continuing=True)
            if result is not None:
                self.review_continuing = False
                self.active = False
                self.flight.send([0,0,0], self.yaw)
        # capture-time位姿缺失等错误不能用旧帧绕过；基类step负责保持/失流终结。
        if self.config.get('STAGE5_BACKEND') != 'airsim':
            raise FatalControl('AirSim 后端配置失配')

    def begin_review(self, result):
        self.review_continuing = result.get('status') == 'done'
        self.review_result = result
        report = self.end(result, keep_running=self.review_continuing)
        self.review_initial_calls = report['jev_calls']
        return report

    def finish_review(self):
        self.review_continuing = False
        if self.actor is None:
            return 0
        final = self.end(self.review_result)
        from evidence import write_json
        write_json(self.directory/'review-continuation.json', final)
        return max(0, final['jev_calls']-self.review_initial_calls)

    def freeze(self):
        self.review_continuing = False
        cancelled = self.config.get('AIRSIM_RUN_DIR') and (Path(self.config['AIRSIM_RUN_DIR'])/'land.request.json').exists()
        if cancelled:
            self.active = False; self.frozen = True
            if self.flight: self.flight.send([0,0,0],getattr(self,'yaw',0))
        else:
            super().freeze()
        self.stop_convoy()

SYSTEM_AIRSIM = SYSTEM_AIRSIM.replace('阶段结束后无人机悬停；Qwen请求期间仿真和车辆持续运动；', '成功阶段结束后继续实时执行上一阶段；Qwen请求期间仿真和车辆持续运动；').replace('验收期间无人机悬停，仿真和车辆持续运动，目标可能在模型等待期间离开视野，不要假定仍能跟随。', '成功阶段验收期间继续实时控制；失败或阶段预算耗尽则保持。').replace('验收应结合valid_follow_s、末段/最新误差和图片', '持续模式验收结合末段/最新误差和图片，不要求固定秒数；其他模式结合valid_follow_s')
SYSTEM_AIRSIM += '\n当前水平速度上限3m/s、垂直1m/s，感知新鲜度1秒；没有65米范围和固定高度中止。\nAirSim覆盖约定：continuous=true的跟随不以秒数结束；成功阶段验收期间保持实时执行上一阶段，验收accept后才切换或结束。'

SYSTEM_AIRSIM = SYSTEM_AIRSIM.replace(
    'reacquire只会原地等待目标回到当前视野，不具备转头、移动搜索能力。相同观测下重复redo并增加额度不是新策略；没有恢复能力时不要编造搜索动作，也不要把失败accept为达标，可用有界observe_target确认能否恢复；明确无法恢复时使用abort结束原任务，并说明无法完成原目标。',
    'reacquire本身只等待，但AirSim的observe_target可开放scan_yaw原地环视和approach_target有目标几何时接近；这些是实际恢复能力。暂时遮挡后可插入重新寻找与确认阶段，再恢复原跟随，不把本轮Jev失败等同于整个任务不可恢复。')
SYSTEM_AIRSIM += '\n临时遮挡恢复与调度：树木短时遮住目标、当前几帧无检测或本轮tracking_lost，只说明当前阶段中断，不证明整任务失败。结合剩余总时间、预算、最近目标事实与当前图像决定恢复；恢复尚可行时优先modify_plan插入observe_target重新寻找/确认，再保留原follow_vehicle要求。不得盲飞追逐不存在的目标。只有有证据表明恢复不可行或资源不足才abort，不强制固定恢复次数。\n协议以action为准，多余字段忽略并记录，不触发修正；redo只重新执行当前阶段，allocation省略则复用当前额度配置，已耗资源不退还；显式allocation无效仍需修正；插入子任务必须action=modify_plan并提供stages。stages仅替换当前及后续阶段，已接受前缀不可重用id，例如recover_pickup_1后接follow。modify_stage使用stage。reviewed_stage_id和reviewed_attempt由本地按当前请求上下文绑定，无需输出；若显式输出必须对应当前阶段和本轮报告；只评价本次阶段报告，不复用history中find的成功结论。failed仍可基于本轮独立证据判断，但不得把观察成功当跟随完成。'
