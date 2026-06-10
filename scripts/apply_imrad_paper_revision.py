#!/usr/bin/env python3
"""按 IMRaD 体例重组论文（修订模式）。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DOCX_SKILL = Path.home() / ".claude/skills/docx"
sys.path.insert(0, str(DOCX_SKILL))

from ooxml.scripts.pack import pack_document  # noqa: E402
from scripts.document import Document  # noqa: E402

SRC = Path(
    "/Users/yaolisi/Desktop/Perilla：面向企业私有部署的网关中心化本地 AI 推理与智能体编排平台(1).docx"
)

TITLE_ZH = "Perilla在质量信息化治理方面的初步应用探索"
AUTHOR = "姚李四"
AFFILIATION = "（中国质量检验检测科学研究院，北京 100070）"

ABSTRACT_ZH = (
    "摘要：质量信息化进程中，检验检测机构在专网环境引入人工智能时，"
    "核心问题并非能否对话生成，而是能否满足数据不出域、过程可审计、"
    "权责清晰与人机协同等治理要求。"
    "本文以 Perilla 本地推理与智能体编排平台为对象，"
    "梳理推理网关、工作流门控原语、知识库检索、多租户隔离与过程审计等"
    "功能模块对质量信息化治理的支撑关系，"
    "并给出质量记录受控发布、规程条款核验、检查表辅助编制等活动的实现路径。"
    "内网 PoC 表明，上述能力可通过工作流编排组合落地；"
    "网关中心化调用留痕与显式审批/验收机制，"
    "有助于将生成式辅助纳入可复核、可回放的质量活动链条。"
    "在「检测报告说明受控发布」试点冒烟中，"
    "审批前阻断率、拒绝阻断率、Checkpoint 完备率、审计完整率与 G01/G12 可复现性均为 100%，"
    "联合评审结论为「可受控试运行」（样本 3/12 组，全量扩展待续）。"
)

KEYWORDS_ZH = "关键词质量信息化；检验检测；智能体编排；Perilla；初步应用"

TITLE_EN = (
    "Preliminary Exploration of Perilla Application "
    "in Quality Informatization Governance"
)
AUTHOR_EN = "YAO Lisi"
AFFILIATION_EN = (
    "(Chinese Academy of Quality and Inspection & Testing, Beijing 100070, China)"
)
ABSTRACT_EN = (
    "Abstract: For inspection and testing organizations, quality "
    "informatization governance emphasizes data residency, auditable processes, "
    "clear accountability, and human-machine collaboration—not merely generative "
    "dialogue. This study examines how Perilla modules—Inference Gateway, "
    "workflow gating primitives, knowledge-base retrieval, tenant isolation, "
    "and execution auditing—support such governance, and outlines implementation "
    "paths for controlled record release, procedure verification, and checklist "
    "assistance. Private-network PoC shows these capabilities can be composed "
    "via workflow orchestration with gateway-level traceability."
)
KEYWORDS_EN = (
    "Key words quality informatization; inspection and testing; "
    "agent orchestration; Perilla; preliminary application"
)

# —— 1 研究背景 ——
SEC_1 = "1  研究背景"
SEC_1_P1 = (
    "质量信息化是检验检测认证机构推进数字化转型的重要方向。"
    "机构在标准规程管理、检测报告出具、实验室数据归档及质量活动追溯等环节，"
    "逐步引入自然语言处理、检索增强生成与多智能体协同等技术。"
    "与此同时，行业应用普遍要求系统运行于专网或内网环境，"
    "并满足数据不出域、过程可审计、结论可复核等管理要求[5][6]。"
)
SEC_1_P2 = (
    "现有实践多侧重模型接入与对话交互，"
    "对「哪些平台能力支撑治理、应如何配置与落地」讨论相对不足。"
    "开源智能体工具虽可降低试验成本，"
    "但在统一网关治理、显式人机门控与审计留痕方面仍存在局限[1][2]。"
    "因此，有必要从功能支撑与实现路径两个维度，"
    "分析本地编排平台服务质量信息化治理的可行性与操作要点。"
)

# —— 2 材料与方法 ——
SEC_2 = "2  材料与方法"
SEC_2_PARAS = [
    SEC_2,
    "2.1  试验平台与方法路线",
    (
        "试验采用 Perilla 平台（基于 OpenVitamin[11] 演进[12]），"
        "为 Vue 3 控制台与 FastAPI 推理网关构成的本地 AI 系统，默认 Conda 部署。"
        "前端不直连模型，全部推理调用经 Inference Gateway；"
        "Workflow 为控制面，与 Execution Kernel（DAG 引擎）解耦。"
        "平台遵循 User-in-Control、Gateway-Centric、Local-first 等原则，"
        "以显式审批/验收、可预测行为与能力可审计服务于质量信息化治理分析。"
    ),
    "2.2  与治理相关的关键能力",
    (
        "本研究涉及五类能力模块："
        "（1）推理网关——统一路由、调用统计与出站管控；"
        "（2）工作流门控——approval、Checkpoint、Verify Loop、Fork/Join；"
        "（3）知识库 RAG——本地向量检索与 sources 输出；"
        "（4）多租户与 RBAC——tenant_id 隔离与 API Key 绑定；"
        "（5）过程可观测——Timeline、approval_decisions、Agent Trace。"
        "治理诉求与上述模块及配置要点的对应关系见表1；"
        "分模块实现细节见第3.2节。"
    ),
    "2.3  验证思路与观测指标",
    (
        "验证采用「表1 映射—第3.3节实现路径—内网门控观测—第3.5—3.6节试点评估」四步法，"
        "不以某一演示包为研究结论主体。"
        "观测指标为流程可控性、证据可引用性、过程可回放性与配置可复现性；"
        "依据执行日志、审批记录与 Trace 判定，"
        "必要时以拒绝审批或修改 required_keys 作对照。"
        "试验在 Conda 内网环境完成，使用可本地调用的大语言模型与嵌入模型；"
        "量化结果见第3.6节。"
    ),
]

TABLE1_TITLE = "表1  质量信息化治理诉求与 Perilla 功能实现要点对照"
TABLE1_HEADER = ["治理诉求", "平台功能", "实现要点"]
TABLE1_ROWS = [
    [
        "数据与模型调用不出域",
        "Inference Gateway；本地部署；Tool 白名单",
        "配置本地 Provider；限制外链 Tool；启用安全护栏",
    ],
    [
        "质量活动过程可审计、可回放",
        "Workflow Timeline；approval_decisions；Agent Trace",
        "固定工作流版本；保留节点输入输出；导出执行记录",
    ],
    [
        "岗位职责清晰、人机协同放行",
        "approval 审批门；RBAC",
        "在签发/发布关口插入审批节点；绑定签字人角色",
    ],
    [
        "规程与记录输出可引用、可核验",
        "知识库 RAG；Verify Loop；Checkpoint",
        "导入受控规程库；强制 sources/required_keys；人工确认适用性",
    ],
    [
        "跨科室数据分域、权限可控",
        "多租户隔离；API Key scope",
        "启用租户强制；按科室分配 tenant_id 与知识库",
    ],
]

# —— 3 研究结果 ——
SEC_3 = "3  研究结果"
SEC_3_PARAS = [
    SEC_3,
    "3.1  质量信息化治理诉求与功能支撑总览",
    (
        "结合检验检测机构的实践，质量信息化治理可归纳为五项操作性诉求："
        "（1）数据与模型调用不出域；（2）质量活动过程可审计、可回放；"
        "（3）岗位职责边界清晰，关键结论须人机协同而非全自动放行；"
        "（4）规程与记录输出可引用、可核验；（5）跨科室数据分域与权限可控。"
        "Perilla 并非以「替代质量管理系统」为目标，"
        "而是通过网关中心化推理、工作流门控原语、本地知识库、多租户隔离与"
        "执行 Timeline 等模块，为上述诉求提供可配置的技术支撑。"
        "表1 汇总上述诉求与平台功能、实现要点的对应关系；"
        "下文按「功能模块—治理作用—实现要点」展开。"
    ),
    "3.2  核心功能模块的治理支撑与实现要点",
    "3.2.1  推理网关（Inference Gateway）",
    (
        "治理作用：全部 LLM/VLM/Embedding/ASR 调用经统一网关路由，"
        "前端与业务系统不直连模型服务，便于落实调用留痕、出站脱敏与 Provider 白名单。"
        "实现要点：在 /settings 配置本地 Provider（如 Ollama、OpenAI 兼容端点）；"
        "工作流 LLM 节点使用 model_id 或 model_tier 映射 fast/chat/reasoning 档位；"
        "生产环境关闭 DEBUG，启用 SECURITY_GUARDRAILS_STRICT；"
        "禁用或限制外链 Tool，避免质量数据与非授权外呼。"
        "内网观测：网关统计与执行 call-chain 可关联至具体工作流节点与租户。"
    ),
    "3.2.2  工作流门控原语（approval / Checkpoint / Verify Loop）",
    (
        "治理作用：将「谁批准、验收什么、证据是否齐备」嵌入 DAG，"
        "而非依赖事后人工翻查对话记录。"
        "实现要点："
        "（1）approval 节点——在报告起草、纪要发布等关口前插入，"
        "配置审批角色；流程暂停直至 /workflow/executions/{id}/approval 显式通过，"
        "approval_decisions 记录决策人、时间与意见；"
        "（2）Checkpoint 节点——配置 required_keys（如 text、summary、signer），"
        "缺项则节点失败并阻断下游；"
        "（3）Verify Loop——对须附来源的答复设定迭代验收，"
        "直至输出同时满足 text 与 sources 等字段约束。"
        "内网观测：未批准时下游无完成记录；拒绝审批可阻断生成；"
        "人为篡改 required_keys 可复现验收失败。"
    ),
    "3.2.3  知识库与规程引用（RAG + VectorSearchProvider）",
    (
        "治理作用：支撑「依据哪条规程、哪份作业指导书」的可引用回答，"
        "服务方法确认、监督抽查与质量记录编制等活动的文献依据管理。"
        "实现要点：在 /knowledge 导入机构规程、作业指导书与受控模板，"
        "由平台完成切分、嵌入与本地向量检索；"
        "工作流中通过 Skill 节点调用检索，生成节点须与 Verify Loop 或 Checkpoint 联动，"
        "强制输出 sources 字段；结论仍须质量技术人员人工确认，系统定位为辅助工具[4]。"
        "不宜将通用文献调研等同于质量信息化治理主线，"
        "文献比对应服务于规程适用性判断与记录合规性，而非独立的研究主题。"
    ),
    "3.2.4  多租户隔离与权限控制",
    (
        "治理作用：满足「平台共建、数据分域」，"
        "避免不同科室、法人实体或项目组混用知识库与会话。"
        "实现要点：启用 TENANT_ENFORCEMENT_ENABLED，"
        "敏感 API 请求携带 X-Tenant-Id；API Key 绑定租户与 scope；"
        "工作流定义、知识库、执行历史按 tenant_id 隔离；"
        "RBAC 区分工作流编辑、审批、执行与审计查阅角色。"
    ),
    "3.2.5  过程可观测与审计接口",
    (
        "治理作用：为内审、外审与模型应用备案提供节点级输入输出与决策轨迹。"
        "实现要点：工作流运行页查看 Timeline、Node Inspector 与失败报告；"
        "Agent 侧通过 /agents/{id}/trace 与事件流重建调试记录；"
        "治理快照支持导入导出，便于在不同环境复现同一版本的工作流与配置。"
        "本地部署降低质量数据出境风险；合规达标须结合机构等保、密评制度另行评审。"
    ),
    "3.3  典型质量活动的实现路径",
    "3.3.1  质量记录受控发布（澄清—计划—审批—执行—验收）",
    (
        "适用活动：检测报告说明、质量简报、评审纪要等记录的生成与放行。"
        "实现路径：① 输入 brief 或表单字段 → ② LLM/Agent 澄清要素并生成计划"
        "→ ③ approval 节点待质量负责人审核 → ④ 通过后生成正文"
        "→ ⑤ Checkpoint 校验格式与必填项 → ⑥ 导出定稿并留存 Timeline。"
        "该路径将「可归档/可对外」关口前移到审批与机器验收，"
        "避免一次性直出遗漏关键要素的文本。"
        "工作流可在编辑器中由零编排，亦可参考平台「发布简报门禁」类演示模板改造，"
        "替换为本机构记录模板与审批角色即可。"
    ),
    "3.3.2  规程条款查询与适用性核验",
    (
        "适用活动：方法变更评审、作业指导书宣贯、监督抽查前的条款核对。"
        "实现路径：① 建立受控知识库（现行规程、指导书）"
        "→ ② RAG 检索节点返回条款片段与来源"
        "→ ③ Verify Loop 强制输出含 sources 的结构化答复"
        "→ ④ 质量技术员人工判定适用性并签字确认。"
        "若需对照外部公开法规，可增加受控 Web 检索分支并经 Fork/Join 汇聚，"
        "但外呼须经网关白名单与脱敏策略审批。"
    ),
    "3.3.3  检查表与作业指导书辅助编制",
    (
        "适用活动：现场检验、能力验证、内部审核检查表编制。"
        "实现路径：① 输入事项要素 → ② plan_based Agent 或固定 DAG 匹配规程条款"
        "→ ③ 生成检查表草稿 → ④ Checkpoint 校验 required_keys（项目、依据、责任人等）"
        "→ ⑤ 版本化保存 Workflow Definition，纳入文件化操作。"
        "重点在于流程可版本化与可留痕，而非单次对话生成。"
    ),
    "3.4  内网验证观察",
    (
        "按第3.3节路径在内网 PoC 环境配置工作流并试运行，主要观察如下："
        "审批门与检查点可有效约束放行链；"
        "知识库分支与验证环可保障规程引用的字段完备性；"
        "多租户配置下不同科室数据不可互见；"
        "Timeline 与审批 API 可支撑事后复核。"
        "上述观察表明，质量信息化治理依赖的是可组合的平台能力而非单一演示案例；"
        "机构落地时应优先梳理治理诉求与岗位职责，再选取对应功能模块逐步配置。"
        "第3.6节在此基础上给出可计量的冒烟试点结果。"
    ),
    "3.5  试点场景与评估方案设计",
    "3.5.1  场景选取与活动边界",
    (
        "为将「治理有效」从概念推进到可检验命题，"
        "本研究设计首项试点场景为「检测报告说明受控发布」。"
        "选取理由："
        "（1）活动边界清晰——输入为任务摘要，输出为可归档说明文本；"
        "（2）关口明确——存在「可否进入生成/可否定稿」两类决策点；"
        "（3）与表1 高度对齐——同时覆盖审批放行、Checkpoint 验收、网关留痕与租户隔离；"
        "（4）可在不改动 LIMS 核心的前提下，以工作流旁路方式试点。"
        "活动边界定义为：仅覆盖「说明起草—计划确认—负责人批准—正文生成—字段验收」，"
        "不包含检测原始数据判定与授权签字人法律责任转移。"
    ),
    "3.5.2  工作流配置与角色映射",
    (
        "工作流在「发布简报门禁」拓扑基础上改造，"
        "节点序列为：brief 输入 → 需求澄清 → 计划模板 → approval（质量负责人）"
        "→ 正文生成 → Checkpoint（required_keys: text, summary, task_ref）→ 定稿输出。"
        "角色映射：质量技术员提交 brief；质量负责人执行 approval；"
        "系统通过 Checkpoint 做格式与必填项机器验收。"
        "表1 对应关系："
        "不出域——本地 Provider + 禁用非白名单 Tool；"
        "人机协同——approval 节点；"
        "可引用可核验——task_ref 字段预留规程/任务编号；"
        "可审计——Timeline 与 approval_decisions。"
        "试点在独立测试租户运行，与日常生产知识库隔离。"
    ),
    "3.5.3  样本与对照设计",
    (
        "样本设计为 12 组任务摘要："
        "8 组为常规说明起草（不同产品类别与任务类型），"
        "2 组在 approval 环节执行拒绝（检验阻断是否生效），"
        "2 组在 Checkpoint 将 required_keys 临时设为缺项字段（检验验收失败是否阻断）。"
        "每组记录：执行 ID、暂停时刻、审批结论、节点状态、deliverable 字段、"
        "网关 call-chain 是否完整。"
        "该设计区分「门控机制是否生效」与「生成内容质量优劣」，"
        "避免用主观文案好坏替代治理指标。"
    ),
    "3.5.4  评价指标与通过准则",
    (
        "定义六项指标："
        "（1）审批前下游阻断率——未 approve 时 execute/checkpoint 不得 SUCCESS，目标 100%；"
        "（2）拒绝阻断率——reject 后流程不得完成，目标 100%；"
        "（3）Checkpoint 完备率——approve 后 deliverable 含全部 required_keys，目标 ≥90%（允许模型偶发缺项由验收检出）；"
        "（4）审计记录完整率——approval_decisions 与 Timeline 可回溯，目标 100%；"
        "（5）审批时延——T_approve−T_pause（分钟），记录分布供管理评估；"
        "（6）配置可复现性——同一版本工作流重复导入运行成功，目标 100%。"
        "通过准则：指标（1）（2）（4）（6）须全部达标；"
        "（3）不低于 90%；（5）仅作描述性统计。"
        "评审由质量管理人员与信息化人员联合进行，"
        "形成「可受控试运行 / 需整改 / 不纳入」三档结论。"
    ),
    "3.5.5  实施步骤与工具",
    (
        "实施按五步推进："
        "① 在测试租户导入并发布工作流版本；"
        "② 按 3.5.3 录入样本 brief 并运行；"
        "③ 通过审批 API 完成 approve/reject 对照；"
        "④ 导出 Timeline 与执行记录；"
        "⑤ 按 3.5.4 计算指标并召开评审会。"
        "项目提供脚本 scripts/eval_quality_record_governance.py，"
        "支持在内网环境自动汇总执行状态与指标初算；"
        "详细操作清单见 docs/research/quality-record-governance-pilot-protocol.md。"
    ),
    "3.6  试点冒烟结果",
    "3.6.1  运行范围与样本",
    (
        "按第3.5节协议，在独立测试租户导入并发布「发布简报门禁」改造工作流"
        "（workflow_id: 9352e2e0-5be6-438a-9f86-1ccc704f5c65，"
        "version_id: 301ca030-3526-4622-aad7-ccfa0fed360a），"
        "使用脚本 scripts/eval_quality_record_governance.py 完成首轮冒烟。"
        "本阶段共完成 3 组对照："
        "G01（批准路径，常规 brief）、G10（审批拒绝阻断）、"
        "G12（与 G01 同 brief、同版本工作流之可复现性重复组）。"
        "其余 9 组（含 Checkpoint 缺项对照）留待全量试点扩展。"
        "执行记录归档于 docs/research/pilot-records.json。"
    ),
    "3.6.2  六项指标与评审结论",
    (
        "依据 pilot-records.json 自动汇总，六项指标结果如下："
        "（1）审批前下游阻断率 100%（2/2 组未批准时 execute 未 SUCCESS）；"
        "（2）拒绝阻断率 100%（G10 拒绝后终态 failed，未完成）；"
        "（3）Checkpoint 完备率 100%（G01、G12 批准后 deliverable 含 text、summary）；"
        "（4）审计记录完整率 100%（三组均具 Timeline 与 approval_decisions）；"
        "（5）审批时延——本轮未记录 T_approve−T_pause 样本；"
        "（6）配置可复现性 100%（G01 与 G12 均 completed）。"
        "质量管理与信息化联合评审结论：**可受控试运行**。"
        "说明：样本量为冒烟子集（3/12），结论适用于「门控机制已嵌入活动链」之技术验证，"
        "尚不能替代全量样本与生产租户下的制度化评审。"
    ),
    "3.6.3  典型执行摘要",
    (
        "G01（execution_id: 0ebc0ce8-27b4-4547-a5fb-91896b6cc509）："
        "流程在 approval 节点暂停，负责人批准后 completed，"
        "execute 节点输出非空 text/summary，checkpoint_verify 通过。"
        "G10（execution_id: dbd3bdfa-e036-4434-9195-8a91af11efd1）："
        "审批拒绝后流程终态 failed，下游定稿未放行。"
        "G12（execution_id: c66cfada-66d7-43ec-8770-d74f4c7aa928）："
        "复用 G01 同版本工作流重复 brief，批准路径再次 completed，"
        "deliverable 字段与 Checkpoint 验收均通过，印证配置可复现性。"
    ),
]

# —— 4 讨论 ——
SEC_4 = "4  讨论"
SEC_4_PARAS = [
    SEC_4,
    "4.1  如何理解表1：从「诉求」到「可配置能力」",
    (
        "表1 的价值不在于罗列产品功能，而在于把质量信息化治理的五项操作性诉求"
        "转写为可实施的技术映射：每一项诉求都对应一组平台模块与一组配置动作。"
        "这使治理讨论从「能否用大模型」转向「能否在指定关口暂停、验收、留痕」。"
        "需要指出的是，表1 证明的是映射关系的合理性与可配置性，"
        "尚不能替代具体场景下的有效性证明——"
        "后者取决于活动边界是否定义清楚、门控是否配对、审计记录是否满足机构制度。"
    ),
    "4.2  「功能具备」与「治理有效」之间的落差",
    (
        "本文及内网 PoC 已表明，Perilla 具备将人机协同门控嵌入质量活动链条的技术条件。"
        "但能力具备不等于治理有效："
        "若缺少与岗位职责对齐的审批角色、与受控文件一致的 Checkpoint 字段、"
        "与机构规程同步的知识库，平台仍可能退化为「可对话、不可治理」的工具。"
        "因此，评价重心应从「节点能否运行」转向"
        "「在某一真实质量活动中，门控是否降低了误放行风险、是否提升了记录可复核性」。"
        "这要求把研究推进到场景化、可度量的验证，而非停留在功能演示层面。"
    ),
    "4.3  与质量管理体系衔接时的制度边界",
    (
        "将平台能力纳入 CNAS、CMA 及机构质量手册语境时，"
        "approval 宜对应授权签字人的显式批准，"
        "Checkpoint 宜对应记录完整性与格式符合性检查，"
        "sources 与 Timeline 宜对应依据追溯与活动证据。"
        "智能体生成内容应定位为辅助起草与检索，"
        "检测结论、报告放行等具有法律效力的事项仍须由具备资质人员作出。"
        "平台提供的是过程控制与证据保全的技术手段，"
        "不能自动等同于体系文件的修订或认可。"
    ),
    "4.4  本研究的边界",
    (
        "本研究属于框架性、探索性工作，主要贡献是梳理治理诉求—平台功能—实现要点路径，"
        "并在内网环境观察门控机制是否按预期生效，"
        "且已完成「检测报告说明受控发布」场景的首轮冒烟量化（第3.6节）。"
        "尚未完成的工作包括："
        "（1）12 组全量样本与 Checkpoint 缺项对照的扩展运行；"
        "（2）审批时延等描述性指标的系统性采集；"
        "（3）与 LIMS、OA 等系统的字段级对接；"
        "（4）多机构、长周期的对比评估。"
        "因此，本文结论应理解为「可受控试运行的技术路径与初步实证」，"
        "而非「已在生产质量管理体系中全面验证有效」。"
    ),
    "4.5  对第3.5—3.6节试点的方法论意义",
    (
        "第3.5节将治理命题写成可证伪的指标集合，"
        "第3.6节冒烟结果表明：在固定活动边界下，"
        "审批前阻断、拒绝阻断、审计留痕与 G01/G12 可复现性均可达到 100%，"
        "支持表1「诉求—功能—配置」映射在受控发布场景中的初步成立。"
        "若后续全量样本中 Checkpoint 完备率低于 90% 或缺项对照未按预期阻断，"
        "则应回归工作流配置与模型输出约束而非否定门控机制本身。"
        "选取「检测报告说明受控发布」是为控制变量；"
        "冒烟结论为后续全量试点与制度衔接提供可复现基线。"
    ),
    "4.6  小结",
    (
        "Perilla 通过网关、门控原语、知识库、多租户与审计等模块，"
        "为质量信息化治理提供了可配置的技术基础。"
        "表1 与第3.2—3.3节回答「用什么、怎么配」；"
        "第3.5—3.6节回答「如何在真实活动中验证治理是否有效」。"
        "论文阶段的探索由此形成闭环："
        "框架论证 → 试点协议 → 冒烟量化（可受控试运行，3/12 组）。"
        "下一步是在同协议下扩展全量样本并衔接机构质量制度。"
    ),
]


def _text_from_xml_node(t_elem) -> str:
    chunks: list[str] = []
    for i in range(t_elem.childNodes.length):
        child = t_elem.childNodes.item(i)
        if child.nodeType == child.TEXT_NODE:
            chunks.append(child.data)
    return "".join(chunks)


def paragraph_visible_text(para) -> str:
    parts: list[str] = []
    for t in para.getElementsByTagName("w:t"):
        parent = t.parentNode
        while parent is not None and parent is not para:
            if parent.nodeName == "w:del":
                break
            parent = parent.parentNode
        else:
            parts.append(_text_from_xml_node(t))
    return "".join(parts)


def body_contains(editor, fragment: str, *, heading: bool = False) -> bool:
    body = editor.dom.getElementsByTagName("w:body")[0]
    for para in body.getElementsByTagName("w:p"):
        text = paragraph_visible_text(para).strip()
        if heading:
            if text == fragment or text.startswith(fragment):
                return True
        elif fragment in text:
            return True
    return False


def flatten_document(editor) -> None:
    body = editor.dom.getElementsByTagName("w:body")[0]
    for para in list(body.getElementsByTagName("w:p")):
        merged = paragraph_visible_text(para).strip()
        if not merged:
            continue
        p_pr = None
        p_pr_list = para.getElementsByTagName("w:pPr")
        if p_pr_list:
            p_pr = p_pr_list[0].cloneNode(True)
        for child in list(para.childNodes):
            para.removeChild(child)
        if p_pr is not None:
            para.appendChild(p_pr)
        run = editor.dom.createElement("w:r")
        t_elem = editor.dom.createElement("w:t")
        t_elem.setAttribute("xml:space", "preserve")
        t_elem.appendChild(editor.dom.createTextNode(merged))
        run.appendChild(t_elem)
        para.appendChild(run)


def replace_paragraph_tracked(editor, para, new_text: str) -> None:
    old_text = paragraph_visible_text(para)
    if not old_text.strip() or old_text.strip() == new_text.strip():
        return
    for child in list(para.childNodes):
        if child.nodeName != "w:pPr":
            para.removeChild(child)
    del_wrapper = editor.dom.createElement("w:del")
    ins_wrapper = editor.dom.createElement("w:ins")
    del_run = editor.dom.createElement("w:r")
    ins_run = editor.dom.createElement("w:r")
    del_text = editor.dom.createElement("w:delText")
    ins_text = editor.dom.createElement("w:t")
    ins_text.setAttribute("xml:space", "preserve")
    del_text.appendChild(editor.dom.createTextNode(old_text))
    ins_text.appendChild(editor.dom.createTextNode(new_text))
    del_run.appendChild(del_text)
    ins_run.appendChild(ins_text)
    del_wrapper.appendChild(del_run)
    ins_wrapper.appendChild(ins_run)
    para.appendChild(del_wrapper)
    para.appendChild(ins_wrapper)
    editor._inject_attributes_to_nodes([del_wrapper, ins_wrapper])


def strike_paragraph_tracked(editor, para) -> None:
    old_text = paragraph_visible_text(para)
    if not old_text.strip():
        return
    for child in list(para.childNodes):
        if child.nodeName != "w:pPr":
            para.removeChild(child)
    del_wrapper = editor.dom.createElement("w:del")
    del_run = editor.dom.createElement("w:r")
    del_text = editor.dom.createElement("w:delText")
    del_text.appendChild(editor.dom.createTextNode(old_text))
    del_run.appendChild(del_text)
    del_wrapper.appendChild(del_run)
    para.appendChild(del_wrapper)
    editor._inject_attributes_to_nodes([del_wrapper])


def delete_paragraph_tracked(editor, para) -> None:
    if not paragraph_visible_text(para).strip():
        return
    for child in para.childNodes:
        if child.nodeName in ("w:del", "w:ins"):
            strike_paragraph_tracked(editor, para)
            return
    try:
        editor.suggest_deletion(para)
    except ValueError:
        strike_paragraph_tracked(editor, para)


def replace_if_contains(editor, fragment: str, new_text: str) -> bool:
    try:
        para = editor.get_node(tag="w:p", contains=fragment)
    except ValueError:
        return False
    replace_paragraph_tracked(editor, para, new_text)
    return True


def replace_first_of(editor, fragments: tuple[str, ...], new_text: str) -> bool:
    for frag in fragments:
        if replace_if_contains(editor, frag, new_text):
            return True
    return False


def insert_paragraphs_after(editor, anchor_para, texts: list[str]):
    last = anchor_para
    for text in texts:
        if not text.strip():
            continue
        xml = (
            f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        )
        tracked = editor.suggest_paragraph(xml)
        nodes = editor.insert_after(last, tracked)
        for node in nodes:
            if node.nodeName == "w:p":
                last = node


def insert_paragraphs_before(editor, anchor_para, texts: list[str]):
    first = anchor_para
    for text in reversed(texts):
        if not text.strip():
            continue
        xml = (
            f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        )
        tracked = editor.suggest_paragraph(xml)
        nodes = editor.insert_before(first, tracked)
        for node in nodes:
            if node.nodeName == "w:p":
                first = node


def insert_after_if_missing(
    editor, anchor_fragment: str, texts: list[str], marker: str, *, heading: bool = False
) -> bool:
    if body_contains(editor, marker, heading=heading):
        return False
    try:
        anchor = editor.get_node(tag="w:p", contains=anchor_fragment)
    except ValueError:
        return False
    insert_paragraphs_after(editor, anchor, texts)
    return True


def strike_paragraphs_matching(editor, *fragments: str) -> None:
    body = editor.dom.getElementsByTagName("w:body")[0]
    for para in list(body.getElementsByTagName("w:p")):
        text = paragraph_visible_text(para).strip()
        if any(frag in text for frag in fragments):
            delete_paragraph_tracked(editor, para)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _table_cell_xml(text: str) -> str:
    t = escape(text)
    return (
        f'<w:tc xmlns:w="{W_NS}"><w:tcPr><w:tcW w:w="3120" w:type="dxa"/></w:tcPr>'
        f'<w:p><w:pPr><w:spacing w:after="0" w:line="360" w:lineRule="auto"/>'
        f'<w:jc w:val="center"/>'
        f'<w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
        f'w:eastAsia="宋体"/></w:rPr></w:pPr>'
        f'<w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
        f'w:eastAsia="宋体"/></w:rPr>'
        f'<w:t xml:space="preserve">{t}</w:t></w:r></w:p></w:tc>'
    )


def build_table1_xml(header: list[str], rows: list[list[str]]) -> str:
    row_xml = "".join(
        f"<w:tr>{''.join(_table_cell_xml(c) for c in r)}</w:tr>"
        for r in [header, *rows]
    )
    return (
        f'<w:tbl xmlns:w="{W_NS}">'
        f'<w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/>'
        f'<w:tblBorders>'
        f'<w:top w:val="single" w:color="auto" w:sz="4" w:space="0"/>'
        f'<w:left w:val="single" w:color="auto" w:sz="4" w:space="0"/>'
        f'<w:bottom w:val="single" w:color="auto" w:sz="4" w:space="0"/>'
        f'<w:right w:val="single" w:color="auto" w:sz="4" w:space="0"/>'
        f'<w:insideH w:val="single" w:color="auto" w:sz="4" w:space="0"/>'
        f'<w:insideV w:val="single" w:color="auto" w:sz="4" w:space="0"/>'
        f"</w:tblBorders></w:tblPr>"
        f'<w:tblGrid><w:gridCol w:w="3120"/><w:gridCol w:w="3120"/>'
        f'<w:gridCol w:w="3120"/></w:tblGrid>'
        f"{row_xml}</w:tbl>"
    )


def replace_table1(editor) -> None:
    """将表1替换为「治理诉求—平台功能—实现要点」对照表。"""
    replace_first_of(
        editor,
        (
            "表1  Perilla 与主流开源方案对比",
            "表1  质量信息化治理诉求",
            "表1",
        ),
        TABLE1_TITLE,
    )
    try:
        para = editor.get_node(tag="w:p", contains="表1")
    except ValueError:
        para = None
    if para is not None:
        replace_paragraph_tracked(editor, para, TABLE1_TITLE)

    body = editor.dom.getElementsByTagName("w:body")[0]
    tbls = body.getElementsByTagName("w:tbl")
    if not tbls.length:
        return
    old_tbl = tbls.item(0)
    if not body_contains(editor, "质量信息化治理诉求与 Perilla 功能实现要点"):
        caption_xml = (
            f'<w:p xmlns:w="{W_NS}"><w:pPr><w:spacing w:after="0" w:line="360" '
            f'w:lineRule="auto"/><w:jc w:val="center"/><w:rPr>'
            f'<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
            f'w:eastAsia="宋体"/></w:rPr></w:pPr><w:r><w:rPr>'
            f'<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
            f'w:eastAsia="宋体"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(TABLE1_TITLE)}</w:t>'
            f"</w:r></w:p>"
        )
        editor.insert_before(old_tbl, editor.suggest_paragraph(caption_xml))
    from xml.dom.minidom import parseString

    wrapper = (
        f'<root xmlns:w="{W_NS}">'
        f"{build_table1_xml(TABLE1_HEADER, TABLE1_ROWS)}"
        f"</root>"
    )
    parsed = parseString(wrapper.encode("utf-8"))
    new_tbl = parsed.getElementsByTagName("w:tbl")[0]
    imported = editor.dom.importNode(new_tbl, deep=True)
    old_tbl.parentNode.replaceChild(imported, old_tbl)


def rebuild_section_between(
    editor,
    start_heading: str,
    stop_prefixes: tuple[str, ...],
    paragraphs: list[str],
) -> None:
    """保留节标题，删除至下一节前内容并写入新段落。"""
    body = editor.dom.getElementsByTagName("w:body")[0]
    paras = list(body.getElementsByTagName("w:p"))
    start_para = None
    start_i = 0
    for i, para in enumerate(paras):
        t = paragraph_visible_text(para).strip()
        if t == start_heading or t.startswith(start_heading[:3]):
            start_para = para
            start_i = i
            break
    if start_para is None:
        return

    end_i = len(paras)
    for i in range(start_i + 1, len(paras)):
        t = paragraph_visible_text(paras[i]).strip()
        if any(t.startswith(p) for p in stop_prefixes):
            end_i = i
            break

    for para in paras[start_i + 1 : end_i]:
        delete_paragraph_tracked(editor, para)

    if not paragraphs:
        return
    if paragraph_visible_text(start_para).strip() != paragraphs[0]:
        replace_paragraph_tracked(editor, start_para, paragraphs[0])
    insert_paragraphs_after(editor, start_para, paragraphs[1:])


def apply_imrad(doc: Document) -> None:
    editor = doc["word/document.xml"]

    # 题名与著录项
    replace_first_of(
        editor,
        (
            "Perilla在质量信息化治理",
            "基于 Perilla 开发的检验检测",
            "Perilla：面向",
        ),
        TITLE_ZH,
    )
    insert_after_if_missing(editor, TITLE_ZH, [AUTHOR, AFFILIATION], AUTHOR, heading=True)
    replace_first_of(
        editor,
        ("摘要：专网环境下", "摘要：检验检测", "摘要：质量信息化", "摘要"),
        ABSTRACT_ZH,
    )
    replace_first_of(editor, ("关键词检验检测", "关键词质量信息化", "关键词"), KEYWORDS_ZH)
    replace_first_of(
        editor,
        ("Development of a Quality", "Preliminary Exploration", "Gateway-Centric"),
        TITLE_EN,
    )
    insert_after_if_missing(editor, TITLE_EN, [AUTHOR_EN, AFFILIATION_EN], "YAO Lisi", heading=True)
    replace_first_of(editor, ("Abstract: Quality-oriented", "Abstract:"), ABSTRACT_EN)
    replace_first_of(editor, ("Key words inspection", "Key words"), KEYWORDS_EN)

    # 删除原“0 引言”及旧章节标题（正文并入新结构）
    strike_paragraphs_matching(
        editor,
        "0  引言",
        "1  研究问题与分析框架",
        "1.1  质量治理需求分析",
        "1.2  技术路线与演示包体系",
        "2  系统方法与设计",
        "2.2  人机门控原语",
        "2.2.1  原语定义与质量含义",
        "2.2.2  演示包与实例映射",
        "2.3  研究方法与评价指标",
        "3  实例统一运行闭环",
        "4  与同类产品横向对比",
        "5  应用实例与验证",
        "5.4  综合讨论",
        "6  部署与复现说明",
        "6.1  演示包导入与复现步骤",
        "6.2  质量职责与推广建议",
        "7  结论与展望",
        "5.1.1  应用背景与问题分析",
        "5.1.2  系统设计与实现",
        "5.1.3  验证结果与分析",
        "5.2.1  应用背景与问题分析",
        "5.2.2  系统设计与实现",
        "5.2.3  验证结果与分析",
        "5.3.1  应用背景与问题分析",
        "5.3.2  系统设计与实现",
        "5.3.3  验证结果与分析",
    )

    # 构建第1、2节（幂等：已有正文则跳过）
    if not body_contains(editor, SEC_1_P1[:24]):
        try:
            anchor = editor.get_node(tag="w:p", contains="随着检验检测认证行业数字化")
        except ValueError:
            try:
                anchor = editor.get_node(tag="w:p", contains="1  研究背景")
            except ValueError:
                anchor = editor.get_node(tag="w:p", contains="质量信息化是检验检测")
        replace_paragraph_tracked(editor, anchor, SEC_1)
        insert_paragraphs_after(editor, anchor, [SEC_1_P1, SEC_1_P2])

    # 第2—4节整体重写（治理逻辑为主轴）
    rebuild_section_between(
        editor,
        SEC_2,
        ("[示意图]", "图1 Perilla", "3  研究结果"),
        SEC_2_PARAS,
    )
    rebuild_section_between(
        editor,
        SEC_3,
        ("4  讨论", "参考文献"),
        SEC_3_PARAS,
    )
    rebuild_section_between(
        editor,
        SEC_4,
        ("参考文献",),
        SEC_4_PARAS,
    )
    replace_table1(editor)

    finalize_imrad_structure(editor)
    cleanup_orphan_paragraphs(editor)


ORPHAN_MARKERS = (
    "结合检验检测业务特征，质量治理需求",
    "本文在此基础上构建原型系统",
    "2.1  试验平台定位与设计原则",
    "2.4  工作流控制面与人机门控原语",
    "2.5  数据持久化、多租户与可观测性",
    "2.6  验证方案与评价指标",
    "3.1  质量信息化治理逻辑与平台契合性",
    "3.2  典型治理场景论证",
    "4.5  下一步：场景设计与效果评估",
    "结合本文分析，后续最紧迫的工作是设计一个实际质量场景",
    "4.4  落地建议与常见误区",
    "4.5  局限性与展望",
    "LangFlow、n8n 等低代码工具长于节点拼装",
    "Perilla 与主流开源方案对比",
)


def cleanup_orphan_paragraphs(editor) -> None:
    """删除未归入 IMRaD 四节的残留旧段落。"""
    strike_paragraphs_matching(editor, *ORPHAN_MARKERS)
    # 重复段
    seen: set[str] = set()
    body = editor.dom.getElementsByTagName("w:body")[0]
    for para in list(body.getElementsByTagName("w:p")):
        text = paragraph_visible_text(para).strip()
        if not text or len(text) < 40:
            continue
        if text in seen:
            delete_paragraph_tracked(editor, para)
        else:
            seen.add(text)


def dedupe_consecutive_paragraphs(editor) -> None:
    prev = ""
    body = editor.dom.getElementsByTagName("w:body")[0]
    for para in list(body.getElementsByTagName("w:p")):
        t = paragraph_visible_text(para).strip()
        if t and t == prev:
            delete_paragraph_tracked(editor, para)
        prev = t


def strike_duplicate_section_block(editor, heading: str) -> None:
    body = editor.dom.getElementsByTagName("w:body")[0]
    paras = list(body.getElementsByTagName("w:p"))
    indices = [
        i
        for i, p in enumerate(paras)
        if paragraph_visible_text(p).strip() == heading
    ]
    if len(indices) < 2:
        return
    for para in paras[indices[1] :]:
        t = paragraph_visible_text(para).strip()
        if t.startswith("3 ") or t.startswith("4 ") or t.startswith("参考文献"):
            break
        if t.startswith("图1") or t.startswith("表1") or t == "[示意图]":
            break
        delete_paragraph_tracked(editor, para)


def _paragraph_index_map(editor) -> list[tuple[int, object, str]]:
    body = editor.dom.getElementsByTagName("w:body")[0]
    return [
        (i, para, paragraph_visible_text(para).strip())
        for i, para in enumerate(body.getElementsByTagName("w:p"))
    ]


def finalize_imrad_structure(editor) -> None:
    dedupe_consecutive_paragraphs(editor)
    strike_duplicate_section_block(editor, SEC_1)
    # 删除错位出现的第2—4节重复标题块
    for heading in (SEC_2, SEC_3, SEC_4):
        strike_duplicate_section_block(editor, heading)


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"源文件不存在: {SRC}")

    with tempfile.TemporaryDirectory(prefix="perilla-imrad-") as tmp:
        unpacked = Path(tmp) / "unpacked"
        subprocess.run(
            [sys.executable, str(DOCX_SKILL / "ooxml/scripts/unpack.py"), str(SRC), str(unpacked)],
            check=True,
            capture_output=True,
            text=True,
        )
        doc = Document(
            str(unpacked),
            track_revisions=True,
            author="姚李四",
            initials="YL",
        )
        flatten_document(doc["word/document.xml"])
        apply_imrad(doc)
        doc.save(validate=False)
        pack_document(unpacked, SRC, validate=False)
        print(f"IMRaD revised: {SRC}")


if __name__ == "__main__":
    main()
