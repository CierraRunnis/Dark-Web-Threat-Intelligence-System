export const monitoringStatus = {
  dateLabel: '2026年3月10日 星期二',
  subtitle: '面向汇报与分析场景的威胁情报监控界面，当前为本地静态占位数据演示。',
  scope: '覆盖 42 个重点国家 / 18 个高风险行业 / 126 个观察点位',
  statusLabel: '监控状态',
  statusValue: '采集中',
  refreshedLabel: '最近刷新',
  refreshedValue: '2026-03-10 09:40 CST'
}

export const routeHeaderMeta = {
  '/': {
    kicker: '总览',
    subtitle: '聚焦当日总体态势、跨模块事件联动与重点国家暴露面。'
  },
  '/ransomware': {
    kicker: '勒索情报',
    subtitle: '跟踪披露事件、活跃团伙、受影响行业与地域扩散情况。'
  },
  '/data-leak': {
    kicker: '数据泄露情报',
    subtitle: '监控泄露事件、敏感类型、受影响实体与暗网暴露线索。'
  },
  '/vulnerability-alerts': {
    kicker: '漏洞预警',
    subtitle: '聚焦公开源高危漏洞、利用状态、受影响厂商与产品热度。'
  },
  '/threat-situation': {
    kicker: '威胁态势',
    subtitle: '集中展示跨模块趋势、排行与区域热区，承担图表深度展示。'
  },
  '/collector-control': {
    kicker: '采集控制',
    subtitle: '统一触发站点采集任务、查看站点健康状态和失败告警。'
  }
}

export const dashboardSummaryCards = [
  {
    label: '重点事件',
    value: '126',
    description: '过去 24 小时进入人工跟踪池',
    trend: '+18%',
    tone: 'danger',
    icon: 'Bell'
  },
  {
    label: '勒索披露',
    value: '42',
    description: '新增公开披露与论坛线索汇总',
    trend: '+11%',
    tone: 'warning',
    icon: 'Warning'
  },
  {
    label: '敏感类型',
    value: '7',
    description: '凭证、客户资料与源代码最常见',
    trend: '客户数据活跃',
    tone: 'primary',
    icon: 'Files'
  },
  {
    label: '重点地区',
    value: '9',
    description: '区域风险指数持续高于阈值',
    trend: '持续关注',
    tone: 'success',
    icon: 'MapLocation'
  },
  {
    label: '高危漏洞',
    value: '12',
    description: '公开源新增高危和超高危漏洞',
    trend: '5 条已被利用',
    tone: 'danger',
    icon: 'WarningFilled'
  }
]

export const modulePreviewCards = [
  {
    route: '/ransomware',
    eyebrow: '模块预览',
    title: '勒索情报',
    summary: '制造、医疗与专业服务行业仍是主要受害面，LockBit 与 Black Basta 活跃度维持高位。',
    highlight: '今日新增 42 起披露',
    tone: 'danger',
    stats: [
      { label: '活跃组织', value: '18' },
      { label: '重点行业', value: '9' },
      { label: '区域外溢', value: '12' }
    ]
  },
  {
    route: '/data-leak',
    eyebrow: '模块预览',
    title: '数据泄露情报',
    summary: '凭证、客户档案与源代码样本占比较高，电商与金融行业暴露强度上升。',
    highlight: '新增 31 起事件',
    tone: 'warning',
    stats: [
      { label: '泄露事件', value: '31' },
      { label: '敏感类型', value: '7' },
      { label: '影响实体', value: '54' }
    ]
  },
  {
    route: '/vulnerability-alerts',
    eyebrow: '模块预览',
    title: '漏洞预警',
    summary: '聚合公开源高危漏洞、厂商与产品热度，突出已被利用和已公开 PoC 的重点事件。',
    highlight: '今日新增 12 条高危漏洞',
    tone: 'danger',
    stats: [
      { label: '已利用', value: '5' },
      { label: '重点厂商', value: '6' },
      { label: '重点产品', value: '8' }
    ]
  },
  {
    route: '/threat-situation',
    eyebrow: '模块预览',
    title: '威胁态势',
    summary: '北美、西欧与东亚仍为主要高热区，勒索、数据泄露与钓鱼活动呈复合上升。',
    highlight: '集中展示所有趋势图表',
    tone: 'primary',
    stats: [
      { label: '高危告警', value: '19' },
      { label: '热区数量', value: '6' },
      { label: '监控源在线', value: '126' }
    ]
  }
]

