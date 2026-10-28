import { useEffect, useMemo, useRef, useState } from 'react'
import Map, { Layer, Marker, NavigationControl, Popup, Source } from 'react-map-gl/maplibre'
import { setWorkerUrl } from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import './maplibre.css'
import {
  ArrowDownLeft, ArrowLeft, ArrowUpRight, Bookmark, Check,
  Compass, Leaf, LoaderCircle, LocateFixed, LogOut, MapPin, Menu, Plus,
  Sparkles, X,
} from 'lucide-react'

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? '/api' : 'http://127.0.0.1:8000')
const DEFAULT_CENTER = [49.0069, 8.4037]
const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json'
const FOCUS_AREAS = [
  { value: 'all', label: 'Everything', prompt: 'places' },
  { value: 'cafe', label: 'Cafés', prompt: 'cafes' },
  { value: 'restaurant', label: 'Restaurants', prompt: 'restaurants' },
  { value: 'playground', label: 'Playgrounds', prompt: 'playgrounds' },
  { value: 'school', label: 'Schools & universities', prompt: 'schools or universities' },
  { value: 'library', label: 'Libraries', prompt: 'libraries' },
  { value: 'healthcare', label: 'Healthcare', prompt: 'hospitals, clinics, pharmacies, or doctors' },
  { value: 'transport', label: 'Transport', prompt: 'train stations, bus stops, or transit stations' },
  { value: 'sports', label: 'Sports', prompt: 'sports centres, swimming pools, or sports grounds' },
  { value: 'services', label: 'Public services', prompt: 'banks, post offices, or public toilets' },
  { value: 'stay', label: 'Places to stay', prompt: 'hotels, hostels, or guest houses' },
  { value: 'fishing', label: 'Fishing areas', prompt: 'fishing areas' },
  { value: 'museum', label: 'Museums', prompt: 'museums' },
  { value: 'attraction', label: 'Attractions', prompt: 'attractions' },
  { value: 'park', label: 'Parks', prompt: 'parks' },
  { value: 'water', label: 'Waterfronts', prompt: 'waterfronts and water features' },
  { value: 'shopping', label: 'Shopping', prompt: 'shopping places' },
]

// Tell Vite to bundle MapLibre's Web Worker for local development and production builds.
setWorkerUrl(maplibreWorkerUrl)

