import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, ArrowLeftRight, CalendarDays, ChevronDown, Clock3, Download, Info, MapPin, Search, TrainFront, Users, WalletCards, AlertTriangle } from 'lucide-react'

const API = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const api = (path) => `${API}${path}`

function fmtDate(iso) {
  return new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(`${iso}T00:00:00`))
}
function fmtTime(iso) {
  return new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso))
}
function optionLabel(s) { return `${s.name} (${s.code})` }

function JourneyCard({ journey, pax }) {
  return <article className="journey-card">
    <div className="journey-head">
      <div>
        <div className="badges">{journey.badges.map(b => <span className="badge" key={b}>{b}</span>)}</div>
        <h3>{journey.route}</h3>
        <p className="muted">{journey.legs.length === 1 ? 'Direct journey' : `${journey.transfers} change${journey.transfers > 1 ? 's' : ''}`} · {journey.duration}</p>
      </div>
      <div className="price"><strong>₹{journey.farePerPerson.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</strong><span>/ person</span><small>₹{journey.totalFare.toLocaleString('en-IN', { maximumFractionDigits: 0 })} total</small></div>
    </div>
    <div className="journey-stats">
      <div><Clock3 size={17}/><span>{journey.duration}</span><small>journey time</small></div>
      <div><TrainFront size={17}/><span>{journey.transfers}</span><small>changes</small></div>
      <div><Users size={17}/><span>{journey.seats}</span><small>scarcest seats</small></div>
      <div><WalletCards size={17}/><span>{journey.legs.length}</span><small>ticket leg{journey.legs.length > 1 ? 's' : ''}</small></div>
    </div>
    <div className="timeline">
      {journey.legs.map((leg, i) => <div className="leg" key={`${leg.trainId}-${leg.fromCode}-${i}`}>
        <div className="dot" />
        <div className="leg-main">
          <div className="leg-time"><strong>{fmtTime(leg.departure)}</strong><span>{leg.fromName}</span></div>
          <div className="line"><span>{leg.trainNumber} · {leg.trainName}</span><b>{leg.class}</b></div>
          <div className="leg-time"><strong>{fmtTime(leg.arrival)}</strong><span>{leg.toName}</span></div>
        </div>
        <div className="leg-meta">₹{leg.fare.toLocaleString('en-IN', { maximumFractionDigits: 0 })} · {leg.seats} seats</div>
      </div>)}
    </div>
    {journey.riskNotes.length > 0 && <div className="warnings">{journey.riskNotes.map(n => <div key={n}><AlertTriangle size={15}/>{n}</div>)}</div>}
  </article>
}

function App() {
  const [meta, setMeta] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(null)
  const [src, setSrc] = useState('')
  const [dst, setDst] = useState('')
  const [day, setDay] = useState('')
  const [cls, setCls] = useState('3A')
  const [pax, setPax] = useState(1)
  const [connections, setConnections] = useState(2)
  const [minTransfer, setMinTransfer] = useState(60)
  const [maxLayover, setMaxLayover] = useState(12)
  const [maxHours, setMaxHours] = useState(36)
  const [sortBy, setSortBy] = useState('fastest')
  const [alwaysAlt, setAlwaysAlt] = useState(false)

  useEffect(() => {
    fetch(api('/api/meta')).then(r => r.ok ? r.json() : Promise.reject(new Error('Could not load API metadata.')))
      .then(m => {
        setMeta(m)
        const preferredSrc = m.stations.find(s => s.code === 'VSKP')?.code || m.stations[0]?.code || ''
        const preferredDst = m.stations.find(s => s.code === 'PGT')?.code || m.stations[m.stations.length - 1]?.code || ''
        setSrc(preferredSrc); setDst(preferredDst); setCls(m.classes.includes('3A') ? '3A' : m.classes[0] || '3A')
        setDay(m.dateRange?.from || '')
      })
      .catch(e => setError(e.message))
  }, [])

  const stationMap = useMemo(() => Object.fromEntries((meta?.stations || []).map(s => [s.code, s])), [meta])
  const swap = () => { setSrc(dst); setDst(src) }

  async function search() {
    if (!src || !dst || src === dst) { setError('Choose different origin and destination stations.'); return }
    setLoading(true); setError('')
    const params = new URLSearchParams({ src, dst, day, cls, passengers: pax, connections, min_transfer: minTransfer, max_layover_hours: maxLayover, max_hours: maxHours, sort_by: sortBy, always_alt: alwaysAlt })
    try {
      const r = await fetch(api(`/api/search?${params}`))
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || 'Search failed.')
      setResults(data)
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }

  function download() {
    const params = new URLSearchParams({ src, dst, day, cls, passengers: pax, connections, min_transfer: minTransfer, max_layover_hours: maxLayover, max_hours: maxHours, sort_by: sortBy })
    window.open(api(`/api/export.csv?${params}`), '_blank')
  }

  if (!meta && !error) return <div className="loading-screen"><TrainFront size={42}/><h2>Loading RailRoute…</h2></div>

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark"><TrainFront size={22}/></span><div><strong>RailRoute</strong><span>Alternate</span></div></div><div className="prototype-pill"><span/> Prototype · Sample data</div></header>
    <main>
      <section className="hero"><div className="eyebrow">SMART CONNECTION FINDER</div><h1>Find a way there when the<br/><em>direct train is full.</em></h1><p>Search alternative connections, split-ticket journeys, and practical routes using the timetable engine.</p></section>
      <section className="search-panel">
        <div className="route-row">
          <label className="field"><span>FROM</span><div className="select-wrap"><MapPin size={17}/><select value={src} onChange={e => setSrc(e.target.value)}>{meta?.stations.map(s => <option key={s.code} value={s.code}>{optionLabel(s)}</option>)}</select></div></label>
          <button className="swap" onClick={swap} aria-label="Swap stations"><ArrowLeftRight size={18}/></button>
          <label className="field"><span>TO</span><div className="select-wrap"><MapPin size={17}/><select value={dst} onChange={e => setDst(e.target.value)}>{meta?.stations.map(s => <option key={s.code} value={s.code}>{optionLabel(s)}</option>)}</select></div></label>
          <label className="field date-field"><span>DEPARTURE</span><div className="select-wrap"><CalendarDays size={17}/><input type="date" value={day} min={meta?.dateRange?.from} max={meta?.dateRange?.to} onChange={e => setDay(e.target.value)}/></div></label>
        </div>
        <div className="options-row">
          <label className="compact"><span>CLASS</span><select value={cls} onChange={e => setCls(e.target.value)}>{meta?.classes.map(c => <option key={c}>{c}</option>)}</select></label>
          <label className="compact"><span>PASSENGERS</span><select value={pax} onChange={e => setPax(Number(e.target.value))}>{[1,2,3,4,5,6].map(n => <option key={n}>{n}</option>)}</select></label>
          <label className="compact"><span>CONNECTIONS</span><select value={connections} onChange={e => setConnections(Number(e.target.value))}><option value={1}>Direct trains only</option><option value={2}>Up to 1 change</option><option value={3}>Up to 2 changes</option></select></label>
          <label className="compact"><span>MIN CHANGE</span><select value={minTransfer} onChange={e => setMinTransfer(Number(e.target.value))}>{[15,30,45,60,90,120,180].map(n => <option key={n} value={n}>{n} min</option>)}</select></label>
          <label className="compact"><span>SORT</span><select value={sortBy} onChange={e => setSortBy(e.target.value)}>{meta?.sorts.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
          <button className="search-btn" onClick={search} disabled={loading}><Search size={18}/>{loading ? 'Searching…' : 'Search trains'}</button>
        </div>
        <div className="advanced-row"><label><input type="checkbox" checked={alwaysAlt} onChange={e => setAlwaysAlt(e.target.checked)}/> Show alternatives even if a direct train exists</label><span>Max wait {maxLayover}h · Max journey {maxHours}h</span></div>
        <div className="range-row"><label>Longest station wait <input type="range" min="1" max="48" value={maxLayover} onChange={e => setMaxLayover(Number(e.target.value))}/><b>{maxLayover}h</b></label><label>Maximum journey <input type="range" min="6" max="72" value={maxHours} onChange={e => setMaxHours(Number(e.target.value))}/><b>{maxHours}h</b></label></div>
      </section>

      {error && <div className="error-banner"><Info size={18}/>{error}</div>}
      {results && <section className="results">
        <div className="results-head"><div><div className="eyebrow">SEARCH RESULTS</div><h2>{stationMap[src]?.name} <ArrowRight size={20}/> {stationMap[dst]?.name}</h2><p>{fmtDate(day)} · {cls} · {pax} passenger{pax > 1 ? 's' : ''}</p></div><button className="download" onClick={download}><Download size={16}/> CSV</button></div>
        {!results.dateInRange && <div className="notice"><Info size={17}/> No timetable coverage is available for this date. Choose a date within {fmtDate(results.dateRange.from)} – {fmtDate(results.dateRange.to)}.</div>}
        <div className="result-summary"><span>{results.direct.length} direct option{results.direct.length !== 1 ? 's' : ''}</span><span>{results.alternatives.length} alternative route{results.alternatives.length !== 1 ? 's' : ''}</span></div>
        {results.direct.length > 0 && <><h3 className="section-title">Direct trains</h3>{results.direct.map(j => <JourneyCard key={j.key} journey={j} pax={pax}/>)}</>}
        {results.alternatives.length > 0 && <><h3 className="section-title">Alternative routes</h3>{results.alternatives.map(j => <JourneyCard key={j.key} journey={j} pax={pax}/>)}</>}
        {results.direct.length === 0 && results.alternatives.length === 0 && <div className="empty"><TrainFront size={36}/><h3>No feasible route found</h3><p>Try a longer wait, a longer maximum journey, a shorter change time, or allow more connections.</p></div>}
      </section>}
    </main>
    <footer><span>RailRoute Alternate · React + Vite frontend · Python routing engine</span><span><strong>Prototype:</strong> timetable, availability and fares are SAMPLE data.</span></footer>
  </div>
}

export default App
