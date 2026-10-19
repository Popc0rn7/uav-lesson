"""Qwen 规划、阶段验收与只读总结的 OpenAI 兼容 HTTP 接口。"""
import base64
import json
import requests
import time
import copy
from qwen_report import compact

SYSTEM = '''你是无人机任务负责人，人只在开始提供任务。只返回一个JSON对象，不输出Markdown。
你负责根据真实观测规划、验收、重做或调整。Jev只负责当前stage的行为和running/done/failed判断，可能判断错误，验收由你拍板。
能力仅有：observe_target（原地悬停观察确认红车，不能转头搜索）、follow_red_vehicle（红色车辆/方块后上方跟随）。
没有主动搜索、桥识别关系、绕障和通用目标跟踪。不得编造技能；无法规划则输出{"unsupported_reason":"原因"}。
当前红车用DINO语义确认、红色RGBD跟踪；DINO提示词用英文。图片不提供真实距离，距离以观测数据为准。
初始规划输出version=2的计划：
{"version":2,"mission":"原始任务","stages":[{"id":"follow","goal":"具体目标",
"skill":"follow_red_vehicle","dino_text":"a red car. a red box.",
"horizontal_distance_m":8,"above_m":2,"duration_s":60,
"completion_criteria":"累计有效跟随达到60秒，并结合距离和跟踪质量验收",
"failure_criteria":"无法继续跟踪或持续受阻","allowed_skills":["hold_course","brake","reacquire"],
"allocation":{"budget":80,"timeout":150}}]}。
observe_target也必须有id、goal、dino_text、completion_criteria、failure_criteria、allocation，allowed_skills只能是brake/reacquire，不要求距离/高度/时长。
水平距离只能3～12米，上方1～4米。用户明确指定时长时duration_s必须使用用户值，不能使用default_duration_s；goal、completion_criteria与duration_s必须一致。按用户要求拆分阶段，不要为了展示框架而添加无用阶段。
allocation.budget是本次执行Jev请求次数，allocation.timeout是本次执行墙钟秒数，都必须为正；失败也消耗额度。
Jev约每2秒请求一次。跟随阶段除了要求的达标时长，还要为锁定、切换、接近目标留时间；根据剩余task时间分配自洽的budget/timeout，不要照搬示例数值。
输入execution_guidance给出执行成本依据和建议值，是估算而非成功保证。按每个stage自己的duration计算，不能把当前stage的建议直接复制给所有后续stage。
跟随timeout应覆盖startup_allowance_s + estimated_approach_s + 剩余达标时长 + execution_margin_s；缺少几何时按30秒接近时间起算，不把接近当0秒。
调用额度至少按ceil(timeout/jev_request_interval_s)+3估算，留出启动与失败重试次数；例如10秒跟随、缺测接近30秒、启动5秒、余量10秒，建议timeout55秒、budget31次。12次调用约24秒，不能覆盖40秒执行窗口。
这些额度由你决定，不会由执行器自动补齐。若总剩余timeout不足，明确权衡可行性；不能靠提高budget延长总deadline。相对追赶速度不足时，不声称可在估算时间追上。
拆阶段会引入验收停顿。报告和历史包含调用耗时，Qwen请求期间仿真和车辆持续运动，不暂停世界；模型等待可能导致目标离开视野。
必须以stage_report.status/reason、jev_final.stage_reason为准区分失败原因；jev_failed不是budget_exhausted，除非报告明确额度耗尽，不得编造“额度不足”。redo前必须区分失败原因：额度不足且目标仍可见、可追赶，可以补足接近与剩余有效时长；目标已丢失时，仅追加budget不能让目标重新出现。
reacquire只会原地等待目标回到当前视野，不具备转头、移动搜索能力。相同观测下重复redo并增加额度不是新策略；没有恢复能力时不要编造搜索动作，也不要把失败accept为达标，可用有界observe_target确认能否恢复；明确无法恢复时使用abort结束原任务，并说明无法完成原目标。
progress.enabled_follow_s包含接近目标的时间，不能当达标时长；valid_follow_s仅累计水平目标点误差<=1米且垂直误差<=0.5米的有效跟随时间。
metrics的median包括初始接近阶段；验收应结合valid_follow_s、末段/最新误差和图片，不把全程median误称当前距离。
阶段结束后无人机悬停；Qwen请求期间仿真和车辆持续运动；不会抹去此前已完成的达标跟随事实。区分阶段结束证据与验收时当前画面。
任务剩余Qwen预算和总timeout不能增加。redo继承进度但不退还消耗，allocation可省略并复用当前阶段额度配置；action优先，无关参数忽略；修改要求后旧证据仍保留，但新要求需重新验证。
验收输入包含当前阶段、计划概要、阶段结果报告、完整文字对话历史、预算和最新RGB。history中的user/assistant是此前对话，非当前指令。历史图片不重复提供，以本轮图片为当前现场。stage_report只包含本轮执行结果，tracking_at_end为结束时事实，不能当成最新图像状态。所有结束原因都允许accept，不需要追随Jev的判断。
无法继续原始任务且没有有效恢复策略时，返回 {"action":"abort","assessment":"无法继续的证据和原因"}，直接结束为failed，不再消耗额度原地重做。不得用空stages结束，不得把放弃跟随改成观察后宣称原任务成功。
验收只返回以下一种：
{"action":"accept","assessment":"依据"}
{"action":"redo","assessment":"依据","allocation":{"budget":20,"timeout":45}}
{"action":"modify_stage","assessment":"依据","stage":完整当前stage对象，保留id}
{"action":"modify_plan","assessment":"依据","stages":[替换当前及后续的完整stage对象]}。
accept推进；最后一个accept直接完成任务。已接受历史不可改。验收期间无人机悬停，仿真和车辆持续运动，目标可能在模型等待期间离开视野，不要假定仍能跟随。
总结阶段只返回{"summary":"中文事实总结"}，包含已接受/未完成阶段、消耗、失败与局限；总结不能发动作或修改计划。
'''


