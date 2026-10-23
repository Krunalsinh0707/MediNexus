import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getEncounter } from '../../services/encounterService';
import { encounterError } from '../encounterUi';

export default function EncounterDetail() {
  const { encounterId } = useParams();
  const [visit, setVisit] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    getEncounter(encounterId).then(data => active && setVisit(data)).catch(err => active && setError(encounterError(err).message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [encounterId]);
  return <div className="max-w-3xl mx-auto space-y-4"><Link to="/admin/encounters" className="text-teal-700 text-sm font-bold">Back to encounter queue</Link><h2 className="text-2xl font-black">Visit overview</h2>
    {loading && <p>Loading visit…</p>}{error && <p role="alert" className="text-rose-700">{error}</p>}
    {visit && <div className="rounded-2xl bg-white border border-slate-200 p-5 space-y-2 text-sm"><p className="text-lg font-bold">{visit.patient_name} · {visit.mrn}</p><p>Visit #{visit.id} · {visit.status.replace('_', ' ')}</p><p>Doctor #{visit.doctor_id || 'unassigned'} · Department #{visit.department_id || 'unassigned'}</p><p>{visit.appointment_id ? `Appointment #${visit.appointment_id}` : 'Walk-in visit'}</p><p>Checked in: {visit.checked_in_at ? new Date(visit.checked_in_at).toLocaleString() : 'Not recorded'}</p><p className="text-slate-500">Clinical notes are available only to authorized clinicians.</p></div>}
  </div>;
}
