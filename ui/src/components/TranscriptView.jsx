import React from 'react'
import { entryLabel, getThinkingSummary, normalizeDisplayText, renderMarkdown, transcriptRole } from '../lib/formatting.js'

const IMAGE_TOKEN_RE = /\[\[image:[^\]]+\]\]/g

function stripImageTokens(text) {
  return (text || '').replace(IMAGE_TOKEN_RE, '').trim()
}

function renderTodoStrip(todo) {
  if (!todo?.items?.length) {
    return null
  }
  const completedCount = todo.items.filter(item => item.done).length
  return (
    <div className={`todo-strip embedded${todo.completed ? ' completed' : ''}`}>
      <div className="todo-strip-header">
        <i className="fas fa-list-check todo-strip-icon" aria-hidden="true" />
        <span className="todo-strip-title">任务列表</span>
        <span className="todo-strip-progress">
          {completedCount} / {todo.items.length}
        </span>
      </div>
      <ol className="todo-strip-list">
        {todo.items.map((item, index) => (
          <li key={`${item.text}_${index}`} className={`todo-strip-item${item.done ? ' done' : ''}`}>
            <span className="todo-checkbox" aria-hidden="true">
              {item.done && <i className="fas fa-check" />}
            </span>
            <span className="todo-item-text">{item.text}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function renderGuidedChoiceCard(entry, onGuidedChoiceSelect, guidedChoiceNow) {
  const guidedChoice = entry.guidedChoice
  if (!guidedChoice) {
    return null
  }
  const isPending = guidedChoice.status === 'pending'
  const isResolved = guidedChoice.status === 'resolved'
  const remainingSeconds = isPending && guidedChoice.deadlineAt ? Math.max(0, Math.ceil((guidedChoice.deadlineAt - guidedChoiceNow) / 1000)) : 0
  return (
    <div className={`guided-choice-card${isResolved ? ' resolved' : ''}${guidedChoice.status === 'cancelled' ? ' cancelled' : ''}`}>
      <div className="guided-choice-head">
        <span className="guided-choice-step">
          {guidedChoice.questionIndex} / {guidedChoice.questionCount}
        </span>
        {isPending ? <span className="guided-choice-timer">默认方案将在 {remainingSeconds}s 后自动采用</span> : null}
      </div>
      <div className="guided-choice-title">{guidedChoice.title}</div>
      {guidedChoice.description ? <div className="guided-choice-description">{guidedChoice.description}</div> : null}
      {isPending ? (
        <div className="guided-choice-options">
          {(guidedChoice.options || []).map(option => (
            <button key={option.value} type="button" className={`guided-choice-option${option.isDefault ? ' default' : ''}`} onClick={() => onGuidedChoiceSelect?.(entry.id, option.value, false)}>
              <span className="guided-choice-option-top">
                <span>{option.label}</span>
                {option.isDefault ? <em>默认</em> : null}
              </span>
              {option.hint ? <span className="guided-choice-option-hint">{option.hint}</span> : null}
            </button>
          ))}
        </div>
      ) : isResolved ? (
        <div className="guided-choice-picked">
          <strong>{guidedChoice.selectedLabel}</strong>
          <span>{guidedChoice.autoSelected ? '已自动采用默认主流方案' : '已按你的选择继续'}</span>
        </div>
      ) : (
        <div className="guided-choice-picked cancelled">
          <strong>已取消</strong>
          <span>本轮 Create 引导问题已停止。</span>
        </div>
      )}
    </div>
  )
}

function processStatusCopy(process, activeEvent, issueEvent, decision) {
  if (issueEvent) {
    return { label: '遇到阻塞', detail: 'Harness 会根据证据进入修复或重新规划。', tone: 'blocked' }
  }
  if (decision?.decision === 'PASS') {
    return { label: '已完成', detail: 'Harness 已完成验收。', tone: 'done' }
  }
  if (activeEvent?.role === 'Planner') {
    return { label: '正在制定计划', detail: '正在分析任务与约束。', tone: 'planning' }
  }
  if (activeEvent?.role === 'Search') {
    return { label: '正在检索资料', detail: '正在补充外部证据与文档依据。', tone: 'planning' }
  }
  if (activeEvent?.role === 'Generator') {
    return { label: '正在修改文件', detail: '正在按计划生成或修复代码。', tone: 'editing' }
  }
  if (activeEvent?.role === 'Runner') {
    const combined = `${activeEvent?.title || ''} ${activeEvent?.detail || ''}`
    if (/页面|浏览器|预览|smoke/i.test(combined)) {
      return { label: '正在验证页面', detail: '正在检查页面是否符合预期。', tone: 'testing' }
    }
    return { label: '正在运行命令', detail: '正在执行构建、测试或启动命令。', tone: 'running' }
  }
  if (activeEvent?.role === 'Evaluator') {
    return { label: '正在检查结果', detail: '正在判断是否达成验收条件。', tone: 'reviewing' }
  }
  return { label: '正在分析', detail: 'Harness 正在准备本轮任务。', tone: 'planning' }
}

const HARNESS_STAGE_META = {
  Planner: {
    title: '分析需求',
    summary: '理解目标、约束和可修改范围。',
    waiting: '等待 Harness 分配规划阶段。'
  },
  Search: {
    title: '补充资料',
    summary: '仅在确实需要时查询外部资料。',
    waiting: '当前任务默认不需要外部检索。'
  },
  Generator: {
    title: '修改代码',
    summary: '根据计划做最小可运行实现。',
    waiting: '等待规划结果后再开始改动。'
  },
  Runner: {
    title: '运行验证',
    summary: '执行构建、启动预览并采集证据。',
    waiting: '代码变更完成后进入验证。'
  },
  Evaluator: {
    title: '检查结果',
    summary: '根据证据判断是否通过验收。',
    waiting: '等待运行结果后输出结论。'
  }
}

const PROCESS_TONE_META = {
  planning: { badge: 'info', live: '进行中' },
  editing: { badge: 'success', live: '处理中' },
  running: { badge: 'running', live: '执行中' },
  testing: { badge: 'running', live: '验证中' },
  reviewing: { badge: 'warning', live: '检查中' },
  blocked: { badge: 'blocked', live: '已阻塞' },
  done: { badge: 'success', live: '已完成' }
}

function statusChipLabel(status) {
  return {
    pending: '等待',
    queued: '即将开始',
    running: '进行中',
    success: '已完成',
    error: '有问题'
  }[status] || '处理中'
}

function splitActionSteps(text) {
  return String(text || '')
    .split(/\n+|(?<=[。；;])/)
    .map(item => item.replace(/[。；;]+$/g, '').trim())
    .filter(Boolean)
    .slice(0, 4)
}

function friendlyDetail(text) {
  const value = normalizeDisplayText(text).trim()
  if (!value) return ''
  if (/No Runner commands were provided/i.test(value)) {
    return '当前计划没有提供可执行的验证命令，暂时无法自动确认结果。'
  }
  if (/Created 0 files, changed 0 files, deleted 0 files/i.test(value)) {
    return '本轮没有检测到文件变更，需要继续生成或修复实现。'
  }
  if (/Runner executed Harness-provided commands/i.test(value)) {
    return '已执行 Harness 指定的验证命令并采集日志。'
  }
  if (/does not exist/i.test(value) && /index\.html/i.test(value)) {
    return '目标页面文件还没有生成，验证无法打开页面。'
  }
  if (/dev server command timed out|server was not ready|expected ['"]?Serving HTTP|preview server|localhost.*timeout/i.test(value)) {
    return '预览服务没有在限定时间内报告可访问地址，Runner 无法继续浏览器验证。这更像是验证环境或 Runner 就绪判断问题，不是已生成作品代码本身的错误。'
  }
  if (/infrastructure\/Runner issue|not a product code error/i.test(value)) {
    return 'Runner 基础设施验证遇到问题，需要优先修复验证链路后再判断作品代码。'
  }
  if (/max iterations reached without verdict/i.test(value)) {
    return '自动化验收没有在预算内得到有效结论，需要重新验证。'
  }
  return value
}

function friendlyIssueTitle(event) {
  const combined = `${event?.title || ''} ${event?.detail || ''} ${event?.evidence || ''}`
  if (/No Runner commands were provided/i.test(combined)) return '缺少验证命令'
  if (/Created 0 files|没有生成|0 files/i.test(combined)) return '没有生成文件'
  if (/index\.html.*does not exist|does not exist.*index\.html/i.test(combined)) return '目标页面尚未生成'
  if (/dev server command timed out|server was not ready|expected ['"]?Serving HTTP|preview server/i.test(combined)) return '预览服务未就绪'
  if (/Playwright|locator|browser|页面|点击/i.test(combined)) return '自动化验证脚本出错'
  return event?.title || '需要处理的问题'
}

function friendlyHighlight(text) {
  const value = String(text || '').trim()
  if (!value) return ''
  const commandMatch = value.match(/^(cmd_\d+|[\w.-]+):\s*(失败|通过|跳过|FAILED|PASSED|SKIPPED)$/i)
  if (commandMatch) {
    const state = commandMatch[2]
    const mapped = /通过|PASSED/i.test(state) ? '通过' : /跳过|SKIPPED/i.test(state) ? '跳过' : '未通过'
    return `验证命令 ${commandMatch[1]}：${mapped}`
  }
  return friendlyDetail(value)
}

function compactStageSummary(item) {
  return friendlyDetail(item.summary)
    .replace(/^基于\s*/g, '')
    .slice(0, 150)
}

const ROLE_LABELS = {
  Planner: { label: '计划', running: '正在收敛任务范围', success: '已制定实现计划', error: '计划需要调整' },
  Search: { label: '资料', running: '正在补充必要资料', success: '资料检查完成', error: '资料检索遇到问题' },
  Generator: { label: '实现', running: '正在按计划修改文件', success: '代码修改完成', error: '代码修改遇到问题' },
  Runner: { label: '验证', running: '正在运行真实验证', success: '验证执行完成', error: '验证发现问题' },
  Evaluator: { label: '验收', running: '正在判断验收证据', success: '验收判断完成', error: '验收未通过' },
  Harness: { label: '流程', running: '正在整理执行结果', success: '流程已完成', error: '流程遇到阻塞' },
}

function eventTone(status) {
  const value = String(status || '').toLowerCase()
  if (/(success|done|pass|passed|complete|completed)/.test(value)) return 'success'
  if (/(error|fail|failed|blocked)/.test(value)) return 'error'
  if (/(queued|pending)/.test(value)) return 'pending'
  return 'running'
}

function toneLabel(tone) {
  return {
    success: '完成',
    error: '需要处理',
    running: '进行中',
    pending: '等待',
    blocked: '阻塞',
  }[tone] || '进行中'
}

function toneIconClass(tone) {
  return {
    success: 'fa-check',
    error: 'fa-triangle-exclamation',
    blocked: 'fa-triangle-exclamation',
    running: 'fa-spinner',
    pending: 'fa-clock',
  }[tone] || 'fa-circle'
}

function isInternalText(text) {
  return /内部事件|internal event/i.test(String(text || ''))
}

function compactText(text, max = 220) {
  const value = normalizeDisplayText(text).replace(/\s+/g, ' ').trim()
  if (!value) return ''
  return value.length > max ? `${value.slice(0, max - 1)}...` : value
}

function publicEventTitle(event) {
  const role = event?.role || 'Harness'
  const tone = eventTone(event?.status)
  const rawTitle = friendlyDetail(event?.title || '')
  if (rawTitle && !isInternalText(rawTitle) && !/步骤已完成|输出已记录|^处理中$/i.test(rawTitle)) {
    return compactText(rawTitle, 90)
  }
  const meta = ROLE_LABELS[role] || ROLE_LABELS.Harness
  if (tone === 'success') return meta.success
  if (tone === 'error') return meta.error
  return meta.running
}

function publicEventMessage(event) {
  const detail = friendlyDetail(event?.detail || '')
  const evidence = friendlyDetail(event?.evidence || '')
  const fallback = ROLE_LABELS[event?.role]?.running || ROLE_LABELS.Harness.running
  const value = [detail, evidence]
    .find(item => item && !isInternalText(item) && !/^\[[^\]]+\]\s+\w+/i.test(item) && !/^执行\s+/i.test(item))
    || fallback
  return compactText(value, 240)
}

function publicEvidenceList(event) {
  return [event?.evidence, event?.detail]
    .map(item => compactText(friendlyDetail(item), 120))
    .filter(item => item && !isInternalText(item) && item !== publicEventMessage(event))
    .slice(0, 3)
}

function normalizeReasoningUpdate(update, index) {
  if (!update || typeof update !== 'object' || update.visibility === 'debug') {
    return null
  }
  const role = update.agent || update.role || 'Harness'
  const phase = update.phase || ''
  const title = compactText(update.title || ROLE_LABELS[role]?.running || ROLE_LABELS.Harness.running, 96)
  const message = compactText(update.message || update.summary || '', 280)
  if (!title && !message) return null
  return {
    id: update.id || `reasoning_${index}`,
    agent: role,
    phase,
    title: isInternalText(title) ? (ROLE_LABELS[role]?.running || ROLE_LABELS.Harness.running) : title,
    message: isInternalText(message) ? '' : message,
    basis: Array.isArray(update.basis) ? update.basis.map(item => compactText(item, 120)).filter(Boolean).slice(0, 3) : [],
    nextAction: compactText(update.next_action || update.nextAction || '', 180),
    confidence: typeof update.confidence === 'number' ? update.confidence : null,
  }
}

function generatedReasoningUpdates(process, publicEvents, issueEvent, latestSummary) {
  const explicit = (process.reasoningUpdates || process.reasoning_updates || [])
    .map(normalizeReasoningUpdate)
    .filter(Boolean)
  if (explicit.length) {
    return explicit.slice(-5)
  }

  const fromEvents = publicEvents.slice(-4).map((event, index) => {
    const tone = event.tone
    const role = event.role || 'Harness'
    return {
      id: `generated_${index}_${event.timestamp || role}`,
      agent: role,
      phase: tone === 'error' ? 'blocked' : tone === 'success' ? 'done' : 'running',
      title: event.title,
      message: event.message,
      basis: event.basis,
      nextAction: tone === 'error'
        ? '根据这条证据缩小修复范围，完成后重新运行验证。'
        : '',
      confidence: null,
    }
  })

  if (issueEvent) {
    fromEvents.push({
      id: 'generated_issue',
      agent: 'Evaluator',
      phase: 'blocked',
      title: friendlyIssueTitle(issueEvent),
      message: publicEventMessage(issueEvent),
      basis: publicEvidenceList(issueEvent),
      nextAction: friendlyDetail(process.nextAction || latestSummary?.nextStep || '先修复当前阻塞点，再回到 Runner 做一次真实验证。'),
      confidence: null,
    })
  } else if (latestSummary?.summary) {
    fromEvents.push({
      id: 'generated_summary',
      agent: 'Harness',
      phase: 'done',
      title: latestSummary.title || '本轮结果已整理',
      message: compactText(latestSummary.summary, 260),
      basis: (latestSummary.highlights || []).map(friendlyHighlight).filter(Boolean).slice(0, 3),
      nextAction: friendlyDetail(latestSummary.nextStep || process.nextAction || ''),
      confidence: null,
    })
  }

  return fromEvents.slice(-5)
}

function AgentProcessCard({ entry, workingTimerLabel, completedLabel, userPrompt }) {
  const [activeDetailTab, setActiveDetailTab] = React.useState('overview')
  const process = entry.agentProcess
  if (!process) {
    return null
  }
  const nameFor = {
    Planner: '制定计划',
    Search: '检索资料',
    Generator: '修改代码',
    Runner: '运行验证',
    Evaluator: '检查结果'
  }
  
  const issueEvent = process.currentIssue || [...(process.events || [])].reverse().find(event => event.status === 'error')
  const timelineEvents = process.events || []
  const timeLabel = entry.streaming ? workingTimerLabel : entry.elapsedLabel || completedLabel || null
  const decision = process.decision || null
  const latestSummary = process.latestSummary || null

  const isPass = decision?.decision === 'PASS' || process.status === 'done' || (!entry.streaming && !issueEvent)
  const isBlocked = !!issueEvent
  const headline = isBlocked
    ? '任务遇到阻塞'
    : isPass
      ? '任务已完成'
      : entry.streaming 
        ? '系统正在处理任务...'
        : '执行完成'
  const taskGoal = compactText(latestSummary?.summary || userPrompt || process.statusLine || 'Harness 正在处理当前任务。', 160)

  const issueTitle = issueEvent ? friendlyIssueTitle(issueEvent) : ''
  const issueDetail = issueEvent ? friendlyDetail(issueEvent.detail || issueEvent.evidence || '') : ''

  const rawHighlights = latestSummary?.highlights;
  const safeHighlights = Array.isArray(rawHighlights) ? rawHighlights : (typeof rawHighlights === 'string' ? [rawHighlights] : []);
  const compactHighlights = safeHighlights
    .map(friendlyHighlight)
    .filter(item => item && !/^验证命令\s+cmd_\d+/i.test(item))
    .slice(0, 4)

  const publicEvents = timelineEvents.map((event, index) => {
    const tone = eventTone(event.status)
    return {
      ...event,
      tone,
      roleLabel: ROLE_LABELS[event.role]?.label || event.role || '流程',
      title: publicEventTitle(event),
      message: publicEventMessage(event),
      basis: publicEvidenceList(event),
      time: event.timestamp ? new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '',
      key: `${event.timestamp || 'event'}_${index}`,
    }
  }).filter(event => event.title || event.message)

  const currentEvent = [...publicEvents].reverse().find(event => event.tone === 'running') || publicEvents.at(-1) || null
  const progressDone = publicEvents.filter(event => event.tone === 'success').length
  const progressTotal = Math.max(publicEvents.length, 1)
  const reasoningUpdates = generatedReasoningUpdates(process, publicEvents, issueEvent, latestSummary)
  const latestReasoning = reasoningUpdates.at(-1) || null
  const earlierReasoning = reasoningUpdates.slice(0, -1)
  const visibleTimeline = publicEvents.slice(-8)
  const resultSummary = latestSummary?.summary || (isPass && !issueEvent ? 'Harness 已完成本轮任务并整理了验证结果。' : '')
  const nextStepText = friendlyDetail(process.nextAction || latestSummary?.nextStep || (issueEvent ? '根据证据进行最小修复，然后重新运行验证。' : '继续根据当前证据推进。'))
  const evidenceItems = issueEvent
    ? publicEvidenceList(issueEvent)
    : compactHighlights.slice(0, 3)
  const changedFiles = Array.isArray(latestSummary?.changedFiles) ? latestSummary.changedFiles : []
  const detailTabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'changes', label: 'Changes' },
    { id: 'tests', label: 'Tests' },
    { id: 'logs', label: 'Logs' },
    { id: 'json', label: 'JSON' },
  ]

  return (
    <div className="agent-process-card codex-style-card" aria-live="polite">
      <div className="agent-process-head task-header-card">
        <div className="agent-process-head-copy">
          <span className="agent-process-kicker">任务进度</span>
          <strong>{headline}</strong>
          <p className="agent-process-summary">{taskGoal}</p>
          <div className="task-header-meta">
            <span>{isBlocked ? '状态：验证遇到阻塞' : isPass ? '状态：已完成' : '状态：进行中'}</span>
            <span>进度：{Math.min(progressDone, progressTotal)} / {progressTotal}</span>
            {process.roundId ? <span>第 {process.roundId} 轮</span> : null}
          </div>
        </div>
        <div className="agent-process-head-meta">
          {timeLabel ? <span className="agent-process-time-badge">{timeLabel}</span> : null}
          {entry.streaming ? <span className="agent-process-live executing">运行中</span> : null}
        </div>
      </div>
      
      <div className="codex-process-body">
        {latestReasoning ? (
          <section className="reasoning-stream" aria-label="Reasoning summary">
            <div className="harness-panel-heading">
              <span>Reasoning Summary</span>
              <em>{latestReasoning.agent}</em>
            </div>
            <div className="reasoning-stack">
              {earlierReasoning.slice(-3).map(update => (
                <div key={update.id} className="reasoning-step compact">
                  <span className="reasoning-agent">{ROLE_LABELS[update.agent]?.label || update.agent}</span>
                  <strong>{update.title}</strong>
                </div>
              ))}
              <article className={`reasoning-step expanded ${latestReasoning.phase || 'running'}`}>
                <div className="reasoning-step-top">
                  <span className="reasoning-agent">{ROLE_LABELS[latestReasoning.agent]?.label || latestReasoning.agent}</span>
                  <strong>{latestReasoning.title}</strong>
                </div>
                {latestReasoning.message ? <p>{latestReasoning.message}</p> : null}
                {latestReasoning.basis?.length ? (
                  <ul className="reasoning-basis">
                    {latestReasoning.basis.slice(0, 3).map((item, index) => (
                      <li key={`${latestReasoning.id}_basis_${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {latestReasoning.nextAction ? (
                  <div className="reasoning-next">
                    <span>下一步</span>
                    <strong>{latestReasoning.nextAction}</strong>
                  </div>
                ) : null}
              </article>
            </div>
          </section>
        ) : null}

        <section className="harness-user-timeline-card">
          <div className="harness-panel-heading">
            <span>Task Timeline</span>
            <em>{visibleTimeline.length ? `${visibleTimeline.length} steps` : 'preparing'}</em>
          </div>
          {visibleTimeline.length ? (
            <ol className="harness-user-timeline">
              {visibleTimeline.map((event, index) => (
                <li key={event.key} className={`harness-user-stage ${event.tone}`}>
                  <span className="harness-user-stage-index" aria-hidden="true">
                    <i className={`fas ${toneIconClass(event.tone)}${event.tone === 'running' ? ' fa-spin' : ''}`} />
                  </span>
                  <div className="harness-user-stage-body">
                    <div className="harness-user-stage-top">
                      <div className="harness-user-stage-titleline">
                        <span className="harness-user-stage-role">{event.roleLabel}</span>
                        <strong>{event.title}</strong>
                      </div>
                      <span className={`harness-user-stage-status ${event.tone}`}>{toneLabel(event.tone)}</span>
                    </div>
                    {event.message ? <p>{event.message}</p> : null}
                    {event.time ? <span className="harness-user-stage-time">{event.time}</span> : null}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div className="harness-timeline-empty">正在准备 Harness 执行链路。</div>
          )}
        </section>

        <section className={`harness-current-action-card ${isBlocked ? 'blocked' : isPass ? 'done' : 'running'}`}>
          <div className="harness-card-eyebrow">{isBlocked ? '当前问题' : isPass ? '完成情况' : '当前动作'}</div>
          <strong>{isBlocked ? issueTitle : isPass ? (latestSummary?.title || '任务已完成') : (currentEvent?.title || '正在推进任务')}</strong>
          <p>{isBlocked ? (issueDetail || '当前验证证据不足，需要先处理阻塞点。') : isPass ? (resultSummary || '本轮执行已经完成。') : (currentEvent?.message || 'Harness 正在根据当前证据推进下一步。')}</p>
          <div className="current-action-grid">
            <span>影响</span>
            <strong>{isBlocked ? '无法确认最终结果是否满足验收标准。' : isPass ? '可以继续查看变更、测试和日志证据。' : '当前步骤完成后会进入下一轮验证或验收。'}</strong>
            <span>下一步</span>
            <strong>{nextStepText}</strong>
          </div>
          <div className="harness-action-row">
            {isBlocked ? <button type="button" disabled title="请在输入框回复继续修复，Harness 会进入下一轮">自动修复并重试</button> : null}
            <button type="button" onClick={() => setActiveDetailTab('tests')}>查看测试结果</button>
            <button type="button" onClick={() => setActiveDetailTab('logs')}>查看技术细节</button>
          </div>
        </section>

        {issueEvent ? (
          <section className="harness-issue-card blocked">
            <div className="harness-card-eyebrow">当前问题</div>
            <strong>{issueTitle}</strong>
            {issueDetail ? <p>{issueDetail}</p> : null}
            {evidenceItems.length ? (
              <ul className="harness-evidence-list">
                {evidenceItems.map((item, index) => (
                  <li key={`issue_evidence_${index}`}>{item}</li>
                ))}
              </ul>
            ) : null}
            <div className="harness-next-step-inline">
              {nextStepText}
            </div>
          </section>
        ) : isPass ? (
          <section className="harness-final-card">
            <div className="harness-card-eyebrow">本轮结果</div>
            <strong>{latestSummary?.title || '任务已完成'}</strong>
            {resultSummary ? <p>{resultSummary}</p> : null}
            {compactHighlights.length ? (
              <ul>
                {compactHighlights.map((item, index) => (
                  <li key={`${item}_${index}`}>{item}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}

        <section className="harness-detail-tabs">
          <div className="harness-detail-tablist" role="tablist" aria-label="Task details">
            {detailTabs.map(tab => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeDetailTab === tab.id}
                className={activeDetailTab === tab.id ? 'active' : ''}
                onClick={() => setActiveDetailTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="harness-detail-panel" role="tabpanel">
            {activeDetailTab === 'overview' ? (
              <div>
                <strong>{headline}</strong>
                <p>{taskGoal}</p>
                <p>{nextStepText}</p>
              </div>
            ) : activeDetailTab === 'changes' ? (
              <div>
                <strong>文件变更</strong>
                {changedFiles.length ? (
                  <ul>{changedFiles.map((file, index) => <li key={`${file}_${index}`}>{file}</li>)}</ul>
                ) : (
                  <p>当前摘要中没有提供逐文件变更列表，详细 diff 可在 Debug/Logs 中查看。</p>
                )}
              </div>
            ) : activeDetailTab === 'tests' ? (
              <div>
                <strong>验证证据</strong>
                {evidenceItems.length ? (
                  <ul>{evidenceItems.map((item, index) => <li key={`test_evidence_${index}`}>{item}</li>)}</ul>
                ) : (
                  <p>暂无可展示的测试摘要。</p>
                )}
              </div>
            ) : activeDetailTab === 'logs' ? (
              <div>
                <strong>日志</strong>
                <p>原始 stdout、stderr 和工具调用默认隐藏在技术细节中。</p>
              </div>
            ) : (
              <div>
                <strong>结构化状态</strong>
                <pre>{JSON.stringify({
                  status: isBlocked ? 'blocked' : isPass ? 'done' : 'running',
                  round_id: process.roundId || 0,
                  decision: decision?.decision || '',
                  next_action: nextStepText,
                }, null, 2)}</pre>
              </div>
            )}
          </div>
        </section>

        {timelineEvents.length ? (
          <details className="harness-debug-details">
            <summary>技术细节</summary>
            <ol className="agent-process-timeline compact">
              {timelineEvents.slice(-10).map((event, index) => (
                <li key={`debug_${event.timestamp || 'event'}_${index}`} className={eventTone(event.status)}>
                  <span className="agent-process-time">{event.timestamp ? new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'}</span>
                  <span className="agent-process-role">{nameFor[event.role] || event.role || 'Harness'}</span>
                  <span className="agent-process-copy">
                    <span className="agent-process-title">{friendlyDetail(event.title || '') || publicEventTitle(event)}</span>
                    {event.detail ? <span className="agent-process-detail">{friendlyDetail(event.detail)}</span> : null}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        ) : null}
      </div>
    </div>
  )
}

function renderAgentProcess(entry, { workingTimerLabel, completedLabel, userPrompt } = {}) {
  return (
    <AgentProcessCard
      entry={entry}
      workingTimerLabel={workingTimerLabel}
      completedLabel={completedLabel}
      userPrompt={userPrompt}
    />
  )
}

export default function TranscriptView({ transcript, chatMessagesRef, expandedThinking, onToggleThinking, onGuidedChoiceSelect, guidedChoiceNow, requestIndicator, workingTimerLabel, completedLabel, routeMode }) {
  const lastUserIndex = (() => {
    for (let index = transcript.length - 1; index >= 0; index -= 1) {
      if (transcript[index]?.role === 'user') {
        return index
      }
    }
    return -1
  })()

  const lastNonUserIndex = (() => {
    for (let index = transcript.length - 1; index >= 0; index -= 1) {
      if (transcript[index]?.role !== 'user') {
        return index
      }
    }
    return -1
  })()

  return (
    <section className="chat-region" style={{ height: '100%', maxHeight: '100%', overflow: 'hidden' }}>
      <div id="chat-messages" className="chat-messages" ref={chatMessagesRef} style={{ height: '100%', overflowY: 'auto' }}>
        {!transcript.length ? (
          <div className="transcript-empty">No transcript items yet. Start with a task request, or ask for a real-time search.</div>
        ) : (
          <div className="message-list">
            {transcript.map((entry, index) => {
              const userPrompt = transcript
                .slice(0, index)
                .reverse()
                .find(item => item?.role === 'user' && String(item.content || '').trim())?.content || ''
              const isThinking = entry.kind === 'thinking_text'
              const isCompressionNotice = entry.kind === 'system_notice' && entry.phase === 'compression'
              const isCompressionComplete = entry.compressionState === 'complete'
              const isExpanded = Boolean(expandedThinking[entry.id])
              const collapsed = isThinking && !isExpanded
              // While streaming, skip markdown parsing entirely – React updates
              // plain text nodes incrementally without replacing the DOM, which
              // eliminates the per-token flicker caused by dangerouslySetInnerHTML.
              const isRenderableKind = entry.kind === 'assistant_text' || entry.kind === 'system_notice' || entry.kind === 'tool_result' || entry.kind === 'thinking_text'
              const isPendingThinking = entry.kind === 'thinking_text' && entry.pendingPlaceholder && !String(entry.content || '').trim()
              const bodyHtml = !isPendingThinking && isRenderableKind && !entry.streaming ? renderMarkdown(entry.content) : null

              return (
                <React.Fragment key={entry.id}>
                  <article className={`message ${transcriptRole(entry)}${entry.isError ? ' error' : ''}${isCompressionNotice ? ' compression-notice' : ''}`}>
                    {!isCompressionNotice ? (
                      <div className="message-meta">
                        <span>{entryLabel(entry)}</span>
                        <span>{new Date(entry.timestamp || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      </div>
                    ) : null}

                    {isThinking ? (
                      <div className="message-actions">
                        <button type="button" className={`message-toggle thinking-toggle${isExpanded ? ' expanded' : ''}`} onClick={() => onToggleThinking(entry.id)} title={isExpanded ? 'Collapse thinking' : 'Expand thinking'}>
                          <i className={`fas fa-chevron-${isExpanded ? 'up' : 'down'}`} aria-hidden="true" />
                        </button>
                      </div>
                    ) : null}

                    {entry.kind === 'tool_use' || entry.kind === 'tool_result' ? (
                      <div className={`tool-card ${entry.kind}`}>
                        <div className={`tool-card-icon ${entry.kind === 'tool_use' ? 'running' : entry.success === false ? 'error' : 'done'}`}>
                          {entry.kind === 'tool_use' ? <i className="fas fa-spinner" /> : entry.success === false ? <i className="fas fa-triangle-exclamation" /> : <i className="fas fa-check" />}
                        </div>
                        <div className="tool-card-content">
                          <div className="tool-card-title">{entry.toolName || entry.taskId || 'tool'}</div>
                          <div className="tool-card-subtitle">{entry.kind === 'tool_use' ? 'Invoking tool' : entry.success === false ? 'Tool finished with an error' : 'Tool result captured'}</div>
                        </div>
                      </div>
                    ) : null}

                    {isThinking && collapsed ? <div className="thinking-summary">{getThinkingSummary(entry.content, entry.streaming)}</div> : null}

                    <div className={`message-body${entry.streaming ? ' is-streaming' : ''}${collapsed ? ' collapsed' : ''}`}>
                      {/* elapsed time pinned to bottom-right of the message bubble */}
                      {(() => {
                        const label = entry.elapsedLabel || (!requestIndicator?.active && index === lastNonUserIndex ? completedLabel : null)
                        return label ? (
                          <div className="completed-elapsed" aria-label={`Completed in ${label}`}>
                            <i className="fas fa-check-circle" aria-hidden="true" />
                            <span>{label}</span>
                          </div>
                        ) : null
                      })()}
                      {entry.kind === 'agent_process' ? (
                        renderAgentProcess(entry, { workingTimerLabel, completedLabel, userPrompt })
                      ) : entry.kind === 'thinking_text' && entry.pendingPlaceholder && !String(entry.content || '').trim() ? (
                        <div className="thinking-pending">
                          <span className="thinking-pending-label">Waiting for first reasoning token</span>
                          <span className="thinking-pending-dots" aria-hidden="true">
                            <span />
                            <span />
                            <span />
                          </span>
                        </div>
                      ) : isCompressionNotice ? (
                        <div className="compression-inline" aria-live="polite">
                          <span className="compression-line" aria-hidden="true" />
                          <span className="compression-copy">
                            {isCompressionComplete ? (
                              <i className="fas fa-check compression-check" />
                            ) : (
                              <span className="compression-spinner">
                                <i className="fas fa-spinner" />
                              </span>
                            )}
                            <span>{entry.content || (isCompressionComplete ? 'Context compacted' : 'Compressing conversation context')}</span>
                          </span>
                          <span className="compression-line" aria-hidden="true" />
                        </div>
                      ) : entry.isError ? (
                        <pre className="error-body">{entry.content}</pre>
                      ) : entry.kind === 'guided_choice' ? (
                        renderGuidedChoiceCard(entry, onGuidedChoiceSelect, guidedChoiceNow)
                      ) : bodyHtml !== null ? (
                        <div dangerouslySetInnerHTML={{ __html: bodyHtml }} />
                      ) : entry.streaming && isRenderableKind ? (
                        <div className="streaming-plain-text">{normalizeDisplayText(entry.content)}</div>
                      ) : (
                        <div>
                          {stripImageTokens(entry.content) ? <span>{stripImageTokens(entry.content)}</span> : null}
                          {Array.isArray(entry.images) && entry.images.length > 0 ? (
                            <div className="message-image-chips">
                              {entry.images.map(img => (
                                <span key={img.id} className="message-image-chip">
                                  {img.dataUrl ? <img src={img.dataUrl} alt={img.name || 'image'} className="message-image-thumb" /> : <i className="fas fa-image" />}
                                  <span className="message-image-chip-name">{img.name || 'image'}</span>
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>

                    {renderTodoStrip(entry.todo)}
                  </article>

                  {requestIndicator?.active && index === lastUserIndex ? (
                    <div className="request-loading-left" aria-live="polite">
                      <span className="request-loading-spinner" aria-hidden="true">
                        <i className="fas fa-spinner" />
                      </span>
                      <span>{requestIndicator.label || 'Working on your request'}</span>
                      {workingTimerLabel ? <span className="request-loading-timer">{workingTimerLabel}</span> : null}
                    </div>
                  ) : null}
                </React.Fragment>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}
