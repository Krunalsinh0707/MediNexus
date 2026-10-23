import { useCallback, useEffect, useState } from 'react';
import { createMedicationOrder, listMedicationOrders, transitionMedicationOrder } from '../../services/medicationOrderService';
import { clinicalOrderError, clinicalOrderErrorIsRetryable, orderActionLabel } from '../clinicalOrderUi';
import { medicationOrderCanSubmit, medicationStatusMessage, visibleMedicationOrders } from '../medicationOrderUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-[#0F9D8A] px-4 py-2 text-sm font-bold text-white disabled:opacity-50';
const localDate = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const emptyForm = () => ({
  priority: 'ROUTINE', medication_identifier_system: 'LOCAL', medication_identifier: '',
  medication_display_name: '', dose: '', dose_unit: '', route: '', frequency: '',
  duration_value: '', duration_unit: '', quantity: '', quantity_unit: '',
  start_date: localDate(), instructions: '',
});

export default function MedicationOrdersPanel({ encounter, doctorId, allergyContext }) {
  const [items, setItems] = useState([]);
  const [loadedEncounterId, setLoadedEncounterId] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [allergyAcknowledged, setAllergyAcknowledged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [unavailable, setUnavailable] = useState(false);
  const [retryable, setRetryable] = useState(false);

  const load = useCallback(async () => {
    if (!encounter?.id) return;
    setLoading(true); setError(''); setRetryable(false);
    try {
      const result = await listMedicationOrders({ encounter_id: encounter.id });
      setItems(Array.isArray(result?.items) ? result.items : []);
      setLoadedEncounterId(encounter.id); setUnavailable(false);
    } catch (err) {
      const parsed = clinicalOrderError(err);
      setItems([]); setLoadedEncounterId(encounter.id);
      setError(parsed.message); setUnavailable(parsed.unavailable);
      setRetryable(clinicalOrderErrorIsRetryable(err));
    } finally {
      setLoading(false);
    }
  }, [encounter?.id]);

  useEffect(() => {
    let active = true;
    setForm(emptyForm()); setAllergyAcknowledged(false); setMessage(''); setError('');
    setUnavailable(false); setRetryable(false); setLoading(true);
    listMedicationOrders({ encounter_id: encounter?.id })
      .then(result => {
        if (!active) return;
        setItems(Array.isArray(result?.items) ? result.items : []);
        setLoadedEncounterId(encounter?.id ?? null);
      })
      .catch(err => {
        if (!active) return;
        const parsed = clinicalOrderError(err);
        setItems([]); setLoadedEncounterId(encounter?.id ?? null);
        setError(parsed.message); setUnavailable(parsed.unavailable);
        setRetryable(clinicalOrderErrorIsRetryable(err));
      })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [encounter?.id]);

  const run = async (action, success) => {
    setBusy(true); setError(''); setMessage(''); setRetryable(false);
    try { await action(); await load(); setMessage(success); }
    catch (err) {
      const parsed = clinicalOrderError(err);
      setError(parsed.message); setUnavailable(parsed.unavailable);
      setRetryable(clinicalOrderErrorIsRetryable(err));
    } finally { setBusy(false); }
  };

  const submit = event => {
    event.preventDefault();
    run(async () => {
      await createMedicationOrder({
        patient_id: encounter.patient_id,
        encounter_id: encounter.id,
        ...form,
        dose: Number(form.dose),
        duration_value: form.duration_value ? Number(form.duration_value) : null,
        duration_unit: form.duration_unit || null,
        quantity: Number(form.quantity),
        instructions: form.instructions.trim() || null,
        allergy_review_acknowledged: true,
      });
      setForm(emptyForm()); setAllergyAcknowledged(false);
    }, 'Prescription draft created. Review and sign it before it is shared as a signed medication order.');
  };

  const transition = (item, status) => {
    let reason = null;
    if (status === 'CANCELLED') {
      reason = window.prompt('Reason for cancelling this prescription')?.trim();
      if (!reason) return;
    }
    run(
      () => transitionMedicationOrder(item.order.id, { expected_version: item.order.version, status, reason }),
      status === 'SIGNED' ? 'Prescription signed.' : 'Prescription cancelled.',
    );
  };

  const canPrescribe = encounter?.doctor_id === doctorId && encounter?.status === 'IN_PROGRESS';
  const visible = visibleMedicationOrders(items, loadedEncounterId, encounter?.id);
  const activeAllergies = (allergyContext?.current_records || []).filter(item => item.status === 'ACTIVE');
  const legacyAllergies = allergyContext?.legacy_unverified || [];
  const canSubmit = medicationOrderCanSubmit(form, allergyContext, allergyAcknowledged);

  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
    <div><h2 className="font-bold text-slate-900">Medication prescriptions</h2><p className="text-sm text-slate-600">Prescribing only. Dispensing, inventory deduction, and administration require separate verified workflows.</p></div>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{error}{retryable && !unavailable && <button type="button" className="ml-2 font-bold underline" onClick={load}>Retry</button>}</div>}
    {message && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">{message}</p>}
    {loading ? <p className="text-sm text-slate-500">Loading medication orders…</p> : unavailable ? <button type="button" className="text-sm font-bold text-teal-700" onClick={load}>Retry medication storage check</button> : <>
      {!visible.length ? <p className="text-sm text-slate-500">No medication orders for this visit.</p> : <div className="space-y-3">{visible.map(item => <article key={item.order.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm space-y-2">
        <div className="flex flex-wrap justify-between gap-2"><strong>{item.medication.medication_display_name}</strong><span className="rounded-full bg-white px-2 py-1 text-xs font-bold">{item.order.status}</span></div>
        <p>{item.medication.dose} {item.medication.dose_unit} · {item.medication.route} · {item.medication.frequency}</p>
        <p>{item.medication.quantity} {item.medication.quantity_unit}{item.medication.duration_value ? ` · ${item.medication.duration_value} ${item.medication.duration_unit.toLowerCase()}` : ''} · starts {item.medication.start_date}</p>
        {item.medication.instructions && <p><strong>Instructions:</strong> {item.medication.instructions}</p>}
        <p className="text-xs text-slate-500">{medicationStatusMessage(item.order.status)}</p>
        {(item.medication.allergy_warnings || []).map((warning, index) => <p key={`${warning.source}-${index}`} className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900"><strong>Allergy review:</strong> {warning.message} ({warning.substance})</p>)}
        <div className="flex gap-2">{(item.order.allowed_actions || []).map(action => <button type="button" key={action} disabled={busy} className={action === 'CANCELLED' ? 'rounded-xl border border-rose-200 px-3 py-2 text-xs font-bold text-rose-700 disabled:opacity-50' : button} onClick={() => transition(item, action)}>{orderActionLabel(action)}</button>)}</div>
      </article>)}</div>}
      {canPrescribe && <form className="space-y-3 border-t border-slate-200 pt-4" onSubmit={submit}>
        <h3 className="font-bold text-slate-900">New prescription draft</h3>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950"><strong>Allergy review required.</strong>
          {!allergyContext ? <p>Allergy context is unavailable. Reload the visit before prescribing.</p> : <>
            {activeAllergies.length === 0 && legacyAllergies.length === 0 && <p>No active structured allergy or legacy allergy text is displayed. This does not constitute comprehensive interaction checking.</p>}
            {activeAllergies.map(item => <p key={item.id}>Recorded active allergy: {item.substance} · {item.severity}</p>)}
            {legacyAllergies.map((item, index) => <p key={index}>Legacy unverified allergy text: {item}</p>)}
            <p>No comprehensive drug interaction or formulary check is performed.</p>
          </>}
        </div>
        <div className="grid gap-3 md:grid-cols-3"><label className="text-xs font-semibold">Identifier system<input required maxLength={64} className={field} value={form.medication_identifier_system} onChange={e => setForm(current => ({ ...current, medication_identifier_system: e.target.value }))} /></label><label className="text-xs font-semibold">Medication identifier<input required maxLength={128} className={field} value={form.medication_identifier} onChange={e => setForm(current => ({ ...current, medication_identifier: e.target.value }))} /></label><label className="text-xs font-semibold">Medication display name<input required maxLength={255} className={field} value={form.medication_display_name} onChange={e => setForm(current => ({ ...current, medication_display_name: e.target.value }))} /></label></div>
        <div className="grid gap-3 md:grid-cols-4"><label className="text-xs font-semibold">Dose<input required min="0.0001" step="any" type="number" className={field} value={form.dose} onChange={e => setForm(current => ({ ...current, dose: e.target.value }))} /></label><label className="text-xs font-semibold">Dose unit<input required maxLength={32} className={field} value={form.dose_unit} onChange={e => setForm(current => ({ ...current, dose_unit: e.target.value }))} /></label><label className="text-xs font-semibold">Route<input required maxLength={64} className={field} value={form.route} onChange={e => setForm(current => ({ ...current, route: e.target.value }))} /></label><label className="text-xs font-semibold">Frequency<input required maxLength={128} className={field} value={form.frequency} onChange={e => setForm(current => ({ ...current, frequency: e.target.value }))} /></label></div>
        <div className="grid gap-3 md:grid-cols-5"><label className="text-xs font-semibold">Duration<input min="1" max="3650" type="number" className={field} value={form.duration_value} onChange={e => setForm(current => ({ ...current, duration_value: e.target.value }))} /></label><label className="text-xs font-semibold">Duration unit<select className={field} value={form.duration_unit} onChange={e => setForm(current => ({ ...current, duration_unit: e.target.value }))}><option value="">None</option>{['DAYS', 'WEEKS', 'MONTHS', 'DOSES'].map(value => <option key={value}>{value}</option>)}</select></label><label className="text-xs font-semibold">Quantity<input required min="0.001" step="any" type="number" className={field} value={form.quantity} onChange={e => setForm(current => ({ ...current, quantity: e.target.value }))} /></label><label className="text-xs font-semibold">Quantity unit<input required maxLength={64} className={field} value={form.quantity_unit} onChange={e => setForm(current => ({ ...current, quantity_unit: e.target.value }))} /></label><label className="text-xs font-semibold">Start date<input required type="date" className={field} value={form.start_date} onChange={e => setForm(current => ({ ...current, start_date: e.target.value }))} /></label></div>
        <div className="grid gap-3 md:grid-cols-3"><label className="text-xs font-semibold">Priority<select className={field} value={form.priority} onChange={e => setForm(current => ({ ...current, priority: e.target.value }))}>{['ROUTINE', 'URGENT', 'STAT'].map(value => <option key={value}>{value}</option>)}</select></label><label className="text-xs font-semibold md:col-span-2">Patient instructions<textarea maxLength={4000} rows={2} className={field} value={form.instructions} onChange={e => setForm(current => ({ ...current, instructions: e.target.value }))} /></label></div>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={allergyAcknowledged} onChange={e => setAllergyAcknowledged(e.target.checked)} />I reviewed the current encounter allergy context and understand that no comprehensive interaction check was performed.</label>
        <button className={button} disabled={busy || !canSubmit}>Create prescription draft</button>
      </form>}
    </>}
  </section>;
}
