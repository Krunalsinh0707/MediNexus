import { useCallback, useEffect, useRef, useState } from 'react';
import { ShieldCheck, RefreshCw } from 'lucide-react';
import * as insurance from '../services/insuranceService';
import { getInvoice, searchBillingPatients } from '../services/billingService';
import { can, canTransition, eligibilityLabel, insuranceError, remittanceLabel } from './insuranceUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-[#0F9D8A] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50';
const policyBlank = { patient_id: '', department_id: '', insurer_code: '', insurer_name: '', plan_code: '', member_identifier: '', policyholder_relationship: 'SELF', coverage_start: '', coverage_end: '' };
const transitionBlank = { to_status: '', reason: '', source_reference: '', insurer_reference: '', insurer_reference_supplied: false, approved_amount: '', denied_amount: '', patient_responsibility: '' };
const label = value => String(value || '').replaceAll('_', ' ');

export default function InsuranceWorkspace({ patientView = false }) {
  const [policies, setPolicies] = useState([]), [claims, setClaims] = useState([]);
  const [selectedPolicy, setSelectedPolicy] = useState(null), [selectedClaim, setSelectedClaim] = useState(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [retryable, setRetryable] = useState(false), [notice, setNotice] = useState('');
  const [search, setSearch] = useState(''), [patientMatches, setPatientMatches] = useState([]);
  const [filters, setFilters] = useState({ patient_id: '', department_id: '', status: '' });
  const applied = useRef({});
  const [policyDraft, setPolicyDraft] = useState(policyBlank);
  const [policyEdit, setPolicyEdit] = useState(null), [policyEditReason, setPolicyEditReason] = useState('');
  const [eligibility, setEligibility] = useState({ status: 'PENDING', source_reference: '', reason: '' });
  const [invoiceId, setInvoiceId] = useState(''), [invoice, setInvoice] = useState(null);
  const [policyId, setPolicyId] = useState(''), [claimLines, setClaimLines] = useState({});
  const claimKey = useRef(crypto.randomUUID());
  const [transition, setTransition] = useState(transitionBlank);
  const [correctionAmounts, setCorrectionAmounts] = useState({}), [correctionReason, setCorrectionReason] = useState('');
  const [remittance, setRemittance] = useState({ billing_payment_id: '', source_reference: '', insurer_origin_confirmed: false });
  const showError = err => { const result = insuranceError(err); setError(result.message); setRetryable(result.retryable); };

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const base = patientView ? {} : Object.fromEntries(Object.entries(applied.current).filter(([, value]) => value));
      const [policyResponse, claimResponse] = await Promise.all([
        insurance.listPolicies({ patient_id: base.patient_id, department_id: base.department_id }),
        insurance.listClaims(base),
      ]);
      setPolicies(Array.isArray(policyResponse?.items) ? policyResponse.items : []);
      setClaims(Array.isArray(claimResponse?.items) ? claimResponse.items : []);
    } catch (err) { showError(err); setPolicies([]); setClaims([]); setSelectedPolicy(null); setSelectedClaim(null); }
    finally { setLoading(false); }
  }, [patientView]);
  useEffect(() => { load(); }, [load]);

  const selectPolicy = async id => {
    setBusy(true); setError('');
    try {
      const row = await insurance.getPolicy(id);
      setSelectedPolicy(row);
      setPolicyEdit({ insurer_name: row.insurer_name, plan_code: row.plan_code,
        policyholder_relationship: row.policyholder_relationship,
        coverage_start: row.coverage_start || '', coverage_end: row.coverage_end || '' });
    } catch (err) { showError(err); setSelectedPolicy(null); }
    finally { setBusy(false); }
  };
  const selectClaim = async id => {
    setBusy(true); setError('');
    try {
      const row = await insurance.getClaim(id);
      setSelectedClaim(row); setTransition(transitionBlank);
      setCorrectionAmounts(Object.fromEntries((row.lines || []).map(line => [line.charge_id,
        { amount: line.requested_amount, review_reference: line.review_reference || '' }])));
      setCorrectionReason('');
    }
    catch (err) { showError(err); setSelectedClaim(null); }
    finally { setBusy(false); }
  };
  const run = async (call, update, message) => {
    setBusy(true); setError(''); setNotice('');
    try { const value = await call(); update(value); setNotice(message); await load(); return true; }
    catch (err) { showError(err); return false; }
    finally { setBusy(false); }
  };
  const searchPatient = async e => {
    e.preventDefault(); setBusy(true); setError('');
    try { setPatientMatches(await searchBillingPatients(search.trim())); }
    catch (err) { showError(err); setPatientMatches([]); }
    finally { setBusy(false); }
  };
  const createPolicy = async e => {
    e.preventDefault();
    const body = { ...policyDraft, patient_id: Number(policyDraft.patient_id),
      department_id: Number(policyDraft.department_id), coverage_end: policyDraft.coverage_end || null };
    const okay = await run(() => insurance.createPolicy(body), setSelectedPolicy, 'Policy saved as unverified. No coverage has been confirmed.');
    if (okay) setPolicyDraft(policyBlank);
  };
  const updatePolicy = e => {
    e.preventDefault(); if (!selectedPolicy || !can(selectedPolicy, 'update')) return;
    run(() => insurance.updatePolicy(selectedPolicy.id, { ...policyEdit, coverage_end: policyEdit.coverage_end || null,
      expected_version: selectedPolicy.version, reason: policyEditReason.trim() }),
      setSelectedPolicy, 'Policy updated; eligibility must be checked again.');
  };
  const checkEligibility = e => {
    e.preventDefault(); if (!selectedPolicy || !can(selectedPolicy, 'record_eligibility')) return;
    run(() => insurance.recordEligibility(selectedPolicy.id, { ...eligibility,
      expected_version: selectedPolicy.version, method: 'MANUAL_STAFF_ENTRY',
      reason: eligibility.reason.trim() || null }),
      setSelectedPolicy, 'Manual eligibility check recorded. This does not guarantee coverage or payment.');
  };
  const loadInvoice = async e => {
    e.preventDefault(); setBusy(true); setError('');
    try { setInvoice(await getInvoice(Number(invoiceId))); setClaimLines({}); }
    catch (err) { showError(err); setInvoice(null); }
    finally { setBusy(false); }
  };
  const createClaim = async e => {
    e.preventDefault(); if (!invoice) return;
    const lines = Object.entries(claimLines).filter(([, value]) => value.selected).map(([charge_id, value]) => ({
      charge_id: Number(charge_id), requested_amount: value.amount, review_reference: value.review_reference.trim(),
    }));
    if (!lines.length) { setError('Select at least one real invoice charge.'); return; }
    const okay = await run(() => insurance.createClaim({ invoice_id: invoice.id, policy_id: Number(policyId),
      lines, creation_key: claimKey.current }), setSelectedClaim,
    'Claim draft created from the selected invoice lines. It has not been submitted.');
    if (okay) claimKey.current = crypto.randomUUID();
  };
  const transitionClaim = e => {
    e.preventDefault(); if (!selectedClaim || !canTransition(selectedClaim, transition.to_status)) return;
    const body = { expected_version: selectedClaim.version, to_status: transition.to_status,
      reason: transition.reason.trim() || null, source_reference: transition.source_reference.trim() || null,
      insurer_reference: transition.insurer_reference.trim() || null,
      insurer_reference_supplied: transition.insurer_reference_supplied,
      approved_amount: transition.approved_amount === '' ? null : transition.approved_amount,
      denied_amount: transition.denied_amount === '' ? null : transition.denied_amount,
      patient_responsibility: transition.patient_responsibility === '' ? null : transition.patient_responsibility };
    run(() => insurance.transitionClaim(selectedClaim.id, body), setSelectedClaim,
      'Claim status saved as a manual staff record; insurer integration is unavailable.');
  };
  const reconcile = e => {
    e.preventDefault(); if (!selectedClaim || !can(selectedClaim, 'reconcile')) return;
    run(() => insurance.reconcileRemittance(selectedClaim.id, { expected_version: selectedClaim.version,
      billing_payment_id: Number(remittance.billing_payment_id), source_reference: remittance.source_reference.trim(),
      insurer_origin_confirmed: remittance.insurer_origin_confirmed }),
      setSelectedClaim, 'Existing billing payment manually linked. Settlement remains unverified.');
  };
  const correctClaim = e => {
    e.preventDefault(); if (!selectedClaim || !can(selectedClaim, 'correct')) return;
    const lines = (selectedClaim.lines || []).map(line => ({
      charge_id: line.charge_id,
      requested_amount: correctionAmounts[line.charge_id]?.amount,
      review_reference: correctionAmounts[line.charge_id]?.review_reference?.trim(),
    }));
    run(() => insurance.correctClaim(selectedClaim.id, { expected_version: selectedClaim.version,
      reason: correctionReason.trim(), lines }), value => {
      setSelectedClaim(value);
      setCorrectionAmounts(Object.fromEntries((value.lines || []).map(line => [line.charge_id,
        { amount: line.requested_amount, review_reference: line.review_reference || '' }])));
      setCorrectionReason('');
    }, 'Claim correction recorded with prior amounts retained in history.');
  };

  return <div className="min-h-full space-y-5 bg-[#F6F9FB] p-4 md:p-8">
    <header className="flex flex-wrap justify-between gap-3"><div><h1 className="flex items-center gap-2 text-2xl font-bold"><ShieldCheck className="text-teal-600"/>{patientView ? 'My insurance' : 'Insurance and claims'}</h1><p className="text-sm text-slate-600">{patientView ? 'Only released policy and claim information is shown.' : 'Department-scoped manual workflows. No live insurer connection or verified settlement.'}</p></div><button className={button} disabled={loading || busy} onClick={load}><RefreshCw size={16} className="mr-1 inline"/>Reload</button></header>
    {error && <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">{error}{retryable && <button className="ml-2 font-bold underline" onClick={load}>Retry</button>}</div>}
    {notice && <p role="status" className="rounded-xl bg-teal-50 p-3 text-sm">{notice}</p>}
    {!patientView && <section className="space-y-3 rounded-2xl border bg-white p-4"><h2 className="font-bold">Patient and claim filters</h2><form onSubmit={searchPatient} className="flex gap-2"><input className={field} required value={search} onChange={e => setSearch(e.target.value)} placeholder="Search assigned patients by MRN, name, or ID"/><button className={button} disabled={busy}>Search</button></form>{patientMatches.map(p => <button key={p.id} className="mr-2 rounded-xl border p-2 text-sm" onClick={() => { setFilters(prev => ({ ...prev, patient_id: String(p.id) })); setPolicyDraft(prev => ({ ...prev, patient_id: String(p.id) })); }}>{p.full_name} · {p.mrn} · #{p.id}</button>)}<div className="grid gap-2 md:grid-cols-3"><label className="text-xs">Patient ID<input className={field} value={filters.patient_id} onChange={e => setFilters(prev => ({ ...prev, patient_id: e.target.value }))}/></label><label className="text-xs">Department ID<input className={field} value={filters.department_id} onChange={e => setFilters(prev => ({ ...prev, department_id: e.target.value }))}/></label><label className="text-xs">Claim status<select className={field} value={filters.status} onChange={e => setFilters(prev => ({ ...prev, status: e.target.value }))}><option value="">All</option>{['DRAFT','READY_FOR_REVIEW','SUBMITTED','ACKNOWLEDGED','UNDER_REVIEW','APPROVED','PARTIALLY_APPROVED','DENIED','PAID','CANCELLED'].map(s => <option key={s}>{s}</option>)}</select></label></div><button className={button} onClick={() => { applied.current = filters; load(); }}>Apply filters</button></section>}
    <div className="grid gap-5 lg:grid-cols-2"><section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Policies</h2>{loading ? <p className="text-sm">Loading policies…</p> : policies.length ? policies.map(row => <button className="block w-full rounded-xl border p-3 text-left text-sm" key={row.id} disabled={busy} onClick={() => selectPolicy(row.id)}><strong>{row.insurer_name} · {row.plan_code}</strong><span className="block">Member {row.member_identifier_masked} · {label(row.status)} · Patient #{row.patient_id}</span><span className="text-xs">{eligibilityLabel(row)}</span></button>) : <p className="text-sm text-slate-500">No accessible insurance policies.</p>}</section>
    <section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Claims</h2>{loading ? <p className="text-sm">Loading claims…</p> : claims.length ? claims.map(row => <button className="block w-full rounded-xl border p-3 text-left text-sm" key={row.id} disabled={busy} onClick={() => selectClaim(row.id)}><strong>{row.claim_number} · {label(row.status)}</strong><span className="block">Invoice #{row.invoice_id} · Patient #{row.patient_id} · {row.currency} {row.requested_total}</span><span className="text-xs">{remittanceLabel(row)}</span></button>) : <p className="text-sm text-slate-500">No accessible claims.</p>}</section></div>
    {!patientView && <div className="grid gap-5 lg:grid-cols-2"><form onSubmit={createPolicy} className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Record a patient policy</h2><p className="text-xs text-slate-500">Enter only a real insurer, plan and member identifier. Coverage starts unverified; benefits and limits are unavailable without trusted evidence.</p><div className="grid gap-2 md:grid-cols-2">{[['patient_id','Patient ID'],['department_id','Assigned department ID'],['insurer_code','Insurer code'],['insurer_name','Insurer name'],['plan_code','Plan code'],['member_identifier','Member identifier'],['coverage_start','Coverage start'],['coverage_end','Coverage end']].map(([name, title]) => <label className="text-xs" key={name}>{title}<input className={field} required={name !== 'coverage_end'} type={name.startsWith('coverage_') ? 'date' : 'text'} autoComplete={name === 'member_identifier' ? 'off' : undefined} value={policyDraft[name]} onChange={e => setPolicyDraft(prev => ({ ...prev, [name]: e.target.value }))}/></label>)}</div><label className="block text-xs">Policyholder relationship<select className={field} value={policyDraft.policyholder_relationship} onChange={e => setPolicyDraft(prev => ({ ...prev, policyholder_relationship: e.target.value }))}>{['SELF','SPOUSE','CHILD','PARENT','OTHER'].map(s => <option key={s}>{s}</option>)}</select></label><button className={button} disabled={busy}>Save unverified policy</button></form>
    <section className="space-y-2 rounded-2xl border bg-white p-4"><h2 className="font-bold">Create claim from an issued invoice</h2><p className="text-xs text-slate-500">Select actual invoice charges and manually reviewed requested amounts. Claim creation does not submit it or guarantee reimbursement.</p><form className="flex gap-2" onSubmit={loadInvoice}><input className={field} required type="number" min="1" value={invoiceId} onChange={e => setInvoiceId(e.target.value)} placeholder="Invoice ID"/><button className={button} disabled={busy}>Load invoice</button></form>{invoice && <form className="space-y-2" onSubmit={createClaim}><p className="text-sm">{invoice.invoice_number} · {invoice.status} · Patient {invoice.patient?.mrn} · {invoice.currency} {invoice.total} total</p><label className="block text-xs">Verified policy ID<input className={field} required type="number" min="1" value={policyId} onChange={e => setPolicyId(e.target.value)}/></label>{invoice.charges?.map(charge => <div key={charge.id} className="rounded-xl border p-2 text-sm"><label><input type="checkbox" checked={!!claimLines[charge.id]?.selected} onChange={e => setClaimLines(prev => ({ ...prev, [charge.id]: { ...prev[charge.id], selected: e.target.checked, amount: prev[charge.id]?.amount || charge.line_total, review_reference: prev[charge.id]?.review_reference || '' } }))}/> {charge.description} · Billed {invoice.currency} {charge.line_total} · Charge #{charge.id}</label>{claimLines[charge.id]?.selected && <div className="grid gap-2 md:grid-cols-2"><input className={field} required type="number" step="0.01" min="0.01" max={charge.line_total} value={claimLines[charge.id]?.amount || ''} onChange={e => setClaimLines(prev => ({ ...prev, [charge.id]: { ...prev[charge.id], amount: e.target.value } }))} placeholder="Requested amount"/><input className={field} required minLength={3} value={claimLines[charge.id]?.review_reference || ''} onChange={e => setClaimLines(prev => ({ ...prev, [charge.id]: { ...prev[charge.id], review_reference: e.target.value } }))} placeholder="Manual line review reference"/></div>}</div>)}<button className={button} disabled={busy || invoice.status === 'DRAFT'}>Create claim draft</button></form>}</section></div>}
    <div className="grid gap-5 lg:grid-cols-2"><section className="space-y-3 rounded-2xl border bg-white p-4"><h2 className="font-bold">Policy detail</h2>{selectedPolicy ? <><p className="text-sm">{selectedPolicy.insurer_name} · {selectedPolicy.plan_code} · Member {selectedPolicy.member_identifier_masked}</p><p className="text-sm">{label(selectedPolicy.status)} · {selectedPolicy.coverage_start} to {selectedPolicy.coverage_end || 'open ended'} · {eligibilityLabel(selectedPolicy)}</p><p className="text-xs text-amber-700">Benefits and limits unavailable; eligibility does not guarantee payment.</p>{!patientView && <>{can(selectedPolicy,'update') && policyEdit && <form onSubmit={updatePolicy} className="space-y-2 rounded-xl bg-slate-50 p-3"><h3 className="font-semibold">Update before claim use</h3>{[['insurer_name','Insurer name'],['plan_code','Plan code'],['coverage_start','Coverage start'],['coverage_end','Coverage end']].map(([name,title]) => <label key={name} className="block text-xs">{title}<input className={field} type={name.startsWith('coverage_') ? 'date' : 'text'} required={name !== 'coverage_end'} value={policyEdit[name]} onChange={e => setPolicyEdit(prev => ({ ...prev, [name]: e.target.value }))}/></label>)}<select className={field} value={policyEdit.policyholder_relationship} onChange={e => setPolicyEdit(prev => ({ ...prev, policyholder_relationship: e.target.value }))}>{['SELF','SPOUSE','CHILD','PARENT','OTHER'].map(s => <option key={s}>{s}</option>)}</select><textarea className={field} required minLength={3} value={policyEditReason} onChange={e => setPolicyEditReason(e.target.value)} placeholder="Reason for change"/><button className={button} disabled={busy}>Save and require re-verification</button></form>}{can(selectedPolicy,'record_eligibility') && <form onSubmit={checkEligibility} className="space-y-2 rounded-xl bg-slate-50 p-3"><h3 className="font-semibold">Record manual eligibility check</h3><select className={field} value={eligibility.status} onChange={e => setEligibility(prev => ({ ...prev, status: e.target.value }))}>{['PENDING','VERIFIED','INELIGIBLE','FAILED'].map(s => <option key={s}>{s}</option>)}</select><input className={field} required minLength={3} placeholder="Real call, portal, or document reference" value={eligibility.source_reference} onChange={e => setEligibility(prev => ({ ...prev, source_reference: e.target.value }))}/><textarea className={field} placeholder="Optional explanation" value={eligibility.reason} onChange={e => setEligibility(prev => ({ ...prev, reason: e.target.value }))}/><button className={button} disabled={busy}>Record as manual</button></form>}{can(selectedPolicy,'release') && <button className={button} disabled={busy} onClick={() => run(() => insurance.releasePolicy(selectedPolicy.id, { expected_version: selectedPolicy.version }), setSelectedPolicy, 'Eligibility status released to the patient.')}>Release to patient</button>}{selectedPolicy.checks?.map(c => <p key={c.id} className="text-xs">{label(c.status)} · {label(c.method)} · {c.checked_at} · Account #{c.checked_by_user_id} · Reference {c.source_reference}</p>)}{selectedPolicy.history?.map(h => <p key={h.sequence} className="text-xs">#{h.sequence} {label(h.action)} · Account #{h.actor_user_id} · {h.occurred_at}</p>)}</>}</> : <p className="text-sm text-slate-500">Select a policy to review its status.</p>}</section>
    <section className="space-y-3 rounded-2xl border bg-white p-4"><h2 className="font-bold">Claim detail</h2>{selectedClaim ? <><p className="text-sm">{selectedClaim.claim_number} · {label(selectedClaim.status)} · Invoice #{selectedClaim.invoice_id} · Patient #{selectedClaim.patient_id}</p><p className="text-sm">Requested {selectedClaim.currency} {selectedClaim.requested_total} · Approved {selectedClaim.approved_amount ?? 'Not decided'} · Denied {selectedClaim.denied_amount ?? 'Not decided'} · Patient responsibility {selectedClaim.patient_responsibility ?? 'Not established'}</p><p className="text-xs text-amber-700">{remittanceLabel(selectedClaim)}. Submission and acknowledgement do not mean approval.</p>{selectedClaim.lines?.map(line => <p key={line.charge_id} className="text-xs">Charge #{line.charge_id} · Billed {line.billed_amount} · Requested {line.requested_amount}</p>)}{!patientView && <>{selectedClaim.allowed_transitions?.length > 0 && <form onSubmit={transitionClaim} className="space-y-2 rounded-xl bg-slate-50 p-3"><h3 className="font-semibold">Attributed manual transition</h3><select className={field} required value={transition.to_status} onChange={e => setTransition(prev => ({ ...prev, to_status: e.target.value }))}><option value="">Select permitted transition</option>{selectedClaim.allowed_transitions.map(s => <option key={s}>{s}</option>)}</select><input className={field} value={transition.source_reference} onChange={e => setTransition(prev => ({ ...prev, source_reference: e.target.value }))} placeholder="Actual submission/call/advice evidence reference when required"/><textarea className={field} value={transition.reason} onChange={e => setTransition(prev => ({ ...prev, reason: e.target.value }))} placeholder="Reason for denial, cancellation or resubmission"/><div className="grid gap-2 md:grid-cols-3">{[['approved_amount','Approved amount'],['denied_amount','Denied amount'],['patient_responsibility','Patient responsibility only if supplied']].map(([name,title]) => <label className="text-xs" key={name}>{title}<input className={field} type="number" min="0" step="0.01" value={transition[name]} onChange={e => setTransition(prev => ({ ...prev, [name]: e.target.value }))}/></label>)}</div><input className={field} value={transition.insurer_reference} onChange={e => setTransition(prev => ({ ...prev, insurer_reference: e.target.value }))} placeholder="Insurer reference, only if actually supplied"/><label className="text-xs"><input type="checkbox" checked={transition.insurer_reference_supplied} onChange={e => setTransition(prev => ({ ...prev, insurer_reference_supplied: e.target.checked }))}/> Confirm insurer supplied this reference</label><button className={button} disabled={busy}>Record transition</button></form>}{can(selectedClaim,'reconcile') && <form onSubmit={reconcile} className="space-y-2 rounded-xl bg-slate-50 p-3"><h3 className="font-semibold">Manual remittance reconciliation</h3><p className="text-xs">Link an existing, manually recorded billing payment. No new invoice payment or fund transfer is created.</p><input className={field} required type="number" min="1" placeholder="Existing billing payment ID" value={remittance.billing_payment_id} onChange={e => setRemittance(prev => ({ ...prev, billing_payment_id: e.target.value }))}/><input className={field} required minLength={3} placeholder="Actual remittance advice reference" value={remittance.source_reference} onChange={e => setRemittance(prev => ({ ...prev, source_reference: e.target.value }))}/><label className="text-xs"><input type="checkbox" checked={remittance.insurer_origin_confirmed} onChange={e => setRemittance(prev => ({ ...prev, insurer_origin_confirmed: e.target.checked }))}/> I independently verified that this payment is from the insurer</label><button className={button} disabled={busy || !remittance.insurer_origin_confirmed}>Reconcile manually</button></form>}{can(selectedClaim,'release') && <button className={button} disabled={busy} onClick={() => run(() => insurance.releaseClaim(selectedClaim.id, { expected_version: selectedClaim.version }), setSelectedClaim, 'Claim status released to the patient.')}>Release to patient</button>}{selectedClaim.history?.map(h => <p key={h.sequence} className="text-xs">#{h.sequence} {label(h.from_status || 'NEW')} → {label(h.to_status)} · {label(h.source)} · Account #{h.actor_user_id}</p>)}{selectedClaim.remittances?.map(r => <p key={r.id} className="text-xs">Manual reconciliation #{r.id} · Billing payment #{r.billing_payment_id} · {r.amount} · {r.source_reference}</p>)}</>}</> : <p className="text-sm text-slate-500">Select a claim to review its details.</p>}</section></div>
    {!patientView && selectedClaim && can(selectedClaim, 'correct') && <form onSubmit={correctClaim} className="space-y-3 rounded-2xl border bg-white p-4"><h2 className="font-bold">Correct draft or denied claim</h2><p className="text-xs text-slate-500">Only requested amounts and their manual review references may be changed. Previous values remain in claim history.</p>{selectedClaim.lines?.map(line => <div key={line.charge_id} className="grid gap-2 md:grid-cols-3"><span className="text-sm">Charge #{line.charge_id} · Billed {line.billed_amount}</span><input className={field} required type="number" step="0.01" min="0.01" max={line.billed_amount} value={correctionAmounts[line.charge_id]?.amount || ''} onChange={e => setCorrectionAmounts(prev => ({ ...prev, [line.charge_id]: { ...prev[line.charge_id], amount: e.target.value } }))} placeholder="Corrected requested amount"/><input className={field} required minLength={3} value={correctionAmounts[line.charge_id]?.review_reference || ''} onChange={e => setCorrectionAmounts(prev => ({ ...prev, [line.charge_id]: { ...prev[line.charge_id], review_reference: e.target.value } }))} placeholder="Updated line review reference"/></div>)}<textarea className={field} required minLength={3} value={correctionReason} onChange={e => setCorrectionReason(e.target.value)} placeholder="Reason for correction"/><button className={button} disabled={busy}>Record correction</button></form>}
  </div>;
}