export const dashboardTrendSeries = {
  labels: ['03-04', '03-05', '03-06', '03-07', '03-08', '03-09', '03-10'],
  ransomware: [26, 31, 28, 36, 39, 33, 42],
  dataLeak: [18, 20, 24, 22, 26, 29, 31],
  vulnerability: [4, 5, 6, 7, 9, 10, 12],
  threatAlerts: [62, 68, 65, 71, 74, 78, 84]
}

export const dashboardCountryFocus = [
  { name: '美国', value: 84 },
  { name: '德国', value: 63 },
  { name: '英国', value: 57 },
  { name: '日本', value: 51 },
  { name: '巴西', value: 43 },
  { name: '印度', value: 39 }
]

export const crossModuleTimeline = [
  {
    time: '09:31',
    module: '漏洞预警',
    title: 'Palo Alto Networks 边界设备高危漏洞进入已利用状态',
    detail: '建议优先核查外网暴露面和补丁窗口',
    tone: 'danger'
  },
  {
    time: '09:18',
    module: '勒索情报',
    title: 'LockBit 关联样本更新受害者清单，新增 3 家制造业实体',
    detail: '地区覆盖美国、德国与波兰',
    tone: 'danger'
  },
  {
    time: '08:46',
    module: '数据泄露情报',
    title: '某电商论坛新出现客户资料售卖贴，进入人工验证池',
    detail: '包含邮箱、手机号与物流地址',
    tone: 'warning'
  },
  {
    time: '08:10',
    module: '威胁态势',
    title: '东亚区域钓鱼活动热区指数突破 70',
    detail: '邮件投递与登录仿冒同时抬升',
    tone: 'primary'
  },
  {
    time: '07:35',
    module: '勒索情报',
    title: 'Black Basta 在医疗领域新增披露，勒索谈判周期缩短',
    detail: '受害方集中在北美',
    tone: 'danger'
  },
  {
    time: '06:52',
    module: '数据泄露情报',
    title: '凭证组合包在暗网频道转售，涉及金融 SaaS 平台',
    detail: '样本已进入验证池',
    tone: 'warning'
  }
]

export const dashboardWatchlist = [
  {
    module: '漏洞预警',
    title: '边界设备类高危漏洞连续 2 日抬升',
    note: '优先关注已被利用与补丁未覆盖的事件',
    tone: 'danger'
  },
  {
    module: '勒索情报',
    title: 'Black Basta 对专业服务行业攻击频次连续 3 日上升',
    note: '需要补充人工研判',
    tone: 'danger'
  },
  {
    module: '数据泄露情报',
    title: '客户档案类泄露占比提升至 31%',
    note: '建议关注后续二次诈骗链路',
    tone: 'warning'
  },
  {
    module: '威胁态势',
    title: '西欧区域风险指数接近橙色阈值',
    note: '区域热矩阵需持续观察',
    tone: 'primary'
  }
]

export const vulnerabilitySummary = [
  {
    label: '高危漏洞',
    value: '12',
    description: '过去 24 小时新增高危与超高危漏洞',
    trend: '5 条已被利用',
    tone: 'danger',
    icon: 'WarningFilled'
  },
  {
    label: '已被利用',
    value: '5',
    description: '公开源已确认存在利用活动',
    trend: '边界设备最突出',
    tone: 'warning',
    icon: 'Bell'
  },
  {
    label: '影响厂商',
    value: '6',
    description: '当前样本覆盖的重点厂商数量',
    trend: '网络设备与中间件为主',
    tone: 'primary',
    icon: 'OfficeBuilding'
  },
  {
    label: '可直接修复',
    value: '9',
    description: '已有补丁或官方修复方案',
    trend: '3 条仅有缓解方案',
    tone: 'success',
    icon: 'CircleCheck'
  }
]

