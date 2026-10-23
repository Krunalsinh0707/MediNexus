import { useCallback, useEffect, useRef, useState } from 'react';
import { Receipt, RefreshCw } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import * as billing from '../services/billingService';
import { billingError, canEditDraft, canRecordPayment, manualPaymentLabel } from './billingUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-[#0F9D8A] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50';
const key = () => crypto.randomUUID();
const allowed = (invoice, action) => Array.isArray(invoice?.allowed_actions) && invoice.allowed_actions.includes(action);

export default function BillingWorkspace({ patientView = false }) {
  const { user } = useAuth();
  const [filters, setFilters] = useState({ patient_id: '', department_id: '', encounter_id: '', status: '', from_date: '', to_date: '' });
  const appliedFilters = useRef({});
  const requestKeys = useRef({ invoice: key(), charge: key(), payment: key() });
  const [items, setItems] = useState([]), [selected, setSelected] = useState(null);
  const [search, setSearch] = useState(''), [patients, setPatients] = useState([]), [statement, setStatement] = useState(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [retryable, setRetryable] = useState(false), [notice, setNotice] = useState('');
  const [tariffs, setTariffs] = useState([]);
  const [invoiceDraft, setInvoiceDraft] = useState({ patient_id: '', department_id: '', appointment_id: '', encounter_id: '', admission_id: '', currency: 'INR' });
  const [chargeDraft, setChargeDraft] = useState({ tariff_id: '', quantity: '1', source_type: 'MANUAL', source_id: '' });
  const [paymentDraft, setPaymentDraft] = useState({ amount: '', method: 'CASH', reference: '', manual_evidence_confirmed: false });
  const [reasonDraft, setReasonDraft] = useState({ amount: '', reason: '', payment_id: '' });
  const [dueDate, setDueDate] = useState('');
  const showError = err => { const result = billingError(err); setError(result.message); setRetryable(result.retryable); };

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params = patientView ? {} : appliedFilters.current;
      const response = await billing.getInvoices(params);
      setItems(Array.isArray(response?.items) ? response.items : []);
      if (selected?.id) {
        const latest = await billing.getInvoice(selected.id);
        setSelected(latest);
      }
    } catch (err) { showError(err); setItems([]); setSelected(null); }
    finally { setLoading(false); }
  }, [patientView, selected?.id]);
  useEffect(() => { load(); }, [load]);

  const selectInvoice = async id => {
    setBusy(true); setError('');
    try { setSelected(await billing.getInvoice(id)); }
    catch (err) { showError(err); setSelected(null); }
    finally { setBusy(false); }
  };
  const act = async (call, success) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const next = await call();
      setSelected(next);
      setItems(current => current.map(item => item.id === next.id ? next : item));
      setNotice(success);
      return true;
    } catch (err) { showError(err); return false; }
    finally { setBusy(false); }
  };
  const searchPatients = async event => {
    event.preventDefault(); setBusy(true); setError('');
    try { setPatients(await billing.searchBillingPatients(search.trim())); }
    catch (err) { showError(err); setPatients([]); }
    finally { setBusy(false); }
  };
  const openStatement = async patientId => {
    setBusy(true); setError('');
    try { setStatement(await billing.getStatement(patientId)); }
    catch (err) { showError(err); setStatement(null); }
    finally { setBusy(false); }
  };
  const create = async event => {
    event.preventDefault();
    const body = { patient_id: Number(invoiceDraft.patient_id), department_id: Number(invoiceDraft.department_id),
      currency: invoiceDraft.currency, creation_key: requestKeys.current.invoice };
    for (const name of ['appointment_id', 'encounter_id', 'admission_id']) body[name] = invoiceDraft[name] ? Number(invoiceDraft[name]) : null;
    const success = await act(() => billing.createInvoice(body), 'Draft invoice created. Add tariff-backed charges before issuing.');
    if (success) { requestKeys.current.invoice = key(); load(); }
  };
  const loadTariffs = async () => {
    if (!selected) return;
    setBusy(true); setError('');
    try { setTariffs(await billing.getTariffs(selected.department_id)); }
    catch (err) { showError(err); setTariffs([]); }
    finally { setBusy(false); }
  };
  const addCharge = event => {
    event.preventDefault(); if (!selected) return;
    const body = { expected_version: selected.version, tariff_id: Number(chargeDraft.tariff_id),
      quantity: chargeDraft.quantity, source_type: chargeDraft.source_type,
      source_id: chargeDraft.source_type === 'MANUAL' ? null : Number(chargeDraft.source_id), idempotency_key: requestKeys.current.charge };
    act(() => billing.addCharge(selected.id, body), 'Tariff-backed charge added.').then(success => { if (success) requestKeys.current.charge = key(); });
  };
  const recordPayment = event => {
    event.preventDefault(); if (!selected || !paymentDraft.manual_evidence_confirmed) return;
    act(() => billing.recordPayment(selected.id, { expected_version: selected.version,
      amount: paymentDraft.amount, currency: selected.currency, method: paymentDraft.method,
      reference: paymentDraft.reference.trim(), manual_evidence_confirmed: true,
      idempotency_key: requestKeys.current.payment }), 'Payment manually recorded. Settlement is unverified.').then(success => { if (success) { requestKeys.current.payment = key(); setPaymentDraft({ amount: '', method: 'CASH', reference: '', manual_evidence_confirmed: false }); } });
  };
  const performReasonAction = async operation => {
    if (!selected || !reasonDraft.reason.trim()) { setError('A reason is required.'); return; }
    const action = { cancel: 'cancel', adjust: 'request_adjustment', refund: 'request_refund' }[operation];
    if (!allowed(selected, action)) { setError('This action is not authorized for your assignment.'); return; }
    const base = { expected_version: selected.version, reason: reasonDraft.reason.trim() };
    if (operation === 'cancel') await act(() => billing.cancelInvoice(selected.id, base), 'Invoice cancelled; history retained.');
    if (operation === 'adjust') await act(() => billing.requestAdjustment(selected.id, { ...base, amount: reasonDraft.amount }), 'Adjustment requested; balance unchanged until approval.');
    if (operation === 'refund') await act(() => billing.requestRefund(selected.id, { ...base, payment_id: Number(reasonDraft.payment_id), amount: reasonDraft.amount }), 'Refund requested; no money has been transferred.');
  };

  return <div className="min-h-full space-y-5 bg-[#F6F9FB] p-4 md:p-8">
    <header className="flex flex-wrap justify-between gap-3"><div><h1 className="flex items-center gap-2 text-2xl font-bold"><Receipt className="text-teal-600"/> {patientView ? 'My billing' : 'Billing workspace'}</h1><p className="text-sm text-slate-600">{patientView ? 'Released invoices and manually recorded payment history.' : 'Department-scoped invoices. Payments are manual records, not verified settlement.'}</p></div><button className={button} disabled={loading || busy} onClick={() => load()}><RefreshCw size={16} className="mr-1 inline"/>Reload</button></header>
    {error && <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">{error}{retryable && <button className="ml-2 font-bold underline" onClick={() => load()}>Retry</button>}</div>}
    {notice && <p role="status" className="rounded-xl bg-teal-50 p-3 text-sm">{notice}</p>}
    {!patientView && <section className="space-y-3 rounded-2xl border bg-white p-4"><h2 className="font-bold">Patient search and invoice filters</h2><form className="flex gap-2" onSubmit={searchPatients}><input className={field} required minLength={1} value={search} onChange={e => setSearch(e.target.value)} placeholder="MRN, patient name, or ID"/><button className={button} disabled={busy}>Search patients</button></form>{patients.map(p => <button className="mr-2 rounded-xl border p-2 text-sm" key={p.id} onClick={() => { setFilters(prev => ({ ...prev, patient_id: String(p.id) })); setInvoiceDraft(prev => ({ ...prev, patient_id: String(p.id) })); openStatement(p.id); }}>{p.full_name} · {p.mrn} · #{p.id}</button>)}<div className="grid gap-2 md:grid-cols-3">{['patient_id', 'department_id', 'encounter_id', 'status', 'from_date', 'to_date'].map(name => <label className="text-xs" key={name}>{name.replaceAll('_', ' ')}{name === 'status' ? <select className={field} value={filters[name]} onChange={e => setFilters(prev => ({ ...prev, [name]: e.target.value }))}><option value="">All statuses</option>{['DRAFT', 'ISSUED', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'CANCELLED'].map(s => <option key={s}>{s}</option>)}</select> : <input className={field} type={name.endsWith('date') ? 'date' : 'text'} value={filters[name]} onChange={e => setFilters(prev => ({ ...prev, [name]: e.target.value }))}/>}</label>)}</div><button className={button} onClick={() => { appliedFilters.current = Object.fromEntries(Object.entries(filters).filter(([, value]) => value)); load(); }}>Apply filters</button></section>}
    {statement && <section className="rounded-2xl border bg-white p-4 text-sm"><h2 className="font-bold">Statement · {statement.patient?.full_name} · {statement.patient?.mrn}</h2><p>{statement.invoices?.length || 0} persisted invoices</p>{Object.entries(statement.outstanding_by_currency || {}).map(([currency, amount]) => <p key={currency}>Outstanding {currency} {amount}</p>)}</section>}
    {!patientView && <form onSubmit={create} className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">New invoice draft</h2><p className="text-xs text-slate-500">Requires an existing MRN and a verified appointment, encounter, or admission in your assigned department.</p><div className="grid gap-2 md:grid-cols-3">{['patient_id', 'department_id', 'appointment_id', 'encounter_id', 'admission_id', 'currency'].map(name => <label key={name} className="text-xs">{name.replaceAll('_', ' ')}<input className={field} required={['patient_id', 'department_id', 'currency'].includes(name)} value={invoiceDraft[name]} onChange={e => setInvoiceDraft(prev => ({ ...prev, [name]: e.target.value }))}/></label>)}</div><button className={button} disabled={busy}>Create draft</button></form>}
    <div className="grid gap-5 lg:grid-cols-[.8fr_1.5fr]"><section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Invoices</h2>{loading ? <p className="text-sm">Loading invoices…</p> : !items.length ? <p className="text-sm text-slate-500">No invoices available for this view.</p> : items.map(item => <button key={item.id} disabled={busy} className="block w-full rounded-xl border p-3 text-left text-sm" onClick={() => selectInvoice(item.id)}><strong>{item.invoice_number}</strong><span className="block">{item.patient?.full_name} · {item.patient?.mrn}</span><span>{item.status} · {item.currency} {item.outstanding} outstanding</span></button>)}</section>
    <div className="space-y-4">{selected ? <><section className="space-y-2 rounded-2xl border bg-white p-5 text-sm"><h2 className="text-lg font-bold">Invoice {selected.invoice_number}</h2><p>{selected.patient?.full_name} · {selected.patient?.mrn} · {selected.status} · Department #{selected.department_id}</p><p>Subtotal {selected.currency} {selected.subtotal} · Approved adjustments {selected.approved_adjustments} · Tax {selected.tax}</p><p className="font-bold">Total {selected.currency} {selected.total} · Manual payment records {selected.manually_recorded_payments} · Outstanding {selected.outstanding}</p><p className="text-xs text-slate-500">Issue: {selected.issued_at || 'Draft'} · Due: {selected.due_date || 'Not set'} · Payment gateway/settlement: unverified</p><h3 className="font-bold">Charges</h3>{!selected.charges?.length ? <p>No charges recorded.</p> : selected.charges.map(c => <p key={c.id}>{c.description} · {c.quantity} × {selected.currency} {c.unit_price} = {c.line_total} ({c.source_type} #{c.source_id || 'manual'})</p>)}<h3 className="font-bold">Payment history</h3>{!selected.payments?.length ? <p>No payments recorded.</p> : selected.payments.map(p => <p key={p.id}>{p.method} · {p.reference} · {selected.currency} {p.amount} · {manualPaymentLabel(p)}{!patientView && p.status === 'MANUALLY_RECORDED' && <button className="ml-2 text-teal-700 underline" disabled={busy || !reasonDraft.reason.trim() || !allowed(selected, 'reverse_payment')} onClick={() => act(() => billing.reversePayment(selected.id, p.id, { expected_version: selected.version, reason: reasonDraft.reason.trim() }), 'Manual payment record reversed; no funds transferred.')}>Reverse record</button>}</p>)}{!patientView && <><h3 className="font-bold">Adjustments and refund requests</h3>{selected.adjustments?.map(a => <p key={a.id}>Adjustment #{a.id}: {selected.currency} {a.amount} · {a.status}{a.status === 'REQUESTED' && allowed(selected, 'decide_adjustment') && <><button className="ml-2 text-teal-700 underline" onClick={() => act(() => billing.decideAdjustment(selected.id, a.id, { expected_version: selected.version, approve: true }), 'Adjustment approved.')}>Approve</button><button className="ml-2 text-amber-700 underline" disabled={!reasonDraft.reason.trim()} onClick={() => act(() => billing.decideAdjustment(selected.id, a.id, { expected_version: selected.version, approve: false, reason: reasonDraft.reason.trim() }), 'Adjustment rejected.')}>Reject</button></>}</p>)}{selected.refund_requests?.map(r => <p key={r.id}>Refund request #{r.id} · Payment #{r.payment_id} · {r.amount} · {r.status} (no payout)</p>)}<h3 className="font-bold">Activity</h3>{selected.history?.map(h => <p key={h.sequence}>#{h.sequence} · {h.action} · Account #{h.actor_user_id} · {h.created_at}</p>)}</>}</section>
      {!patientView && <><section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Tariff-backed charge</h2><button className="text-sm font-semibold text-teal-700 underline" onClick={loadTariffs}>Load approved tariffs</button>{!tariffs.length && <p className="text-xs text-amber-700">No configured tariffs loaded. Prices cannot be invented.</p>}{canEditDraft(selected) && allowed(selected, 'add_charge') && <form onSubmit={addCharge} className="space-y-2"><select className={field} required value={chargeDraft.tariff_id} onChange={e => setChargeDraft(prev => ({ ...prev, tariff_id: e.target.value }))}><option value="">Select approved tariff</option>{tariffs.map(t => <option value={t.id} key={t.id}>{t.service_code} · {t.description} · {t.currency} {t.unit_price}{t.tax_required ? ' (tax configuration required)' : ''}</option>)}</select><input className={field} required type="number" min="0.001" step="0.001" value={chargeDraft.quantity} onChange={e => setChargeDraft(prev => ({ ...prev, quantity: e.target.value }))}/><select className={field} value={chargeDraft.source_type} onChange={e => setChargeDraft(prev => ({ ...prev, source_type: e.target.value }))}>{['MANUAL', 'APPOINTMENT', 'ENCOUNTER', 'ADMISSION', 'CLINICAL_ORDER'].map(t => <option key={t}>{t}</option>)}</select>{chargeDraft.source_type !== 'MANUAL' && <input className={field} required type="number" min="1" placeholder="Verified source ID" value={chargeDraft.source_id} onChange={e => setChargeDraft(prev => ({ ...prev, source_id: e.target.value }))}/>}<button className={button} disabled={busy || !tariffs.length}>Add charge</button></form>}{canEditDraft(selected) && allowed(selected, 'issue') && <div className="flex gap-2"><input className={field} type="date" value={dueDate} onChange={e => setDueDate(e.target.value)}/><button className={button} disabled={busy || !dueDate} onClick={() => act(() => billing.issueInvoice(selected.id, { expected_version: selected.version, due_date: dueDate }), 'Invoice issued and released.')}>Issue invoice</button></div>}</section>
      <section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Manual payment recording</h2><p className="text-xs text-slate-600">Use only after independent evidence of payment. This record does not confirm gateway settlement.</p>{canRecordPayment(selected) && <form onSubmit={recordPayment} className="space-y-2"><input className={field} type="number" min="0.01" step="0.01" required placeholder="Amount" value={paymentDraft.amount} onChange={e => setPaymentDraft(prev => ({ ...prev, amount: e.target.value }))}/><select className={field} value={paymentDraft.method} onChange={e => setPaymentDraft(prev => ({ ...prev, method: e.target.value }))}>{['CASH', 'BANK_TRANSFER', 'CHEQUE', 'OTHER'].map(s => <option key={s}>{s}</option>)}</select><input className={field} required minLength={3} placeholder="External receipt or manual reference (never card details)" value={paymentDraft.reference} onChange={e => setPaymentDraft(prev => ({ ...prev, reference: e.target.value }))}/><label className="text-sm"><input type="checkbox" checked={paymentDraft.manual_evidence_confirmed} onChange={e => setPaymentDraft(prev => ({ ...prev, manual_evidence_confirmed: e.target.checked }))}/> I independently confirmed payment evidence</label><button className={button} disabled={busy || !paymentDraft.manual_evidence_confirmed}>Record manually</button></form>}</section>
      <section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Adjustment, cancellation, or refund request</h2><textarea className={field} placeholder="Required reason" value={reasonDraft.reason} onChange={e => setReasonDraft(prev => ({ ...prev, reason: e.target.value }))}/><input className={field} type="number" min="0.01" step="0.01" placeholder="Adjustment or refund amount" value={reasonDraft.amount} onChange={e => setReasonDraft(prev => ({ ...prev, amount: e.target.value }))}/><input className={field} type="number" min="1" placeholder="Payment ID for refund request" value={reasonDraft.payment_id} onChange={e => setReasonDraft(prev => ({ ...prev, payment_id: e.target.value }))}/><div className="flex flex-wrap gap-2"><button className={button} disabled={busy || !allowed(selected, 'cancel')} onClick={() => performReasonAction('cancel')}>Cancel invoice</button><button className={button} disabled={busy || !allowed(selected, 'request_adjustment') || !reasonDraft.amount} onClick={() => performReasonAction('adjust')}>Request adjustment</button><button className={button} disabled={busy || !allowed(selected, 'request_refund') || !reasonDraft.amount || !reasonDraft.payment_id} onClick={() => performReasonAction('refund')}>Request refund</button></div></section></>}
    </> : <section className="rounded-2xl border bg-white p-5 text-sm text-slate-500">Select an invoice to review details.</section>}</div></div>
    {patientView && user && <button className="text-sm font-semibold text-teal-700 underline" onClick={() => openStatement(user.id)}>View my statement</button>}
  </div>;
}
