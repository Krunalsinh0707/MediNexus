import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MessageSquare, AlertCircle, ShieldAlert, CheckCircle2, User,
  Clock, ArrowRight, RefreshCw, Filter, Search, Send, UserCheck,
  Building, ChevronRight, Stethoscope, Sparkles, Activity, FileText,
  AlertTriangle, PhoneCall, History, Info, X
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import clinicalChatService from '../../services/clinicalChatService';
import api from '../../services/api';
import { clinicalWriteError } from '../clinicalWriteErrors';

const QUICK_CLINICAL_TEMPLATES = [
  "I have reviewed your message and clinical findings. Vital signs appear stable. Continue current medications.",
  "Based on your reported symptoms, please schedule an in-person clinical follow-up within 24–48 hours.",
  "Please proceed immediately to the Urgent Care clinic or nearest Emergency Room for direct evaluation.",
  "Your lab results have been reviewed. Kindly ensure adequate hydration, rest, and monitor your temperature."
];

export default function ClinicalChatConsole() {
  const { user } = useAuth();

  // State
  const [inboxItems, setInboxItems] = useState([]);
  const [selectedConvId, setSelectedConvId] = useState(null);
  const [selectedConv, setSelectedConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingInbox, setLoadingInbox] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sendingReply, setSendingReply] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [activeTab, setActiveTab] = useState('messages'); // 'messages' | 'ai_insights' | 'timeline'
  const [timelineEvents, setTimelineEvents] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [doctorsList, setDoctorsList] = useState([]);

  // Filters
  const [queueFilter, setQueueFilter] = useState('all');
  const [urgencyFilter, setUrgencyFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [isPollingActive, setIsPollingActive] = useState(true);
  const [unreadAlerts, setUnreadAlerts] = useState(0);

  // Modals
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [escalateModalOpen, setEscalateModalOpen] = useState(false);
  const [resolveModalOpen, setResolveModalOpen] = useState(false);

  const [targetDeptId, setTargetDeptId] = useState('');
  const [targetDoctorId, setTargetDoctorId] = useState('');
  const [assignReason, setAssignReason] = useState('');

  const [targetUrgency, setTargetUrgency] = useState('HIGH_PRIORITY');
  const [escalateReason, setEscalateReason] = useState('');

  const [resolutionNotes, setResolutionNotes] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);

  const messagesEndRef = useRef(null);

  const showToast = (text) => {
    setToastMessage(text);
    setTimeout(() => setToastMessage(null), 4000);
  };

  // Fetch departments and doctors for assignment modal
  useEffect(() => {
    api.get('/departments').then(res => {
      setDepartments(res.data.departments || res.data || []);
    }).catch(err => console.error("Error fetching departments", err));

    api.get('/doctors').then(res => {
      setDoctorsList(res.data.doctors || res.data || []);
    }).catch(err => console.error("Error fetching doctors", err));
  }, []);

  // Fetch inbox function
  const fetchInbox = useCallback(async (silent = false) => {
    if (!silent) setLoadingInbox(true);
    try {
      const params = { queue: queueFilter };
      if (urgencyFilter) params.urgency = urgencyFilter;
      if (searchQuery) params.search = searchQuery;

      const data = await clinicalChatService.getDoctorInbox(params);
      setInboxItems(data.conversations || []);
      setUnreadAlerts(data.unread_alerts_count || 0);

      // If nothing selected or selected conv no longer exists, select first
      if (!selectedConvId && data.conversations && data.conversations.length > 0) {
        setSelectedConvId(data.conversations[0].id);
      }
    } catch (err) {
      console.error("Failed to load clinical inbox", err);
    } finally {
      if (!silent) setLoadingInbox(false);
    }
  }, [queueFilter, urgencyFilter, searchQuery, selectedConvId]);

  // Initial load and filter change
  useEffect(() => {
    fetchInbox();
  }, [fetchInbox]);

  // Live polling every 6 seconds
  useEffect(() => {
    if (!isPollingActive) return;
    const interval = setInterval(() => {
      fetchInbox(true);
      if (selectedConvId) {
        fetchMessagesOnly(selectedConvId);
      }
    }, 6000);
    return () => clearInterval(interval);
  }, [isPollingActive, fetchInbox, selectedConvId]);

  // Fetch full conversation details when selected
  const fetchConversationDetail = async (id) => {
    setLoadingDetail(true);
    try {
      const data = await clinicalChatService.getConversation(id);
      setSelectedConv(data);
      setMessages(data.messages || []);
      // Scroll to bottom
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    } catch (err) {
      console.error("Failed to load conversation details", err);
      showToast("Unable to load consultation details. Access may be restricted.");
    } finally {
      setLoadingDetail(false);
    }
  };

  const fetchMessagesOnly = async (id) => {
    try {
      const msgs = await clinicalChatService.getConversationMessages(id);
      setMessages(msgs || []);
    } catch (err) {
      console.error("Silent message refresh failed", err);
    }
  };

  useEffect(() => {
    if (selectedConvId) {
      fetchConversationDetail(selectedConvId);
    }
  }, [selectedConvId]);

  // Fetch timeline events when switching to timeline tab
  useEffect(() => {
    if (activeTab === 'timeline' && selectedConvId) {
      clinicalChatService.getConversationEvents(selectedConvId).then(events => {
        setTimelineEvents(events || []);
      }).catch(err => console.error("Error loading events", err));
    }
  }, [activeTab, selectedConvId]);

  // Actions
  const handleAcknowledgeAlert = async () => {
    if (!selectedConvId) return;
    setActionLoading(true);
    try {
      await clinicalChatService.acknowledgeAlert(selectedConvId, "Clinician acknowledged via Doctor Console");
      showToast("Alert successfully acknowledged.");
      await fetchConversationDetail(selectedConvId);
      await fetchInbox(true);
    } catch (err) {
      showToast("Failed to acknowledge alert.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleSendReply = async (e) => {
    if (e) e.preventDefault();
    if (!replyText.trim() || !selectedConvId || sendingReply) return;

    setSendingReply(true);
    try {
      await clinicalChatService.sendMessage(selectedConvId, replyText.trim());
      setReplyText('');
      await fetchConversationDetail(selectedConvId);
      await fetchInbox(true);
      showToast("Clinical response delivered to patient.");
    } catch (err) {
      showToast(clinicalWriteError(err, 'chat'));
    } finally {
      setSendingReply(false);
    }
  };

  const handleAssignSubmit = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await clinicalChatService.assignConversation(selectedConvId, {
        doctorId: targetDoctorId ? parseInt(targetDoctorId) : null,
        departmentId: targetDeptId ? parseInt(targetDeptId) : null,
        reason: assignReason || "Clinician transfer via console"
      });
      setAssignModalOpen(false);
      showToast("Conversation reassigned successfully.");
      await fetchConversationDetail(selectedConvId);
      await fetchInbox(true);
    } catch (err) {
      showToast(clinicalWriteError(err, 'chat'));
    } finally {
      setActionLoading(false);
    }
  };

  const handleEscalateSubmit = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await clinicalChatService.escalateConversation(selectedConvId, {
        urgency: targetUrgency,
        reason: escalateReason || "Physician escalation",
        departmentId: targetDeptId ? parseInt(targetDeptId) : null
      });
      setEscalateModalOpen(false);
      showToast("Conversation urgency escalated.");
      await fetchConversationDetail(selectedConvId);
      await fetchInbox(true);
    } catch (err) {
      showToast(clinicalWriteError(err, 'chat'));
    } finally {
      setActionLoading(false);
    }
  };

  const handleResolveSubmit = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await clinicalChatService.resolveConversation(selectedConvId, {
        resolutionNotes: resolutionNotes || "Clinically resolved by attending doctor"
      });
      setResolveModalOpen(false);
      showToast("Consultation marked as resolved.");
      await fetchConversationDetail(selectedConvId);
      await fetchInbox(true);
    } catch (err) {
      showToast(clinicalWriteError(err, 'chat'));
    } finally {
      setActionLoading(false);
    }
  };

  // Helper badge formatters
  const getUrgencyBadge = (urgency) => {
    switch (urgency) {
      case 'EMERGENCY_REVIEW':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
            <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
            <AlertCircle size={13} className="text-rose-600" />
            EMERGENCY REVIEW
          </span>
        );
      case 'HIGH_PRIORITY':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200">
            <AlertTriangle size={12} className="text-amber-600" />
            High Priority
          </span>
        );
      case 'MODERATE':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-50 text-yellow-800 border border-yellow-200">
            Moderate
          </span>
        );
      case 'LOW_PRIORITY':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            Low Priority
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
            Normal
          </span>
        );
    }
  };

  const getEscalationBadge = (escStatus) => {
    if (escStatus === 'PENDING_ACK') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-rose-600 text-white shadow-sm animate-pulse">
          <AlertCircle size={13} />
          ACTION REQUIRED
        </span>
      );
    } else if (escStatus === 'ACKNOWLEDGED') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
          <UserCheck size={12} />
          Acknowledged
        </span>
      );
    } else if (escStatus === 'RESOLVED') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">
          <CheckCircle2 size={12} />
          Resolved
        </span>
      );
    }
    return null;
  };

  return (
    <div className="flex flex-col h-[calc(100vh-1rem)] bg-[#F8FAFC] text-slate-800 p-4 md:p-6 overflow-hidden">
      {/* Toast */}
      <AnimatePresence>
        {toastMessage && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="fixed top-6 right-8 z-50 bg-slate-900 text-white px-4 py-2.5 rounded-xl shadow-xl flex items-center gap-2 border border-slate-700 text-sm font-medium"
          >
            <Info size={16} className="text-cyan-400" />
            {toastMessage}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Header Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-600 to-blue-600 flex items-center justify-center text-white shadow-md shadow-cyan-500/20">
              <Stethoscope size={22} />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-bold tracking-tight text-slate-900">
                Doctor Clinical Chat Console
              </h1>
              <p className="text-xs md:text-sm text-slate-500">
                Authorized patient consultation inbox, emergency triage alerts & clinical escalation management
              </p>
            </div>
          </div>
        </div>

        {/* Polling & Refresh status */}
        <div className="flex items-center gap-3 self-end md:self-auto">
          {unreadAlerts > 0 && (
            <div className="flex items-center gap-1.5 bg-rose-50 border border-rose-200 text-rose-700 px-3 py-1.5 rounded-lg text-xs font-semibold">
              <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
              {unreadAlerts} Unacknowledged Alert{unreadAlerts > 1 ? 's' : ''}
            </div>
          )}

          <button
            onClick={() => setIsPollingActive(!isPollingActive)}
            className={`text-xs px-3 py-1.5 rounded-lg border font-medium flex items-center gap-1.5 transition-colors ${
              isPollingActive
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                : 'bg-slate-100 text-slate-600 border-slate-300 hover:bg-slate-200'
            }`}
            title={isPollingActive ? "Click to pause live polling" : "Click to resume live polling"}
          >
            <span className={`w-2 h-2 rounded-full ${isPollingActive ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`} />
            {isPollingActive ? 'Live Polling On' : 'Polling Paused'}
          </button>

          <button
            onClick={() => fetchInbox(false)}
            disabled={loadingInbox}
            className="p-2 text-slate-600 hover:text-cyan-600 hover:bg-white bg-slate-100 border border-slate-200 rounded-lg shadow-xs transition-colors"
            title="Manual Refresh"
          >
            <RefreshCw size={16} className={loadingInbox ? 'animate-spin text-cyan-600' : ''} />
          </button>
        </div>
      </div>

      {/* Main Master-Detail Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 flex-1 min-h-0 pt-4">

        {/* Left Column: Triage Queue & Inbox (4 Cols) */}
        <div className="lg:col-span-4 flex flex-col bg-white rounded-2xl border border-slate-200/80 shadow-xs overflow-hidden h-full">
          {/* Filter Bar */}
          <div className="p-3.5 border-b border-slate-100 space-y-2.5 bg-slate-50/50">
            {/* Search Input */}
            <div className="relative">
              <Search size={15} className="absolute left-3 top-2.5 text-slate-400" />
              <input
                type="text"
                placeholder="Search patient name, ID, or title..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg focus:outline-hidden focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
              />
            </div>

            {/* Queue Tabs */}
            <div className="flex gap-1 bg-slate-200/70 p-1 rounded-xl text-xs font-medium">
              {[
                { id: 'all', label: 'All Active' },
                { id: 'assigned', label: 'My Cases' },
                { id: 'department', label: 'Dept Queue' },
                { id: 'emergency', label: '🚨 Urgent' }
              ].map(t => (
                <button
                  key={t.id}
                  onClick={() => setQueueFilter(t.id)}
                  className={`flex-1 py-1 px-1.5 rounded-lg text-center transition-all ${
                    queueFilter === t.id
                      ? 'bg-white text-slate-900 shadow-xs font-semibold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Urgency Quick Chips */}
            <div className="flex items-center gap-1.5 overflow-x-auto text-[11px] pt-0.5">
              <span className="text-slate-400 font-medium">Tier:</span>
              {['', 'EMERGENCY_REVIEW', 'HIGH_PRIORITY', 'MODERATE', 'NORMAL'].map((u) => (
                <button
                  key={u}
                  onClick={() => setUrgencyFilter(u)}
                  className={`px-2 py-0.5 rounded-md shrink-0 transition-colors ${
                    urgencyFilter === u
                      ? 'bg-cyan-600 text-white font-semibold'
                      : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {u ? u.replace('_', ' ') : 'All'}
                </button>
              ))}
            </div>
          </div>

          {/* Conversation List */}
          <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
            {loadingInbox ? (
              <div className="p-8 text-center text-slate-400 text-xs flex flex-col items-center gap-2">
                <RefreshCw size={20} className="animate-spin text-cyan-600" />
                Loading authorized patient queues...
              </div>
            ) : inboxItems.length === 0 ? (
              <div className="p-8 text-center text-slate-400 text-xs flex flex-col items-center gap-2">
                <CheckCircle2 size={28} className="text-slate-300" />
                No consultations found in current queue.
              </div>
            ) : (
              inboxItems.map((item) => {
                const isSelected = item.id === selectedConvId;
                const isActionRequired = item.escalation_status === 'PENDING_ACK';
                return (
                  <div
                    key={item.id}
                    onClick={() => setSelectedConvId(item.id)}
                    className={`p-3.5 cursor-pointer transition-all border-l-4 ${
                      isSelected
                        ? 'bg-cyan-50/60 border-l-cyan-600 shadow-xs'
                        : isActionRequired
                        ? 'border-l-rose-500 bg-rose-50/20 hover:bg-rose-50/40'
                        : 'border-l-transparent hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <div className="flex items-center gap-1.5 font-semibold text-sm text-slate-900 truncate">
                        <span>{item.patient_name}</span>
                        <span className="text-[11px] font-normal text-slate-400">#{item.id}</span>
                      </div>
                      <span className="text-[10px] text-slate-400 whitespace-nowrap">
                        {new Date(item.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>

                    <div className="text-xs text-slate-700 font-medium mb-1.5 line-clamp-1">
                      {item.title}
                    </div>

                    {item.latest_message_snippet && (
                      <div className="text-[11px] text-slate-500 line-clamp-1 mb-2">
                        "{item.latest_message_snippet}"
                      </div>
                    )}

                    <div className="flex items-center justify-between gap-1 flex-wrap">
                      <div className="flex items-center gap-1 flex-wrap">
                        {getUrgencyBadge(item.urgency)}
                        {getEscalationBadge(item.escalation_status)}
                      </div>
                      {item.department_name && (
                        <span className="text-[10px] text-slate-500 font-medium bg-slate-100 px-2 py-0.5 rounded-sm">
                          {item.department_name}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Active Conversation Workspace (8 Cols) */}
        <div className="lg:col-span-8 flex flex-col bg-white rounded-2xl border border-slate-200/80 shadow-xs overflow-hidden h-full">
          {selectedConv ? (
            <>
              {/* Workspace Header */}
              <div className="p-4 border-b border-slate-200 bg-slate-50/80">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                  {/* Patient Info */}
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-cyan-100 text-cyan-800 font-bold flex items-center justify-center text-sm border border-cyan-200">
                      {selectedConv.patient_name.charAt(0)}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="text-base font-bold text-slate-900">{selectedConv.patient_name}</h2>
                        {selectedConv.patient_blood_group && (
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700">
                            {selectedConv.patient_blood_group}
                          </span>
                        )}
                        <span className="text-xs text-slate-500">Patient ID #{selectedConv.patient_id}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5">
                        <span className="flex items-center gap-1">
                          <Building size={12} />
                          {selectedConv.department_name || 'General Triage'}
                        </span>
                        <span>•</span>
                        <span className="flex items-center gap-1">
                          <User size={12} />
                          {selectedConv.assigned_doctor_name || 'Unassigned'}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Urgency & Action Buttons */}
                  <div className="flex items-center gap-2 flex-wrap">
                    {getUrgencyBadge(selectedConv.urgency)}

                    {selectedConv.escalation_status === 'PENDING_ACK' && (
                      <button
                        onClick={handleAcknowledgeAlert}
                        disabled={actionLoading}
                        className="px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-600 text-white hover:bg-rose-700 shadow-sm flex items-center gap-1.5 transition-colors"
                      >
                        <CheckCircle2 size={14} />
                        Acknowledge Alert
                      </button>
                    )}

                    <button
                      onClick={() => setAssignModalOpen(true)}
                      className="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 transition-colors"
                    >
                      Assign
                    </button>

                    <button
                      onClick={() => setEscalateModalOpen(true)}
                      className="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 transition-colors"
                    >
                      Escalate
                    </button>

                    {selectedConv.status !== 'RESOLVED' && (
                      <button
                        onClick={() => setResolveModalOpen(true)}
                        className="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 text-white hover:bg-emerald-700 transition-colors"
                      >
                        Resolve
                      </button>
                    )}
                  </div>
                </div>

                {/* Subnav Tabs */}
                <div className="flex gap-4 mt-3 pt-3 border-t border-slate-200/60 text-xs font-semibold">
                  <button
                    onClick={() => setActiveTab('messages')}
                    className={`pb-1 border-b-2 flex items-center gap-1.5 transition-colors ${
                      activeTab === 'messages' ? 'border-cyan-600 text-cyan-700' : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <MessageSquare size={14} />
                    Messages ({messages.length})
                  </button>
                  <button
                    onClick={() => setActiveTab('ai_insights')}
                    className={`pb-1 border-b-2 flex items-center gap-1.5 transition-colors ${
                      activeTab === 'ai_insights' ? 'border-cyan-600 text-cyan-700' : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <Sparkles size={14} />
                    AI Triage Insights ({selectedConv.ai_analyses?.length || 0})
                  </button>
                  <button
                    onClick={() => setActiveTab('timeline')}
                    className={`pb-1 border-b-2 flex items-center gap-1.5 transition-colors ${
                      activeTab === 'timeline' ? 'border-cyan-600 text-cyan-700' : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <History size={14} />
                    Clinical Audit Timeline
                  </button>
                </div>
              </div>

              {/* Tab 1: Messages Transcript */}
              {activeTab === 'messages' && (
                <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/30">
                  {messages.length === 0 ? (
                    <div className="text-center py-12 text-slate-400 text-xs">
                      No consultation messages recorded yet.
                    </div>
                  ) : (
                    messages.map((m) => {
                      const isPatient = m.sender_type === 'patient';
                      const isDoctor = m.sender_type === 'doctor';
                      const isAssistant = m.sender_type === 'assistant';

                      return (
                        <div
                          key={m.id}
                          className={`flex flex-col ${isDoctor ? 'items-end' : 'items-start'}`}
                        >
                          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-500 mb-1 px-1">
                            {isPatient && <User size={12} className="text-cyan-600" />}
                            {isDoctor && <Stethoscope size={12} className="text-blue-600" />}
                            {isAssistant && <Sparkles size={12} className="text-purple-600" />}
                            <span>{m.sender_name}</span>
                            <span className="text-[10px] font-normal text-slate-400">
                              {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                          </div>

                          <div
                            className={`max-w-[85%] rounded-2xl p-3.5 text-xs shadow-xs leading-relaxed whitespace-pre-wrap ${
                              isPatient
                                ? 'bg-white text-slate-800 border border-slate-200 rounded-tl-xs'
                                : isDoctor
                                ? 'bg-blue-600 text-white font-medium rounded-tr-xs shadow-blue-500/10'
                                : 'bg-gradient-to-br from-purple-50 to-indigo-50 border border-purple-200/70 text-slate-800 rounded-tl-xs'
                            }`}
                          >
                            {m.body}
                          </div>
                        </div>
                      );
                    })
                  )}
                  <div ref={messagesEndRef} />
                </div>
              )}

              {/* Tab 2: AI Triage Insights */}
              {activeTab === 'ai_insights' && (
                <div className="flex-1 overflow-y-auto p-5 space-y-4 bg-slate-50/50">
                  <div className="bg-purple-50 border border-purple-200 rounded-xl p-4 text-xs">
                    <div className="flex items-center gap-2 font-bold text-purple-900 mb-1">
                      <Sparkles size={16} />
                      Clinical Triage & Decision Support Classifier
                    </div>
                    <p className="text-purple-700">
                      These structured evidence codes are computed by deterministic rules and isolated NLP classifiers.
                      They serve as triage indicators and do NOT replace physician diagnostic assessment.
                    </p>
                  </div>

                  {(!selectedConv.ai_analyses || selectedConv.ai_analyses.length === 0) ? (
                    <div className="text-center py-8 text-slate-400 text-xs">No analysis records available.</div>
                  ) : (
                    selectedConv.ai_analyses.map((ai) => (
                      <div key={ai.id} className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs space-y-2 text-xs">
                        <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                          <span className="font-bold text-slate-900 text-sm">{ai.category || 'General Assessment'}</span>
                          <span className="text-[10px] text-slate-400">
                            {new Date(ai.created_at).toLocaleString()}
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-slate-600">
                          <div><span className="font-semibold text-slate-700">Confidence:</span> {ai.confidence ? `${(ai.confidence * 100).toFixed(0)}%` : 'N/A'}</div>
                          <div><span className="font-semibold text-slate-700">Rule Engine Version:</span> {ai.model_rule_version}</div>
                          <div><span className="font-semibold text-slate-700">Review Required:</span> {ai.human_review_required ? 'Yes' : 'No'}</div>
                        </div>

                        {ai.evidence_codes && (
                          <div className="pt-2">
                            <span className="font-semibold text-slate-700 block mb-1">Triggered Evidence Codes:</span>
                            <div className="flex flex-wrap gap-1">
                              {ai.evidence_codes.map((code, i) => (
                                <span key={i} className="px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700 text-[10px] font-mono">
                                  {code}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* Tab 3: Timeline & Audit Trail */}
              {activeTab === 'timeline' && (
                <div className="flex-1 overflow-y-auto p-5 space-y-3 bg-slate-50/50">
                  <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-2">
                    Append-Only Clinical Workflow Timeline
                  </h3>
                  {timelineEvents.length === 0 ? (
                    <div className="text-center py-8 text-slate-400 text-xs">Loading clinical events...</div>
                  ) : (
                    <div className="space-y-3">
                      {timelineEvents.map((ev) => (
                        <div key={ev.id} className="bg-white border border-slate-200 rounded-xl p-3 shadow-xs text-xs flex items-start gap-3">
                          <div className="w-7 h-7 rounded-full bg-cyan-100 text-cyan-800 flex items-center justify-center shrink-0 mt-0.5 font-bold">
                            <Clock size={14} />
                          </div>
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <span className="font-bold text-slate-900">{ev.event_type.replace(/_/g, ' ')}</span>
                              <span className="text-[10px] text-slate-400">{new Date(ev.created_at).toLocaleString()}</span>
                            </div>
                            <div className="text-slate-600 mt-0.5">
                              Actor: <span className="font-semibold">{ev.actor_name}</span>
                            </div>
                            {ev.reason && (
                              <div className="text-slate-500 italic mt-0.5">
                                Reason: "{ev.reason}"
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Reply Composer & Quick Templates */}
              {selectedConv.status !== 'RESOLVED' && (
                <div className="p-3.5 border-t border-slate-200 bg-white space-y-2">
                  {/* Quick template pill shortcuts */}
                  <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-[11px]">
                    <span className="text-slate-400 shrink-0 font-medium">Quick Phrases:</span>
                    {QUICK_CLINICAL_TEMPLATES.map((tmpl, idx) => (
                      <button
                        key={idx}
                        onClick={() => setReplyText(tmpl)}
                        className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-700 whitespace-nowrap transition-colors"
                      >
                        {tmpl.substring(0, 32)}...
                      </button>
                    ))}
                  </div>

                  <form onSubmit={handleSendReply} className="flex gap-2 items-end">
                    <textarea
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                          handleSendReply();
                        }
                      }}
                      placeholder="Type your clinical response to patient... (Ctrl+Enter to send)"
                      rows={2}
                      className="flex-1 p-2.5 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:outline-hidden focus:bg-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none"
                    />
                    <button
                      type="submit"
                      disabled={sendingReply || !replyText.trim()}
                      className="px-4 py-2.5 rounded-xl bg-blue-600 text-white font-semibold text-xs hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-blue-500/20 flex items-center gap-1.5 transition-all"
                    >
                      <Send size={14} />
                      {sendingReply ? 'Sending...' : 'Send Reply'}
                    </button>
                  </form>
                </div>
              )}
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-400">
              <MessageSquare size={36} className="text-slate-300 mb-3" />
              <h3 className="text-sm font-semibold text-slate-700">No Consultation Selected</h3>
              <p className="text-xs text-slate-400 max-w-sm mt-1">
                Select an active patient case from the left triage inbox to view history, review AI classifications, and communicate.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── MODAL: Assign / Transfer ── */}
      <AnimatePresence>
        {assignModalOpen && (
          <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-md w-full p-6 text-xs text-slate-800"
            >
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <h3 className="text-sm font-bold text-slate-900">Assign or Transfer Consultation</h3>
                <button onClick={() => setAssignModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                  <X size={18} />
                </button>
              </div>

              <form onSubmit={handleAssignSubmit} className="space-y-4 pt-4">
                <div>
                  <label className="font-semibold block mb-1">Target Department:</label>
                  <select
                    value={targetDeptId}
                    onChange={(e) => setTargetDeptId(e.target.value)}
                    className="w-full p-2 border border-slate-200 rounded-lg text-xs"
                  >
                    <option value="">-- Keep Current Department --</option>
                    {departments.map(d => (
                      <option key={d.id} value={d.id}>{d.name} ({d.code})</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="font-semibold block mb-1">Target Clinician:</label>
                  <select
                    value={targetDoctorId}
                    onChange={(e) => setTargetDoctorId(e.target.value)}
                    required
                    className="w-full p-2 border border-slate-200 rounded-lg text-xs"
                  >
                    <option value="">-- Select an active clinician --</option>
                    {doctorsList.map(doc => (
                      <option key={doc.id} value={doc.id}>
                        {doc.full_name || `Dr. #${doc.id}`} ({doc.specialization})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="font-semibold block mb-1">Reason for Reassignment:</label>
                  <textarea
                    rows={2}
                    value={assignReason}
                    onChange={(e) => setAssignReason(e.target.value)}
                    placeholder="e.g. Specialty consultation needed, transferring to Cardiology team."
                    className="w-full p-2 border border-slate-200 rounded-lg text-xs resize-none"
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setAssignModalOpen(false)}
                    className="px-4 py-2 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold"
                  >
                    {actionLoading ? 'Updating...' : 'Confirm Assignment'}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ── MODAL: Escalate Urgency ── */}
      <AnimatePresence>
        {escalateModalOpen && (
          <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-md w-full p-6 text-xs text-slate-800"
            >
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <h3 className="text-sm font-bold text-slate-900">Escalate Consultation Urgency</h3>
                <button onClick={() => setEscalateModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                  <X size={18} />
                </button>
              </div>

              <form onSubmit={handleEscalateSubmit} className="space-y-4 pt-4">
                <div>
                  <label className="font-semibold block mb-1">Target Urgency Tier:</label>
                  <select
                    value={targetUrgency}
                    onChange={(e) => setTargetUrgency(e.target.value)}
                    className="w-full p-2 border border-slate-200 rounded-lg text-xs font-semibold"
                  >
                    <option value="HIGH_PRIORITY">HIGH PRIORITY (Clinical Attention Required)</option>
                    <option value="EMERGENCY_REVIEW">EMERGENCY REVIEW (Acute Life-Safety Protocol)</option>
                  </select>
                </div>

                <div>
                  <label className="font-semibold block mb-1">Clinical Escalation Reason:</label>
                  <textarea
                    rows={2}
                    required
                    value={escalateReason}
                    onChange={(e) => setEscalateReason(e.target.value)}
                    placeholder="Describe clinical rationale for escalating priority tier..."
                    className="w-full p-2 border border-slate-200 rounded-lg text-xs resize-none"
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setEscalateModalOpen(false)}
                    className="px-4 py-2 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-lg font-semibold"
                  >
                    {actionLoading ? 'Escalating...' : 'Trigger Escalation Alert'}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ── MODAL: Resolve Consultation ── */}
      <AnimatePresence>
        {resolveModalOpen && (
          <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-md w-full p-6 text-xs text-slate-800"
            >
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <h3 className="text-sm font-bold text-slate-900">Mark Consultation as Resolved</h3>
                <button onClick={() => setResolveModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                  <X size={18} />
                </button>
              </div>

              <form onSubmit={handleResolveSubmit} className="space-y-4 pt-4">
                <p className="text-slate-600 text-xs">
                  Resolving this consultation closes any active escalation alerts and logs a clinical conclusion event in the patient's record.
                </p>

                <div>
                  <label className="font-semibold block mb-1">Resolution Summary & Clinical Notes:</label>
                  <textarea
                    rows={3}
                    value={resolutionNotes}
                    onChange={(e) => setResolutionNotes(e.target.value)}
                    placeholder="e.g. Clinical assessment completed. Patient advised on treatment plan and medication. Case closed."
                    className="w-full p-2 border border-slate-200 rounded-lg text-xs resize-none"
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setResolveModalOpen(false)}
                    className="px-4 py-2 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-semibold"
                  >
                    {actionLoading ? 'Closing...' : 'Close & Mark Resolved'}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

    </div>
  );
}
