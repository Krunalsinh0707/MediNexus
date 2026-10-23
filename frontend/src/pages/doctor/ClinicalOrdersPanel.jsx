import { useCallback, useEffect, useState } from 'react';
import { getDepartments } from '../../services/hospitalService';
import { createClinicalOrder, listClinicalOrders, transitionClinicalOrder } from '../../services/clinicalOrderService';
import { createImagingOrder, getReleasedRadiologyReport } from '../../services/radiologyService';
import { getFinalLaboratoryResults } from '../../services/laboratoryService';
import { canCreateClinicalOrder, clinicalOrderError, clinicalOrderErrorIsRetryable, orderActionLabel, ordersForEncounter, releasedResultForEncounter } from '../clinicalOrderUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-[#0F9D8A] px-4 py-2 text-sm font-bold text-white disabled:opacity-50';
const blank = { destination_department_id: '', order_type: 'LAB', priority: 'ROUTINE', order_code: '', display_name: '', clinical_indication: '', modality: '', body_region: '' };

export default function ClinicalOrdersPanel({ encounter, doctorId }) {
  const [orders, setOrders] = useState([]);
  const [loadedEncounterId, setLoadedEncounterId] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [form, setForm] = useState(blank);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [conflict, setConflict] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [retryable, setRetryable] = useState(false);
  const [departmentError, setDepartmentError] = useState('');
  const [released, setReleased] = useState({});
  const [resultBusy, setResultBusy] = useState(null);

  const load = useCallback(async () => {
    if (!encounter?.id) return;
    setLoading(true); setError(''); setConflict(false); setRetryable(false);
    try {
      const result = await listClinicalOrders({ encounter_id: encounter.id });
      setOrders(Array.isArray(result?.items) ? result.items : []);
      setLoadedEncounterId(encounter.id);
      setUnavailable(false);
    } catch (err) {
      setOrders([]); setLoadedEncounterId(encounter.id);
      const parsed = clinicalOrderError(err);
      setError(parsed.message); setConflict(parsed.conflict); setUnavailable(parsed.unavailable);
      setRetryable(clinicalOrderErrorIsRetryable(err));
    } finally {
      setLoading(false);
    }
  }, [encounter?.id]);

  useEffect(() => {
    let active = true;
    setForm(blank); setMessage(''); setError(''); setConflict(false); setUnavailable(false); setRetryable(false);
    setDepartmentError(''); setLoading(true);
    setReleased({});
    Promise.allSettled([listClinicalOrders({ encounter_id: encounter?.id }), getDepartments()])
      .then(([ordersResult, departmentsResult]) => {
        if (!active) return;
        if (ordersResult.status === 'fulfilled') {
          setOrders(Array.isArray(ordersResult.value?.items) ? ordersResult.value.items : []);
          setLoadedEncounterId(encounter?.id ?? null);
        } else {
          setOrders([]); setLoadedEncounterId(encounter?.id ?? null);
          const parsed = clinicalOrderError(ordersResult.reason);
          setError(parsed.message); setConflict(parsed.conflict); setUnavailable(parsed.unavailable);
          setRetryable(clinicalOrderErrorIsRetryable(ordersResult.reason));
        }
        if (departmentsResult.status === 'fulfilled') {
          const result = departmentsResult.value;
          setDepartments(Array.isArray(result) ? result : result?.departments || []);
        } else {
          setDepartments([]);
          setDepartmentError('Departments could not be loaded. Retry before creating an order.');
        }
      })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [encounter?.id]);

  const run = async (action, success) => {
    setBusy(true); setError(''); setMessage(''); setConflict(false); setRetryable(false);
    try { await action(); await load(); setMessage(success); }
    catch (err) { const parsed = clinicalOrderError(err); setError(parsed.message); setConflict(parsed.conflict); setUnavailable(parsed.unavailable); setRetryable(clinicalOrderErrorIsRetryable(err)); }
    finally { setBusy(false); }
  };

  const submit = event => {
    event.preventDefault();
    run(async () => {
      const common = {
        patient_id: encounter.patient_id,
        encounter_id: encounter.id,
        priority: form.priority,
      };
      if (form.order_type === 'IMAGING') {
        await createImagingOrder({ ...common, procedure_code: form.order_code.trim() || null,
          requested_procedure: form.display_name.trim(), modality: form.modality.trim(),
          body_region: form.body_region.trim(), clinical_indication: form.clinical_indication.trim() || null });
      } else {
        await createClinicalOrder({ ...common, destination_department_id: Number(form.destination_department_id),
          order_type: form.order_type, order_code: form.order_code.trim() || null,
          display_name: form.display_name.trim(), clinical_indication: form.clinical_indication.trim() || null });
      }
      setForm(blank);
    }, 'Clinical order draft created. Review and sign it before departmental work begins.');
  };

  const transition = (order, status) => {
    let reason = null;
    if (status === 'CANCELLED') {
      reason = window.prompt('Reason for cancelling this clinical order')?.trim();
      if (!reason) return;
    }
    run(
      () => transitionClinicalOrder(order.id, { expected_version: order.version, status, reason }),
      `Order ${status.toLowerCase().replace('_', ' ')}.`,
    );
  };

  const viewReleased = async order => {
    setResultBusy(order.id);
    setReleased(current => ({ ...current, [order.id]: null }));
    try {
      const payload = order.order_type === 'LAB'
        ? await getFinalLaboratoryResults(order.id) : await getReleasedRadiologyReport(order.id);
      const result = releasedResultForEncounter(payload, order, encounter);
      setReleased(current => ({ ...current, [order.id]: { data: result } }));
    } catch (err) {
      const message = err?.response || err?.request ? clinicalOrderError(err).message : err?.message || 'Unable to load released results. Retry.';
      setReleased(current => ({ ...current, [order.id]: { error: message } }));
    } finally { setResultBusy(null); }
  };

  const canCreate = canCreateClinicalOrder(encounter, doctorId);
  const visibleOrders = ordersForEncounter(orders, loadedEncounterId, encounter?.id)
    .filter(order => order.order_type !== 'MEDICATION');
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
    <div><h2 className="font-bold text-slate-900">Clinical orders</h2><p className="text-sm text-slate-600">Create and track requests routed to hospital departments.</p></div>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{error}{retryable && !unavailable && <button type="button" className="ml-2 font-bold underline" onClick={load}>{conflict ? 'Reload orders' : 'Retry'}</button>}</div>}
    {departmentError && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{departmentError}<button type="button" className="ml-2 font-bold underline" onClick={() => { setDepartmentError(''); getDepartments().then(result => setDepartments(Array.isArray(result) ? result : result?.departments || [])).catch(() => setDepartmentError('Departments could not be loaded. Retry before creating an order.')); }}>Retry departments</button></div>}
    {message && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">{message}</p>}
    {loading ? <p className="text-sm text-slate-500">Loading clinical orders…</p> : unavailable ? <button type="button" className="text-sm font-bold text-teal-700" onClick={load}>Retry readiness check</button> : <>
      {!visibleOrders.length ? <p className="text-sm text-slate-500">No clinical orders for this visit.</p> : <div className="space-y-3">{visibleOrders.map(order => <article key={order.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm space-y-2">
        <div className="flex flex-wrap justify-between gap-2"><strong>{order.display_name}</strong><span className="rounded-full bg-white px-2 py-1 text-xs font-bold">{order.status.replace('_', ' ')}</span></div>
        <p className="text-slate-600">{order.order_type} · {order.priority} · Department #{order.destination_department_id} · Version {order.version}</p>
        {order.order_code && <p>Code: {order.order_code}</p>}{order.clinical_indication && <p><strong>Indication:</strong> {order.clinical_indication}</p>}
        {order.cancellation_reason && <p className="text-amber-800"><strong>Cancelled:</strong> {order.cancellation_reason}</p>}
        <div className="flex flex-wrap gap-2">{(order.allowed_actions || []).map(action => <button key={action} type="button" disabled={busy} onClick={() => transition(order, action)} className={action === 'CANCELLED' ? 'rounded-xl border border-rose-200 px-3 py-2 text-xs font-bold text-rose-700 disabled:opacity-50' : button}>{orderActionLabel(action)}</button>)}</div>
        {['LAB', 'IMAGING'].includes(order.order_type) && order.signed_at && order.status !== 'CANCELLED' && <div className="border-t border-slate-200 pt-2 space-y-2">
          <button type="button" disabled={resultBusy === order.id} onClick={() => viewReleased(order)} className="text-xs font-bold text-teal-700 disabled:opacity-50">{resultBusy === order.id ? 'Loading released results…' : released[order.id] ? 'Refresh released results' : 'View released results'}</button>
          {released[order.id]?.error && <p role="alert" className="text-xs text-amber-800">{released[order.id].error}</p>}
          {released[order.id]?.data?.kind === 'LAB' && (released[order.id].data.results.length ? released[order.id].data.results.map(row => <p key={row.test_identifier} className="text-xs"><strong>{row.test_name}</strong>: {row.result_value} {row.result_unit || ''} · {row.abnormality_flag || 'not assessed'} · Revision {row.revision_number}{row.corrected ? ' (corrected)' : ''}</p>) : <p className="text-xs text-slate-500">No finalized laboratory results yet.</p>)}
          {released[order.id]?.data?.kind === 'LAB' && released[order.id].data.revisionHistory.length > released[order.id].data.results.length && <details className="text-xs"><summary className="cursor-pointer font-semibold">Finalized laboratory revision history</summary>{released[order.id].data.revisionHistory.map(row => <p key={`${row.test_identifier}:${row.revision_number}`}>{row.test_name} · Revision {row.revision_number}: {row.result_value} {row.result_unit || ''}</p>)}</details>}
          {released[order.id]?.data?.kind === 'IMAGING' && (released[order.id].data.report ? <div className="text-xs space-y-1"><p><strong>Finalized imaging report · Revision {released[order.id].data.report.revision_number}{released[order.id].data.report.amended ? ' (amended)' : ''}</strong></p><p className="whitespace-pre-wrap">Findings: {released[order.id].data.report.findings}</p><p className="whitespace-pre-wrap">Impression: {released[order.id].data.report.impression}</p></div> : <p className="text-xs text-slate-500">No finalized imaging report yet.</p>)}
          {released[order.id]?.data?.kind === 'IMAGING' && released[order.id].data.revisionHistory.length > 1 && <details className="text-xs"><summary className="cursor-pointer font-semibold">Finalized imaging amendment history</summary>{released[order.id].data.revisionHistory.map(row => <div key={row.revision_number} className="border-t border-slate-200 py-1"><strong>Revision {row.revision_number}</strong><p className="whitespace-pre-wrap">Findings: {row.findings}</p><p className="whitespace-pre-wrap">Impression: {row.impression}</p></div>)}</details>}
        </div>}
      </article>)}</div>}
      {canCreate && <form onSubmit={submit} className="space-y-3 border-t border-slate-200 pt-4">
        <h3 className="font-bold text-slate-900">New order draft</h3>
        <div className="grid gap-3 md:grid-cols-3"><label className="text-xs font-semibold">Destination department<select required={form.order_type !== 'IMAGING'} disabled={form.order_type === 'IMAGING'} className={field} value={form.destination_department_id} onChange={e => setForm(current => ({ ...current, destination_department_id: e.target.value }))}><option value="">{form.order_type === 'IMAGING' ? 'Derived from radiology configuration' : 'Select department'}</option>{departments.map(department => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
          <label className="text-xs font-semibold">Order type<select className={field} value={form.order_type} onChange={e => setForm(current => ({ ...current, order_type: e.target.value }))}>{['LAB', 'IMAGING', 'PROCEDURE', 'OTHER'].map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="text-xs font-semibold">Priority<select className={field} value={form.priority} onChange={e => setForm(current => ({ ...current, priority: e.target.value }))}>{['ROUTINE', 'URGENT', 'STAT'].map(value => <option key={value}>{value}</option>)}</select></label></div>
        {form.order_type === 'IMAGING' && <div className="grid gap-3 md:grid-cols-2"><label className="text-xs font-semibold">Modality<input required maxLength={32} className={field} value={form.modality} onChange={e => setForm(current => ({ ...current, modality: e.target.value }))} /></label><label className="text-xs font-semibold">Body region<input required maxLength={128} className={field} value={form.body_region} onChange={e => setForm(current => ({ ...current, body_region: e.target.value }))} /></label></div>}
        <div className="grid gap-3 md:grid-cols-3"><label className="text-xs font-semibold md:col-span-2">Order name<input required maxLength={255} className={field} value={form.display_name} onChange={e => setForm(current => ({ ...current, display_name: e.target.value }))} /></label><label className="text-xs font-semibold">Code (optional)<input maxLength={64} className={field} value={form.order_code} onChange={e => setForm(current => ({ ...current, order_code: e.target.value }))} /></label></div>
        <label className="block text-xs font-semibold">Clinical indication (optional)<textarea maxLength={4000} rows={2} className={field} value={form.clinical_indication} onChange={e => setForm(current => ({ ...current, clinical_indication: e.target.value }))} /></label>
        <button disabled={busy || !form.display_name.trim() || (form.order_type === 'IMAGING' ? (!form.modality.trim() || !form.body_region.trim()) : (departments.length === 0 || !form.destination_department_id))} className={button}>Create draft</button>
      </form>}
    </>}
  </section>;
}