async function api(path, options = {}, token = '') {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${response.status})`)
  }
  if (response.status === 204) return null
  return response.json()
}

function PlaceMap({ places, route, userLocation, selectedOrigin }) {
  const mapRef = useRef(null)
  const [selectedPlace, setSelectedPlace] = useState(null)

  useEffect(() => {
    const map = mapRef.current?.getMap()
    if (!map) return undefined

    const fitResults = () => {
      const points = route?.geometry?.length > 1
        ? route.geometry
        : places.map((place) => [place.lat, place.lon])
      if (points.length === 1) {
        map.flyTo({ center: [points[0][1], points[0][0]], zoom: 14, duration: 700 })
      } else if (points.length > 1) {
        const longitudes = points.map((point) => point[1])
        const latitudes = points.map((point) => point[0])
        map.fitBounds(
          [[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]],
          { padding: 70, maxZoom: 14, duration: 700 },
        )
      } else {
        const focus = userLocation || route?.origin || selectedOrigin
        if (focus) map.flyTo({ center: [focus.lon, focus.lat], zoom: 14, duration: 700 })
      }
    }

    if (map.isStyleLoaded()) fitResults()
    else map.once('load', fitResults)
    setSelectedPlace(null)
    return () => map.off('load', fitResults)
  }, [places, route, selectedOrigin, userLocation])

  const routeOrigin = route?.origin || selectedOrigin
  const userIsStart = userLocation && routeOrigin
    && Math.abs(userLocation.lat - routeOrigin.lat) < 0.00005
    && Math.abs(userLocation.lon - routeOrigin.lon) < 0.00005

  const routeFeature = route?.geometry?.length > 1 ? {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'LineString',
      coordinates: route.geometry.map(([latitude, longitude]) => [longitude, latitude]),
    },
  } : null

  return (
    <div className="map-shell">
      <Map
        ref={mapRef}
        className="map"
        initialViewState={{ longitude: DEFAULT_CENTER[1], latitude: DEFAULT_CENTER[0], zoom: 12 }}
        mapStyle={MAP_STYLE}
      >
        <NavigationControl position="top-right" showCompass={false} />
        {routeFeature && <Source id="suggested-route" type="geojson" data={routeFeature}>
          <Layer id="route-line" type="line" layout={{ 'line-join': 'round', 'line-cap': 'round' }} paint={{ 'line-color': '#52765b', 'line-width': 4, 'line-opacity': 0.76, 'line-dasharray': [2, 2] }} />
        </Source>}
        {routeOrigin && <Marker longitude={routeOrigin.lon} latitude={routeOrigin.lat} anchor="center">
          <span className={userIsStart ? 'map-user-marker' : 'map-origin-marker'} role="img" aria-label={`Starting point: ${routeOrigin.label || 'selected location'}`} title={`Starting point: ${routeOrigin.label || 'selected location'}`} />
        </Marker>}
        {userLocation && !userIsStart && <Marker longitude={userLocation.lon} latitude={userLocation.lat} anchor="center">
          <span className="map-user-marker" role="img" aria-label="Your current location" title="Your current location" />
        </Marker>}
        {places.map((place) => (
          <Marker key={place.id} longitude={place.lon} latitude={place.lat} anchor="bottom">
            <button className="map-stop-marker" onClick={() => setSelectedPlace(place)} aria-label={`Show stop ${place.route_order}: ${place.name}`}>
              {place.route_order}
            </button>
          </Marker>
        ))}
        {selectedPlace && <Popup
          longitude={selectedPlace.lon}
          latitude={selectedPlace.lat}
          anchor="bottom"
          offset={30}
          onClose={() => setSelectedPlace(null)}
        >
          <strong>{selectedPlace.name}</strong><br />{selectedPlace.place_type}<br />
          Stop {selectedPlace.route_order} · {selectedPlace.leg_distance_km?.toFixed(1)} km {route?.mode === 'walking' ? 'walking' : 'straight-line estimate'}
        </Popup>}
      </Map>
      <div className="map-label"><span className="map-pulse" /> {userLocation ? 'Your current location' : 'Karlsruhe & surroundings'}</div>
    </div>
  )
}

function AuthDialog({ mode, setMode, onClose, onSuccess }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api(`/auth/${mode}`, {
        method: 'POST', body: JSON.stringify({ email, password }),
      })
      onSuccess(result)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="auth-card" role="dialog" aria-modal="true" aria-labelledby="auth-title">
        <button className="icon-button modal-close" onClick={onClose} aria-label="Close"><X size={19} /></button>
        <div className="brand-mark small"><Compass size={20} /></div>
        <span className="eyebrow">YOUR KARLSRUHE GUIDE</span>
        <h2 id="auth-title">{mode === 'register' ? 'Keep good places close.' : 'Welcome back.'}</h2>
        <p className="muted">{mode === 'register' ? 'Create an account to save places into trips.' : 'Sign in to pick up where your next city plan begins.'}</p>
        <form onSubmit={submit} className="auth-form">
          <label>Email address<input autoFocus type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com" /></label>
          <label>Password<input type="password" minLength={mode === 'register' ? 8 : 1} value={password} onChange={(e) => setPassword(e.target.value)} required placeholder={mode === 'register' ? 'At least 8 characters' : 'Your password'} /></label>
          {error && <p className="form-error">{error}</p>}
          <button className="primary-button full" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : null}{mode === 'register' ? 'Create account' : 'Sign in'}<ArrowUpRight size={17} /></button>
        </form>
        <p className="switch-auth">{mode === 'register' ? 'Already have an account?' : 'New around here?'} <button onClick={() => { setError(''); setMode(mode === 'register' ? 'login' : 'register') }}>{mode === 'register' ? 'Sign in' : 'Create an account'}</button></p>
      </section>
    </div>
  )
}

function listedValue(tags, ...keys) {
  for (const key of keys) {
    const value = tags?.[key]
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim()
  }
  return ''
}

function PlaceCard({ place, index, onSave, saved, routeMode }) {
  const tags = place.tags || {}
  const hours = listedValue(tags, 'opening_hours')
  const wheelchair = listedValue(tags, 'wheelchair')
  const outdoor = listedValue(tags, 'outdoor_seating')
  const entrance = listedValue(tags, 'entrance', 'addr:entrance')
  const website = listedValue(tags, 'website', 'contact:website')
  const websiteUrl = website && (/^https?:\/\//i.test(website) ? website : `https://${website}`)
  const verificationLabel = place.verification_status === 'confirmed_live_osm'
    ? 'OSM record checked just now · opening status unknown'
    : place.verification_status === 'osm_snapshot'
      ? 'Local OSM snapshot · not checked live · current status unknown'
      : 'Verification status unavailable'

  return (
    <article className="place-card" style={{ '--card-order': index }}>
      <div className="place-card-top">
        <span className="place-kind"><MapPin size={13} />{place.place_type}</span>
        <button className={`save-button ${saved ? 'saved' : ''}`} onClick={() => onSave(place)} aria-label={saved ? 'Saved to a trip' : 'Save to a trip'} title={saved ? 'Saved' : 'Save place'}>
          {saved ? <Check size={16} /> : <Bookmark size={16} />}
        </button>
      </div>
      <h3>{place.name}</h3>
      <div className="place-distance-grid">
        <div><span>From start · straight line</span><strong>{place.distance_km?.toFixed(1) ?? '—'} km</strong></div>
        <div><span>{routeMode === 'walking' ? 'Walk from previous stop' : 'Map estimate from previous stop'}</span><strong>{place.leg_distance_km?.toFixed(1) ?? '—'} km{routeMode === 'walking' && place.leg_duration_minutes != null ? ` · ${Math.round(place.leg_duration_minutes)} min` : ''}</strong></div>
      </div>
      <dl className="place-facts">
        <div><dt>OSM-listed hours</dt><dd>{hours || 'Not listed'}</dd></div>
        <div><dt>Wheelchair access</dt><dd>{wheelchair || 'Not listed'}</dd></div>
        <div><dt>Outdoor seating</dt><dd>{outdoor || 'Not listed'}</dd></div>
        <div><dt>Entrance tag</dt><dd>{entrance && place.source_url ? <a href={`${place.source_url}#map=19/${place.lat}/${place.lon}`} target="_blank" rel="noreferrer">View tagged OSM point <ArrowUpRight size={11} /></a> : entrance || 'Not listed'}</dd></div>
        <div><dt>Website</dt><dd>{websiteUrl ? <a href={websiteUrl} target="_blank" rel="noreferrer">Open website <ArrowUpRight size={11} /></a> : 'Not listed'}</dd></div>
      </dl>
      <div className={`place-verification ${place.verification_status === 'confirmed_live_osm' ? 'verified' : 'snapshot'}`}><span>{verificationLabel}</span></div>
      {place.source_url && <a className="source-link" href={place.source_url} target="_blank" rel="noreferrer">Open OSM record <ArrowUpRight size={12} /></a>}
    </article>
  )
}