export const vulnerabilityEvents = [
  {
    id: 'vuln:cve-2026-24001',
    disclosureTime: '2026-03-10 09:31',
    cveId: 'CVE-2026-24001',
    title: 'Palo Alto PAN-OS GlobalProtect 网关未授权命令执行',
    category: '远程代码执行',
    vendor: 'Palo Alto Networks',
    product: 'PAN-OS GlobalProtect',
    severity: 'critical',
    cvss: 10.0,
    isExploited: true,
    patchAvailable: true,
    summary: '影响互联网暴露的边界设备，公开源已确认存在利用活动。'
  },
  {
    id: 'vuln:cve-2026-18113',
    disclosureTime: '2026-03-10 08:54',
    cveId: 'CVE-2026-18113',
    title: 'Apache Tomcat 反向代理链路请求走私漏洞',
    category: '请求走私',
    vendor: 'Apache',
    product: 'Tomcat',
    severity: 'high',
    cvss: 8.8,
    isExploited: false,
    patchAvailable: true,
    summary: '公开 PoC 已出现，适合优先核查反向代理与容器链路。'
  },
  {
    id: 'vuln:cve-2026-17420',
    disclosureTime: '2026-03-10 08:07',
    cveId: 'CVE-2026-17420',
    title: 'Ivanti Connect Secure 身份认证绕过',
    category: '身份认证绕过',
    vendor: 'Ivanti',
    product: 'Connect Secure',
    severity: 'critical',
    cvss: 9.1,
    isExploited: true,
    patchAvailable: true,
    summary: '边界接入设备受影响，公开源已提示真实利用迹象。'
  },
  {
    id: 'vuln:cve-2026-20884',
    disclosureTime: '2026-03-10 07:22',
    cveId: 'CVE-2026-20884',
    title: 'Oracle WebLogic 反序列化高危漏洞',
    category: '反序列化漏洞',
    vendor: 'Oracle',
    product: 'WebLogic Server',
    severity: 'critical',
    cvss: 9.8,
    isExploited: false,
    patchAvailable: true,
    summary: '中间件版本覆盖面较广，PoC 已公开。'
  },
  {
    id: 'vuln:cve-2026-21101',
    disclosureTime: '2026-03-10 06:41',
    cveId: 'CVE-2026-21101',
    title: 'FortiManager 任意文件写入漏洞',
    category: '任意文件写入',
    vendor: 'Fortinet',
    product: 'FortiManager',
    severity: 'high',
    cvss: 8.7,
    isExploited: true,
    patchAvailable: false,
    summary: '补丁尚未完全可用，当前仅有缓解方案。'
  }
]

export const vulnerabilityTrend = {
  labels: ['03-04', '03-05', '03-06', '03-07', '03-08', '03-09', '03-10'],
  values: [4, 5, 6, 7, 9, 10, 12]
}

export const vulnerabilityVendorRanking = [
  { name: 'Palo Alto Networks', value: 3 },
  { name: 'Ivanti', value: 2 },
  { name: 'Fortinet', value: 2 },
  { name: 'Apache', value: 2 },
  { name: 'Oracle', value: 1 }
]

export const vulnerabilityProductRanking = [
  { name: 'PAN-OS GlobalProtect', value: 3 },
  { name: 'Connect Secure', value: 2 },
  { name: 'Tomcat', value: 2 },
  { name: 'FortiManager', value: 2 },
  { name: 'WebLogic Server', value: 1 }
]

export const ransomwareSummary = [
  {
    label: '事件数',
    value: '42',
    description: '过去 24 小时新增披露事件',
    trend: '+14%',
    tone: 'danger',
    icon: 'Warning'
  },
  {
    label: '活跃组织数',
    value: '18',
    description: '进入重点观察名单的勒索团伙',
    trend: '2 个新团伙',
    tone: 'warning',
    icon: 'UserFilled'
  },
  {
    label: '受影响行业数',
    value: '9',
    description: '制造、医疗与服务业为主',
    trend: '制造业最高',
    tone: 'primary',
    icon: 'OfficeBuilding'
  },
  {
    label: '趋势变化',
    value: '+14%',
    description: '较 2026-03-09 同时段',
    trend: '连续 3 日上行',
    tone: 'success',
    icon: 'TrendCharts'
  }
]

