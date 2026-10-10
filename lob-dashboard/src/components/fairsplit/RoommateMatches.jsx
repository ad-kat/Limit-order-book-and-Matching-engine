import React from 'react'

function formatBudget(cents) {
  return '$' + (cents / 100).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

function BudgetBar({ budget, perPersonRent }) {
  const pct = Math.min(100, Math.round((budget / (perPersonRent * 1.5)) * 100))
  const slack = budget - perPersonRent
  const comfortable = slack > 0
  return (
    <div className="budget-bar">
      <div className="budget-bar__track">
        <div
          className={`budget-bar__fill${comfortable ? ' budget-bar__fill--ok' : ' budget-bar__fill--tight'}`}
          style={{ width: `${pct}%` }}
        />
        <div
          className="budget-bar__marker"
          style={{ left: `${Math.min(100, Math.round((perPersonRent / (perPersonRent * 1.5)) * 100))}%` }}
          title={`Rent: ${formatBudget(perPersonRent)}`}
        />
      </div>
      <span className={`budget-bar__label${comfortable ? ' budget-bar__label--ok' : ' budget-bar__label--tight'}`}>
        {comfortable ? `+${formatBudget(slack)} slack` : 'tight'}
      </span>
    </div>
  )
}

function MoveInBadge({ moveInDate, refDate }) {
  const d1 = new Date(moveInDate)
  const d2 = refDate ? new Date(refDate) : new Date()
  const diff = Math.abs(Math.round((d1 - d2) / 86400000))
  const label = diff <= 7 ? 'Exact match' : diff <= 30 ? `${diff}d apart` : 'Flexible'
  const cls = diff <= 7 ? 'movein--exact' : diff <= 30 ? 'movein--close' : 'movein--flexible'
  return <span className={`movein-badge ${cls}`}>{label}</span>
}

function GroupCard({ group, perPersonRent, rank }) {
  const medalEmoji = ['🥇', '🥈', '🥉'][rank] || `#${rank + 1}`
  return (
    <div className="match-card">
      <div className="match-card__header">
        <span className="match-card__rank">{medalEmoji}</span>
        <span className="match-card__score">Score {Math.round(group.score)}</span>
      </div>

      <div className="match-card__explanation">{group.explanation}</div>

      <div className="match-card__members">
        {group.members.map((m, i) => (
          <div key={m.id || i} className="match-member">
            <div className="match-member__avatar">
              {(m.display_name || 'U')[0].toUpperCase()}
            </div>
            <div className="match-member__info">
              <div className="match-member__name">{m.display_name || m.id}</div>
              <div className="match-member__meta">
                Budget: {formatBudget(m.max_budget)} &middot; {m.smoking_preference.replace('_', ' ')}
              </div>
              <BudgetBar budget={m.max_budget} perPersonRent={perPersonRent} />
            </div>
            <MoveInBadge moveInDate={m.move_in_date} />
          </div>
        ))}
      </div>
    </div>
  )
}

export default function RoommateMatches({ matchResult, loading }) {
  if (loading) {
    return (
      <div className="matches-empty">
        <div className="spinner" />
        <p>Finding compatible roommates…</p>
      </div>
    )
  }

  if (!matchResult) {
    return (
      <div className="matches-empty">
        <p>Select an apartment and click "Find Roommates" to see compatible groups.</p>
      </div>
    )
  }

  const { top_groups = [], per_person_rent, apartment_id, candidate_count } = matchResult

  return (
    <div className="matches">
      <div className="matches__summary">
        <span>{candidate_count} candidates evaluated</span>
        <span>&middot;</span>
        <span>Per-person rent: {formatBudget(per_person_rent)}/mo</span>
        <span>&middot;</span>
        <span>{top_groups.length} compatible group{top_groups.length !== 1 ? 's' : ''} found</span>
      </div>

      {top_groups.length === 0 ? (
        <div className="matches-empty">
          <p>No compatible groups found for this apartment. Try a different apartment.</p>
        </div>
      ) : (
        <div className="matches__list">
          {top_groups.map((group, i) => (
            <GroupCard
              key={i}
              group={group}
              perPersonRent={per_person_rent}
              rank={i}
            />
          ))}
        </div>
      )}
    </div>
  )
}