function TripsView({ trips, setTrips, token, onBack, onError }) {
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)

  async function createTrip(event) {
    event.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      const trip = await api('/trips', { method: 'POST', body: JSON.stringify({ name: name.trim() }) }, token)
      setTrips((current) => [...current, trip])
      setName('')
    } catch (err) { onError(err.message) }
    finally { setCreating(false) }
  }

  async function removeTrip(id) {
    try {
      await api(`/trips/${id}`, { method: 'DELETE' }, token)
      setTrips((current) => current.filter((trip) => trip.id !== id))
    } catch (err) { onError(err.message) }
  }

  async function removePlace(trip, place) {
    try {
      await api(`/trips/${trip.id}/places/${place.id}`, { method: 'DELETE' }, token)
      setTrips((current) => current.map((item) => item.id === trip.id ? { ...item, places: item.places.filter((saved) => saved.id !== place.id) } : item))
    } catch (err) { onError(err.message) }
  }

  return (
    <main className="trips-page">
      <button className="back-link" onClick={onBack}><ArrowLeft size={16} /> Back to discovery</button>
      <div className="trips-heading"><div><span className="eyebrow">YOUR COLLECTION</span><h1>Trips worth taking.</h1><p>Gather your favourite places into little plans for later.</p></div><div className="trip-count"><strong>{trips.length.toString().padStart(2, '0')}</strong><span>saved trips</span></div></div>
      <form className="new-trip-form" onSubmit={createTrip}><Plus size={18} /><input aria-label="New trip name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name a new trip…" maxLength={120} /><button disabled={!name.trim() || creating}>{creating ? 'Creating…' : 'Create trip'}<ArrowUpRight size={15} /></button></form>
      {trips.length === 0 ? <div className="empty-trips"><div className="empty-icon"><Bookmark size={22} /></div><h2>Your first collection starts here.</h2><p>Save a place from discovery, or create a trip above.</p></div> : (
        <div className="trip-grid">{trips.map((trip, index) => (
          <section className="trip-card" key={trip.id} style={{ '--card-order': index }}>
            <div className="trip-card-heading"><div className="trip-card-icon"><Compass size={18} /></div><button className="text-danger" onClick={() => removeTrip(trip.id)}>Delete trip</button></div>
            <h2>{trip.name}</h2><p className="trip-meta">{trip.places.length} {trip.places.length === 1 ? 'place' : 'places'} · Created {new Date(trip.created_at).toLocaleDateString()}</p>
            {trip.places.length ? <div className="saved-list">{trip.places.map((place) => <div className="saved-place" key={place.id}><div><strong>{place.name}</strong><span>{place.place_type}</span></div><button className="icon-button" aria-label={`Remove ${place.name}`} onClick={() => removePlace(trip, place)}><X size={15} /></button></div>)}</div> : <div className="trip-empty-note">Places you save will find a home here.</div>}
          </section>
        ))}</div>
      )}
    </main>
  )
}

