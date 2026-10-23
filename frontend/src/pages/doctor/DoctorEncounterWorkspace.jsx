import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getDoctorProfile } from '../../services/hospitalService';
import {
  getEncounter, getEncounterAllergies, transitionEncounter, writeEncounterNote,
  writeEncounterVitals, writeEncounterDiagnosis, writeEncounterAllergy, reviewEncounterAllergies,
} from '../../services/encounterService';
import { canEditEncounter, encounterError, latestRevisions } from '../encounterUi';
import ClinicalOrdersPanel from './ClinicalOrdersPanel';
import MedicationOrdersPanel from './MedicationOrdersPanel';

const panel = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-3';
const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-[#0F9D8A] px-4 py-2 text-sm font-bold text-white disabled:opacity-50';
const emptyNote = { subjective: '', objective: '', assessment: '', plan: '', patient_summary: '' };
const vitalLabels = {
  systolic_mmhg: 'Systolic (mmHg)', diastolic_mmhg: 'Diastolic (mmHg)', pulse_bpm: 'Pulse (bpm)',
  respiratory_rate_per_min: 'Respiratory rate/min', temperature_c: 'Temperature (°C)',
  spo2_percent: 'SpO₂ (%)', weight_kg: 'Weight (kg)', height_cm: 'Height (cm)',
};
const emptyVitals = Object.fromEntries(Object.keys(vitalLabels).map(key => [key, '']));
const emptyDiagnosis = { description: '', coding_system: '', code: '', status: 'PROVISIONAL', is_primary: false };
const emptyAllergy = { substance: '', reaction: '', severity: 'UNKNOWN', status: 'ACTIVE' };
const localMeasurementTime = (value = new Date()) => {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

function RevisionList({ title, rows, render, onCorrect, editable }) {
  const latest = new Set(latestRevisions(rows).map(row => row.id));
  return <div className="space-y-2"><h3 className="font-bold text-slate-900">{title}</h3>{rows.length === 0 ? <p className="text-sm text-slate-500">No records yet.</p> : rows.map(row => <div key={row.id} className={`rounded-xl border p-3 text-sm ${latest.has(row.id) ? 'border-slate-200 bg-slate-50' : 'border-slate-100 bg-white text-slate-500'}`}>
    <div className="flex justify-between gap-2"><span className="font-semibold">Revision #{row.id}{row.previous_id ? ` · corrects #${row.previous_id}` : ''}</span><span>{row.recorded_at ? new Date(row.recorded_at).toLocaleString() : ''}</span></div>
    {render(row)}{row.reason && <p className="text-xs text-slate-500">Correction reason: {row.reason}</p>}
    {editable && latest.has(row.id) && <button type="button" className="text-teal-700 font-bold mt-2" onClick={() => onCorrect(row)}>Correct this record</button>}
  </div>)}</div>;
}

export default function DoctorEncounterWorkspace() {
  const { encounterId } = useParams();
  const [visit, setVisit] = useState(null);
  const [doctor, setDoctor] = useState(null);
  const [allergies, setAllergies] = useState(null);
  const [note, setNote] = useState(emptyNote);
  const [addendumReason, setAddendumReason] = useState('');
  const [vitals, setVitals] = useState(emptyVitals);
  const [measuredAt, setMeasuredAt] = useState(() => localMeasurementTime());
  const [vitalCorrection, setVitalCorrection] = useState(null);
  const [diagnosis, setDiagnosis] = useState(emptyDiagnosis);
  const [diagnosisCorrection, setDiagnosisCorrection] = useState(null);
  const [allergy, setAllergy] = useState(emptyAllergy);
  const [allergyCorrection, setAllergyCorrection] = useState(null);
  const [reviewOutcome, setReviewOutcome] = useState('UNKNOWN');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    const [nextVisit, nextDoctor] = await Promise.all([getEncounter(encounterId), getDoctorProfile()]);
    setVisit(nextVisit); setDoctor(nextDoctor);
    if (nextVisit.status === 'IN_PROGRESS' || nextVisit.status === 'COMPLETED') {
      try { setAllergies(await getEncounterAllergies(encounterId)); }
      catch (err) { setAllergies(null); setError(encounterError(err).message); }
    }
  }, [encounterId]);

  useEffect(() => {
    let active = true;
    Promise.all([getEncounter(encounterId), getDoctorProfile()]).then(async ([nextVisit, nextDoctor]) => {
      if (!active) return;
      setVisit(nextVisit); setDoctor(nextDoctor);
      if (nextVisit.status === 'IN_PROGRESS' || nextVisit.status === 'COMPLETED') {
        try { const context = await getEncounterAllergies(encounterId); if (active) setAllergies(context); }
        catch (err) { if (active) setError(encounterError(err).message); }
      }
    }).catch(err => active && setError(encounterError(err).message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [encounterId]);

  const run = async (action, success) => {
    setBusy(true); setError(''); setConflict(false); setMessage('');
    try { await action(); await refresh(); setMessage(success); }
    catch (err) { const parsed = encounterError(err); setError(parsed.message); setConflict(parsed.conflict); }
    finally { setBusy(false); }
  };

  const editable = canEditEncounter(visit, doctor?.id);
  const assigned = Boolean(visit && doctor?.id === visit.doctor_id);
  const completed = visit?.status === 'COMPLETED';
  const latestNote = visit?.notes?.at(-1);
  const activeAllergies = latestRevisions(allergies?.current_records || []).filter(row => row.status === 'ACTIVE');

  if (loading) return <div className="p-10 text-sm text-slate-600">Loading encounter…</div>;
  return <div className="max-w-6xl mx-auto p-5 md:p-8 space-y-5">
    <Link to="/doctor/appointments" className="text-teal-700 text-sm font-bold">Back to appointments</Link>
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="text-2xl font-black text-slate-900">Clinical encounter</h1><p className="text-sm text-slate-600">{visit ? `${visit.patient_name} · ${visit.mrn} · Visit #${visit.id}` : 'Visit unavailable'}</p></div><button onClick={() => { setError(''); setConflict(false); refresh().catch(err => setError(encounterError(err).message)); }} className="text-sm font-bold text-teal-700">Reload visit</button></div>
    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}{conflict && <button onClick={() => { setError(''); setConflict(false); refresh().catch(err => setError(encounterError(err).message)); }} className="ml-2 underline font-bold">Reload latest version</button>}</div>}
    {message && <p role="status" className="rounded-xl bg-teal-50 border border-teal-200 p-3 text-sm text-teal-900">{message}</p>}
    {visit && <>
      <section className={panel}><div className="flex flex-wrap justify-between gap-2"><h2 className="font-bold text-lg">{visit.patient_name} <span className="text-teal-700">{visit.mrn}</span></h2><span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-bold text-teal-800">{visit.status.replace('_', ' ')}</span></div>
        <p className="text-sm text-slate-600">Assigned clinician: Doctor #{visit.doctor_id || 'unassigned'} · Department #{visit.department_id || 'unassigned'} · Version {visit.version}</p>
        <p className="text-sm text-slate-600">{visit.appointment_id ? `Appointment #${visit.appointment_id}` : 'Walk-in visit'} · Checked in {visit.checked_in_at ? new Date(visit.checked_in_at).toLocaleString() : 'time unavailable'}</p>
        {visit.chief_complaint && <p className="text-sm"><strong>Chief complaint:</strong> {visit.chief_complaint}</p>}
        {visit.status === 'CHECKED_IN' && assigned && <button disabled={busy} className={button} onClick={() => run(() => transitionEncounter(visit.id, { expected_version: visit.version, status: 'IN_PROGRESS' }), 'Visit started.')}>Start visit</button>}
        {visit.status === 'IN_PROGRESS' && assigned && <button disabled={busy} className="ml-2 rounded-xl border border-rose-200 px-4 py-2 text-sm font-bold text-rose-700 disabled:opacity-50" onClick={() => { const reason = window.prompt('Reason for cancelling this visit'); if (reason?.trim()) run(() => transitionEncounter(visit.id, { expected_version: visit.version, status: 'CANCELLED', reason: reason.trim() }), 'Visit cancelled.'); }}>Cancel visit</button>}
        {editable && <button disabled={busy || !latestNote?.assessment?.trim() || !latestNote?.plan?.trim() || !latestNote?.patient_summary?.trim() || !visit.allergy_reviews?.length} className={button} onClick={() => run(() => transitionEncounter(visit.id, { expected_version: visit.version, status: 'COMPLETED' }), 'Visit completed and final note signed.')}>Sign final note and complete visit</button>}
      </section>
      {visit.status === 'CANCELLED' && <p className="rounded-xl bg-amber-50 p-3 text-sm">Cancelled: {visit.cancellation_reason || 'Reason unavailable'}</p>}
      <ClinicalOrdersPanel encounter={visit} doctorId={doctor?.id} />
      <MedicationOrdersPanel encounter={visit} doctorId={doctor?.id} allergyContext={allergies} />
      {(editable || (completed && assigned)) && <section className={panel}><h2 className="font-bold text-slate-900">{completed ? 'Signed addendum' : 'Clinical note'}</h2>
        {Object.keys(emptyNote).map(key => <label key={key} className="block text-sm font-semibold text-slate-700">{key.replace('_', ' ')}<textarea className={field} rows={key === 'patient_summary' ? 3 : 2} maxLength={20000} value={note[key]} onChange={e => setNote(current => ({ ...current, [key]: e.target.value }))} /></label>)}
        {completed && <label className="block text-sm font-semibold">Reason for addendum<input className={field} maxLength={4000} value={addendumReason} onChange={e => setAddendumReason(e.target.value)} /></label>}
        <button disabled={busy || (completed && !addendumReason.trim())} className={button} onClick={() => run(async () => { await writeEncounterNote(visit.id, { expected_version: visit.version, ...note, ...(completed ? { reason: addendumReason.trim() } : {}) }, completed); setNote(emptyNote); setAddendumReason(''); }, completed ? 'Signed addendum saved.' : 'Note revision saved. Complete the visit to sign the final note.')}>{completed ? 'Sign addendum' : 'Save note revision'}</button>
      </section>}
      <section className={panel}><h2 className="font-bold text-slate-900">Notes and correction history</h2>{!visit.notes?.length ? <p className="text-sm text-slate-500">No notes recorded.</p> : visit.notes.map(row => <div key={row.id} className="rounded-xl border border-slate-200 p-3 text-sm space-y-1"><p className="font-bold">Revision {row.revision} · {row.kind} · {row.signed_at ? 'Signed' : 'Unsigned draft'}</p><p className="text-xs text-slate-500">Clinician #{row.author_doctor_id} · {new Date(row.created_at).toLocaleString()}</p>{['subjective', 'objective', 'assessment', 'plan', 'patient_summary'].map(key => row[key] && <p key={key}><strong className="capitalize">{key.replace('_', ' ')}:</strong> {row[key]}</p>)}{row.reason && <p>Reason: {row.reason}</p>}</div>)}</section>
      <section className={panel}><RevisionList title="Recorded vitals" rows={visit.vitals || []} editable={editable} onCorrect={row => { setVitals(Object.fromEntries(Object.keys(vitalLabels).map(key => [key, row[key] ?? '']))); setMeasuredAt(localMeasurementTime(row.measured_at)); setVitalCorrection(row); }} render={row => <p>{Object.entries(vitalLabels).filter(([key]) => row[key] != null).map(([key, label]) => `${label}: ${row[key]}`).join(' · ')} · Measured {new Date(row.measured_at).toLocaleString()}</p>} />
        {editable && <form onSubmit={e => { e.preventDefault(); run(async () => { await writeEncounterVitals(visit.id, { expected_version: visit.version, previous_id: vitalCorrection?.id || null, reason: vitalCorrection ? e.currentTarget.elements.reason.value.trim() : null, measured_at: new Date(measuredAt).toISOString(), ...Object.fromEntries(Object.keys(vitalLabels).map(key => [key, vitals[key] === '' ? null : Number(vitals[key])])) }); setVitals(emptyVitals); setMeasuredAt(localMeasurementTime()); setVitalCorrection(null); }, 'Measured vitals saved.'); }} className="space-y-3"><h3 className="font-bold">{vitalCorrection ? `Correct vitals #${vitalCorrection.id}` : 'Record actual measured vitals'}</h3><label className="block text-xs">Measured at<input required type="datetime-local" className={field} value={measuredAt} onChange={e => setMeasuredAt(e.target.value)} /></label><div className="grid grid-cols-2 md:grid-cols-4 gap-2">{Object.entries(vitalLabels).map(([key, label]) => <label key={key} className="text-xs">{label}<input type="number" step="any" className={field} value={vitals[key]} onChange={e => setVitals(current => ({ ...current, [key]: e.target.value }))} /></label>)}</div>{vitalCorrection && <label className="block text-xs">Correction reason<input name="reason" required maxLength={4000} className={field} /></label>}<button disabled={busy || !Object.values(vitals).some(value => value !== '')} className={button}>Save vitals</button>{vitalCorrection && <button type="button" className="ml-3 text-sm text-slate-600" onClick={() => { setVitals(emptyVitals); setMeasuredAt(localMeasurementTime()); setVitalCorrection(null); }}>Cancel correction</button>}</form>}
      </section>
      <section className={panel}><RevisionList title="Diagnoses" rows={visit.diagnoses || []} editable={editable} onCorrect={row => { setDiagnosis({ description: row.description, coding_system: row.coding_system || '', code: row.code || '', status: row.status, is_primary: row.is_primary }); setDiagnosisCorrection(row); }} render={row => <p>{row.description} · {row.status}{row.is_primary ? ' · Primary' : ''}{row.code ? ` · ${row.coding_system} ${row.code}` : ''}</p>} />
        {editable && <form onSubmit={e => { e.preventDefault(); run(async () => { await writeEncounterDiagnosis(visit.id, { expected_version: visit.version, ...diagnosis, coding_system: diagnosis.coding_system.trim() || null, code: diagnosis.code.trim() || null, previous_id: diagnosisCorrection?.id || null, reason: diagnosisCorrection ? e.currentTarget.elements.reason.value.trim() : null }); setDiagnosis(emptyDiagnosis); setDiagnosisCorrection(null); }, 'Diagnosis saved.'); }} className="space-y-2"><h3 className="font-bold">{diagnosisCorrection ? `Correct diagnosis #${diagnosisCorrection.id}` : 'Record diagnosis'}</h3><input className={field} required maxLength={4000} placeholder="Diagnosis description" value={diagnosis.description} onChange={e => setDiagnosis(current => ({ ...current, description: e.target.value }))} /><div className="grid grid-cols-2 gap-2"><input className={field} maxLength={64} placeholder="Coding system (optional)" value={diagnosis.coding_system} onChange={e => setDiagnosis(current => ({ ...current, coding_system: e.target.value }))} /><input className={field} maxLength={64} placeholder="Code (optional)" value={diagnosis.code} onChange={e => setDiagnosis(current => ({ ...current, code: e.target.value }))} /></div><select className={field} value={diagnosis.status} onChange={e => setDiagnosis(current => ({ ...current, status: e.target.value }))}><option value="PROVISIONAL">Provisional</option><option value="CONFIRMED">Confirmed</option>{diagnosisCorrection && <option value="ENTERED_IN_ERROR">Entered in error</option>}</select><label className="text-sm"><input type="checkbox" checked={diagnosis.is_primary} onChange={e => setDiagnosis(current => ({ ...current, is_primary: e.target.checked }))} /> Primary diagnosis</label>{diagnosisCorrection && <label className="block text-xs">Correction reason<input name="reason" required maxLength={4000} className={field} /></label>}<div><button disabled={busy} className={button}>Save diagnosis</button>{diagnosisCorrection && <button type="button" className="ml-3 text-sm" onClick={() => { setDiagnosis(emptyDiagnosis); setDiagnosisCorrection(null); }}>Cancel correction</button>}</div></form>}
      </section>
      <section className={panel}><h2 className="font-bold">Allergy context and explicit review</h2>{!allergies ? <p className="text-sm text-slate-500">Allergy context unavailable. Reload before review.</p> : <><p className="text-sm text-amber-800">{allergies.message}</p>{allergies.legacy_unverified?.length > 0 && <div className="rounded-xl bg-amber-50 p-3 text-sm"><strong>Unverified legacy information:</strong><ul className="list-disc pl-5">{allergies.legacy_unverified.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
        <RevisionList title="Recorded allergies" rows={allergies.current_records || []} editable={editable} onCorrect={row => { setAllergy({ substance: row.substance, reaction: row.reaction || '', severity: row.severity, status: row.status }); setAllergyCorrection(row); }} render={row => <p>{row.substance} · {row.status} · {row.severity}{row.reaction ? ` · ${row.reaction}` : ''}</p>} />
        {editable && <><form onSubmit={e => { e.preventDefault(); run(async () => { await writeEncounterAllergy(visit.id, { expected_version: visit.version, ...allergy, reaction: allergy.reaction.trim() || null, previous_id: allergyCorrection?.id || null, reason: allergyCorrection ? e.currentTarget.elements.reason.value.trim() : null }); setAllergy(emptyAllergy); setAllergyCorrection(null); }, 'Allergy record saved. Review allergies again before completion.'); }} className="space-y-2"><h3 className="font-bold">{allergyCorrection ? `Correct allergy #${allergyCorrection.id}` : 'Record allergy'}</h3><input className={field} required maxLength={255} placeholder="Substance" value={allergy.substance} onChange={e => setAllergy(current => ({ ...current, substance: e.target.value }))} /><input className={field} maxLength={4000} placeholder="Reaction (optional)" value={allergy.reaction} onChange={e => setAllergy(current => ({ ...current, reaction: e.target.value }))} /><div className="flex gap-2"><select className={field} value={allergy.severity} onChange={e => setAllergy(current => ({ ...current, severity: e.target.value }))}>{['UNKNOWN', 'MILD', 'MODERATE', 'SEVERE'].map(item => <option key={item}>{item}</option>)}</select><select className={field} value={allergy.status} onChange={e => setAllergy(current => ({ ...current, status: e.target.value }))}><option value="ACTIVE">Active</option>{allergyCorrection && <><option value="INACTIVE">Inactive</option><option value="ENTERED_IN_ERROR">Entered in error</option></>}</select></div>{allergyCorrection && <label className="block text-xs">Correction reason<input name="reason" required maxLength={4000} className={field} /></label>}<button disabled={busy} className={button}>Save allergy</button>{allergyCorrection && <button type="button" className="ml-3 text-sm" onClick={() => { setAllergy(emptyAllergy); setAllergyCorrection(null); }}>Cancel correction</button>}</form>
          <div className="border-t pt-3 space-y-2"><p className="text-sm">Review outcome: {visit.allergy_reviews?.at(-1)?.outcome || 'Not reviewed for this visit'}</p><select className={field} value={reviewOutcome} onChange={e => setReviewOutcome(e.target.value)}><option value="UNKNOWN">Unknown / not established</option><option value="NO_KNOWN" disabled={activeAllergies.length > 0}>No known allergies</option><option value="RECORDED" disabled={activeAllergies.length === 0}>Recorded active allergies</option></select><button disabled={busy} className={button} onClick={() => run(() => reviewEncounterAllergies(visit.id, { expected_version: visit.version, outcome: reviewOutcome }), 'Allergies reviewed for this visit.')}>Record explicit allergy review</button></div>
        </>}
      </>}
      </section>
    </>}
  </div>;
}
