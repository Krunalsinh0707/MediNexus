import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { FileText, Cpu, CheckCircle2, AlertTriangle, XCircle, Edit3, ShieldCheck } from 'lucide-react';
import { getReportsPendingReview, submitDoctorReview } from '../../services/medicalReportsService';
import AIAnalysisCard from '../../components/AIAnalysisCard';
import { clinicalWriteError } from '../clinicalWriteErrors';

const DoctorReports = () => {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedReport, setSelectedReport] = useState(null);
  const [reviewStatus, setReviewStatus] = useState('APPROVED');
  const [clinicalNotes, setClinicalNotes] = useState('');
  const [finalAssessment, setFinalAssessment] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetchQueue();
  }, []);

  const fetchQueue = async () => {
    setLoading(true);
    try {
      const data = await getReportsPendingReview();
      setReports(data || []);
    } catch (err) {
      console.error(err);
      setMessage(clinicalWriteError(err, 'review'));
      setReports([]);
    } finally {
      setLoading(false);
    }
  };

  const handleReviewSubmit = async (e) => {
    e.preventDefault();
    if (!selectedReport) return;

    try {
      await submitDoctorReview(selectedReport.id, {
        review_status: reviewStatus,
        clinical_notes: clinicalNotes,
        final_assessment: finalAssessment
      });

      setMessage(`Report #${selectedReport.id} successfully finalized with status: ${reviewStatus}`);
      setSelectedReport(null);
      setClinicalNotes('');
      setFinalAssessment('');
      fetchQueue();
    } catch (err) {
      console.error(err);
      setMessage(clinicalWriteError(err, 'review'));
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-black text-slate-900 tracking-tight uppercase">DOCTOR CLINICAL DECISION SUPPORT & REVIEW</h1>
        <p className="text-xs font-semibold text-slate-500 mt-1">
          Review extracted diagnostic parameters and AI pre-analysis. Authorize, modify, or reject AI findings before final medical record entry.
        </p>
      </div>

      {message && (
        <div className="p-4 bg-teal-50 border border-teal-200 text-teal-800 font-bold text-xs rounded-xl flex items-center justify-between">
          <span>{message}</span>
          <button onClick={() => setMessage('')} className="text-teal-600">✕</button>
        </div>
      )}

      {/* Reports Queue */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1 bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4">
          <h2 className="text-base font-extrabold text-slate-900 uppercase tracking-tight">Reports Pending Review ({reports.length})</h2>

          {loading ? (
            <p className="text-xs text-slate-400 py-6 text-center">Loading queue...</p>
          ) : reports.length === 0 ? (
            <div className="text-center py-10 text-slate-400">
              <CheckCircle2 size={36} className="mx-auto mb-2 opacity-40 text-teal-600" />
              <p className="text-xs font-bold text-slate-600">Queue Clean!</p>
              <p className="text-[10px] text-slate-400 mt-0.5">All pending reports have been reviewed.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {reports.map((r) => (
                <div
                  key={r.id}
                  onClick={() => {
                    setSelectedReport(r);
                    setClinicalNotes('');
                    setFinalAssessment(r.ai_analysis?.prediction ? `Confirmed: ${r.ai_analysis.prediction}` : '');
                  }}
                  className={`p-4 rounded-2xl border transition-all cursor-pointer ${
                    selectedReport?.id === r.id 
                      ? 'bg-teal-50/60 border-teal-500 shadow-sm' 
                      : 'bg-slate-50 border-slate-200 hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-black text-slate-500 uppercase">{r.report_type || 'Diagnostic Report'}</span>
                    <span className="text-[10px] font-bold text-slate-400">{r.created_at}</span>
                  </div>
                  <h3 className="text-xs font-extrabold text-slate-900 mt-1">{r.report_title}</h3>
                  <p className="text-[10px] font-medium text-slate-500">Patient: {r.patient_name}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Selected Report Workspace & Doctor Form */}
        <div className="lg:col-span-2 space-y-6">
          {selectedReport ? (
            <div className="bg-white p-6 md:p-8 rounded-3xl border border-slate-200 shadow-sm space-y-6">
              <div className="border-b border-slate-100 pb-4 flex items-center justify-between">
                <div>
                  <span className="text-[10px] font-black text-[#0F9D8A] uppercase tracking-widest">PATIENT REPORT #{selectedReport.id}</span>
                  <h2 className="text-xl font-black text-slate-900">{selectedReport.report_title}</h2>
                  <p className="text-xs text-slate-500 font-medium">Patient: {selectedReport.patient_name} ({selectedReport.patient_email})</p>
                </div>
                {selectedReport.patient_id && (
                  <Link
                    to={`/doctor/patients/${selectedReport.patient_id}`}
                    className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-xl text-xs font-bold transition-colors"
                  >
                    Open Patient Chart →
                  </Link>
                )}
              </div>

              {/* Extracted Parameters */}
              {selectedReport.extracted_json && Object.keys(selectedReport.extracted_json).length > 0 && (
                <div className="bg-slate-50 p-4 rounded-2xl border border-slate-200 space-y-2">
                  <h4 className="text-xs font-extrabold uppercase tracking-wider text-slate-700">Extracted Lab Parameters</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {Object.entries(selectedReport.extracted_json).map(([k, v]) => (
                      <div key={k} className="bg-white p-2 rounded-lg border border-slate-100 text-xs">
                        <span className="text-slate-400 block text-[9px] uppercase font-bold">{k}</span>
                        <span className="font-extrabold text-slate-800">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* AI Pre-analysis display */}
              {selectedReport.ai_analysis && (
                <AIAnalysisCard analysis={selectedReport.ai_analysis} />
              )}

              {/* Doctor Review Form */}
              <form onSubmit={handleReviewSubmit} className="bg-slate-900 text-white p-6 rounded-2xl space-y-4">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={20} className="text-teal-400" />
                  <h3 className="text-sm font-black uppercase tracking-wider text-white">Authorized Doctor Decision & Signing</h3>
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Review Decision</label>
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { status: 'APPROVED', label: 'Approve AI', color: 'bg-emerald-600' },
                      { status: 'MODIFIED', label: 'Modify Diagnosis', color: 'bg-amber-600' },
                      { status: 'REJECTED', label: 'Reject AI Result', color: 'bg-rose-600' }
                    ].map((opt) => (
                      <button
                        key={opt.status}
                        type="button"
                        onClick={() => setReviewStatus(opt.status)}
                        className={`py-2.5 rounded-xl text-xs font-black transition-all border ${
                          reviewStatus === opt.status 
                            ? `${opt.color} text-white border-transparent shadow-md` 
                            : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">Doctor Clinical Notes</label>
                  <textarea
                    rows="3"
                    value={clinicalNotes}
                    onChange={(e) => setClinicalNotes(e.target.value)}
                    placeholder="Enter formal clinical observation, diagnostic notes, and patient advice..."
                    required
                    className="w-full p-3 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-teal-400"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">Final Medical Assessment</label>
                  <input
                    type="text"
                    value={finalAssessment}
                    onChange={(e) => setFinalAssessment(e.target.value)}
                    placeholder="Final medical diagnostic statement..."
                    required
                    className="w-full p-3 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-teal-400"
                  />
                </div>

                <button
                  type="submit"
                  className="w-full py-3.5 bg-[#0F9D8A] hover:bg-teal-600 text-white font-black text-xs uppercase tracking-widest rounded-xl transition-all shadow-lg shadow-teal-900/40"
                >
                  [ Finalize Digital Medical Record ]
                </button>
              </form>
            </div>
          ) : (
            <div className="bg-white p-12 rounded-3xl border border-slate-200 text-center text-slate-400">
              <FileText size={48} className="mx-auto mb-3 opacity-30" />
              <h3 className="text-sm font-bold text-slate-700">No Report Selected</h3>
              <p className="text-xs text-slate-400 mt-1">Select a pending report from the left queue to review AI pre-analysis and finalize patient medical records.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default DoctorReports;
