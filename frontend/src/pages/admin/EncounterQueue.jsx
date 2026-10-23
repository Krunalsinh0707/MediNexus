import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../../services/api';
import { getAllDoctors, getDoctorAppointments } from '../../services/hospitalService';
import { createEncounter, listEncounters, assignEncounter, transitionEncounter } from '../../services/encounterService';
import { encounterError, newCreationKey } from '../encounterUi';

const statuses = ['CHECKED_IN', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'];
const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm';
const input = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';

export default function EncounterQueue() {
  const [visits, setVisits] = useState([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState('CHECKED_IN');
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [search, setSearch] = useState('');
  const [patients, setPatients] = useState([]);
  const [searched, setSearched] = useState(false);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [appointments, setAppointments] = useState([]);
  const [doctors, setDoctors] = useState([]);
  const [appointmentId, setAppointmentId] = useState('');
  const [doctorId, setDoctorId] = useState('');
  const [complaint, setComplaint] = useState('');
  const [creationKey, setCreationKey] = useState('');

  const refresh = useCallback(async (nextStatus = status, nextOffset = offset) => {
    setLoading(true);
    setError('');
    try {
      const result = await listEncounters({ status: nextStatus, limit: 25, offset: nextOffset });
      setVisits(result.items || []);
      setTotal(result.total || 0);
    } catch (err) {
      setError(encounterError(err).message);
    } finally {
      setLoading(false);
    }
  }, [status, offset]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    Promise.all([getDoctorAppointments(), getAllDoctors()]).then(([apps, docs]) => {
      setAppointments(Array.isArray(apps) ? apps : []);
      setDoctors(Array.isArray(docs) ? docs.filter(doc => doc.status === 'Active') : []);
    }).catch(err => setError(encounterError(err).message));
  }, []);

  const findPatients = async (event) => {
    event.preventDefault();
    setSelectedPatient(null);
    setPatients([]);
    setSearched(true);
    setError('');
    if (!search.trim()) return setError('Enter a name, MRN, email, or phone number.');
    try {
      const response = await api.post('/patients/search', { query: search.trim(), limit: 25 });
      setPatients(response.data.items || []);
    } catch (err) { setError(encounterError(err).message); }
  };

  const checkIn = async (event) => {
    event.preventDefault();
    if (!selectedPatient) return setError('Select a patient from the registry search first.');
    setBusy(true); setError(''); setMessage('');
    try {
      const key = creationKey || newCreationKey();
      setCreationKey(key);
      const result = await createEncounter({
        patient_id: selectedPatient.id,
        appointment_id: appointmentId ? Number(appointmentId) : null,
        doctor_id: !appointmentId && doctorId ? Number(doctorId) : null,
        creation_key: key,
        chief_complaint: complaint.trim() || null,
      });
      setMessage(`Visit #${result.id} checked in for ${result.patient_name} (${result.mrn}).`);
      setCreationKey(''); setAppointmentId(''); setDoctorId(''); setComplaint('');
      await refresh();
    } catch (err) { setError(encounterError(err).message); }
    finally { setBusy(false); }
  };

  const updateVisit = async (visit, action, value) => {
    setBusy(true); setError(''); setMessage('');
    try {
      if (action === 'assign') await assignEncounter(visit.id, { expected_version: visit.version, doctor_id: Number(value) });
      if (action === 'cancel') await transitionEncounter(visit.id, { expected_version: visit.version, status: 'CANCELLED', reason: value });
      setMessage(`Visit #${visit.id} updated.`);
      await refresh();
    } catch (err) { setError(encounterError(err).message); }
    finally { setBusy(false); }
  };

  const patientAppointments = appointments.filter(app => app.patient_id === selectedPatient?.id && app.status === 'CONFIRMED');

  return <div className="space-y-6 max-w-6xl mx-auto">
    <div><h2 className="text-2xl font-black text-slate-900">Encounter queue</h2><p className="text-sm text-slate-500">Register visits and coordinate checked-in patients. Clinical documentation stays with the assigned doctor.</p></div>
    {error && <div role="alert" className="rounded-xl bg-rose-50 border border-rose-200 p-3 text-sm text-rose-800">{error} <button className="underline ml-2" onClick={() => refresh()}>Reload queue</button></div>}
    {message && <div role="status" className="rounded-xl bg-teal-50 border border-teal-200 p-3 text-sm text-teal-900">{message}</div>}
    <section className={card}>
      <h3 className="font-bold text-slate-900 mb-3">Patient check-in</h3>
      <form onSubmit={findPatients} className="flex gap-2 mb-3"><input className={input} value={search} onChange={e => setSearch(e.target.value)} placeholder="Search patient registry" aria-label="Search patient registry" /><button className="rounded-xl bg-slate-900 text-white px-4 text-sm">Search</button></form>
      {patients.length > 0 && <div className="max-h-40 overflow-auto border rounded-xl mb-3">{patients.map(patient => <button key={patient.id} type="button" className={`block w-full text-left px-3 py-2 text-sm border-b ${selectedPatient?.id === patient.id ? 'bg-teal-50' : 'hover:bg-slate-50'}`} onClick={() => { setSelectedPatient(patient); setAppointmentId(''); setCreationKey(''); }}>{patient.full_name} · {patient.mrn}</button>)}</div>}
      {searched && patients.length === 0 && !error && <p className="text-sm text-slate-500 mb-3">No matching registered patients. Search another identifier or use Patient Registry.</p>}
      {selectedPatient && <form onSubmit={checkIn} className="space-y-3">
        <p className="text-sm font-semibold text-teal-800">Selected: {selectedPatient.full_name} · {selectedPatient.mrn}</p>
        <label className="block text-xs font-semibold text-slate-600">Confirmed appointment (optional)<select className={input} value={appointmentId} onChange={e => { setAppointmentId(e.target.value); setCreationKey(''); }}><option value="">Walk-in visit</option>{patientAppointments.map(app => <option key={app.id} value={app.id}>#{app.id} · {app.appointment_date} · {app.patient_name}</option>)}</select></label>
        {!appointmentId && <label className="block text-xs font-semibold text-slate-600">Assign doctor (optional)<select className={input} value={doctorId} onChange={e => { setDoctorId(e.target.value); setCreationKey(''); }}><option value="">Unassigned</option>{doctors.map(doctor => <option key={doctor.id} value={doctor.id}>{doctor.full_name || doctor.name || `Doctor #${doctor.id}`}</option>)}</select></label>}
        <label className="block text-xs font-semibold text-slate-600">Chief complaint<textarea className={input} maxLength={4000} value={complaint} onChange={e => { setComplaint(e.target.value); setCreationKey(''); }} rows={2} /></label>
        <button disabled={busy} className="rounded-xl bg-[#0F9D8A] text-white px-4 py-2 text-sm font-bold disabled:opacity-50">{busy ? 'Checking in…' : 'Check in patient'}</button>
      </form>}
    </section>
    <section className={card}>
      <div className="flex flex-wrap gap-2 justify-between mb-4"><h3 className="font-bold text-slate-900">Visits ({total})</h3><button onClick={() => refresh()} className="text-sm text-teal-700 font-bold">Refresh</button></div>
      <div className="flex gap-2 overflow-auto mb-4">{statuses.map(item => <button key={item} onClick={() => { setStatus(item); setOffset(0); }} className={`rounded-xl px-3 py-2 text-xs font-bold ${status === item ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'}`}>{item.replace('_', ' ')}</button>)}</div>
      {loading ? <p className="text-sm text-slate-500">Loading visits…</p> : visits.length === 0 ? <p className="text-sm text-slate-500">No visits in this queue.</p> : <div className="divide-y divide-slate-100">{visits.map(visit => <div key={visit.id} className="py-3 flex flex-wrap gap-3 items-center justify-between text-sm"><div><strong>{visit.patient_name}</strong> <span className="text-slate-500">{visit.mrn} · Visit #{visit.id}</span><p className="text-xs text-slate-500">{visit.status.replace('_', ' ')} · Doctor #{visit.doctor_id || 'unassigned'} · {visit.appointment_id ? `Appointment #${visit.appointment_id}` : 'Walk-in'}</p></div><div className="flex gap-2 items-center"><Link to={`/admin/encounters/${visit.id}`} className="text-teal-700 font-bold">View</Link>{visit.status === 'CHECKED_IN' && <><select aria-label={`Assign doctor for visit ${visit.id}`} className="border rounded-lg p-1 text-xs" defaultValue="" disabled={busy} onChange={e => e.target.value && updateVisit(visit, 'assign', e.target.value)}><option value="">Assign doctor</option>{doctors.map(doc => <option key={doc.id} value={doc.id}>{doc.full_name || doc.name || `Doctor #${doc.id}`}</option>)}</select><button disabled={busy} onClick={() => { const reason = window.prompt('Cancellation reason'); if (reason?.trim()) updateVisit(visit, 'cancel', reason.trim()); }} className="text-rose-700 text-xs">Cancel</button></>}</div></div>)}</div>}
      <div className="flex justify-between mt-4 text-sm"><button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><button disabled={offset + 25 >= total || loading} onClick={() => setOffset(offset + 25)}>Next</button></div>
    </section>
  </div>;
}
