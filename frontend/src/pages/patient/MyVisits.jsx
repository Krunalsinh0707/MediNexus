import { useEffect, useState } from 'react';
import { getEncounter, listEncounters } from '../../services/encounterService';
import { encounterError, patientSummaries } from '../encounterUi';
import MedicalHistoryTimeline from '../../components/MedicalHistoryTimeline';

export default function MyVisits() {
  const [visits, setVisits] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    listEncounters({ status: 'COMPLETED', limit: 25, offset }).then(data => {
      if (active) { setVisits(data.items || []); setTotal(data.total || 0); }
    }).catch(err => active && setError(encounterError(err).message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [offset]);

  const openSummary = async (id) => {
    setDetailLoading(true); setError(''); setSelected(null);
    try {
      const detail = await getEncounter(id);
      // Patient responses contain only signed summaries. Project that field again
      // so a future backend field addition cannot accidentally render a draft.
      setSelected({ id: detail.id, patient_name: detail.patient_name, mrn: detail.mrn,
        completed_at: detail.completed_at, summaries: patientSummaries(detail) });
    } catch (err) { setError(encounterError(err).message); }
    finally { setDetailLoading(false); }
  };

  return <div className="max-w-5xl mx-auto p-5 md:p-8 space-y-5"><div><h1 className="text-2xl font-black text-slate-900">My visit summaries</h1><p className="text-sm text-slate-500">Signed patient-facing summaries from completed hospital visits.</p></div>
    {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">{loading ? <p>Loading visits…</p> : visits.length === 0 ? <p className="text-sm text-slate-500">No completed visits are available yet.</p> : <div className="divide-y divide-slate-100">{visits.map(visit => <button key={visit.id} onClick={() => openSummary(visit.id)} className="block w-full text-left py-3 hover:text-teal-700"><span className="font-bold">Visit #{visit.id}</span> · {visit.completed_at ? new Date(visit.completed_at).toLocaleDateString() : 'Date unavailable'}<span className="block text-xs text-slate-500">{visit.mrn}</span></button>)}</div>}
      <div className="flex justify-between mt-4 text-sm"><button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><span>{total} completed visits</span><button disabled={offset + 25 >= total || loading} onClick={() => setOffset(offset + 25)}>Next</button></div>
    </section>
    {detailLoading && <p className="text-sm">Loading signed summary…</p>}
    {selected && <section className="rounded-2xl border border-teal-200 bg-white p-5 space-y-3"><h2 className="font-bold text-lg">Visit #{selected.id} · {selected.mrn}</h2>{selected.summaries.length === 0 ? <p className="text-sm text-slate-500">No signed patient-facing summary is available.</p> : selected.summaries.map(summary => <article key={summary.id} className="border-t pt-3"><p className="text-xs font-semibold text-slate-500">{summary.kind === 'ADDENDUM' ? 'Signed addendum' : 'Signed visit summary'} · {new Date(summary.signed_at).toLocaleString()}</p><p className="mt-2 text-sm whitespace-pre-wrap text-slate-800">{summary.patient_summary}</p></article>)}</section>}
    <MedicalHistoryTimeline />
  </div>;
}
