import React, { useEffect, useState } from 'react'
import ApartmentCard from './components/fairsplit/ApartmentCard'
import OfferCard from './components/fairsplit/OfferCard'
import VoiceAgent from './components/fairsplit/VoiceAgent'
import RoommateMatches from './components/fairsplit/RoommateMatches'
import MyGroups from './components/fairsplit/MyGroups'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const TABS = [
  { id: 'discover', label: 'Discover' },
  { id: 'agent',    label: 'Voice Agent' },
  { id: 'matches',  label: 'Matches' },
  { id: 'groups',   label: 'My Groups' },
]

// Demo profile for hackathon
const DEMO_PROFILE_ID = 'profile-alex-001'

export default function FairSplitApp() {
  const [tab, setTab]                     = useState('discover')
  const [apartments, setApartments]       = useState([])
  const [aptsLoading, setAptsLoading]     = useState(true)
  const [selectedApt, setSelectedApt]     = useState(null)
  const [matchResult, setMatchResult]     = useState(null)
  const [matchLoading, setMatchLoading]   = useState(false)
  const [groups, setGroups]               = useState([])
  const [groupsLoading, setGroupsLoading] = useState(false)
  const [offers, setOffers]               = useState([])
  const [searchNhd, setSearchNhd]         = useState('')
  const [searchBeds, setSearchBeds]       = useState('')
  const [apiError, setApiError]           = useState('')

  // Load apartments and offers on mount
  useEffect(() => {
    loadApartments()
    loadOffers()
  }, [])

  // Load groups when groups tab is opened
  useEffect(() => {
    if (tab === 'groups') loadGroups()
  }, [tab])

  async function loadApartments(params = {}) {
    setAptsLoading(true)
    setApiError('')
    try {
      let url = `${API_BASE}/fairsplit/apartments`
      if (params.neighborhood || params.bedrooms) {
        const body = {}
        if (params.neighborhood) body.neighborhood = params.neighborhood
        if (params.bedrooms) body.bedrooms = parseInt(params.bedrooms)
        const res = await fetch(`${API_BASE}/fairsplit/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        const data = await res.json()
        setApartments(Array.isArray(data) ? data : [])
      } else {
        const res = await fetch(url)
        const data = await res.json()
        setApartments(Array.isArray(data) ? data : [])
      }
    } catch (e) {
      setApiError('Could not connect to API. Make sure the backend is running.')
      setApartments([])
    } finally {
      setAptsLoading(false)
    }
  }

  async function findRoommates(apt) {
    setMatchLoading(true)
    setMatchResult(null)
    setTab('matches')
    try {
      const res = await fetch(`${API_BASE}/fairsplit/match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apartment_id: apt.id }),
      })
      const data = await res.json()
      setMatchResult(data)
    } catch (e) {
      setApiError('Match request failed: ' + e.message)
    } finally {
      setMatchLoading(false)
    }
  }

  async function loadGroups() {
    setGroupsLoading(true)
    try {
      const res = await fetch(`${API_BASE}/fairsplit/profiles/${DEMO_PROFILE_ID}/groups`)
      const data = await res.json()
      setGroups(data.groups || [])
    } catch (e) {
      // fallback: empty
      setGroups([])
    } finally {
      setGroupsLoading(false)
    }
  }

  async function handleAcceptInvitation(groupId, memberId) {
    // In full product: accept by invitation token; here just refresh
    await loadGroups()
  }

  async function loadOffers(params = {}) {
    try {
      const qs = new URLSearchParams()
      if (params.neighborhood) qs.set('neighborhood', params.neighborhood)
      const res = await fetch(`${API_BASE}/fairsplit/offers?${qs}`)
      const data = await res.json()
      setOffers(Array.isArray(data) ? data : [])
    } catch {
      setOffers([])
    }
  }

  function handleSearch(e) {
    e.preventDefault()
    loadApartments({ neighborhood: searchNhd, bedrooms: searchBeds })
    loadOffers({ neighborhood: searchNhd })
  }

  return (
    <div className="fs-app">
      {/* Header */}
      <header className="fs-header">
        <div className="fs-header__inner">
          <div className="fs-header__brand">
            <span className="fs-header__logo">🏠</span>
            <span className="fs-header__name">FairSplit</span>
            <span className="fs-header__tagline">AI-powered shared housing</span>
          </div>
          <nav className="fs-nav">
            {TABS.map(t => (
              <button
                key={t.id}
                className={`fs-nav__tab${tab === t.id ? ' fs-nav__tab--active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Error banner */}
      {apiError && (
        <div className="fs-error-banner">
          {apiError}
          <button onClick={() => setApiError('')} className="fs-error-banner__close">✕</button>
        </div>
      )}

      {/* Main content */}
      <main className="fs-main">

        {/* DISCOVER TAB */}
        {tab === 'discover' && (
          <div className="fs-section">
            <div className="fs-section__header">
              <h2 className="fs-section__title">Find Your Next Home</h2>
              <p className="fs-section__sub">Browse shared apartments and find compatible roommates.</p>
            </div>

            {/* Search bar */}
            <form className="search-bar" onSubmit={handleSearch}>
              <input
                type="text"
                placeholder="Neighborhood (e.g. Brooklyn)"
                value={searchNhd}
                onChange={e => setSearchNhd(e.target.value)}
                className="search-bar__input"
              />
              <select
                value={searchBeds}
                onChange={e => setSearchBeds(e.target.value)}
                className="search-bar__select"
              >
                <option value="">Any bedrooms</option>
                {[1,2,3,4].map(n => (
                  <option key={n} value={n}>{n} BR</option>
                ))}
              </select>
              <button type="submit" className="btn btn--primary">Search</button>
              {(searchNhd || searchBeds) && (
                <button
                  type="button"
                  className="btn btn--outline"
                  onClick={() => { setSearchNhd(''); setSearchBeds(''); loadApartments(); loadOffers() }}
                >
                  Clear
                </button>
              )}
            </form>

            {/* Apartment grid */}
            {aptsLoading ? (
              <div className="loading-grid">
                {[1,2,3].map(i => <div key={i} className="apt-card apt-card--skeleton" />)}
              </div>
            ) : apartments.length === 0 ? (
              <div className="empty-state">No apartments found. Try adjusting your search.</div>
            ) : (
              <div className="apt-grid">
                {apartments.map(apt => (
                  <div key={apt.id} className="apt-grid__item">
                    <ApartmentCard
                      apartment={apt}
                      selected={selectedApt?.id === apt.id}
                      onSelect={setSelectedApt}
                    />
                    <button
                      className="btn btn--primary btn--full"
                      onClick={() => findRoommates(apt)}
                    >
                      Find Roommates
                    </button>
                  </div>
                ))}
              </div>
            )}
            {/* Room offers */}
            {offers.length > 0 && (
              <div className="fs-section__offers">
                <h3 className="fs-section__subtitle">Room Offers</h3>
                <p className="fs-section__sub">People who already have a place and need a roommate.</p>
                <div className="apt-grid">
                  {offers.map(offer => (
                    <div key={offer.id} className="apt-grid__item">
                      <OfferCard offer={offer} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* VOICE AGENT TAB */}
        {tab === 'agent' && (
          <div className="fs-section">
            <div className="fs-section__header">
              <h2 className="fs-section__title">FairSplit AI Agent</h2>
              <p className="fs-section__sub">
                Talk to FairSplit — find apartments, match roommates, create groups.
                Powered by Gemini Live.
              </p>
            </div>
            <VoiceAgent />
          </div>
        )}

        {/* MATCHES TAB */}
        {tab === 'matches' && (
          <div className="fs-section">
            <div className="fs-section__header">
              <h2 className="fs-section__title">Compatible Roommates</h2>
              <p className="fs-section__sub">
                AI-ranked groups based on budget compatibility, move-in windows, and lifestyle.
              </p>
            </div>
            <RoommateMatches matchResult={matchResult} loading={matchLoading} />
          </div>
        )}

        {/* MY GROUPS TAB */}
        {tab === 'groups' && (
          <div className="fs-section">
            <div className="fs-section__header">
              <h2 className="fs-section__title">My Groups</h2>
              <p className="fs-section__sub">Track your roommate groups and pending invitations.</p>
            </div>
            <MyGroups
              groups={groups}
              loading={groupsLoading}
              onAccept={handleAcceptInvitation}
            />
          </div>
        )}

      </main>

      {/* Hackathon footer */}
      <footer className="fs-footer">
        <span>FairSplit &mdash; The New Agentic Economy Hackathon &middot; Betaworks NYC, October 10 2026</span>
        <span>Supported by Google DeepMind &middot; Forever 22</span>
      </footer>
    </div>
  )
}
