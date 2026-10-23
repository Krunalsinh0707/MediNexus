import { useCallback,useEffect,useState } from 'react';
import { FlaskConical,RefreshCw,Search,TriangleAlert } from 'lucide-react';
import {
  createLaboratoryResult,getLaboratoryOrder,listLaboratoryOrders,
  transitionLaboratoryOrder,transitionLaboratoryResult,
} from '../../services/laboratoryService';
import {
  canSubmitLaboratoryAction,laboratoryActionLabel,laboratoryError,laboratoryErrorIsRetryable,
  laboratoryResultPayload,laboratoryTransitionPayload,
} from '../laboratoryUi';

const field='w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none';
const button='rounded-xl bg-[#0F9D8A] px-3 py-2 text-sm font-bold text-white disabled:opacity-50';
const blankAction={reason:'',specimen_identifier:'',specimen_type:'',recollection_requested:false};
const blankResult={specimen_id:'',test_identifier:'',test_name:'',result_value:'',result_unit:'',correction_reason:''};

export default function LaboratoryWorkspace(){
  const [filters,setFilters]=useState({search:'',order_id:'',encounter_id:'',priority:'',status:''});
  const [items,setItems]=useState([]); const [selected,setSelected]=useState(null);
  const [action,setAction]=useState(''); const [actionForm,setActionForm]=useState(blankAction);
  const [resultForm,setResultForm]=useState(blankResult); const [showResult,setShowResult]=useState(false);
  const [loading,setLoading]=useState(true); const [busy,setBusy]=useState(false);
  const [error,setError]=useState(''); const [retryable,setRetryable]=useState(false); const [message,setMessage]=useState('');

  const load=useCallback(async()=>{
    setLoading(true); setError(''); setRetryable(false);
    try{
      const params=Object.fromEntries(Object.entries(filters).filter(([,v])=>String(v).trim()));
      const data=await listLaboratoryOrders(params); const next=Array.isArray(data?.items)?data.items:[];
      setItems(next); setSelected(current=>next.find(item=>item.order_id===current?.order_id)||next[0]||null);
    }catch(err){const parsed=laboratoryError(err);setItems([]);setSelected(null);setError(parsed.message);setRetryable(laboratoryErrorIsRetryable(err));}
    finally{setLoading(false);}
  },[filters]);
  useEffect(()=>{load();},[load]);
  const choose=async id=>{setBusy(true);setError('');try{setSelected(await getLaboratoryOrder(id));}catch(err){const parsed=laboratoryError(err);setError(parsed.message);setRetryable(laboratoryErrorIsRetryable(err));}finally{setBusy(false);}};
  const refreshSelected=async id=>{const updated=await getLaboratoryOrder(id);setSelected(updated);return updated;};
  const submitAction=async event=>{
    event.preventDefault(); if(!selected||!canSubmitLaboratoryAction(action,actionForm))return;
    setBusy(true);setError('');setMessage('');
    try{const updated=await transitionLaboratoryOrder(selected.order_id,laboratoryTransitionPayload(selected,action,actionForm));setSelected(updated);setAction('');setActionForm(blankAction);setMessage(`Laboratory workflow updated to ${updated.laboratory_status.replaceAll('_',' ').toLowerCase()}.`);await load();}
    catch(err){const parsed=laboratoryError(err);setError(parsed.message);setRetryable(laboratoryErrorIsRetryable(err));}finally{setBusy(false);}
  };
  const submitResult=async event=>{
    event.preventDefault();setBusy(true);setError('');setMessage('');
    try{const updated=await createLaboratoryResult(selected.order_id,laboratoryResultPayload(selected,resultForm));setSelected(updated);setResultForm(blankResult);setShowResult(false);setMessage('Result draft recorded. Verification and finalization are separate authorized actions.');await load();}
    catch(err){const parsed=laboratoryError(err);setError(parsed.message);setRetryable(laboratoryErrorIsRetryable(err));}finally{setBusy(false);}
  };
  const resultAction=async(result,status)=>{
    const comment=status==='REJECTED'?window.prompt('Reason for rejecting this result')?.trim():null;
    if(status==='REJECTED'&&!comment)return;
    setBusy(true);setError('');setMessage('');
    try{const updated=await transitionLaboratoryResult(selected.order_id,result.id,{expected_workflow_version:selected.version,expected_result_version:result.version,status,comment});setSelected(updated);setMessage(`Result ${status.toLowerCase()}.`);await refreshSelected(selected.order_id);}
    catch(err){const parsed=laboratoryError(err);setError(parsed.message);setRetryable(laboratoryErrorIsRetryable(err));}finally{setBusy(false);}
  };
  const setFilter=(name,value)=>setFilters(current=>({...current,[name]:value}));
  const reasonAction=['CLARIFICATION_REQUESTED','REJECTED','SPECIMEN_REJECTED'].includes(action);
  const canEnterResult=['PROCESSING','RESULT_DRAFTED','RESULT_VERIFIED','FINALIZED'].includes(selected?.laboratory_status)&&selected?.specimens?.some(s=>s.status==='RECEIVED');
  return <div className="min-h-full bg-[#F6F9FB] p-4 md:p-8 space-y-5">
    <header><h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900"><FlaskConical className="text-teal-600"/>Laboratory workspace</h1><p className="text-sm text-slate-600">Process signed orders, specimens, and versioned results without converting findings into diagnoses.</p></header>
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="grid gap-3 md:grid-cols-6">
      <label className="md:col-span-2 text-xs font-semibold">MRN, test name, or code<div className="relative"><Search size={16} className="absolute left-3 top-3 text-slate-400"/><input className={`${field} pl-9`} value={filters.search} onChange={e=>setFilter('search',e.target.value)}/></div></label>
      <label className="text-xs font-semibold">Order ID<input type="number" min="1" className={field} value={filters.order_id} onChange={e=>setFilter('order_id',e.target.value)}/></label>
      <label className="text-xs font-semibold">Encounter ID<input type="number" min="1" className={field} value={filters.encounter_id} onChange={e=>setFilter('encounter_id',e.target.value)}/></label>
      <label className="text-xs font-semibold">Priority<select className={field} value={filters.priority} onChange={e=>setFilter('priority',e.target.value)}><option value="">All</option>{['ROUTINE','URGENT','STAT'].map(v=><option key={v}>{v}</option>)}</select></label>
      <label className="text-xs font-semibold">Status<select className={field} value={filters.status} onChange={e=>setFilter('status',e.target.value)}><option value="">All</option>{['AWAITING_REVIEW','ACCEPTED','CLARIFICATION_REQUESTED','REJECTED','COLLECTION_PENDING','COLLECTED','RECEIVED','SPECIMEN_REJECTED','PROCESSING','RESULT_DRAFTED','RESULT_REJECTED','RESULT_VERIFIED','FINALIZED','ORDER_CANCELLED'].map(v=><option key={v}>{v.replaceAll('_',' ')}</option>)}</select></label>
    </div></section>
    {error&&<div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><TriangleAlert size={16} className="mr-2 inline"/>{error}{retryable&&<button className="ml-2 font-bold underline" onClick={load}>Reload</button>}</div>}
    {message&&<p role="status" className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-900">{message}</p>}
    {loading?<p className="text-sm text-slate-500">Loading laboratory queue…</p>:<div className="grid gap-5 lg:grid-cols-[minmax(280px,.8fr)_minmax(0,1.5fr)]">
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3 flex justify-between"><h2 className="font-bold">Order queue</h2><button aria-label="Refresh" onClick={load}><RefreshCw size={17}/></button></div>{!items.length?<p className="text-sm text-slate-500">No signed laboratory orders match these filters.</p>:<div className="space-y-2">{items.map(item=><button type="button" key={item.order_id} onClick={()=>choose(item.order_id)} className={`w-full rounded-xl border p-3 text-left text-sm ${selected?.order_id===item.order_id?'border-teal-400 bg-teal-50':'border-slate-200'}`}><span className="flex justify-between"><strong>{item.test_name}</strong><span>{item.priority}</span></span><span className="block text-slate-600">{item.patient.mrn} · Encounter #{item.encounter.id}</span><span className="text-xs font-bold text-teal-800">{item.laboratory_status.replaceAll('_',' ')}</span></button>)}</div>}</section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">{!selected?<p className="text-sm text-slate-500">Select a laboratory order.</p>:<>
        <div className="flex flex-wrap justify-between gap-2"><div><h2 className="text-lg font-bold">{selected.test_name} {selected.test_code&&`(${selected.test_code})`}</h2><p className="text-sm text-slate-600">Order #{selected.order_id} · {selected.patient.mrn} · {selected.patient.full_name} · Encounter #{selected.encounter.id}</p><p className="text-sm text-slate-600">Requested by {selected.requesting_clinician.full_name}</p></div><span className="h-fit rounded-full bg-slate-100 px-3 py-1 text-xs font-bold">{selected.laboratory_status.replaceAll('_',' ')}</span></div>
        {!!selected.allowed_actions?.length&&<div className="flex flex-wrap gap-2">{selected.allowed_actions.map(value=><button type="button" className={value.includes('REJECTED')?'rounded-xl border border-rose-200 px-3 py-2 text-sm font-bold text-rose-700':button} disabled={busy} key={value} onClick={()=>{setAction(value);setActionForm(blankAction);}}>{laboratoryActionLabel(value)}</button>)}</div>}
        {action&&<form onSubmit={submitAction} className="rounded-xl border border-slate-200 p-4 space-y-3"><h3 className="font-bold">{laboratoryActionLabel(action)}</h3>{reasonAction&&<label className="block text-xs font-semibold">Reason<textarea required maxLength={4000} className={field} value={actionForm.reason} onChange={e=>setActionForm(v=>({...v,reason:e.target.value}))}/></label>}{action==='SPECIMEN_REJECTED'&&<label className="flex gap-2 text-sm"><input type="checkbox" checked={actionForm.recollection_requested} onChange={e=>setActionForm(v=>({...v,recollection_requested:e.target.checked}))}/>Request recollection</label>}{action==='COLLECTED'&&<div className="grid gap-3 md:grid-cols-2"><label className="text-xs font-semibold">Specimen identifier<input required maxLength={128} className={field} value={actionForm.specimen_identifier} onChange={e=>setActionForm(v=>({...v,specimen_identifier:e.target.value}))}/></label><label className="text-xs font-semibold">Specimen type<input required maxLength={128} className={field} value={actionForm.specimen_type} onChange={e=>setActionForm(v=>({...v,specimen_type:e.target.value}))}/></label></div>}<div className="flex gap-2"><button className={button} disabled={busy||!canSubmitLaboratoryAction(action,actionForm)}>Confirm</button><button type="button" className="rounded-xl border px-3 py-2 text-sm font-bold" onClick={()=>setAction('')}>Cancel</button></div></form>}
        <div><h3 className="font-bold">Specimens</h3>{!selected.specimens?.length?<p className="text-sm text-slate-500">No collection has been recorded.</p>:<div className="mt-2 space-y-2">{selected.specimens.map(s=><article key={s.id} className="rounded-xl bg-slate-50 p-3 text-sm"><strong>{s.specimen_identifier}</strong> · {s.specimen_type} · {s.status}{s.rejection_reason&&<p className="text-rose-700">Rejected: {s.rejection_reason}{s.recollection_requested?' · Recollection requested':''}</p>}{s.events?.length>0&&<p className="mt-1 text-xs text-slate-500">{s.events.map(e=>`${e.from_status||'CREATED'} → ${e.to_status}`).join(' · ')}</p>}</article>)}</div>}</div>
        {canEnterResult&&<button type="button" className={button} onClick={()=>{const received=selected.specimens.filter(s=>s.status==='RECEIVED').at(-1);setResultForm({...blankResult,specimen_id:String(received.id),test_identifier:selected.test_code||'',test_name:selected.test_name});setShowResult(true);}}>Enter result or correction</button>}
        {showResult&&<form onSubmit={submitResult} className="rounded-xl border border-slate-200 p-4 space-y-3"><h3 className="font-bold">Result draft</h3><p className="text-xs text-slate-500">Reference ranges and flags are supplied only by an approved server catalogue. No automatic diagnosis is produced.</p><input type="hidden" value={resultForm.specimen_id}/><div className="grid gap-3 md:grid-cols-2"><label className="text-xs font-semibold">Test identifier<input required className={field} value={resultForm.test_identifier} onChange={e=>setResultForm(v=>({...v,test_identifier:e.target.value}))}/></label><label className="text-xs font-semibold">Test name<input required className={field} value={resultForm.test_name} onChange={e=>setResultForm(v=>({...v,test_name:e.target.value}))}/></label><label className="text-xs font-semibold">Result value<input required className={field} value={resultForm.result_value} onChange={e=>setResultForm(v=>({...v,result_value:e.target.value}))}/></label><label className="text-xs font-semibold">Unit<input className={field} value={resultForm.result_unit} onChange={e=>setResultForm(v=>({...v,result_unit:e.target.value}))}/></label></div><label className="block text-xs font-semibold">Correction reason (required when revising a finalized test)<textarea className={field} value={resultForm.correction_reason} onChange={e=>setResultForm(v=>({...v,correction_reason:e.target.value}))}/></label><div className="flex gap-2"><button className={button} disabled={busy||!resultForm.result_value.trim()}>Save draft</button><button type="button" className="rounded-xl border px-3 py-2 text-sm font-bold" onClick={()=>setShowResult(false)}>Cancel</button></div></form>}
        <div><h3 className="font-bold">Results and revisions</h3>{!selected.results?.length?<p className="text-sm text-slate-500">No results have been entered.</p>:<div className="mt-2 space-y-3">{selected.results.map(result=><article key={result.id} className="rounded-xl border border-slate-200 p-3 text-sm"><div className="flex justify-between"><strong>{result.test_name} · revision {result.revision_number}</strong><span>{result.status}</span></div><p>{result.result_value} {result.result_unit||''} · {result.abnormality_flag.replaceAll('_',' ')}</p>{result.reference_range_text?<p>Reference: {result.reference_range_text} · source {result.reference_range_source}</p>:<p className="text-slate-500">No approved reference range supplied; abnormality not assessed.</p>}{result.correction_reason&&<p><strong>Correction reason:</strong> {result.correction_reason}</p>}<div className="mt-2 flex gap-2">{result.allowed_actions?.map(value=><button className={value==='REJECTED'?'rounded-xl border border-rose-200 px-3 py-2 text-sm font-bold text-rose-700':button} disabled={busy} key={value} onClick={()=>resultAction(result,value)}>{value==='REJECTED'?'Reject result':laboratoryActionLabel(value)}</button>)}</div></article>)}</div>}</div>
        <div><h3 className="font-bold">Workflow history</h3>{!selected.events?.length?<p className="text-sm text-slate-500">No laboratory actions recorded.</p>:<ol className="mt-2 space-y-2 text-sm">{selected.events.map(e=><li className="rounded-lg border border-slate-100 p-2" key={e.sequence}>#{e.sequence} {e.from_status||'AWAITING REVIEW'} → {e.to_status}{e.reason?` · ${e.reason}`:''}</li>)}</ol>}</div>
      </>}</section>
    </div>}
  </div>;
}
