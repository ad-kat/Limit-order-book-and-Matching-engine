import React, { useState } from 'react'

const STATUS_LABELS = {
  forming: { label: 'Forming', cls: 'status--forming' },
  complete: { label: 'Complete', cls: 'status--complete' },
  cancelled: { label: 'Cancelled', cls: 'status--cancelled' },
}

const MEMBER_STATUS_LABELS = {
  pending: { label: 'Invited', cls: 'mstatus--pending' },
  accepted: { label: 'Joined', cls: 'mstatus--accepted' },
  declined: { label: 'Declined', cls: 'mstatus--declined' },
}

function GroupCard({ group, onAccept, accepting }) {
  const stInfo = STATUS_LABELS[group.status] || { label: group.status, cls: '' }
  const pendingForMe = group.members.filter(m => m.status === 'pending')
  const acceptedCount = group.members.filter(m => m.status === 'accepted').length
  const total = group.members.length

  return (
    <div className="group-card">
      <div className="group-card__header">
        <div>
          <div className="group-card__title">Group for Apartment</div>
          <div className="group-card__apt-id">{group.apartment_id}</div>
        </div>
        <span className={`group-status ${stInfo.cls}`}>{stInfo.label}</span>
      </div>

      <div className="group-card__progress">
        <div className="group-progress__bar">
          <div
            className="group-progress__fill"
            style={{ width: `${total > 0 ? (acceptedCount / total) * 100 : 0}%` }}
          />
        </div>
        <span className="group-progress__label">{acceptedCount}/{total} confirmed</span>
      </div>

      <div className="group-card__members">
        {group.members.map((m, i) => {
          const msInfo = MEMBER_STATUS_LABELS[m.status] || { label: m.status, cls: '' }
          const isPending = m.status === 'pending'
          return (
            <div key={m.id || i} className="group-member-row">
              <div className="group-member-row__avatar">
                {(m.display_name || 'U')[0].toUpperCase()}
              </div>
              <span className="group-member-row__name">{m.display_name || m.profile_id}</span>
              <span className={`member-status ${msInfo.cls}`}>{msInfo.label}</span>
              {isPending && onAccept && (
                <button
                  className="btn btn--sm btn--accept"
                  onClick={() => onAccept(group.id, m.id)}
                  disabled={accepting}
                >
                  {accepting ? '…' : 'Accept'}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {group.created_at && (
        <div className="group-card__footer">
          Created {new Date(group.created_at).toLocaleDateString()}
        </div>
      )}
    </div>
  )
}

export default function MyGroups({ groups, loading, onAccept }) {
  const [accepting, setAccepting] = useState(false)

  async function handleAccept(groupId, memberId) {
    setAccepting(true)
    try {
      await onAccept(groupId, memberId)
    } finally {
      setAccepting(false)
    }
  }

  if (loading) {
    return (
      <div className="groups-empty">
        <div className="spinner" />
        <p>Loading your groups…</p>
      </div>
    )
  }

  if (!groups || groups.length === 0) {
    return (
      <div className="groups-empty">
        <p>You are not in any groups yet.</p>
        <p style={{ marginTop: 8, color: '#64748b', fontSize: 14 }}>
          Use the Discover tab to find apartments and the Voice Agent to propose a group.
        </p>
      </div>
    )
  }

  return (
    <div className="groups-list">
      {groups.map((g, i) => (
        <GroupCard
          key={g.id || i}
          group={g}
          onAccept={handleAccept}
          accepting={accepting}
        />
      ))}
    </div>
  )
}
