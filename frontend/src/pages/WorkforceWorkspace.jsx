import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw, Users } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import * as workforce from '../services/workforceService';
import { canSubmitAssignment, canSubmitShift, toOffsetISOString, workforceError } from './workforceUi';

const input = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const primary = 'rounded-xl bg-teal-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50';
const blankAssignment = { user_id: '', department_id: '', ward_id: '', location_id: '', source_module: 'WARD', assignment_role: 'NURSE', starts_at: '', expires_at: '', reason: '' };
const blankShift = { user_id: '', department_id: '', ward_id: '', title: '', starts_at: '', ends_at: '' };
const roles = {
  DOCTOR: ['MEMBER', 'RESPONDER', 'LEAD'], WARD: ['ADT_STAFF', 'WARD_MANAGER', 'NURSE', 'CHARGE_NURSE'],
  PHARMACY: ['PHARMACY_STAFF', 'PHARMACY_MANAGER'], LABORATORY: ['LAB_STAFF', 'LAB_VERIFIER', 'LAB_MANAGER'],
  RADIOLOGY: ['RAD_STAFF', 'RADIOLOGIST', 'RAD_MANAGER'], BILLING: ['BILLING_STAFF', 'BILLING_MANAGER'],
  INVENTORY: ['INVENTORY_STAFF', 'INVENTORY_MANAGER'],
};