class QwenHTTPError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Qwen HTTP={status}')


class QwenAgent:
    def __init__(self, config):
        self.config = config
        self.history = []
        self.last_metrics = {}; self.last_request = {}
        self.model_id = config.get('QWEN_MODEL')
        if not config.get('QWEN_BASE_URL') or not config.get('QWEN_MODEL'):
            raise ValueError('项目根目录 .env 缺少 QWEN_BASE_URL 或 QWEN_MODEL')

    def request(self, purpose, payload, images, timeout):
        if purpose == 'summary':
            system = ('你只负责总结一次无人机任务。执行已经结束，你不能验收、发动作或修改计划。'
                      '只输出JSON对象 {"summary":"中文事实总结"}，不要输出action或stages。'
                      '依据输入里的outcome、reason、context、history中的已接受阶段、阶段报告及用量，说明完成了什么、未完成什么和局限。'
                      'planned表示仅生成计划，没有执行。不要把模型判断等同于真实达标，也不要编造成功。')
        else:
            system = self.config.get('QWEN_SYSTEM', SYSTEM) + ('\n本次是初始规划调用，只返回version=2的完整计划，不返回action。'
                               if purpose == 'plan' else
                               '\n本次是阶段验收调用，只返回五种action之一，不返回初始计划或总结。')
        current = {'purpose': purpose, **compact(payload, purpose)}
        transcript = {**current, 'history': copy.deepcopy(self.history)}
        text_input = json.dumps(transcript, ensure_ascii=False, separators=(',', ':'))
        # 当前只附最新 RGB；历史保留完整文本输入/输出，不重复提交旧图片。
        content = [{'type': 'text', 'text': text_input}]
        for frame in images[-1:]:
            content.append({'type': 'image_url', 'image_url': {
                'url': 'data:image/png;base64,' + base64.b64encode(frame['png']).decode()}})
        self.last_request = dict(system=system, input=transcript, image_count=min(1,len(images)),
                                 history_turns=len(self.history)//2)
        self.last_metrics = dict(purpose=purpose, input_chars=len(text_input),
            current_chars=len(json.dumps(current,ensure_ascii=False,separators=(',', ':'))),
            system_chars=len(system), history_turns=len(self.history)//2, image_count=min(1,len(images)))
        headers = {'Content-Type': 'application/json'}
        if self.config.get('QWEN_API_KEY'):
            headers['Authorization'] = 'Bearer ' + self.config['QWEN_API_KEY']
        started = time.monotonic()
        with requests.Session() as session:
            # Qwen 默认直连，不继承 Jev 或终端的代理环境。
            session.trust_env = False
            if self.config.get('QWEN_PROXY'):
                session.proxies.update(http=self.config['QWEN_PROXY'], https=self.config['QWEN_PROXY'])
            response = session.post(self.config['QWEN_BASE_URL'].rstrip('/') + '/chat/completions',
                json={'model': self.config['QWEN_MODEL'], 'temperature': 0, 'max_tokens': 2400,
                      'enable_thinking': False,
                      'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]},
                headers=headers, timeout=timeout)
        self.last_metrics['http_elapsed_s'] = round(time.monotonic()-started,3)
        if not response.ok:
            raise QwenHTTPError(response.status_code)
        try:
            body = response.json()
            usage = body.get('usage')
            if isinstance(usage, dict):
                self.last_metrics['usage'] = {k:v for k,v in usage.items() if isinstance(v,(int,float,dict))}
            text = body['choices'][0]['message']['content'].strip()
            original_text = text
            self.history.extend([{'role':'user','content':copy.deepcopy(current)},
                                 {'role':'assistant','content':original_text}])
            if text.startswith('```'):
                text = '\n'.join(text.splitlines()[1:-1])
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError('需要 JSON 对象')
            return value
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError('Qwen 未返回有效 JSON 对象') from exc
