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
  const value = String(text || '').trim()
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

function renderAgentProcess(entry, { workingTimerLabel, completedLabel } = {}) {
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

  const issueTitle = issueEvent ? friendlyIssueTitle(issueEvent) : ''
  const issueDetail = issueEvent ? friendlyDetail(issueEvent.detail || issueEvent.evidence || '') : ''

  const rawHighlights = latestSummary?.highlights;
  const safeHighlights = Array.isArray(rawHighlights) ? rawHighlights : (typeof rawHighlights === 'string' ? [rawHighlights] : []);
  const compactHighlights = safeHighlights
    .map(friendlyHighlight)
    .filter(item => item && !/^验证命令\s+cmd_\d+/i.test(item))
    .slice(0, 4)

  return (
    <div className="agent-process-card codex-style-card" aria-live="polite">
      <div className="agent-process-head">
        <div className="agent-process-head-copy">
          <span className="agent-process-kicker">任务进度</span>
          <strong>{headline}</strong>
        </div>
        <div className="agent-process-head-meta">
          {timeLabel ? <span className="agent-process-time-badge">{timeLabel}</span> : null}
          {entry.streaming ? <span className="agent-process-live executing">●</span> : null}
        </div>
      </div>
      
      <div className="codex-process-body" style={{ padding: '0', display: 'flex', flexDirection: 'column' }}>
        
        <div className="harness-realtime-timeline" style={{ padding: '16px', maxHeight: '300px', overflowY: 'auto', background: 'var(--bg-inset)', fontSize: '14px' }}>
          {timelineEvents.length ? (
            <ul className="agent-process-timeline" style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {timelineEvents.map((event, index) => {
                const isError = event.status === 'error' || event.status === 'FAILED'
                const isRunning = event.status === 'running'
                const roleName = nameFor[event.role] || event.role || '系统'
                // Codex spec: "✅ 制定实现计划" / "⚠️ 运行验证" / "⏸ 等待处理"
                const icon = isError ? '⚠️' : isRunning ? '🔄' : '✅'
                
                return (
                  <li key={`${event.timestamp}_${index}`} style={{ display: 'flex', flexDirection: 'column', gap: '4px', opacity: isRunning ? 1 : 0.85, color: isError ? 'var(--text-error)' : 'inherit' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                      <span>{icon}</span>
                      <span>{roleName}</span>
                      <span style={{ opacity: 0.5, fontWeight: 400, fontSize: '12px', marginLeft: 'auto' }}>
                         {new Date(event.timestamp || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </span>
                    </div>
                    <div style={{ paddingLeft: '24px', opacity: 0.9 }}>
                      {friendlyDetail(event.title || event.detail || '')}
                    </div>
                  </li>
                )
              })}
            </ul>
          ) : (
            <div style={{ opacity: 0.5, fontStyle: 'italic' }}>正在准备执行...</div>
          )}
        </div>

        {compactHighlights.length > 0 && !issueEvent ? (
          <div className="harness-highlights-card" style={{ margin: '0', padding: '16px', borderTop: '1px solid var(--border-light)' }}>
            <div className="harness-card-eyebrow" style={{ marginBottom: '8px' }}>阶段总结</div>
            <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px' }}>
              {compactHighlights.map((item, index) => (
                <li key={`${item}_${index}`}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {issueEvent ? (
          <div className="harness-issue-card" style={{ margin: '0', padding: '16px', borderTop: '1px solid var(--border-light)', background: 'var(--bg-error-light, #fef2f2)' }}>
            <div className="harness-card-eyebrow" style={{ color: 'var(--text-error)' }}>阻塞原因</div>
            <strong style={{ color: 'var(--text-error)' }}>{issueTitle}</strong>
            {issueDetail ? <p style={{marginTop: '8px', fontSize: '13px', color: 'var(--text-error)'}}>{issueDetail}</p> : null}
          </div>
        ) : null}

      </div>
    </div>
  )
}

export default function TranscriptView({ transcript, chatMessagesRef, expandedThinking, onToggleThinking, onGuidedChoiceSelect, guidedChoiceNow, requestIndicator, workingTimerLabel, completedLabel }) {
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
    <section className="chat-region">
      <div id="chat-messages" className="chat-messages" ref={chatMessagesRef}>
        {!transcript.length ? (
          <div className="transcript-empty">No transcript items yet. Start with a task request, or ask for a real-time search.</div>
        ) : (
          <div className="message-list">
            {transcript.map((entry, index) => {
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
                        renderAgentProcess(entry, { workingTimerLabel, completedLabel })
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