export default function App() {
  const [question, setQuestion] = useState('')
  const [origin, setOrigin] = useState('49.0069, 8.4037')
  const [selectedOrigin, setSelectedOrigin] = useState({ lat: DEFAULT_CENTER[0], lon: DEFAULT_CENTER[1], label: 'Karlsruhe city centre (default)' })
  const [userLocation, setUserLocation] = useState(null)
  const [locating, setLocating] = useState(false)
  const [focusArea, setFocusArea] = useState('all')
  const [answer, setAnswer] = useState('')
  const [places, setPlaces] = useState([])
  const [route, setRoute] = useState(null)
  const [verification, setVerification] = useState(null)
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const [page, setPage] = useState('discover')
  const [authMode, setAuthMode] = useState('')
  const [mobileMenu, setMobileMenu] = useState(false)
  const [token, setToken] = useState(() => localStorage.getItem('khg-token') || '')
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('khg-user') || 'null') } catch { return null }
  })
  const [trips, setTrips] = useState([])
  const [savedIds, setSavedIds] = useState(() => new Set())
  const examples = useMemo(() => [
    { icon: '◌', text: 'Find sushi or a restaurant near me', detail: 'Food and cafes around your starting point' },
    { icon: '⌁', text: 'Plan a fun afternoon with two kids', detail: 'Attractions, parks, and playgrounds' },
    { icon: '▤', text: 'Where can I shop for a washing machine?', detail: 'Appliance shops and shopping centres' },
    { icon: '☕', text: 'A relaxed cafe for a coffee break', detail: 'Nearby cafes, ranked for a short visit' },
    { icon: '≈', text: 'A park and a peaceful place by water', detail: 'A small multi-stop route outdoors' },
  ], [])

  useEffect(() => {
    if (!token) { setTrips([]); return }
    api('/trips', {}, token).then((items) => {
      setTrips(items)
      setSavedIds(new Set(items.flatMap((trip) => trip.places.map((place) => place.place_id))))
    }).catch(() => signOut())
  }, [token])

  function signOut() {
    localStorage.removeItem('khg-token')
    localStorage.removeItem('khg-user')
    setToken(''); setUser(null); setTrips([]); setSavedIds(new Set()); setPage('discover')
  }

  function handleAuth(result) {
    localStorage.setItem('khg-token', result.access_token)
    localStorage.setItem('khg-user', JSON.stringify(result.user))
    setToken(result.access_token); setUser(result.user); setAuthMode('')
  }

  async function search(text = question) {
    const focus = FOCUS_AREAS.find((area) => area.value === focusArea)
    const query = text.trim() || (focusArea !== 'all' ? `Find ${focus.prompt} near my starting point` : '')
    if ((query.length < 3 && focusArea === 'all') || loading) return
    setQuestion(query); setLoading(true); setNotice(''); setAnswer(''); setPlaces([]); setRoute(null); setVerification(null)
    try {
      const result = await api('/ask', { method: 'POST', body: JSON.stringify({
        question: query,
        limit: 5,
        origin: origin.trim() || null,
        category: focusArea === 'all' ? null : focusArea,
      }) })
      setAnswer(result.answer); setPlaces(result.places); setRoute(result.route); setVerification(result.verification)
      if (result.model_status === 'ollama-unavailable') setNotice('Your place matches are ready; the recommendation model is temporarily offline.')
      if (result.model_status === 'no-results') setNotice(result.verification?.mode === 'osm_unavailable'
        ? 'Live OpenStreetMap verification is temporarily unavailable. No unchecked places were shown.'
        : 'No matching live OpenStreetMap places were found. Try another description or focus area.')
      if (result.model_status === 'records-only') setNotice('These map records list place names and types, but do not include details about their individual features.')
    } catch (err) {
      if (err.message.includes('collection') || err.message.includes('index') || err.message.includes('places first')) {
        setNotice('Place search is not ready yet. Start Milvus, ingest the OSM places, and build the vector index first.')
      } else setNotice(err.message)
    } finally { setLoading(false) }
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      setNotice('This browser does not provide location access. Enter a Karlsruhe place name or coordinates instead.')
      return
    }
    setLocating(true)
    setNotice('')
    navigator.geolocation.getCurrentPosition((position) => {
      const { latitude, longitude } = position.coords
      const location = { lat: latitude, lon: longitude, label: 'Your current location' }
      setUserLocation(location)
      setSelectedOrigin(location)
      setOrigin(`${latitude.toFixed(6)}, ${longitude.toFixed(6)}`)
      setAnswer(''); setPlaces([]); setRoute(null); setVerification(null)
      setLocating(false)
      setNotice('Your location is shown on the map. The indexed place data currently covers Karlsruhe only.')
    }, (error) => {
      const message = error.code === error.PERMISSION_DENIED
        ? 'Location permission was denied. You can enter a Karlsruhe starting point instead.'
        : 'Could not read your current location. Try again or enter a starting point.'
      setNotice(message)
      setLocating(false)
    }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 })
  }

  function changeOrigin(value) {
    setOrigin(value)
    setUserLocation(null)
    setAnswer(''); setPlaces([]); setRoute(null); setVerification(null)
    const match = value.match(/^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$/)
    setSelectedOrigin(match ? { lat: Number(match[1]), lon: Number(match[2]), label: 'Selected starting point' } : null)
  }

  async function savePlace(place) {
    if (!token) { setAuthMode('login'); return }
    try {
      let currentTrips = trips
      if (currentTrips.length === 0) {
        const created = await api('/trips', { method: 'POST', body: JSON.stringify({ name: 'Karlsruhe ideas' }) }, token)
        currentTrips = [created]
        setTrips(currentTrips)
      }
      const trip = currentTrips[0]
      const updated = await api(`/trips/${trip.id}/places`, {
        method: 'POST',
        body: JSON.stringify({
          place_id: place.id, name: place.name, place_type: place.place_type,
          lat: place.lat, lon: place.lon, description: place.description, tags: place.tags,
        }),
      }, token)
      setTrips((items) => items.map((item) => item.id === updated.id ? updated : item))
      setSavedIds((ids) => new Set([...ids, place.id]))
    } catch (err) { setNotice(err.message) }
  }

  const signOutLink = user ? <><span className="user-email">{user.email}</span><button className="nav-text signout" onClick={signOut}><LogOut size={15} /> Sign out</button></> : <button className="nav-text" onClick={() => setAuthMode('login')}>Sign in</button>

  return (
    <div className="app-shell">
        <header className="topbar">
        <button className="brand" onClick={() => setPage('discover')}><span className="brand-mark"><Compass size={21} /></span><span className="brand-copy">City Compass<span>KARLSRUHE, GERMANY</span></span></button>
        <nav className={`top-nav ${mobileMenu ? 'open' : ''}`}>
          <button className={`nav-link ${page === 'discover' ? 'active' : ''}`} onClick={() => { setPage('discover'); setMobileMenu(false) }}>Discover</button>
          {user && <button className={`nav-link ${page === 'trips' ? 'active' : ''}`} onClick={() => { setPage('trips'); setMobileMenu(false) }}>My trips <span className="nav-count">{trips.length}</span></button>}
          <span className="nav-divider" />{signOutLink}
        </nav>
        <button className="icon-button menu-toggle" onClick={() => setMobileMenu(!mobileMenu)} aria-label="Toggle menu">{mobileMenu ? <X size={20} /> : <Menu size={20} />}</button>
      </header>

      {page === 'trips' && user ? <TripsView trips={trips} setTrips={setTrips} token={token} onBack={() => setPage('discover')} onError={setNotice} /> : (
        <main className="discover-layout">
          <section className="discovery-panel">
            <div className="hero-intro"><span className="eyebrow"><span className="eyebrow-dot" /> FOOD · CULTURE · SHOPPING · OUTDOORS</span><h1>Find your<br /><em>next stop.</em></h1><p className="hero-description">Tell us what you’re looking for. We’ll search local map records, explain the evidence, and suggest a nearby order to explore.</p></div>
            <form className="search-form" onSubmit={(event) => { event.preventDefault(); search() }}>
              <label className="sr-only" htmlFor="outing-search">What are you looking for in Karlsruhe?</label>
              <textarea id="outing-search" rows="3" maxLength="1000" placeholder="A cafe, a museum, a shop for a washing machine…" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); search() } }} />
              <div className="origin-field"><MapPin size={14} /><label htmlFor="outing-origin">Start from</label><input id="outing-origin" maxLength={255} value={origin} onChange={(event) => changeOrigin(event.target.value)} placeholder="Place name or 49.0093, 8.4020" /><button type="button" className="location-button" onClick={useCurrentLocation} disabled={locating}>{locating ? <LoaderCircle className="spin" size={13} /> : <LocateFixed size={13} />}<span>{locating ? 'Locating…' : 'Use my location'}</span></button></div>
              <fieldset className="focus-area"><legend>Focus area</legend><div className="focus-options">{FOCUS_AREAS.map((area) => <button key={area.value} type="button" className={`focus-chip ${focusArea === area.value ? 'active' : ''}`} aria-pressed={focusArea === area.value} onClick={() => setFocusArea(area.value)}>{area.label}</button>)}</div></fieldset>
              <div className="search-form-bottom"><span><Sparkles size={14} /> A little guidance, grounded in local places</span><button className="search-button" disabled={loading || (question.trim().length < 3 && focusArea === 'all')} aria-label="Search places">{loading ? <LoaderCircle className="spin" size={18} /> : <ArrowUpRight size={19} />}</button></div>
            </form>

            {!answer && !loading && places.length === 0 && <div className="examples"><div className="section-kicker">A FEW PLACES TO START</div>{examples.map((example) => <button className="example-row" key={example.text} onClick={() => search(example.text)}><span className="example-icon">{example.icon}</span><span><strong>{example.text}</strong><small>{example.detail}</small></span><ArrowUpRight size={16} className="example-arrow" /></button>)}</div>}
            {loading && <div className="loading-state"><span className="loading-orbit"><Leaf size={20} /></span><div><strong>Looking around for you…</strong><span>Finding places that fit your kind of day.</span></div></div>}
            {notice && <div className="notice"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss"><X size={15} /></button></div>}
            {answer && <section className="answer-panel">
              <div className="answer-heading"><span className="answer-spark"><Sparkles size={15} /></span><span>GROUNDED KARLSRUHE RECOMMENDATION</span><button className="icon-button answer-clear" onClick={() => { setAnswer(''); setPlaces([]); setRoute(null); setVerification(null); setNotice('') }} aria-label="Clear search"><X size={16} /></button></div>
              <p className="answer-copy">{answer}</p>
              {route && <div className="route-summary">
                <span><MapPin size={14} /> {route.origin.label}</span>
                <strong>{route.distance_km.toFixed(1)} km {route.mode === 'walking' ? 'walking itinerary' : 'straight-line itinerary estimate'}</strong>
                {route.duration_minutes != null && <small>About {Math.round(route.duration_minutes)} minutes on mapped foot routes.</small>}
                <small>{route.disclaimer}</small>
              </div>}
              {verification && <div className={`verification-summary ${verification.mode}`} role="status">
                <strong>{verification.mode === 'osm_snapshot' ? 'Local OSM snapshot results' : verification.mode === 'osm_unavailable' ? 'Live OpenStreetMap check unavailable' : verification.mode === 'osm_partial' ? 'Partial OpenStreetMap check' : 'Live OpenStreetMap check'}</strong>
                <span>{verification.message}</span>
              </div>}
              <div className="results-heading">
                <span>{places.length} {places.length === 1 ? 'place' : 'places'} to compare</span>
                <span className="grounded-note">{verification?.mode === 'osm_snapshot' ? 'Snapshot · not live verified' : verification?.mode === 'osm_live' || verification?.mode === 'osm_partial' ? 'OSM checked now · opening status unknown' : 'No live-verified results'}</span>
              </div>
              <div className="place-list">{places.map((place, index) => <PlaceCard key={place.id} place={place} index={index} onSave={savePlace} saved={savedIds.has(place.id)} routeMode={route?.mode} />)}</div>
            </section>}
            <footer className="panel-footer"><span><span className="footer-dot" /> Local places, thoughtfully connected</span><nav aria-label="Project policies"><a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a></nav><a href="https://www.openstreetmap.org/" target="_blank" rel="noreferrer">OpenStreetMap <ArrowUpRight size={12} /></a></footer>
          </section>
          <section className="map-panel" aria-label="Map of your starting point, suggested Karlsruhe places, and route"><div className="map-ornament"><span>49°00′N</span><i /><span>08°24′E</span></div><PlaceMap places={places} route={route} userLocation={userLocation} selectedOrigin={selectedOrigin} /><div className="map-caption"><span className="caption-icon"><MapPin size={16} /></span><span><strong>{places.length ? 'Your Karlsruhe route idea' : userLocation ? 'Your current location' : 'A familiar place, seen differently'}</strong><small>{places.length ? route?.mode === 'walking' ? 'Mapped walking path · estimated time' : 'Numbered stops · straight-line estimate' : userLocation ? 'Blue dot marks your device location' : 'Search to see local places on the map'}</small></span><span className="map-caption-arrow"><ArrowDownLeft size={17} /></span></div></section>
        </main>
      )}
      {authMode && <AuthDialog mode={authMode} setMode={setAuthMode} onClose={() => setAuthMode('')} onSuccess={handleAuth} />}
      {notice && page === 'trips' && <div className="toast" role="status">{notice}<button onClick={() => setNotice('')} aria-label="Dismiss"><X size={15} /></button></div>}
    </div>
  )
}
