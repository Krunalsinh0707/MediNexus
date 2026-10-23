import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Link } from 'react-router-dom';
import { 
  Calendar, Clock, User, CheckCircle2, XCircle, AlertCircle, 
  Search, Filter, Check, X, FileText, ChevronRight, MessageSquare
} from 'lucide-react';
import { getDoctorAppointments, updateAppointmentStatus } from '../../services/hospitalService';
import { useAuth } from '../../context/AuthContext';

const STATUS_TABS = [
  { id: 'ALL', label: 'All Consultations' },
  { id: 'REQUESTED', label: 'Pending Requests' },
  { id: 'CONFIRMED', label: 'Confirmed' },
  { id: 'COMPLETED', label: 'Completed' },
  { id: 'REJECTED', label: 'Rejected' },
];

const DoctorAppointments = () => {
  const { user } = useAuth();
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [actionLoading, setActionLoading] = useState(null);
  const [feedbackMessage, setFeedbackMessage] = useState(null);

  // Reject modal state
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [selectedAppointment, setSelectedAppointment] = useState(null);
  const [rejectNotes, setRejectNotes] = useState('');

  useEffect(() => {
    fetchAppointments();
  }, []);

  const fetchAppointments = async () => {
    setLoading(true);
    try {
      const data = await getDoctorAppointments();
      setAppointments(data || []);
    } catch (err) {
      console.error('Error fetching doctor appointments:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleStatusChange = async (appointmentId, newStatus, notes = '') => {
    setActionLoading(appointmentId);
    try {
      await updateAppointmentStatus(appointmentId, newStatus, notes);
      setFeedbackMessage({
        type: 'success',
        text: `Consultation #${appointmentId} successfully updated to ${newStatus}.`
      });
      // Refresh local list
      await fetchAppointments();
      if (rejectModalOpen) {
        setRejectModalOpen(false);
        setSelectedAppointment(null);
        setRejectNotes('');
      }
    } catch (err) {
      console.error('Failed to update appointment status:', err);
      setFeedbackMessage({
        type: 'error',
        text: 'Failed to update consultation status. Please try again.'
      });
    } finally {
      setActionLoading(null);
      setTimeout(() => setFeedbackMessage(null), 4500);
    }
  };

  const openRejectModal = (appointment) => {
    setSelectedAppointment(appointment);
    setRejectNotes('');
    setRejectModalOpen(true);
  };

  const filteredAppointments = appointments.filter(app => {
    const matchesTab = activeTab === 'ALL' ? true : app.status === activeTab;
    const query = searchQuery.toLowerCase().trim();
    const matchesSearch = !query || 
      (app.patient_name && app.patient_name.toLowerCase().includes(query)) ||
      (app.patient_email && app.patient_email.toLowerCase().includes(query)) ||
      (app.reason && app.reason.toLowerCase().includes(query)) ||
      (app.time_slot && app.time_slot.toLowerCase().includes(query));
    return matchesTab && matchesSearch;
  });

  return (
    <div className="p-5 md:p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-teal-50 text-[#0F9D8A] border border-teal-200 uppercase tracking-wider">
              Clinical Triage & Scheduling
            </span>
          </div>
          <h1 className="text-2xl font-black text-slate-900 tracking-tight">Patient Consultations Management</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Review incoming consultation requests, confirm clinical appointments, manage schedule, and access patient EMR records.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            to="/doctor/dashboard"
            className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-bold transition-colors"
          >
            ← Back to Overview
          </Link>
          <button
            onClick={fetchAppointments}
            disabled={loading}
            className="px-4 py-2 bg-[#0F9D8A] hover:bg-teal-700 text-white rounded-xl text-xs font-bold transition-colors shadow-sm disabled:opacity-50"
          >
            {loading ? 'Refreshing...' : 'Refresh List'}
          </button>
        </div>
      </div>

      {/* Notifications */}
      {feedbackMessage && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className={`p-3.5 rounded-xl border text-xs font-semibold flex items-center justify-between ${
            feedbackMessage.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
              : 'bg-rose-50 border-rose-200 text-rose-800'
          }`}
        >
          <div className="flex items-center gap-2">
            {feedbackMessage.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span>{feedbackMessage.text}</span>
          </div>
          <button onClick={() => setFeedbackMessage(null)} className="opacity-70 hover:opacity-100">✕</button>
        </motion.div>
      )}

      {/* Filter and Search Bar */}
      <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row gap-4 justify-between items-stretch md:items-center">
        {/* Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0 custom-scrollbar">
          {STATUS_TABS.map(tab => {
            const count = tab.id === 'ALL' ? appointments.length : appointments.filter(a => a.status === tab.id).length;
            const isSelected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3.5 py-2 rounded-xl text-xs font-bold whitespace-nowrap transition-all flex items-center gap-2 ${
                  isSelected
                    ? 'bg-slate-900 text-white shadow-xs'
                    : 'bg-slate-50 text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <span>{tab.label}</span>
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-black ${
                  isSelected ? 'bg-slate-700 text-white' : 'bg-slate-200 text-slate-700'
                }`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Search */}
        <div className="relative min-w-[240px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search patient, complaint..."
            className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-[#0F9D8A]"
          />
        </div>
      </div>

      {/* Appointment Cards / List */}
      {loading ? (
        <div className="p-12 text-center bg-white rounded-2xl border border-slate-200">
          <div className="w-8 h-8 border-3 border-[#0F9D8A] border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>
          <p className="text-xs font-bold text-slate-500">Loading consultations roster...</p>
        </div>
      ) : filteredAppointments.length === 0 ? (
        <div className="p-12 text-center bg-white rounded-2xl border border-slate-200">
          <Calendar size={36} className="text-slate-300 mx-auto mb-2" />
          <h3 className="text-sm font-bold text-slate-800">No Consultations Found</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            {activeTab === 'REQUESTED' 
              ? 'There are no pending consultation requests. All patient requests have been triaged.' 
              : 'No appointments match the current filter or search criteria.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredAppointments.map((app) => {
            const isRequested = app.status === 'REQUESTED';
            const isConfirmed = app.status === 'CONFIRMED';
            const isCompleted = app.status === 'COMPLETED';
            const isRejected = app.status === 'REJECTED';

            return (
              <div
                key={app.id}
                className={`bg-white rounded-2xl border transition-all p-5 shadow-xs flex flex-col lg:flex-row lg:items-center justify-between gap-5 ${
                  isRequested ? 'border-amber-300 bg-amber-50/20' : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                {/* Left: Patient & Appointment Details */}
                <div className="flex items-start gap-4 min-w-0">
                  <div className={`w-11 h-11 rounded-xl flex items-center justify-center font-black text-sm shrink-0 border ${
                    isRequested 
                      ? 'bg-amber-100 text-amber-800 border-amber-200' 
                      : isConfirmed 
                      ? 'bg-teal-100 text-teal-800 border-teal-200'
                      : isCompleted
                      ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
                      : 'bg-slate-100 text-slate-700 border-slate-200'
                  }`}>
                    {app.patient_name ? app.patient_name.charAt(0).toUpperCase() : 'P'}
                  </div>

                  <div className="space-y-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-bold text-slate-900 truncate">
                        {app.patient_name || 'Patient'}
                      </h3>
                      <span className={`text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded-full ${
                        isRequested ? 'bg-amber-100 text-amber-800' :
                        isConfirmed ? 'bg-teal-100 text-teal-800' :
                        isCompleted ? 'bg-emerald-100 text-emerald-800' :
                        isRejected ? 'bg-rose-100 text-rose-800' :
                        'bg-slate-100 text-slate-700'
                      }`}>
                        {app.status}
                      </span>
                      <span className="text-[11px] text-slate-400 font-mono">
                        Ref #{app.id}
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 font-medium">
                      <span className="inline-flex items-center gap-1 text-slate-700 font-semibold">
                        <Calendar size={13} className="text-slate-400" />
                        {app.appointment_date}
                      </span>
                      <span className="inline-flex items-center gap-1 text-slate-700 font-semibold">
                        <Clock size={13} className="text-slate-400" />
                        {app.time_slot || 'Standard Slot'}
                      </span>
                      {app.patient_mobile && (
                        <span>📞 {app.patient_mobile}</span>
                      )}
                      {app.patient_email && (
                        <span className="truncate max-w-[200px]">✉️ {app.patient_email}</span>
                      )}
                    </div>

                    {app.reason && (
                      <p className="text-xs text-slate-700 bg-slate-50 border border-slate-100 rounded-lg p-2 mt-2">
                        <strong className="text-slate-900 font-semibold">Clinical Reason: </strong>
                        {app.reason}
                      </p>
                    )}

                    {app.notes && (
                      <p className="text-xs text-slate-500 italic mt-1">
                        Doctor Note: {app.notes}
                      </p>
                    )}
                  </div>
                </div>

                {/* Right: Actions */}
                <div className="flex flex-wrap items-center gap-2 shrink-0 pt-3 lg:pt-0 border-t lg:border-t-0 border-slate-100">
                  {/* Link to Patient EMR */}
                  <Link
                    to={`/doctor/patients/${app.patient_id}`}
                    className="inline-flex items-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-xl text-xs font-bold transition-colors"
                  >
                    <FileText size={14} className="text-slate-500" />
                    <span>Open Patient Chart</span>
                  </Link>

                  {/* If Requested: Confirm / Reject */}
                  {isRequested && (
                    <>
                      <button
                        onClick={() => handleStatusChange(app.id, 'CONFIRMED')}
                        disabled={actionLoading === app.id}
                        className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#0F9D8A] hover:bg-teal-700 text-white rounded-xl text-xs font-bold transition-colors shadow-xs disabled:opacity-50"
                      >
                        <Check size={14} />
                        <span>Confirm Consultation</span>
                      </button>

                      <button
                        onClick={() => openRejectModal(app)}
                        disabled={actionLoading === app.id}
                        className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-xl text-xs font-bold transition-colors disabled:opacity-50"
                      >
                        <X size={14} />
                        <span>Reject</span>
                      </button>
                    </>
                  )}

                  {/* Linked visits must be completed in the encounter workflow. */}
                  {isConfirmed && (
                    <Link
                      to={`/doctor/encounters/new?appointment_id=${app.id}&patient_id=${app.patient_id}`}
                      className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold transition-colors shadow-xs disabled:opacity-50"
                    >
                      <CheckCircle2 size={14} /><span>Open encounter</span>
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Reject Consultation Modal */}
      <AnimatePresence>
        {rejectModalOpen && selectedAppointment && (
          <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4 border border-slate-200"
            >
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div className="flex items-center gap-2 text-rose-600">
                  <XCircle size={20} />
                  <h3 className="font-extrabold text-sm text-slate-900">Decline Consultation Request</h3>
                </div>
                <button
                  onClick={() => { setRejectModalOpen(false); setSelectedAppointment(null); }}
                  className="text-slate-400 hover:text-slate-600"
                >
                  ✕
                </button>
              </div>

              <div className="text-xs text-slate-600 space-y-1">
                <p>
                  You are declining the consultation request for <strong>{selectedAppointment.patient_name}</strong> scheduled on {selectedAppointment.appointment_date} ({selectedAppointment.time_slot}).
                </p>
                <p className="text-slate-500">
                  Please provide a clinical rationale or rescheduling recommendation for the patient.
                </p>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">
                  Clinical Reason / Patient Advice <span className="text-rose-500">*</span>
                </label>
                <textarea
                  rows="3"
                  value={rejectNotes}
                  onChange={(e) => setRejectNotes(e.target.value)}
                  placeholder="e.g. Doctor is in emergency surgery. Please reschedule for tomorrow morning or consult on-call physician."
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-rose-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => { setRejectModalOpen(false); setSelectedAppointment(null); }}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-bold transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => handleStatusChange(selectedAppointment.id, 'REJECTED', rejectNotes || 'Doctor unavailable. Please select another slot.')}
                  disabled={actionLoading === selectedAppointment.id}
                  className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-xl text-xs font-bold transition-colors shadow-sm disabled:opacity-50"
                >
                  {actionLoading === selectedAppointment.id ? 'Processing...' : 'Confirm Rejection'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default DoctorAppointments;