export default function WorkforceWorkspace() {
  const { user } = useAuth();
  const isAdmin = ['admin', 'hospital_admin'].includes(user?.role);
  const [tab, setTab] = useState(isAdmin ? 'staff' : 'shifts');
  const [search, setSearch] = useState('');
  const [departmentFilter, setDepartmentFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [staff, setStaff] = useState([]);
  const [selected, setSelected] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [wards, setWards] = useState([]);
  const [locations, setLocations] = useState([]);
  const [shifts, setShifts] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [summary, setSummary] = useState(null);
  const [corrections, setCorrections] = useState([]);
  const [assignment, setAssignment] = useState(blankAssignment);
  const [shift, setShift] = useState(blankShift);
  const [reason, setReason] = useState('');
  const [correctionTime, setCorrectionTime] = useState('');
  const [reschedule, setReschedule] = useState(null);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retryable, setRetryable] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError(''); setRetryable(false); setUnavailable(false);
    try {
      if (isAdmin) {
        const [directory, depts] = await Promise.all([
          workforce.listStaff({ search: search || undefined, department_id: departmentFilter || undefined,
            role: roleFilter || undefined,
            active: statusFilter === '' ? undefined : statusFilter === 'active' }), workforce.departments(),
        ]);
        const rows = Array.isArray(directory?.items) ? directory.items : [];
        setStaff(rows); setDepartments(Array.isArray(depts?.items) ? depts.items : []);
        const chosen = rows.find(row => row.user_id === selected?.user_id) || rows[0];
        setSelected(chosen ? await workforce.getStaff(chosen.user_id) : null);
      }
      const target = isAdmin ? selected?.user_id : user?.id;
      const params = isAdmin && target ? { user_id: target } : {};
      const [roster, records, pending] = await Promise.all([
        workforce.listShifts(params), workforce.listAttendance(params), workforce.listCorrections(),
      ]);
      setShifts(Array.isArray(roster?.items) ? roster.items : []);
      setAttendance(Array.isArray(records?.items) ? records.items : []);
      setSummary(records);
      setCorrections(Array.isArray(pending?.items) ? pending.items : []);
    } catch (err) {
      const state = workforceError(err);
      setError(state.message); setRetryable(state.retryable); setUnavailable(!!state.unavailable);
      setStaff([]); setSelected(null); setShifts([]); setAttendance([]); setCorrections([]); setSummary(null);
    } finally { setLoading(false); }
  }, [isAdmin, search, departmentFilter, roleFilter, statusFilter, selected?.user_id, user?.id]);

  useEffect(() => { load(); }, [load]);

  const loadScope = async module => {
    try {
      if (module === 'WARD' && !wards.length) setWards((await workforce.wards()).items || []);
      if (module === 'INVENTORY' && !locations.length) setLocations((await workforce.locations()).items || []);
    } catch (err) { const state = workforceError(err); setError(state.message); setRetryable(state.retryable); }
  };
  const act = async (operation, message, onSuccess) => {
    setBusy(true); setError(''); setNotice('');
    try { await operation(); onSuccess?.(); setNotice(message); setHistory(null); await load(); }
    catch (err) { const state = workforceError(err); setError(state.message); setRetryable(state.retryable); setUnavailable(!!state.unavailable); }
    finally { setBusy(false); }
  };
  const change = (setter, key, value) => setter(old => ({ ...old, [key]: value }));
  const assign = event => {
    event.preventDefault(); if (!canSubmitAssignment(assignment)) return;
    const body = { ...assignment, user_id: Number(assignment.user_id), department_id: Number(assignment.department_id),
      ward_id: assignment.source_module === 'WARD' ? Number(assignment.ward_id) : null,
      location_id: assignment.source_module === 'INVENTORY' ? Number(assignment.location_id) : null,
      starts_at: toOffsetISOString(assignment.starts_at), expires_at: toOffsetISOString(assignment.expires_at) };
    act(() => workforce.createAssignment(body), 'Assignment recorded. Clinical access still follows the linked module permission.');
  };
  const schedule = event => {
    event.preventDefault(); if (!canSubmitShift(shift)) return;
    act(() => workforce.createShift({ ...shift, user_id: Number(shift.user_id),
      department_id: Number(shift.department_id), ward_id: shift.ward_id ? Number(shift.ward_id) : null,
      starts_at: toOffsetISOString(shift.starts_at), ends_at: toOffsetISOString(shift.ends_at) }), 'Shift scheduled.');
  };
  const viewEvents = async (kind, id) => {
    setError('');
    try {
      const response = kind === 'assignment' ? await workforce.assignmentEvents(id)
        : kind === 'shift' ? await workforce.shiftEvents(id) : await workforce.attendanceEvents(id);
      setHistory({ kind, id, items: response?.items || [] });
    } catch (err) { setError(workforceError(err).message); }
  };
  const chooseStaff = async row => {
    setError(''); setSelected(row); setTab('assignments');
    try { setSelected(await workforce.getStaff(row.user_id)); }
    catch (err) { setError(workforceError(err).message); }
  };
  const setSource = value => {
    setAssignment(old => ({ ...old, source_module: value, assignment_role: roles[value][0], ward_id: '', location_id: '' }));
    loadScope(value);
  };

  return <div className="min-h-full space-y-5 bg-[#F6F9FB] p-4 md:p-8">
    <header><h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900"><Users className="text-teal-600" />Hospital workforce</h1>
      <p className="text-sm text-slate-600">Existing staff accounts, current assignments, scheduled shifts, and recorded attendance.</p></header>
    <div className="flex flex-wrap gap-2">{(isAdmin ? ['staff', 'assignments', 'shifts', 'attendance'] : ['shifts', 'attendance']).map(value =>
      <button type="button" key={value} className={tab === value ? primary : 'rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold'} onClick={() => setTab(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}
      <button type="button" className="rounded-xl border border-slate-200 bg-white px-3" disabled={busy || loading} onClick={load} aria-label="Reload workforce"><RefreshCw size={16} /></button></div>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><AlertTriangle size={16} className="mr-2 inline" />{error}{retryable && <button type="button" className="ml-2 font-bold underline" onClick={load}>Retry</button>}</div>}
    {notice && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">{notice}</p>}
    {loading ? <p className="text-sm text-slate-500">Loading workforce records…</p> : unavailable ? <p className="text-sm text-slate-600">Workforce records require an approved database schema.</p> : <>
      {isAdmin && tab === 'staff' && <section className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">Staff directory</h2>
        <div className="grid gap-3 md:grid-cols-4"><label className="text-xs font-semibold">Name or staff ID<input className={input} value={search} onChange={e => setSearch(e.target.value)} /></label>
          <label className="text-xs font-semibold">Department<select className={input} value={departmentFilter} onChange={e => setDepartmentFilter(e.target.value)}><option value="">All</option>{departments.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label className="text-xs font-semibold">Role<select className={input} value={roleFilter} onChange={e => setRoleFilter(e.target.value)}><option value="">All</option>{['admin', 'hospital_admin', 'department_admin', 'doctor', 'emergency_doctor'].map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label>
          <label className="text-xs font-semibold">Account status<select className={input} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="">All</option><option value="active">Eligible</option><option value="inactive">Inactive</option></select></label></div>
        {!staff.length ? <p className="text-sm text-slate-500">No staff accounts match these filters.</p> : staff.map(row => <button type="button" key={row.user_id} onClick={() => chooseStaff(row)} className="block w-full rounded-xl border border-slate-100 p-3 text-left text-sm"><strong>{row.name}</strong> · {row.staff_identifier} · {row.role} · {row.active ? 'Eligible' : 'Inactive'}</button>)}</section>}
      {isAdmin && tab === 'assignments' && <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">Assignment history</h2>
        {!selected ? <p className="text-sm text-slate-500">Select a staff member in the directory.</p> : <><p className="text-sm font-medium">{selected.name} · {selected.staff_identifier}</p>{!selected.assignments?.length ? <p className="text-sm text-slate-500">No managed assignments recorded.</p> : selected.assignments.map(row => <div key={row.id} className="rounded-xl border border-slate-100 p-3 text-sm"><strong>{row.source_module} · {row.assignment_role}</strong><p>Department #{row.department_id}{row.ward_id ? ` · Ward #${row.ward_id}` : ''} · {row.status}{!row.effective ? ' · Not currently effective' : ''}</p><p>From {row.starts_at} to {row.expires_at || 'no set expiry'} · version {row.version}</p><button type="button" className="text-teal-700 underline" onClick={() => viewEvents('assignment', row.id)}>History</button>{['ACTIVE', 'SUSPENDED'].includes(row.status) && <div className="mt-2 flex flex-wrap gap-2">{(row.status === 'ACTIVE' ? ['SUSPEND', 'REVOKE'] : ['RESUME', 'REVOKE']).map(action => <button type="button" key={action} disabled={busy || reason.trim().length < 3} className="rounded-lg border px-2 py-1" onClick={() => act(() => workforce.changeAssignment(row.id, { expected_version: row.version, action, reason }), `Assignment ${action.toLowerCase()}d.`)}>{action}</button>)}</div>}</div>)}{selected.legacy_assignments?.length > 0 && <div className="space-y-2 border-t pt-3"><h3 className="font-semibold">Existing permissions outside workforce history</h3>{selected.legacy_assignments.map(row => <p key={`${row.source_module}-${row.source_assignment_id}`} className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-sm">{row.source_module} · {row.assignment_role} · {row.active ? 'Active in source module' : 'Inactive'} · Department #{row.department_id}. No workforce history is available.</p>)}</div>}</>}
        <label className="block text-xs font-semibold">Reason for change<input className={input} value={reason} onChange={e => setReason(e.target.value)} /></label></section>
        <form onSubmit={assign} className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">Assign existing staff</h2>
          <label className="block text-xs font-semibold">Staff<select required className={input} value={assignment.user_id} onChange={e => change(setAssignment, 'user_id', e.target.value)}><option value="">Select</option>{staff.map(row => <option key={row.user_id} value={row.user_id}>{row.name} · {row.staff_identifier}</option>)}</select></label>
          <label className="block text-xs font-semibold">Department<select required className={input} value={assignment.department_id} onChange={e => change(setAssignment, 'department_id', e.target.value)}><option value="">Select</option>{departments.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label className="block text-xs font-semibold">Workflow<select className={input} value={assignment.source_module} onChange={e => setSource(e.target.value)}>{Object.keys(roles).map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="block text-xs font-semibold">Permission role<select className={input} value={assignment.assignment_role} onChange={e => change(setAssignment, 'assignment_role', e.target.value)}>{roles[assignment.source_module].map(value => <option key={value}>{value}</option>)}</select></label>
          {assignment.source_module === 'WARD' && <label className="block text-xs font-semibold">Ward<select required className={input} value={assignment.ward_id} onFocus={() => loadScope('WARD')} onChange={e => change(setAssignment, 'ward_id', e.target.value)}><option value="">Select an existing ward</option>{wards.filter(row => String(row.department_id) === String(assignment.department_id)).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
          {assignment.source_module === 'INVENTORY' && <label className="block text-xs font-semibold">Storage location<select required className={input} value={assignment.location_id} onFocus={() => loadScope('INVENTORY')} onChange={e => change(setAssignment, 'location_id', e.target.value)}><option value="">Select an existing location</option>{locations.filter(row => String(row.department_id) === String(assignment.department_id)).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
          <label className="block text-xs font-semibold">Starts at<input required type="datetime-local" className={input} value={assignment.starts_at} onChange={e => change(setAssignment, 'starts_at', e.target.value)} /></label>
          <label className="block text-xs font-semibold">Expires at (optional)<input type="datetime-local" className={input} value={assignment.expires_at} onChange={e => change(setAssignment, 'expires_at', e.target.value)} /></label>
          <label className="block text-xs font-semibold">Reason<input required className={input} value={assignment.reason} onChange={e => change(setAssignment, 'reason', e.target.value)} /></label>
          <button className={primary} disabled={busy || !canSubmitAssignment(assignment)}>Assign staff</button></form></div>}
      {tab === 'shifts' && <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">{isAdmin ? `Shifts${selected ? ` for ${selected.name}` : ''}` : 'My shifts'}</h2>
        {!shifts.length ? <p className="text-sm text-slate-500">No scheduled shifts recorded.</p> : shifts.map(row => <div key={row.id} className="rounded-xl border p-3 text-sm"><strong>{row.title} · {row.status}</strong><p>{row.starts_at} → {row.ends_at} · Department #{row.department_id}{row.ward_id ? ` · Ward #${row.ward_id}` : ''}</p><button type="button" className="text-teal-700 underline" onClick={() => viewEvents('shift', row.id)}>History</button>{row.status === 'SCHEDULED' && <div className="mt-2 flex gap-2">{!isAdmin && <button type="button" className={primary} disabled={busy} onClick={() => act(() => workforce.clockIn(row.id), 'Clock-in recorded.')}>Clock in</button>}{isAdmin && <><button type="button" className="rounded-lg border px-2" onClick={() => setReschedule({ id: row.id, expected_version: row.version, starts_at: '', ends_at: '' })}>Reschedule</button><button type="button" className="rounded-lg border px-2" disabled={busy || reason.trim().length < 3} onClick={() => act(() => workforce.changeShift(row.id, { expected_version: row.version, action: 'CANCEL', reason }), 'Shift cancelled.')}>Cancel shift</button></>}</div>}</div>)}
        {isAdmin && reschedule && <form className="space-y-2 rounded-xl border border-teal-200 p-3" onSubmit={event => { event.preventDefault(); act(() => workforce.changeShift(reschedule.id, { expected_version: reschedule.expected_version, action: 'RESCHEDULE', starts_at: toOffsetISOString(reschedule.starts_at), ends_at: toOffsetISOString(reschedule.ends_at), reason }), 'Shift rescheduled.', () => setReschedule(null)); }}><h3 className="font-semibold">Reschedule shift #{reschedule.id}</h3>{['starts_at', 'ends_at'].map(key => <label key={key} className="block text-xs font-semibold">New {key.replace('_', ' ')}<input required type="datetime-local" className={input} value={reschedule[key]} onChange={e => change(setReschedule, key, e.target.value)} /></label>)}<button disabled={busy || reason.trim().length < 3 || !reschedule.starts_at || !reschedule.ends_at || new Date(reschedule.ends_at) <= new Date(reschedule.starts_at)} className={primary}>Save new times</button></form>}
        {isAdmin && <label className="block text-xs font-semibold">Change reason<input className={input} value={reason} onChange={e => setReason(e.target.value)} /></label>}</section>
        {isAdmin && <form onSubmit={schedule} className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">Schedule a shift</h2>
          <label className="block text-xs font-semibold">Staff<select required className={input} value={shift.user_id} onChange={e => change(setShift, 'user_id', e.target.value)}><option value="">Select</option>{staff.map(row => <option key={row.user_id} value={row.user_id}>{row.name}</option>)}</select></label>
          <label className="block text-xs font-semibold">Department<select required className={input} value={shift.department_id} onChange={e => change(setShift, 'department_id', e.target.value)}><option value="">Select</option>{departments.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label className="block text-xs font-semibold">Ward (optional)<select className={input} value={shift.ward_id} onFocus={() => loadScope('WARD')} onChange={e => change(setShift, 'ward_id', e.target.value)}><option value="">Department shift</option>{wards.filter(row => String(row.department_id) === String(shift.department_id)).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label className="block text-xs font-semibold">Shift title<input required className={input} value={shift.title} onChange={e => change(setShift, 'title', e.target.value)} /></label>
          {['starts_at', 'ends_at'].map(key => <label key={key} className="block text-xs font-semibold">{key.replace('_', ' ')}<input required type="datetime-local" className={input} value={shift[key]} onChange={e => change(setShift, key, e.target.value)} /></label>)}
          <button className={primary} disabled={busy || !canSubmitShift(shift)}>Schedule</button></form>}</div>}
      {tab === 'attendance' && <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">{isAdmin ? 'Recorded attendance' : 'My attendance'}</h2>
        <p className="text-sm">Recorded hours in this page: {summary?.recorded_hours ?? 0} · Missing clock-outs: {summary?.missing_clock_outs ?? 0}</p>
        {!attendance.length ? <p className="text-sm text-slate-500">No attendance events recorded.</p> : attendance.map(row => <div key={row.id} className="rounded-xl border p-3 text-sm"><strong>Shift #{row.shift_id} · {row.missing_clock_out ? 'Missing clock-out' : `${row.hours} hours`}</strong><p>In {row.clocked_in_at} · Out {row.clocked_out_at || 'not recorded'}</p><button type="button" className="text-teal-700 underline" onClick={() => viewEvents('attendance', row.id)}>Event history</button>{!isAdmin && <div className="mt-2 flex flex-wrap gap-2">{row.missing_clock_out && <button type="button" disabled={busy} className={primary} onClick={() => act(() => workforce.clockOut(row.id, row.version), 'Clock-out recorded.')}>Clock out</button>}<button type="button" disabled={busy || reason.trim().length < 3 || !correctionTime} className="rounded-lg border px-2" onClick={() => act(() => workforce.requestCorrection(row.id, { proposed_clock_out_at: toOffsetISOString(correctionTime), reason }), 'Correction submitted for review.')}>Request correction</button></div>}</div>)}
        {!isAdmin && <div className="grid gap-2"><label className="text-xs font-semibold">Proposed clock-out<input type="datetime-local" className={input} value={correctionTime} onChange={e => setCorrectionTime(e.target.value)} /></label><label className="text-xs font-semibold">Correction reason<input className={input} value={reason} onChange={e => setReason(e.target.value)} /></label></div>}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">Correction requests</h2>{!corrections.length ? <p className="text-sm text-slate-500">No correction requests.</p> : corrections.map(row => <div key={row.id} className="rounded-xl border p-3 text-sm"><strong>#{row.id} · attendance #{row.attendance_id} · {row.status}</strong><p>Proposed out: {row.proposed_clock_out_at} · {row.reason}</p>{isAdmin && row.status === 'PENDING' && <div className="mt-2 flex gap-2">{['APPROVED', 'REJECTED'].map(decision => <button type="button" key={decision} disabled={busy || reason.trim().length < 3} className={primary} onClick={() => act(() => workforce.decideCorrection(row.id, { decision, reason }), `Correction ${decision.toLowerCase()}.`)}>{decision}</button>)}</div>}</div>)}{isAdmin && <label className="block text-xs font-semibold">Review reason<input className={input} value={reason} onChange={e => setReason(e.target.value)} /></label>}</section></div>}
      {history && <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-2 font-bold">{history.kind} #{history.id} history</h2>{history.items.length ? <ol className="space-y-2 text-sm">{history.items.map((row, index) => <li key={row.sequence || row.version || index} className="rounded-lg border p-2">{row.action || row.to_status} · {row.effective_at || row.occurred_at || row.recorded_at}{row.reason ? ` · ${row.reason}` : ''}</li>)}</ol> : <p className="text-sm text-slate-500">No events recorded.</p>}</section>}
    </>}
  </div>;
}
