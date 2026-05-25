import React from 'react'

export default function RequestStatusIndicator({ label, timerLabel }) {
  return (
    <div className="request-loading-left" aria-live="polite">
      <span className="request-loading-spinner" aria-hidden="true">
        <i className="fas fa-spinner" />
      </span>
      <span>{label || 'Working on your request'}</span>
      {timerLabel ? <span className="request-loading-timer">{timerLabel}</span> : null}
    </div>
  )
}
