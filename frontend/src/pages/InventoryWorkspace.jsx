import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Package, RefreshCw } from 'lucide-react';
import * as inventory from '../services/inventoryService';
import { canMove, inventoryError, stockLabel } from './inventoryUi';

const field = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button = 'rounded-xl bg-teal-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50';
const blankReceipt = { item_id: '', lot_number: '', quantity: '', receipt_reference: '', reason: '', expires_on: '', manufactured_on: '', supplier_reference: '', unit_cost: '', currency: '' };
const blankMove = { movement_type: 'ISSUE', quantity: '', reason: '', reference: '', destination_location_id: '', workflow_type: '', workflow_reference: '', related_movement_id: '' };

export default function InventoryWorkspace() {
  const [locations, setLocations] = useState([]);
  const [locationId, setLocationId] = useState('');
  const [catalog, setCatalog] = useState([]);
  const [batches, setBatches] = useState([]);
  const [report, setReport] = useState(null);
  const [history, setHistory] = useState([]);
  const [counts, setCounts] = useState([]);
  const [selected, setSelected] = useState(null);
  const [tab, setTab] = useState('stock');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [selectedItem, setSelectedItem] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [item, setItem] = useState({ code: '', name: '', category: 'SUPPLY', unit: '', reorder_level: '0', supplier_reference: '' });
  const [receipt, setReceipt] = useState(blankReceipt);
  const [movement, setMovement] = useState(blankMove);
  const [counted, setCounted] = useState('');
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retryable, setRetryable] = useState(false);
  const [notice, setNotice] = useState('');
  const requestKey = useRef(crypto.randomUUID());

  const load = useCallback(async () => {
    setLoading(true); setError(''); setRetryable(false); setUnavailable(false);
    try {
      const access = await inventory.locations();
      const nextLocations = Array.isArray(access?.items) ? access.items : [];
      const chosen = nextLocations.some(row => String(row.id) === String(locationId)) ? locationId : String(nextLocations[0]?.id || '');
      setLocations(nextLocations); setLocationId(chosen);
      if (!chosen) { setCatalog([]); setBatches([]); setReport(null); setHistory([]); setCounts([]); return; }
      const [items, stock, batches, movements, discrepancies] = await Promise.all([
        inventory.items(search, category), inventory.stock(chosen), inventory.batches(chosen),
        inventory.movements(chosen), inventory.discrepancies(chosen),
      ]);
      setCatalog(Array.isArray(items?.items) ? items.items : []);
      setSelectedItem(old => items?.items?.find(row => row.id === old?.id) || null);
      setReport(stock);
      const next = Array.isArray(batches?.items) ? batches.items : [];
      setBatches(next);
      setHistory(Array.isArray(movements?.items) ? movements.items : []);
      setCounts(Array.isArray(discrepancies?.items) ? discrepancies.items : []);
      setSelected(old => next.find(row => row.id === old?.id) || next[0] || null);
    } catch (err) {
      const state = inventoryError(err);
      setError(state.message); setRetryable(state.retryable);
      setUnavailable(err?.response?.status === 503);
      setCatalog([]); setBatches([]); setSelected(null); setReport(null); setHistory([]); setCounts([]);
    } finally { setLoading(false); }
  }, [locationId, search, category]);

  useEffect(() => { load(); }, [load]);

  const mutate = async (action, success) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); requestKey.current = crypto.randomUUID(); setNotice(success); await load(); }
    catch (err) { const state = inventoryError(err); setError(state.message); setRetryable(state.retryable); setUnavailable(err?.response?.status === 503); }
    finally { setBusy(false); }
  };
  const change = (setter, key, value) => setter(old => ({ ...old, [key]: value }));
  const submitItem = event => { event.preventDefault(); mutate(() => inventory.createItem({ ...item, supplier_reference: item.supplier_reference || null }), 'Catalog item created.'); };
  const submitReceipt = event => {
    event.preventDefault();
    mutate(() => inventory.receive({ ...receipt, item_id: Number(receipt.item_id), location_id: Number(locationId),
      unit_cost: receipt.unit_cost || null, currency: receipt.currency || null,
      expires_on: receipt.expires_on || null, manufactured_on: receipt.manufactured_on || null,
      supplier_reference: receipt.supplier_reference || null, request_key: requestKey.current }), 'Goods receipt recorded.');
  };
  const submitMovement = event => {
    event.preventDefault(); if (!canMove(selected, movement)) return;
    mutate(() => inventory.move(selected.id, { ...movement, expected_version: selected.version,
      destination_location_id: movement.movement_type === 'TRANSFER' ? Number(movement.destination_location_id) : null,
      workflow_type: movement.workflow_type || null, workflow_reference: movement.workflow_reference || null,
      related_movement_id: movement.movement_type === 'RETURN' ? Number(movement.related_movement_id) : null,
      request_key: requestKey.current }), 'Stock movement recorded.');
  };
  const submitCount = event => {
    event.preventDefault(); if (!selected) return;
    mutate(() => inventory.reportCount(selected.id, { expected_version: selected.version,
      counted_quantity: counted, reason }), 'Physical count submitted for review.');
  };
  const decide = (row, decision) => mutate(() => inventory.decideCount(row.id, {
    expected_version: row.expected_version, decision, reason: reason.trim(), request_key: requestKey.current,
  }), `Count ${decision.toLowerCase()}.`);
  const manager = locations.find(row => String(row.id) === String(locationId))?.assignment_role === 'INVENTORY_MANAGER';

  return <div className="min-h-full space-y-5 bg-[#F6F9FB] p-4 md:p-8">
    <header><h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900"><Package className="text-teal-600" />Hospital inventory</h1>
      <p className="text-sm text-slate-600">Recorded stock by assigned location. Pharmacy dispensing remains unavailable until its transaction link is validated.</p></header>
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm flex flex-wrap items-end gap-3">
      <label className="text-xs font-semibold">Storage location<select className={field} value={locationId} onChange={e => setLocationId(e.target.value)}>
        {!locations.length && <option value="">No assigned locations</option>}{locations.map(row => <option key={row.id} value={row.id}>{row.name} ({row.code})</option>)}</select></label>
      <label className="text-xs font-semibold">Search catalog<input className={field} value={search} onChange={e => setSearch(e.target.value)} placeholder="Code or name" /></label>
      <label className="text-xs font-semibold">Category<select className={field} value={category} onChange={e => setCategory(e.target.value)}><option value="">All</option><option value="MEDICATION">Medication</option><option value="SUPPLY">Supply</option></select></label>
      <button type="button" onClick={load} disabled={busy || loading} className={button}><RefreshCw size={15} className="mr-2 inline" />Reload</button>
    </div>
    {error && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><AlertTriangle size={16} className="mr-2 inline" />{error}{retryable && <button type="button" className="ml-2 font-bold underline" onClick={load}>Retry</button>}</div>}
    {notice && <p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">{notice}</p>}
    {loading ? <p className="text-sm text-slate-500">Loading inventory…</p> : unavailable ? <p className="text-sm text-slate-600">Inventory operations remain unavailable until their database schema is installed.</p> : !locationId ? <p className="text-sm text-slate-500">No authorized storage location is available.</p> : <>
      <nav className="flex flex-wrap gap-2">{['stock', 'catalog', 'receipts', 'movements', 'counts'].map(value =>
        <button type="button" key={value} onClick={() => setTab(value)} className={tab === value ? button : 'rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold'}>{value[0].toUpperCase() + value.slice(1)}</button>)}</nav>
      {tab === 'stock' && <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-3 font-bold">Availability by item</h2>
          {!report?.items?.length ? <p className="text-sm text-slate-500">No catalog items recorded.</p> : <div className="space-y-2">{report.items.map(row =>
            <div key={row.item_id} className="rounded-xl border border-slate-100 p-3 text-sm"><strong>{row.name}</strong> <span className="text-slate-500">{row.code}</span>
              <p>On hand {row.on_hand} · Reserved {row.reserved} · Available {row.available} {row.unit}</p>
              {row.low_stock && <strong className="text-amber-700">Low stock (threshold {row.reorder_level})</strong>}</div>)}</div>}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-3 font-bold">Batches</h2>
          {!batches.length ? <p className="text-sm text-slate-500">No batches at this location.</p> : <div className="space-y-2">{batches.map(row =>
            <button type="button" key={row.id} onClick={() => setSelected(row)} className={`block w-full rounded-xl border p-3 text-left text-sm ${selected?.id === row.id ? 'border-teal-400 bg-teal-50' : 'border-slate-100'}`}>
              <strong>{row.item_name} · {row.lot_number}</strong><span className="block text-slate-600">{row.available} {row.unit} available · {stockLabel(row)}</span></button>)}</div>}
          {selected && <p className="mt-3 text-sm">Selected batch #{selected.id}, version {selected.version}, received {selected.quantity_received}, expires {selected.expires_on || 'not recorded'}.</p>}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-2 font-bold">Expiry review</h2>
          {!report?.expiring?.length ? <p className="text-sm text-slate-500">No recorded expiry within 30 days.</p> : report.expiring.map(row => <p key={row.id} className="text-sm">{row.item_name} · {row.lot_number} · {row.expires_on}</p>)}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-2 font-bold">Quarantine and recall</h2>
          {!report?.quarantined?.length ? <p className="text-sm text-slate-500">No quarantined or recalled batches.</p> : report.quarantined.map(row => <p key={row.id} className="text-sm">{row.item_name} · {row.lot_number} · {row.status}</p>)}</section>
      </div>}
      {tab === 'catalog' && <section className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3"><h2 className="font-bold">Item catalog</h2>
        {!catalog.length ? <p className="text-sm text-slate-500">No matching items.</p> : catalog.map(row => <button type="button" key={row.id} onClick={() => setSelectedItem(row)} className="block w-full rounded-lg border border-slate-100 p-2 text-left text-sm">#{row.id} · {row.code} · {row.name} · {row.category} · {row.unit}</button>)}
        {selectedItem && <div className="rounded-xl bg-slate-50 p-3 text-sm"><strong>{selectedItem.name}</strong><p>{selectedItem.description || 'No description recorded.'}</p><p>Reorder threshold: {selectedItem.reorder_level} {selectedItem.unit} · Supplier reference: {selectedItem.supplier_reference || 'Not recorded'} · {selectedItem.is_active ? 'Active' : 'Inactive'}</p></div>}
        {manager && <form onSubmit={submitItem} className="grid gap-3 border-t pt-4 md:grid-cols-3"><h3 className="md:col-span-3 font-semibold">Add catalog item</h3>
          {['code', 'name', 'unit', 'reorder_level', 'supplier_reference'].map(key => <label key={key} className="text-xs font-semibold">{key.replaceAll('_', ' ')}<input required={key !== 'supplier_reference'} className={field} value={item[key]} onChange={e => change(setItem, key, e.target.value)} /></label>)}
          <label className="text-xs font-semibold">Category<select className={field} value={item.category} onChange={e => change(setItem, 'category', e.target.value)}><option>SUPPLY</option><option>MEDICATION</option></select></label>
          <label className="text-xs font-semibold">Description<textarea className={field} value={item.description || ''} onChange={e => change(setItem, 'description', e.target.value)} /></label>
          <button disabled={busy} className={button}>Create item</button></form>}</section>}
      {tab === 'receipts' && <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-3 font-bold">Goods receipt</h2>
        <p className="mb-3 text-xs text-amber-800">Unknown expiry is recorded but cannot be issued or reserved.</p>
        <form onSubmit={submitReceipt} className="grid gap-3 md:grid-cols-3"><label className="text-xs font-semibold">Item<select required className={field} value={receipt.item_id} onChange={e => change(setReceipt, 'item_id', e.target.value)}><option value="">Select an item</option>{catalog.map(row => <option key={row.id} value={row.id}>{row.code} · {row.name}</option>)}</select></label>
          {['lot_number', 'quantity', 'receipt_reference', 'reason', 'expires_on', 'manufactured_on', 'supplier_reference', 'unit_cost', 'currency'].map(key => <label key={key} className="text-xs font-semibold">{key.replaceAll('_', ' ')}<input className={field} required={['lot_number', 'quantity', 'receipt_reference', 'reason'].includes(key)} type={key.endsWith('_on') ? 'date' : ['quantity', 'unit_cost'].includes(key) ? 'number' : 'text'} step={key === 'quantity' ? '.001' : key === 'unit_cost' ? '.01' : undefined} min={key === 'quantity' ? '.001' : key === 'unit_cost' ? '0' : undefined} value={receipt[key]} onChange={e => change(setReceipt, key, e.target.value)} /></label>)}
          <button disabled={busy} className={button}>Record receipt</button></form></section>}
      {tab === 'movements' && <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-3 font-bold">Move selected batch</h2>
        {!selected ? <p className="text-sm text-slate-500">Select a batch in Stock first.</p> : <form onSubmit={submitMovement} className="space-y-3"><p className="text-sm">{selected.item_name} · {selected.lot_number} · version {selected.version}</p>
          <label className="block text-xs font-semibold">Action<select className={field} value={movement.movement_type} onChange={e => change(setMovement, 'movement_type', e.target.value)}>{['ISSUE', 'TRANSFER', 'RESERVE', 'RELEASE', 'RETURN', 'DAMAGE', 'EXPIRY', 'QUARANTINE', 'RECALL', 'ADJUST_IN', 'ADJUST_OUT'].filter(kind => manager || !['DAMAGE', 'EXPIRY', 'QUARANTINE', 'RECALL', 'ADJUST_IN', 'ADJUST_OUT'].includes(kind)).map(kind => <option key={kind}>{kind}</option>)}</select></label>
          {['quantity', 'reason', 'reference'].map(key => <label key={key} className="block text-xs font-semibold">{key}<input className={field} required value={movement[key]} type={key === 'quantity' ? 'number' : 'text'} min={key === 'quantity' ? '.001' : undefined} step={key === 'quantity' ? '.001' : undefined} onChange={e => change(setMovement, key, e.target.value)} /></label>)}
          {movement.movement_type === 'TRANSFER' && <label className="block text-xs font-semibold">Destination location<select required className={field} value={movement.destination_location_id} onChange={e => change(setMovement, 'destination_location_id', e.target.value)}><option value="">Select location</option>{locations.filter(row => String(row.id) !== String(locationId)).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
          {movement.movement_type === 'RETURN' && <label className="block text-xs font-semibold">Original issue movement ID<input className={field} required min="1" type="number" value={movement.related_movement_id} onChange={e => change(setMovement, 'related_movement_id', e.target.value)} /></label>}
          {['RESERVE', 'RELEASE'].includes(movement.movement_type) && ['workflow_type', 'workflow_reference'].map(key => <label key={key} className="block text-xs font-semibold">{key.replaceAll('_', ' ')}<input className={field} required value={movement[key]} onChange={e => change(setMovement, key, e.target.value)} /></label>)}
          <button className={button} disabled={busy || !canMove(selected, movement)}>Record movement</button></form>}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-3 font-bold">Recent movements</h2>{!history.length ? <p className="text-sm text-slate-500">No movements recorded.</p> : <ol className="space-y-2 text-sm">{history.map(row => <li key={row.id} className="rounded-lg border border-slate-100 p-2">#{row.id} · {row.movement_type} · batch #{row.batch_id} · {row.quantity} · {row.reference} · {row.occurred_at}<span className="block text-slate-500">{row.reason} · recorded by user #{row.actor_user_id}{row.related_movement_id ? ` · issue #${row.related_movement_id}` : ''}</span></li>)}</ol>}</section></div>}
      {tab === 'counts' && <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-3 font-bold">Physical stock count</h2>
        {!selected ? <p className="text-sm text-slate-500">Select a batch in Stock first.</p> : <form onSubmit={submitCount} className="space-y-3"><p className="text-sm">Batch #{selected.id} · recorded {selected.on_hand} {selected.unit}</p><label className="block text-xs font-semibold">Counted quantity<input className={field} required type="number" min="0" step=".001" value={counted} onChange={e => setCounted(e.target.value)} /></label><label className="block text-xs font-semibold">Reason<input className={field} required value={reason} onChange={e => setReason(e.target.value)} /></label><button className={button} disabled={busy}>Submit count</button></form>}</section>
        <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-3 font-bold">Discrepancy review</h2>{!counts.length ? <p className="text-sm text-slate-500">No counts recorded.</p> : counts.map(row => <div key={row.id} className="mb-2 rounded-xl border p-3 text-sm"><strong>#{row.id} · batch {row.batch_id} · {row.status}</strong><p>Counted {row.counted_quantity} · {row.reason}</p>{manager && row.status === 'OPEN' && <div className="mt-2 flex gap-2"><button type="button" disabled={busy || reason.trim().length < 3} className={button} onClick={() => decide(row, 'APPROVED')}>Approve</button><button type="button" disabled={busy || reason.trim().length < 3} className="rounded-xl border px-3 text-sm" onClick={() => decide(row, 'REJECTED')}>Reject</button></div>}</div>)}</section></div>}
    </>}
  </div>;
}
