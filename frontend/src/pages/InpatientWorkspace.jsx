import { useCallback, useEffect, useState } from 'react';
import { BedDouble } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { listEncounters } from '../services/encounterService';
import * as inpatient from '../services/inpatientService';
import { availableBed, canAct, inpatientError } from './inpatientUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-[#0F9D8A] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50';
const label = value => String(value || '').replaceAll('_', ' ');

export default function InpatientWorkspace() {
  const { user } = useAuth();
  const clinician = ['doctor', 'emergency_doctor'].includes((user?.role || '').toLowerCase());
  const [wards, setWards] = useState([]), [rooms, setRooms] = useState([]), [beds, setBeds] = useState([]), [admissions, setAdmissions] = useState([]);
  const [encounters, setEncounters] = useState([]), [selected, setSelected] = useState(null), [bedHistory, setBedHistory] = useState(null);
  const [wardId, setWardId] = useState(''), [status, setStatus] = useState(''), [action, setAction] = useState('');
  const [form, setForm] = useState({ encounter: '', targetWard: '', bed: '', reason: '', plannedAt: '' });
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [retryable, setRetryable] = useState(false), [message, setMessage] = useState('');
  const showError = err => { const result = inpatientError(err); setError(result.message); setRetryable(result.retryable); };

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [w, r, b, a, e] = await Promise.all([inpatient.listWards(), inpatient.listRooms(), inpatient.listBeds(),
        inpatient.listAdmissions({ status: status || undefined, limit: 100 }),
        clinician ? listEncounters({ status: 'IN_PROGRESS', limit: 100 }) : Promise.resolve({ items: [] })]);
      const rows = Array.isArray(a?.items) ? a.items : [];
      setWards(Array.isArray(w?.items) ? w.items : []); setRooms(Array.isArray(r?.items) ? r.items : []);
      setBeds(Array.isArray(b?.items) ? b.items : []);
      setAdmissions(rows); setEncounters(Array.isArray(e?.items) ? e.items : []);
      setSelected(current => rows.find(row => row.id === current?.id) || null);
    } catch (err) {
      const result = inpatientError(err); setError(result.message); setRetryable(result.retryable);
      setWards([]); setRooms([]); setBeds([]); setAdmissions([]); setEncounters([]); setSelected(null);
    } finally { setLoading(false); }
  }, [clinician, status]);
  useEffect(() => { load(); }, [load]);

  const choose = async id => {
    setBusy(true); setError(''); setAction('');
    try { setSelected(await inpatient.getAdmission(id)); } catch (err) { showError(err); } finally { setBusy(false); }
  };
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      let result;
      if (action === 'REQUEST') {
        const encounter = encounters.find(row => row.id === Number(form.encounter));
        if (!encounter) { setError('Select an active assigned encounter.'); return; }
        result = await inpatient.requestAdmission({ patient_id: encounter.patient_id, source_encounter_id: encounter.id,
          ward_id: Number(form.targetWard), reason: form.reason.trim() });
      } else if (canAct(selected, action)) {
        if (action === 'ADMIT' || action === 'REJECT') result = await inpatient.decideAdmission(selected.id, {
          expected_version: selected.version, decision: action, bed_id: action === 'ADMIT' ? Number(form.bed) : null,
          reason: action === 'REJECT' ? form.reason.trim() : null });
        if (action === 'TRANSFER') result = await inpatient.transferAdmission(selected.id, {
          expected_version: selected.version, ward_id: Number(form.targetWard), bed_id: Number(form.bed), reason: form.reason.trim() });
        if (action === 'DISCHARGE') result = await inpatient.dischargeAdmission(selected.id, {
          expected_version: selected.version, reason: form.reason.trim() });
        if (action === 'PLAN_DISCHARGE') result = await inpatient.planDischarge(selected.id, {
          expected_version: selected.version, planned_at: new Date(form.plannedAt).toISOString(), reason: form.reason.trim() });
      }
      if (result) { setSelected(result); setMessage(`${label(action)} saved.`); setAction(''); await load(); }
    } catch (err) { showError(err); } finally { setBusy(false); }
  };
  const changeBed = async (bed, operation) => {
    const reason = ['BLOCKED', 'CLEANING', 'RELEASE'].includes(operation) ? window.prompt('Reason for this bed change')?.trim() : null;
    if (['BLOCKED', 'CLEANING', 'RELEASE'].includes(operation) && !reason) return;
    setBusy(true); setError(''); setMessage('');
    try {
      if (operation === 'RESERVE') await inpatient.reserveBed(bed.id, { admission_id: selected.id, expected_bed_version: bed.version });
      else if (operation === 'RELEASE') await inpatient.releaseBedReservation(bed.id, { expected_bed_version: bed.version, reason });
      else await inpatient.setBedStatus(bed.id, { expected_version: bed.version, status: operation, reason });
      setMessage('Bed state updated.'); await load();
    } catch (err) { showError(err); } finally { setBusy(false); }
  };
  const filteredAdmissions = wardId ? admissions.filter(row => row.ward_id === Number(wardId)) : admissions;
  const filteredBeds = wardId ? beds.filter(row => row.ward_id === Number(wardId)) : beds;
  const targetWard = Number(action === 'ADMIT' ? selected?.ward_id : form.targetWard);
  const candidateBeds = beds.filter(row => availableBed(row, targetWard) ||
    (action === 'ADMIT' && row.status === 'RESERVED' && row.reserved_for_admission_id === selected?.id));
  return <div className="min-h-full space-y-5 bg-[#F6F9FB] p-4 md:p-8">
    <header><h1 className="flex items-center gap-2 text-2xl font-bold"><BedDouble className="text-teal-600"/>Inpatient operations</h1><p className="text-sm text-slate-600">Ward census, beds, and operational ADT. Clinical discharge clearance is not recorded here.</p></header>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">{error}{retryable && <button className="ml-2 font-bold underline" onClick={load}>Reload</button>}</div>}
    {message && <p role="status" className="rounded-xl bg-teal-50 p-3 text-sm">{message}</p>}
    {loading ? <p>Loading inpatient information…</p> : <><div className="flex flex-wrap gap-3 rounded-2xl border bg-white p-4"><select aria-label="Ward filter" className={field} value={wardId} onChange={e => setWardId(e.target.value)}><option value="">All assigned wards</option>{wards.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><select aria-label="Admission status filter" className={field} value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{['REQUESTED', 'ACTIVE', 'REJECTED', 'DISCHARGED'].map(value => <option key={value}>{value}</option>)}</select><button className={button} onClick={load}>Reload</button>{clinician && <button className={button} onClick={() => { setAction('REQUEST'); setSelected(null); }}>Request admission</button>}</div>
      <div className="grid gap-5 lg:grid-cols-[.8fr_1.5fr]"><section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Admissions and census</h2>{!filteredAdmissions.length ? <p className="text-sm text-slate-500">No admissions in your permitted scope.</p> : filteredAdmissions.map(row => <button key={row.id} className="w-full rounded-xl border p-3 text-left text-sm hover:bg-teal-50" onClick={() => choose(row.id)}><strong>{row.patient_name} · {row.mrn}</strong><span className="block">#{row.id} · {label(row.status)} · Ward {row.ward_id}{row.bed_code ? ` · Bed ${row.bed_code}` : ''}</span></button>)}</section>
      <section className="space-y-4 rounded-2xl border bg-white p-5">{selected ? <><h2 className="text-lg font-bold">{selected.patient_name} · {selected.mrn}</h2><p className="text-sm">Admission #{selected.id} · {label(selected.status)} · Encounter #{selected.source_encounter_id} · Ward {selected.ward_id}{selected.room_code ? ` · Room ${selected.room_code} · Bed ${selected.bed_code}` : ''}</p>{selected.planned_discharge_at && <p className="text-sm">Tentative discharge: {new Date(selected.planned_discharge_at).toLocaleString()}</p>}<div className="flex flex-wrap gap-2">{selected.allowed_actions?.map(value => <button key={value} className={button} disabled={busy} onClick={() => { setAction(value); setForm({ encounter: '', targetWard: String(selected.ward_id), bed: '', reason: '', plannedAt: '' }); }}>{label(value)}</button>)}</div><h3 className="font-bold">History</h3>{selected.events?.map(row => <p className="rounded-lg bg-slate-50 p-2 text-sm" key={row.sequence}>#{row.sequence} · {label(row.event_type)} · {row.created_at ? new Date(row.created_at).toLocaleString() : 'Time unavailable'}{row.reason ? ` · ${row.reason}` : ''}</p>)}</> : <p className="text-sm text-slate-500">Select an admission to review location and history.</p>}
      {action && <form onSubmit={submit} className="space-y-3 rounded-xl border p-3"><h3 className="font-bold">{label(action)}</h3>{action === 'REQUEST' && <label className="block text-sm">Active assigned encounter<select required className={field} value={form.encounter} onChange={e => setForm(prev => ({ ...prev, encounter: e.target.value }))}><option value="">Select encounter</option>{encounters.map(row => <option key={row.id} value={row.id}>{row.mrn} · {row.patient_name} · #{row.id}</option>)}</select></label>}{['REQUEST', 'TRANSFER'].includes(action) && <label className="block text-sm">Ward<select required className={field} value={form.targetWard} onChange={e => setForm(prev => ({ ...prev, targetWard: e.target.value, bed: '' }))}><option value="">Select ward</option>{wards.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}{['ADMIT', 'TRANSFER'].includes(action) && <label className="block text-sm">Available bed<select required className={field} value={form.bed} onChange={e => setForm(prev => ({ ...prev, bed: e.target.value }))}><option value="">Select bed</option>{candidateBeds.map(row => <option key={row.id} value={row.id}>{row.room_code} · {row.code}</option>)}</select></label>}{action === 'PLAN_DISCHARGE' && <label className="block text-sm">Tentative discharge date and time<input required type="datetime-local" className={field} value={form.plannedAt} onChange={e => setForm(prev => ({ ...prev, plannedAt: e.target.value }))}/></label>}{action !== 'ADMIT' && <label className="block text-sm">Reason<textarea required className={field} value={form.reason} onChange={e => setForm(prev => ({ ...prev, reason: e.target.value }))}/></label>}<button className={button} disabled={busy}>Confirm</button><button type="button" className="ml-2 text-sm underline" onClick={() => setAction('')}>Cancel</button></form>}</section></div>
      <section className="rounded-2xl border bg-white p-4"><h2 className="mb-3 font-bold">Ward beds</h2>{!filteredBeds.length ? <p className="text-sm text-slate-500">No beds in your assigned wards.</p> : <div className="grid gap-3 md:grid-cols-3">{filteredBeds.map(row => <article className="rounded-xl border p-3 text-sm" key={row.id}><strong>{row.room_code} · Bed {row.code}</strong><p>{label(row.status)}{row.admission_id ? ` · Admission #${row.admission_id}` : ''}{row.reserved_for_admission_id ? ` · Reserved for #${row.reserved_for_admission_id}` : ''}</p><div className="mt-2 flex flex-wrap gap-2"><button className="underline" onClick={async () => { try { setBedHistory(await inpatient.getBedHistory(row.id)); } catch (err) { showError(err); } }}>History</button>{row.status === 'AVAILABLE' && <><button className="underline" disabled={busy} onClick={() => changeBed(row, 'BLOCKED')}>Block</button><button className="underline" disabled={busy} onClick={() => changeBed(row, 'CLEANING')}>Cleaning</button>{selected?.status === 'REQUESTED' && selected.ward_id === row.ward_id && canAct(selected, 'ADMIT') && <button className="underline" disabled={busy} onClick={() => changeBed(row, 'RESERVE')}>Reserve</button>}</>}{['BLOCKED', 'CLEANING'].includes(row.status) && <button className="underline" disabled={busy} onClick={() => changeBed(row, 'AVAILABLE')}>Mark available</button>}{row.status === 'RESERVED' && <button className="underline" disabled={busy} onClick={() => changeBed(row, 'RELEASE')}>Release</button>}</div></article>)}</div>}{bedHistory && <div className="mt-4 rounded-xl bg-slate-50 p-3 text-sm"><h3 className="font-bold">Bed {bedHistory.bed.code} history</h3>{bedHistory.events?.map(row => <p key={row.version}>#{row.version} · {label(row.event_type)}{row.reason ? ` · ${row.reason}` : ''}</p>)}<button className="mt-2 underline" onClick={() => setBedHistory(null)}>Close</button></div>}</section>
      <section className="rounded-2xl border bg-white p-4"><h2 className="mb-3 font-bold">Ward and room directory</h2>{!rooms.length ? <p className="text-sm text-slate-500">No rooms in your assigned wards.</p> : <div className="flex flex-wrap gap-2">{rooms.filter(row => !wardId || row.ward_id === Number(wardId)).map(row => <span key={row.id} className="rounded-lg bg-slate-50 px-3 py-2 text-sm">Ward {row.ward_id} · Room {row.code}</span>)}</div>}</section>
    </>}
  </div>;
}