export const ransomwareEvents = [
  {
    disclosureTime: '2026-03-10 09:12',
    title: 'LockBit 宣布披露北美制造商财务与工程文档',
    category: '双重勒索',
    attacker: 'LockBit',
    industry: '制造业',
    region: '美国 / 加拿大',
    severity: 'critical'
  },
  {
    disclosureTime: '2026-03-10 08:44',
    title: 'Black Basta 声称入侵欧洲医疗集团并启动谈判倒计时',
    category: '勒索谈判',
    attacker: 'Black Basta',
    industry: '医疗',
    region: '德国 / 波兰',
    severity: 'high'
  },
  {
    disclosureTime: '2026-03-10 08:03',
    title: 'Akira 针对专业服务公司投放新一轮加密载荷',
    category: '加密执行',
    attacker: 'Akira',
    industry: '专业服务',
    region: '英国',
    severity: 'high'
  },
  {
    disclosureTime: '2026-03-10 07:35',
    title: 'Play 团伙新增东南亚制造业受害者披露',
    category: '站点披露',
    attacker: 'Play',
    industry: '制造业',
    region: '越南 / 泰国',
    severity: 'medium'
  },
  {
    disclosureTime: '2026-03-10 06:58',
    title: 'RansomHub 在政府承包商环境中复用旧版初始访问链路',
    category: '初始访问',
    attacker: 'RansomHub',
    industry: '政府承包',
    region: '美国',
    severity: 'high'
  },
  {
    disclosureTime: '2026-03-10 05:46',
    title: 'Cactus 对日本零售企业发动周末批量入侵',
    category: '双重勒索',
    attacker: 'Cactus',
    industry: '零售',
    region: '日本',
    severity: 'medium'
  },
  {
    disclosureTime: '2026-03-09 23:28',
    title: 'INC Ransom 披露医疗影像系统访问凭证',
    category: '数据外泄',
    attacker: 'INC Ransom',
    industry: '医疗',
    region: '法国',
    severity: 'high'
  },
  {
    disclosureTime: '2026-03-09 22:12',
    title: 'Hunters International 将化工企业样本列入新受害者页面',
    category: '站点披露',
    attacker: 'Hunters',
    industry: '化工',
    region: '巴西',
    severity: 'medium'
  }
]

export const ransomwareTrend = {
  labels: ['03-04', '03-05', '03-06', '03-07', '03-08', '03-09', '03-10'],
  values: [18, 24, 21, 29, 33, 37, 42]
}

export const ransomwareIndustryImpact = [
  { name: '制造业', value: 17 },
  { name: '医疗', value: 11 },
  { name: '专业服务', value: 9 },
  { name: '零售', value: 7 },
  { name: '政府承包', value: 5 }
]

export const ransomwareActorRanking = [
  { name: 'LockBit', value: 12 },
  { name: 'Black Basta', value: 9 },
  { name: 'Akira', value: 7 },
  { name: 'RansomHub', value: 6 },
  { name: 'Play', value: 5 }
]

export const dataLeakSummary = [
  {
    label: '泄露事件数',
    value: '31',
    description: '过去 24 小时新增追踪事件',
    trend: '+9%',
    tone: 'warning',
    icon: 'DocumentRemove'
  },
  {
    label: '敏感信息类型数',
    value: '7',
    description: '凭证、客户资料、源代码占比最高',
    trend: '凭证类居首',
    tone: 'primary',
    icon: 'Key'
  },
  {
    label: '受影响实体数',
    value: '54',
    description: '涉及金融、电商、教育与 SaaS',
    trend: '+6 家重点实体',
    tone: 'success',
    icon: 'OfficeBuilding'
  }
]

