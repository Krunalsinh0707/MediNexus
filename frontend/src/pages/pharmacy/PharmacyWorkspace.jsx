import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Pill, RefreshCw, Search } from 'lucide-react';

import {
  getPharmacyPrescription, listPharmacyPrescriptions, transitionPharmacyPrescription,
} from '../../services/pharmacyService';
import {
  canSubmitPharmacyAction, pharmacyActionLabel, pharmacyError,
  pharmacyErrorIsRetryable, pharmacyTransitionPayload,
} from '../pharmacyUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const primary = 'rounded-xl bg-[#0F9D8A] px-3 py-2 text-sm font-bold text-white disabled:opacity-50';
const blankAction = { reason: '', quantity: '', quantity_unit: '', stock_item_identifier: '' };

export default function PharmacyWorkspace() {
  const [filters, setFilters] = useState({ search: '', prescription_id: '', priority: '', status: '' });
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [action, setAction] = useState('');
  const [actionForm, setActionForm] = useState(blankAction);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retryable, setRetryable] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError(''); setRetryable(false);
    try {
      const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => String(value).trim()));
      const result = await listPharmacyPrescriptions(params);
      const next = Array.isArray(result?.items) ? result.items : [];
      setItems(next);
      setSelected(current => next.find(item => item.prescription_id === current?.prescription_id) || next[0] || null);
    } catch (err) {
      const parsed = pharmacyError(err);
      setItems([]); setSelected(null); setError(parsed.message); setRetryable(pharmacyErrorIsRetryable(err));
    } finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { load(); }, [load]);

  const choose = async id => {
    setBusy(true); setError('');
    try { setSelected(await getPharmacyPrescription(id)); }
    catch (err) { const parsed = pharmacyError(err); setError(parsed.message); setRetryable(pharmacyErrorIsRetryable(err)); }
    finally { setBusy(false); }
  };

  const submit = async event => {
    event.preventDefault();
    if (!selected || !canSubmitPharmacyAction(action, actionForm)) return;
    setBusy(true); setError(''); setMessage(''); setRetryable(false);
    try {
      const updated = await transitionPharmacyPrescription(
        selected.prescription_id, pharmacyTransitionPayload(selected, action, actionForm),
      );
      setSelected(updated); setAction(''); setActionForm(blankAction);
      setMessage(`Pharmacy workflow updated to ${updated.pharmacy_status.replaceAll('_', ' ').toLowerCase()}.`);
      await load();
    } catch (err) {
      const parsed = pharmacyError(err);
      setError(parsed.message); setRetryable(pharmacyErrorIsRetryable(err));
    } finally { setBusy(false); }
  };

  const setFilter = (name, value) => setFilters(current => ({ ...current, [name]: value }));
  const med = selected?.medication;
  const needsReason = action === 'REJECTED' || action === 'CLARIFICATION_REQUESTED';
  const dispensing = action === 'PARTIALLY_DISPENSED' || action === 'COMPLETED';

  return <div className="min-h-full bg-[#F6F9FB] p-4 md:p-8 space-y-5">
    <header><h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900"><Pill className="text-teal-600" />Pharmacy workspace</h1><p className="text-sm text-slate-600">Review signed prescriptions and record dispensing only through verified inventory transactions.</p></header>
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm space-y-3">
      <div className="grid gap-3 md:grid-cols-5">
        <label className="md:col-span-2 text-xs font-semibold">Patient MRN or medication<div className="relative"><Search size={16} className="absolute left-3 top-3 text-slate-400" /><input className={`${field} pl-9`} value={filters.search} onChange={e => setFilter('search', e.target.value)} /></div></label>
        <label className="text-xs font-semibold">Prescription ID<input className={field} min="1" type="number" value={filters.prescription_id} onChange={e => setFilter('prescription_id', e.target.value)} /></label>
        <label className="text-xs font-semibold">Priority<select className={field} value={filters.priority} onChange={e => setFilter('priority', e.target.value)}><option value="">All</option>{['ROUTINE', 'URGENT', 'STAT'].map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="text-xs font-semibold">Status<select className={field} value={filters.status} onChange={e => setFilter('status', e.target.value)}><option value="">All</option>{['AWAITING_REVIEW', 'ACCEPTED', 'CLARIFICATION_REQUESTED', 'REJECTED', 'IN_PROGRESS', 'PARTIALLY_DISPENSED', 'COMPLETED', 'PRESCRIPTION_CANCELLED'].map(value => <option key={value}>{value.replaceAll('_', ' ')}</option>)}</select></label>
      </div>
    </section>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><AlertTriangle className="mr-2 inline" size={16} />{error}{retryable && <button type="button" className="ml-2 font-bold underline" onClick={load}>Reload queue</button>}</div>}
    {message && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">{message}</p>}
    {loading ? <p className="text-sm text-slate-500">Loading pharmacy queue…</p> : <div className="grid gap-5 lg:grid-cols-[minmax(280px,0.85fr)_minmax(0,1.5fr)]">
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3 flex items-center justify-between"><h2 className="font-bold">Prescription queue</h2><button aria-label="Refresh queue" onClick={load} disabled={busy}><RefreshCw size={17} /></button></div>
        {!items.length ? <p className="text-sm text-slate-500">No signed prescriptions match these filters.</p> : <div className="space-y-2">{items.map(item => <button type="button" key={item.prescription_id} onClick={() => choose(item.prescription_id)} className={`w-full rounded-xl border p-3 text-left text-sm ${selected?.prescription_id === item.prescription_id ? 'border-teal-400 bg-teal-50' : 'border-slate-200 hover:bg-slate-50'}`}><span className="flex justify-between gap-2"><strong>{item.medication.medication_display_name}</strong><span>{item.priority}</span></span><span className="block text-slate-600">{item.patient.mrn} · {item.patient.full_name}</span><span className="text-xs font-semibold text-teal-800">{item.pharmacy_status.replaceAll('_', ' ')}</span></button>)}</div>}
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        {!selected ? <p className="text-sm text-slate-500">Select a prescription to review.</p> : <>
          <div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-lg font-bold">Prescription #{selected.prescription_id}</h2><p className="text-sm text-slate-600">{selected.patient.mrn} · {selected.patient.full_name} · Prescribed by {selected.prescriber.full_name}</p></div><span className="h-fit rounded-full bg-slate-100 px-3 py-1 text-xs font-bold">{selected.pharmacy_status.replaceAll('_', ' ')}</span></div>
          <div className="grid gap-2 rounded-xl bg-slate-50 p-4 text-sm md:grid-cols-2"><p><strong>Medication:</strong> {med.medication_display_name} ({med.medication_identifier})</p><p><strong>Dose:</strong> {med.dose} {med.dose_unit} · {med.route} · {med.frequency}</p><p><strong>Quantity:</strong> {med.quantity} {med.quantity_unit}</p><p><strong>Start:</strong> {med.start_date}{med.duration_value ? ` · ${med.duration_value} ${med.duration_unit.toLowerCase()}` : ''}</p>{med.instructions && <p className="md:col-span-2"><strong>Instructions:</strong> {med.instructions}</p>}</div>
          {(selected.allergy_warnings || []).map((warning, index) => <p key={index} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><strong>Recorded allergy warning:</strong> {warning.message}</p>)}
          {!selected.inventory_ready && <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Inventory verification is unavailable. Dispensing actions are disabled; review actions remain available.</p>}
          {(selected.allowed_actions || []).length > 0 && <div className="flex flex-wrap gap-2">{selected.allowed_actions.map(value => <button type="button" className={value === 'REJECTED' ? 'rounded-xl border border-rose-200 px-3 py-2 text-sm font-bold text-rose-700' : primary} disabled={busy} key={value} onClick={() => { setAction(value); setActionForm(blankAction); }}>{pharmacyActionLabel(value)}</button>)}</div>}
          {action && <form onSubmit={submit} className="rounded-xl border border-slate-200 p-4 space-y-3"><h3 className="font-bold">{pharmacyActionLabel(action)}</h3>{needsReason && <label className="block text-xs font-semibold">Reason<textarea autoFocus required maxLength={4000} className={field} value={actionForm.reason} onChange={e => setActionForm(current => ({ ...current, reason: e.target.value }))} /></label>}{dispensing && <div className="grid gap-3 md:grid-cols-3"><label className="text-xs font-semibold">Quantity<input required min="0.001" step="any" type="number" className={field} value={actionForm.quantity} onChange={e => setActionForm(current => ({ ...current, quantity: e.target.value }))} /></label><label className="text-xs font-semibold">Unit<input required maxLength={64} className={field} value={actionForm.quantity_unit} onChange={e => setActionForm(current => ({ ...current, quantity_unit: e.target.value }))} /></label><label className="text-xs font-semibold">Stock item identifier<input required maxLength={128} className={field} value={actionForm.stock_item_identifier} onChange={e => setActionForm(current => ({ ...current, stock_item_identifier: e.target.value }))} /></label></div>}<div className="flex gap-2"><button className={primary} disabled={busy || !canSubmitPharmacyAction(action, actionForm)}>Confirm</button><button type="button" className="rounded-xl border border-slate-200 px-3 py-2 text-sm font-bold" onClick={() => setAction('')}>Cancel</button></div></form>}
          <div><h3 className="font-bold">Workflow history</h3>{!selected.events?.length ? <p className="text-sm text-slate-500">No pharmacy actions recorded.</p> : <ol className="mt-2 space-y-2 text-sm">{selected.events.map(event => <li key={event.sequence} className="rounded-lg border border-slate-100 p-2">#{event.sequence} {event.from_status || 'AWAITING REVIEW'} → {event.to_status}{event.reason ? ` · ${event.reason}` : ''}</li>)}</ol>}</div>
          <div><h3 className="font-bold">Dispensing history</h3>{!selected.dispensing_history?.length ? <p className="text-sm text-slate-500">No medication has been recorded as dispensed.</p> : <ul className="mt-2 space-y-2 text-sm">{selected.dispensing_history.map((record, index) => <li key={`${record.inventory_transaction_reference}-${index}`}>{record.quantity} {record.quantity_unit} · inventory transaction {record.inventory_transaction_reference}</li>)}</ul>}</div>
        </>}
      </section>
    </div>}
  </div>;
}
