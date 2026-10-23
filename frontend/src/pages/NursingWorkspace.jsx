import { useCallback, useEffect, useRef, useState } from 'react';
import { ClipboardList, RefreshCw } from 'lucide-react';
import * as nursing from '../services/nursingService';
import { allowed, measurementNames, medicationState, nursingError } from './nursingUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-[#0F9D8A] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50';
const blankVitals = { measured_at: '', previous_id: null, correction_reason: '', ...Object.fromEntries(measurementNames.map(([key]) => [key, ''])) };
const label = value => String(value || '').replaceAll('_', ' ');

export default function NursingWorkspace() {
  const [census, setCensus] = useState([]), [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [retryable, setRetryable] = useState(false), [message, setMessage] = useState('');
  const [vitals, setVitals] = useState(blankVitals);
  const [note, setNote] = useState({ kind: 'ASSESSMENT', content: '' });
  const [plan, setPlan] = useState({ goal: '', intervention: '' });
  const [taskText, setTaskText] = useState({});
  const selectedId = useRef(null);
  const clearDrafts = useCallback(() => {
    setVitals(blankVitals); setNote({ kind: 'ASSESSMENT', content: '' });
    setPlan({ goal: '', intervention: '' }); setTaskText({});
  }, []);
  const showError = err => { const result = nursingError(err); setError(result.message); setRetryable(result.retryable); };

  const load = useCallback(async (preferredId = null) => {
    setLoading(true); setError('');
    try {
      const response = await nursing.getNursingCensus({ limit: 100 });
      const items = Array.isArray(response?.items) ? response.items : [];
      setCensus(items);
      const target = preferredId || items[0]?.admission_id;
      if (selectedId.current !== target) { clearDrafts(); selectedId.current = target || null; }
      setSelected(target && items.some(row => row.admission_id === target)
        ? await nursing.getNursingWorkspace(target) : null);
    } catch (err) {
      const result = nursingError(err); setError(result.message); setRetryable(result.retryable);
      setCensus([]); setSelected(null);
    } finally { setLoading(false); }
  }, [clearDrafts]);
  useEffect(() => { load(); }, [load]);

  const choose = async id => {
    setBusy(true); setError('');
    if (selectedId.current !== id) { clearDrafts(); selectedId.current = id; }
    try { setSelected(await nursing.getNursingWorkspace(id)); }
    catch (err) { showError(err); setSelected(null); }
    finally { setBusy(false); }
  };
  const save = async (operation, messageText) => {
    setBusy(true); setError(''); setMessage('');
    try {
      const updated = await operation(); setSelected(updated); setMessage(messageText);
      setCensus(current => current.map(row => row.admission_id === updated.admission_id
        ? { ...row, admission_status: updated.admission_status } : row));
      return true;
    } catch (err) { showError(err); return false; }
    finally { setBusy(false); }
  };
  const recordVitals = event => {
    event.preventDefault();
    if (!selected?.can_record) return;
    const measurements = Object.fromEntries(measurementNames.map(([key]) => [key, vitals[key] === '' ? null : Number(vitals[key])]));
    if (Object.values(measurements).every(value => value === null)) { setError('Record at least one measured value.'); return; }
    if ((measurements.systolic_mmhg === null) !== (measurements.diastolic_mmhg === null)) { setError('Enter both blood pressure values.'); return; }
    save(() => nursing.recordNursingObservation(selected.admission_id, {
      measured_at: new Date(vitals.measured_at).toISOString(), previous_id: vitals.previous_id,
      correction_reason: vitals.previous_id ? vitals.correction_reason.trim() : null, ...measurements,
    }), vitals.previous_id ? 'Correction recorded without altering the previous observation.' : 'Observation recorded. Review any flagged values.')
      .then(saved => { if (saved) setVitals(blankVitals); });
  };
  const saveNote = event => {
    event.preventDefault(); if (!selected?.can_record) return;
    save(() => nursing.addNursingNote(selected.admission_id, { kind: note.kind, content: note.content.trim() }),
      'Final nursing note saved.').then(saved => { if (saved) setNote({ kind: 'ASSESSMENT', content: '' }); });
  };
  const savePlan = event => {
    event.preventDefault(); if (!selected?.can_record) return;
    save(() => nursing.addNursingPlan(selected.admission_id, { goal: plan.goal.trim(), intervention: plan.intervention.trim() }),
      'Care plan draft created.').then(saved => { if (saved) setPlan({ goal: '', intervention: '' }); });
  };
  const doTransition = (kind, row, status) => {
    if (!selected?.can_record || !allowed(row, status)) return;
    const reason = status === 'CANCELLED' ? window.prompt('Reason for cancellation')?.trim() : null;
    if (status === 'CANCELLED' && !reason) return;
    const call = kind === 'plan' ? nursing.transitionNursingPlan : nursing.transitionNursingTask;
    save(() => call(selected.admission_id, row.id, { expected_version: row.version, status, reason }),
      `${kind === 'plan' ? 'Care plan' : 'Task'} marked ${label(status).toLowerCase()}.`);
  };
  return <div className="min-h-full space-y-5 bg-[#F6F9FB] p-4 md:p-8">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="flex items-center gap-2 text-2xl font-bold"><ClipboardList className="text-teal-600"/>Nursing station</h1><p className="text-sm text-slate-600">Assigned active inpatients, observations, care plans, and handovers. Medication administration is unavailable.</p></div><button className={button} onClick={() => load(selected?.admission_id)} disabled={busy || loading}><RefreshCw size={16} className="mr-1 inline"/>Reload</button></header>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">{error}{retryable && <button className="ml-2 font-bold underline" onClick={() => load(selected?.admission_id)}>Reload</button>}</div>}
    {message && <p role="status" className="rounded-xl bg-teal-50 p-3 text-sm">{message}</p>}
    {loading ? <p className="text-sm">Loading assigned inpatients…</p> : <div className="grid gap-5 lg:grid-cols-[.8fr_1.5fr]"><section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Current census</h2>{!census.length ? <p className="text-sm text-slate-500">No active inpatients in your assigned wards.</p> : census.map(row => <button key={row.admission_id} onClick={() => choose(row.admission_id)} disabled={busy} className={`w-full rounded-xl border p-3 text-left text-sm ${selected?.admission_id === row.admission_id ? 'border-teal-400 bg-teal-50' : ''}`}><strong>{row.patient_name} · {row.mrn}</strong><span className="block">Ward {row.ward_id} · Room {row.room_code} · Bed {row.bed_code}</span><span>Admission #{row.admission_id} · Encounter #{row.encounter_id} · {label(row.admission_status)}</span></button>)}</section>
      <div className="space-y-5">{selected ? <>
        <section className="rounded-2xl border bg-white p-5"><h2 className="text-lg font-bold">{selected.patient_name} · {selected.mrn}</h2><p className="text-sm text-slate-600">Admission #{selected.admission_id} · {label(selected.admission_status)} · Ward {selected.ward_id} / Room {selected.room_code} / Bed {selected.bed_code} · Encounter #{selected.encounter_id} ({label(selected.encounter_status)})</p></section>
        <section className="space-y-3 rounded-2xl border bg-white p-5"><h2 className="font-bold">Vital-sign observations</h2><p className="text-xs text-slate-500">Clinician measurements and nursing observations have separate attribution. Flags prompt review; they are not diagnoses.</p>{!selected.observations?.length ? <p className="text-sm text-slate-500">No observations recorded.</p> : selected.observations.map(row => <article key={`${row.source}-${row.id}`} className="rounded-xl border p-3 text-sm"><strong>{row.source === 'CLINICIAN' ? 'Clinician measurement' : 'Nursing observation'} · {new Date(row.measured_at).toLocaleString()}</strong><p>Recorded by account #{row.recorded_by_user_id}{row.previous_id ? ` · Correction of #${row.previous_id}` : ''}</p><p>{measurementNames.filter(([key]) => row.measurements?.[key] !== null && row.measurements?.[key] !== undefined).map(([key, name, unit]) => `${name}: ${row.measurements[key]} ${unit}`).join(' · ')}</p>{row.correction_reason && <p>Correction reason: {row.correction_reason}</p>}{row.review_flags?.map(value => <p className="text-amber-700" key={value}>{value}</p>)}{selected.can_record && row.source === 'NURSING' && <button className="mt-1 font-semibold text-teal-700 underline" onClick={() => setVitals({ ...blankVitals, previous_id: row.id })}>Correct with new observation</button>}</article>)}
        {selected.can_record && <form onSubmit={recordVitals} className="space-y-3 rounded-xl bg-slate-50 p-3"><h3 className="font-bold">{vitals.previous_id ? `Correct observation #${vitals.previous_id}` : 'Record observation'}</h3><label className="block text-sm">Measured at<input required type="datetime-local" className={field} value={vitals.measured_at} onChange={e => setVitals(prev => ({ ...prev, measured_at: e.target.value }))}/></label><div className="grid gap-2 md:grid-cols-2">{measurementNames.map(([key, name, unit]) => <label className="text-sm" key={key}>{name} ({unit})<input type="number" step="0.01" className={field} value={vitals[key]} onChange={e => setVitals(prev => ({ ...prev, [key]: e.target.value }))}/></label>)}</div>{vitals.previous_id && <label className="block text-sm">Correction reason<textarea required className={field} value={vitals.correction_reason} onChange={e => setVitals(prev => ({ ...prev, correction_reason: e.target.value }))}/></label>}<button className={button} disabled={busy}>Save observation</button></form>}</section>
        <section className="space-y-3 rounded-2xl border bg-white p-5"><h2 className="font-bold">Nursing assessments and shift handovers</h2>{!selected.notes?.length ? <p className="text-sm text-slate-500">No finalized nursing notes.</p> : selected.notes.map(row => <article key={row.id} className="rounded-xl border p-3 text-sm"><strong>{label(row.kind)} · {new Date(row.created_at).toLocaleString()}</strong><p className="whitespace-pre-wrap">{row.content}</p><small>Author account #{row.author_user_id}</small></article>)}{selected.can_record && <form onSubmit={saveNote} className="space-y-2 rounded-xl bg-slate-50 p-3"><select className={field} value={note.kind} onChange={e => setNote(prev => ({ ...prev, kind: e.target.value }))}><option value="ASSESSMENT">Assessment</option><option value="HANDOVER">Shift handover</option></select><textarea required className={field} value={note.content} onChange={e => setNote(prev => ({ ...prev, content: e.target.value }))} placeholder="Document observed findings or handover details"/><button className={button} disabled={busy}>Finalize note</button></form>}</section>
        <section className="space-y-3 rounded-2xl border bg-white p-5"><h2 className="font-bold">Care plans and tasks</h2>{!selected.plans?.length ? <p className="text-sm text-slate-500">No care plans recorded.</p> : selected.plans.map(row => <article key={row.id} className="space-y-2 rounded-xl border p-3 text-sm"><strong>Plan #{row.id} · {label(row.status)}</strong><p><b>Goal:</b> {row.goal}</p><p><b>Intervention:</b> {row.intervention}</p><div className="flex gap-2">{row.allowed_actions?.map(status => <button key={status} disabled={busy} className="font-semibold text-teal-700 underline" onClick={() => doTransition('plan', row, status)}>{label(status)}</button>)}</div><h3 className="font-semibold">Tasks</h3>{!row.tasks?.length ? <p className="text-slate-500">No tasks yet.</p> : row.tasks.map(task => <div key={task.id} className="rounded-lg bg-slate-50 p-2"><span>{task.description} · {label(task.status)}</span><div className="flex gap-2">{task.allowed_actions?.map(status => <button key={status} disabled={busy} className="font-semibold text-teal-700 underline" onClick={() => doTransition('task', task, status)}>{label(status)}</button>)}</div></div>)}{selected.can_record && row.status === 'ACTIVE' && <form onSubmit={e => { e.preventDefault(); save(() => nursing.addNursingTask(selected.admission_id, row.id, { description: (taskText[row.id] || '').trim() }), 'Task created as pending.').then(saved => { if (saved) setTaskText(prev => ({ ...prev, [row.id]: '' })); }); }} className="flex gap-2"><input required className={field} value={taskText[row.id] || ''} onChange={e => setTaskText(prev => ({ ...prev, [row.id]: e.target.value }))} placeholder="New task"/><button className={button} disabled={busy}>Add task</button></form>}</article>)}{selected.can_record && <form onSubmit={savePlan} className="space-y-2 rounded-xl bg-slate-50 p-3"><h3 className="font-semibold">New care plan</h3><textarea required className={field} placeholder="Goal" value={plan.goal} onChange={e => setPlan(prev => ({ ...prev, goal: e.target.value }))}/><textarea required className={field} placeholder="Intervention" value={plan.intervention} onChange={e => setPlan(prev => ({ ...prev, intervention: e.target.value }))}/><button className={button} disabled={busy}>Save draft plan</button></form>}{selected.workflow_history?.length > 0 && <div className="rounded-xl bg-slate-50 p-3 text-sm"><h3 className="font-semibold">Workflow history</h3>{selected.workflow_history.map(row => <p key={row.id}>{row.plan_id ? `Plan #${row.plan_id}` : `Task #${row.task_id}`} · {label(row.from_status || 'NEW')} → {label(row.to_status)} · Account #{row.actor_user_id}{row.reason ? ` · ${row.reason}` : ''}</p>)}</div>}</section>
        <section className="space-y-2 rounded-2xl border bg-white p-5"><h2 className="font-bold">Signed clinical orders and medication safety</h2>{!selected.orders_available ? <p className="text-sm text-amber-700">Clinical order storage is unavailable; no order status can be confirmed.</p> : !selected.orders?.length ? <p className="text-sm text-slate-500">No signed orders linked to this encounter.</p> : selected.orders.map(row => <article key={row.id} className="rounded-xl border p-3 text-sm"><strong>{row.display_name} · {label(row.order_type)}</strong><p>Order #{row.id} · {label(row.status)} · {label(row.priority)}</p>{row.order_type === 'MEDICATION' && <><p>{row.medication ? `${row.medication.dose} ${row.medication.dose_unit} · ${row.medication.route} · ${row.medication.frequency}` : 'Medication detail unavailable'}</p><p>Prescription: {label(medicationState(row).prescription)} · Pharmacy: {label(medicationState(row).pharmacy)} · Administration: unavailable</p></>}</article>)}<p className="text-xs text-slate-500">A prescription or pharmacy event does not confirm administration. Administration recording is unavailable.</p></section>
      </> : <section className="rounded-2xl border bg-white p-5 text-sm text-slate-500">Select an assigned inpatient to review nursing records.</section>}</div></div>}
  </div>;
}