export const dataLeakEvents = [
  {
    disclosureTime: '2026-03-10 09:26',
    title: '某跨境电商客户订单与联系方式样本在论坛售卖',
    category: '客户数据',
    attacker: 'Forum Seller 17',
    industry: '电商',
    region: '美国 / 英国',
    severity: 'critical'
  },
  {
    disclosureTime: '2026-03-10 08:58',
    title: '金融 SaaS 后台凭证包进入二次分销频道',
    category: '凭证泄露',
    attacker: 'Broker-X',
    industry: '金融 SaaS',
    region: '美国',
    severity: 'high'
  },
  {
    disclosureTime: '2026-03-10 08:14',
    title: '某制造企业源代码仓库样本被打包出售',
    category: '源代码泄露',
    attacker: 'LockBit',
    industry: '制造业',
    region: '德国',
    severity: 'high'
  },
  {
    disclosureTime: '2026-03-10 07:49',
    title: '教育平台身份认证日志在灰产频道流转',
    category: '日志与配置',
    attacker: 'Anonymous',
    industry: '教育',
    region: '印度',
    severity: 'medium'
  },
  {
    disclosureTime: '2026-03-10 06:42',
    title: '医疗预约系统数据库镜像样本被公开兜售',
    category: '数据库泄露',
    attacker: 'Market Delta',
    industry: '医疗',
    region: '法国',
    severity: 'critical'
  },
  {
    disclosureTime: '2026-03-10 05:58',
    title: '某支付服务商商户报表与联系人数据外泄',
    category: '客户数据',
    attacker: 'Clop',
    industry: '支付服务',
    region: '巴西',
    severity: 'high'
  },
  {
    disclosureTime: '2026-03-09 23:51',
    title: '东亚社交平台凭证组合包在暗网频道更新',
    category: '凭证泄露',
    attacker: 'ComboBase',
    industry: '社交平台',
    region: '日本',
    severity: 'medium'
  },
  {
    disclosureTime: '2026-03-09 22:24',
    title: '云服务商内部文档与配置片段样本流出',
    category: '文档泄露',
    attacker: 'Forum Seller 09',
    industry: '云服务',
    region: '新加坡',
    severity: 'medium'
  }
]

export const dataLeakEventTrend = {
  labels: ['03-04', '03-05', '03-06', '03-07', '03-08', '03-09', '03-10'],
  values: [12, 15, 18, 16, 22, 27, 31]
}

export const sensitiveTypeShare = [
  { name: '凭证', value: 32 },
  { name: '客户资料', value: 24 },
  { name: '源代码', value: 18 },
  { name: '数据库镜像', value: 14 },
  { name: '配置文档', value: 12 }
]

export const dataLeakRanking = [
  { name: '金融 / 北美', value: 18 },
  { name: '电商 / 北美', value: 15 },
  { name: '制造 / 欧洲', value: 13 },
  { name: '教育 / 亚太', value: 11 },
  { name: '医疗 / 欧洲', value: 10 }
]

export const threatSituationSummary = {
  title: '全球威胁态势总览',
  description: '统一承接勒索、数据泄露与漏洞预警模块的趋势、排行和分布图表，模块页则聚焦事件列表本身。',
  stats: [
    { label: '泄露事件', value: '31' },
    { label: '勒索受害者', value: '42' },
    { label: '漏洞预警', value: '12' },
    { label: '高危告警', value: '19' }
  ]
}

export const threatSituationBehavior = {
  summaryCards: [
    {
      label: '标准化事件',
      value: '126',
      description: '已完成清洗和结构化提取的事件数。',
      tone: 'primary'
    },
    {
      label: '高风险事件',
      value: '27',
      description: '规则评分达到高风险阈值的事件数量。',
      tone: 'danger'
    },
    {
      label: '活跃主体',
      value: '12',
      description: '可用于行为分析的主体数量。',
      tone: 'warning'
    },
    {
      label: '重复受害实体',
      value: '9',
      description: '多次出现的受害者实体数量。',
      tone: 'success'
    }
  ],
  actorRiskRanking: [
    { actor: 'LockBit', eventCount: 6, crossSiteCount: 2, averageRiskScore: 78, topLeakType: '勒索披露', lastSeenAt: '2026-03-10 09:12', reasons: ['近期多次出现', '跨站点出现'] },
    { actor: 'Black Basta', eventCount: 4, crossSiteCount: 1, averageRiskScore: 71, topLeakType: '勒索披露', lastSeenAt: '2026-03-10 08:44', reasons: ['近期多次出现'] }
  ],
  victimRiskRanking: [
    { victim: 'Acme Corp', eventCount: 3, averageRiskScore: 74, lastSeenAt: '2026-03-10 09:26', industries: ['制造业'] },
    { victim: 'Foo Health', eventCount: 2, averageRiskScore: 68, lastSeenAt: '2026-03-10 08:44', industries: ['医疗'] }
  ],
  industryRiskDistribution: [
    { name: '制造业', value: 12, averageRiskScore: 73 },
    { name: '医疗', value: 9, averageRiskScore: 69 }
  ],
  regionRiskDistribution: [
    { name: '北美', value: 18, averageRiskScore: 72 },
    { name: '欧洲', value: 13, averageRiskScore: 68 }
  ],
  anomalyEvents: [
    { id: 'victim:demo:1', title: 'LockBit 披露制造企业财务文档', attacker: 'LockBit', victim: 'Acme Corp', category: '勒索披露', sourceSite: 'DragonForce', disclosureTime: '2026-03-10 09:12', riskScore: 82, reasons: ['近期多次出现', '命中重点情报类型：勒索披露'] }
  ],
  behaviorSignals: [
    { title: 'LockBit 活跃度最高', description: '近期出现频次最高，平均风险分保持高位。', tone: 'danger' },
    { title: '制造业为高频受影响行业', description: '当前高风险事件主要集中在制造业。', tone: 'primary' }
  ],
  extractionStats: {
    dataLeakCount: 31,
    ransomwareCount: 42,
    vulnerabilityCount: 12,
    updatedAt: '2026-03-10 09:40 CST'
  }
}

