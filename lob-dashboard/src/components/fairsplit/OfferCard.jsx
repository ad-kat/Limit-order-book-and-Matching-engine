import React from 'react'

function formatRent(cents) {
  return '$' + (cents / 100).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

const SMOKING_LABELS = {
  non_smoker:    'Non-smoking',
  smoker:        'Smoking ok',
  no_preference: 'Any',
}

export default function OfferCard({ offer, onSelect, selected }) {
  const avail = offer.available_from
    ? new Date(offer.available_from).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
      })
    : '—'

  return (
    <div
      className={`apt-card apt-card--offer${selected ? ' apt-card--selected' : ''}`}
      onClick={() => onSelect && onSelect(offer)}
      style={{ cursor: onSelect ? 'pointer' : 'default' }}
    >
      <div className="apt-card__header">
        <span className="apt-card__badge apt-card__badge--offer">Room Available</span>
        <span className="apt-card__neighborhood">{offer.neighborhood}</span>
      </div>

      <h3 className="apt-card__title">{offer.title}</h3>

      <div className="apt-card__stats">
        <div className="apt-card__stat">
          <span className="apt-card__stat-label">Rent/Room</span>
          <span className="apt-card__stat-value apt-card__stat-value--primary">
            {formatRent(offer.rent_per_room_cents)}/mo
          </span>
        </div>
        <div className="apt-card__stat">
          <span className="apt-card__stat-label">Rooms</span>
          <span className="apt-card__stat-value">{offer.rooms_available}</span>
        </div>
        <div className="apt-card__stat">
          <span className="apt-card__stat-label">Smoking</span>
          <span className="apt-card__stat-value">
            {SMOKING_LABELS[offer.smoking_policy] || offer.smoking_policy}
          </span>
        </div>
      </div>

      {offer.description && (
        <p className="apt-card__desc">{offer.description}</p>
      )}

      <div className="apt-card__footer">
        <span className="apt-card__avail">Available {avail}</span>
        {offer.is_synthetic && <span className="apt-card__synthetic">Demo</span>}
      </div>
    </div>
  )
}
