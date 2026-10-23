import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { getDoctorAppointments } from '../../services/hospitalService';
import { createEncounter, listEncounters } from '../../services/encounterService';
import { encounterError, newCreationKey } from '../encounterUi';

export default function DoctorEncounterEntry() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const appointmentId = Number(params.get('appointment_id'));
  const patientId = Number(params.get('patient_id'));
  const [appointment, setAppointment] = useState(null);
  const [existing, setExisting] = useState(null);
  const [complaint, setComplaint] = useState('');
  const [key, setKey] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    if (!Number.isSafeInteger(appointmentId) || appointmentId <= 0 || !Number.isSafeInteger(patientId) || patientId <= 0) {
      setError('Select a confirmed appointment from your roster.'); setLoading(false); return;
    }
    Promise.all([getDoctorAppointments(), listEncounters({ patient_id: patientId, limit: 100 })]).then(([apps, visits]) => {
      if (!active) return;
      const app = apps.find(item => item.id === appointmentId && item.patient_id === patientId);
      if (!app) setError('Appointment unavailable to your account.');
      else { setAppointment(app); setComplaint(app.reason || ''); }
      setExisting(visits.items?.find(item => item.appointment_id === appointmentId) || null);
    }).catch(err => active && setError(encounterError(err).message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [appointmentId, patientId]);

  const checkIn = async () => {
    if (!appointment || appointment.status !== 'CONFIRMED') return;
    setBusy(true); setError('');
    try {
      const creationKey = key || newCreationKey();
      setKey(creationKey);
      const visit = await createEncounter({ patient_id: patientId, appointment_id: appointmentId, creation_key: creationKey, chief_complaint: complaint.trim() || null });
      navigate(`/doctor/encounters/${visit.id}`);
    } catch (err) { setError(encounterError(err).message); }
    finally { setBusy(false); }
  };

  return <div className="max-w-3xl mx-auto p-6 space-y-5"><Link className="text-teal-700 text-sm font-bold" to="/doctor/appointments">Back to appointments</Link><h1 className="text-2xl font-black text-slate-900">Appointment check-in</h1>
    {error && <p role="alert" className="rounded-xl bg-rose-50 border border-rose-200 p-3 text-rose-800 text-sm">{error}</p>}
    {loading ? <p>Loading appointment…</p> : appointment && <div className="rounded-2xl bg-white border border-slate-200 p-5 space-y-3">
      <p className="font-bold">{appointment.patient_name} · Appointment #{appointment.id}</p><p className="text-sm text-slate-600">{appointment.appointment_date} · {appointment.status}</p>
      {existing ? <Link to={`/doctor/encounters/${existing.id}`} className="text-teal-700 font-bold">Open existing visit #{existing.id}</Link> : appointment.status === 'CONFIRMED' ? <><label className="block text-sm font-semibold">Chief complaint<textarea maxLength={4000} value={complaint} onChange={e => { setComplaint(e.target.value); setKey(''); }} className="w-full border rounded-xl p-3 mt-1" rows={3} /></label><button disabled={busy} onClick={checkIn} className="rounded-xl bg-[#0F9D8A] px-4 py-2 text-white text-sm font-bold disabled:opacity-50">{busy ? 'Checking in…' : 'Check in and open visit'}</button></> : <p className="text-sm text-amber-800">Only confirmed appointments can be checked in.</p>}
    </div>}
  </div>;
}