export const threatHeatmap = {
  regions: ['北美', '西欧', '东亚', '东南亚', '拉美', '中东'],
  categories: ['勒索', '数据泄露', '钓鱼', 'DDoS', '恶意软件'],
  values: [
    [0, 0, 88], [0, 1, 79], [0, 2, 67], [0, 3, 54], [0, 4, 61],
    [1, 0, 72], [1, 1, 76], [1, 2, 64], [1, 3, 41], [1, 4, 58],
    [2, 0, 69], [2, 1, 63], [2, 2, 81], [2, 3, 46], [2, 4, 66],
    [3, 0, 58], [3, 1, 51], [3, 2, 72], [3, 3, 44], [3, 4, 62],
    [4, 0, 47], [4, 1, 52], [4, 2, 49], [4, 3, 39], [4, 4, 45],
    [5, 0, 43], [5, 1, 38], [5, 2, 55], [5, 3, 34], [5, 4, 51]
  ]
}

export const attackTypeShare = [
  { name: '勒索', value: 28 },
  { name: '数据泄露', value: 24 },
  { name: '漏洞预警', value: 17 },
  { name: '钓鱼', value: 19 },
  { name: '恶意软件', value: 16 }
]

export const threatLevelTrend = {
  labels: ['03-04', '03-05', '03-06', '03-07', '03-08', '03-09', '03-10'],
  high: [18, 21, 22, 24, 27, 29, 32],
  medium: [36, 34, 39, 41, 40, 44, 46],
  low: [22, 20, 21, 24, 23, 22, 21]
}

export const regionalThreatComparison = [
  { name: '北美', value: 84 },
  { name: '西欧', value: 72 },
  { name: '东亚', value: 69 },
  { name: '东南亚', value: 58 },
  { name: '拉美', value: 47 },
  { name: '中东', value: 43 }
]

export const situationAlerts = [
  {
    level: 'critical',
    title: '边界设备高危漏洞出现利用活动',
    description: 'Palo Alto 与 Ivanti 相关漏洞已被公开源标记为已利用，适合纳入优先处置说明。',
    time: '2026-03-10 09:31',
    source: '漏洞预警'
  },
  {
    level: 'critical',
    title: '北美制造业勒索告警持续上扬',
    description: 'LockBit 与 RansomHub 在制造业链条中出现重复投放迹象，相关谈判贴文增量明显。',
    time: '2026-03-10 09:24',
    source: '勒索情报 / 暗网监测'
  },
  {
    level: 'high',
    title: '西欧医疗行业出现数据库镜像交易',
    description: '疑似医疗预约与病历相关数据库在论坛上架，样本标签与历史泄露事件一致。',
    time: '2026-03-10 08:51',
    source: '数据泄露情报'
  },
  {
    level: 'high',
    title: '东亚登录仿冒活动进入高频期',
    description: '仿冒 Microsoft 365 与 Okta 的页面模板在多个钓鱼源中复用，企业员工成为主要目标。',
    time: '2026-03-10 08:17',
    source: '邮件与域名监测'
  },
  {
    level: 'medium',
    title: '东南亚电商站点遭受中等强度 DDoS 预热',
    description: '边缘流量突增，攻击流量尚未进入峰值，但准备动作已具备一致性。',
    time: '2026-03-10 07:42',
    source: '流量监测'
  },
  {
    level: 'medium',
    title: '中东区域恶意软件下载链复活',
    description: '旧版下载器家族重新活跃，当前以伪装浏览器更新为主。',
    time: '2026-03-10 06:36',
    source: '终端情报'
  }
]
