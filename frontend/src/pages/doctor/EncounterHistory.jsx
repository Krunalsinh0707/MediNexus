import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getEncounter, listEncounters } from '../../services/encounterService';
import { encounterError } from '../encounterUi';

export default function EncounterHistory({ patientId }) {
  const [visits, setVisits] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    listEncounters({ patient_id: Number(patientId), limit: 100 }).then(data => active && setVisits(data.items || []))
      .catch(err => active && setError(encounterError(err).message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [patientId]);

  const openVisit = async (id) => {
    setError(''); setSelected(null);
    try { setSelected(await getEncounter(id)); }
    catch (err) { setError(encounterError(err).message); }
  };

  return <div className="space-y-4 rounded-3xl bg-white border border-slate-200 p-6"><h3 className="font-extrabold text-slate-900">Encounter history</h3>
    {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
    {loading ? <p className="text-sm text-slate-500">Loading visits…</p> : visits.length === 0 ? <p className="text-sm text-slate-500">No accessible encounters for this patient.</p> : <div className="divide-y divide-slate-100">{visits.map(visit => <div key={visit.id} className="flex justify-between gap-3 py-3 text-sm"><div><button className="font-bold text-teal-700" onClick={() => openVisit(visit.id)}>Visit #{visit.id}</button> · {visit.status.replace('_', ' ')}<p className="text-xs text-slate-500">{visit.checked_in_at ? new Date(visit.checked_in_at).toLocaleString() : ''} · {visit.mrn}</p></div><Link className="font-bold text-teal-700" to={`/doctor/encounters/${visit.id}`}>Open workspace</Link></div>)}</div>}
    {selected && <div className="rounded-xl bg-slate-50 border p-4 text-sm space-y-2"><h4 className="font-bold">Visit #{selected.id} · {selected.status}</h4>{selected.chief_complaint && <p><strong>Chief complaint:</strong> {selected.chief_complaint}</p>}{selected.notes?.map(note => <div key={note.id} className="border-t pt-2"><p className="font-semibold">Note revision {note.revision} · {note.signed_at ? 'Signed' : 'Draft'}</p>{note.assessment && <p>Assessment: {note.assessment}</p>}{note.plan && <p>Plan: {note.plan}</p>}</div>)}{selected.diagnoses?.map(row => <p key={row.id}>Diagnosis: {row.description} ({row.status})</p>)}</div>}
  </div>;
}
