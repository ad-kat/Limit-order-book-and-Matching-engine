import React from 'react'

const BADGES = ['Great Deal', 'Hot Listing', 'New', 'Popular', 'Pet Friendly']

function getBadge(apt) {
  // deterministic synthetic badge based on apartment id hash
  const idx = apt.id ? apt.id.charCodeAt(4) % BADGES.length : 0
  return BADGES[idx]
}

function formatRent(cents) {
  return '$' + (cents / 100).toLocaleString('en-US', { maximumFractionDigits: 0 })
}

export default function ApartmentCard({ apartment, onSelect, selected }) {
  const perPerson = apartment.per_person_rent || Math.ceil(apartment.monthly_rent / apartment.bedrooms)
  const badge = getBadge(apartment)
  const avail = apartment.available_from
    ? new Date(apartment.available_from).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : '—'

  return (
    <div
      className={`apt-card${selected ? ' apt-card--selected' : ''}`}
      onClick={() => onSelect && onSelect(apartment)}
      style={{ cursor: onSelect ? 'pointer' : 'default' }}
    >
      <div className="apt-card__header">
        <span className="apt-card__badge">{badge}</span>
        <span className="apt-card__neighborhood">{apartment.neighborhood}</span>
      </div>

      <h3 className="apt-card__title">{apartment.title}</h3>

      <div className="apt-card__stats">
        <div className="apt-card__stat">
          <span className="apt-card__stat-label">Total Rent</span>
          <span className="apt-card__stat-value">{formatRent(apartment.monthly_rent)}/mo</span>
        </div>
        <div className="apt-card__stat">
          <span className="apt-card__stat-label">Per Person</span>
          <span className="apt-card__stat-value apt-card__stat-value--primary">{formatRent(perPerson)}/mo</span>
        </div>
        <div className="apt-card__stat">
          <span className="apt-card__stat-label">Bedrooms</span>
          <span className="apt-card__stat-value">{apartment.bedrooms} BR</span>
        </div>
      </div>

      {apartment.description && (
        <p className="apt-card__desc">{apartment.description}</p>
      )}

      <div className="apt-card__footer">
        <span className="apt-card__avail">Available {avail}</span>
        {apartment.is_synthetic && (
          <span className="apt-card__synthetic">Demo</span>
        )}
      </div>
    </div>
  )
}
