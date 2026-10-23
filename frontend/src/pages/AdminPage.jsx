import React, { useEffect, useState, useMemo } from "react";
import { Routes, Route, NavLink, Navigate, useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Activity, Users, AlertTriangle, Settings, RefreshCw, Search, 
  ChevronRight, X, FileText, CheckCircle, Clock, Heart, 
  Droplets, Zap, ShieldCheck, Database, Layout, 
  TrendingUp, TrendingDown, Bell, LogOut, Terminal, Cpu, Cloud, Download,
  Filter, MoreVertical, Server, HardDrive, Shield, BellRing, Calendar
} from "lucide-react";
import { 
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, AreaChart, Area, LineChart, Line
} from "recharts";
import { useAuth } from "../context/AuthContext";
import api from "../services/api";
import { useNotification } from "../context/NotificationContext";
import VERSION_CONFIG from "../config/versionConfig";
import PatientRegistry from "./PatientRegistry";
import EncounterQueue from "./admin/EncounterQueue";
import EncounterDetail from "./admin/EncounterDetail";
import "./admin.css";

// --- Mock Data Generator ---
const MOCK_ALERTS = [
  { id: "ALT-001", patient: "John Doe", condition: "Severe Hypertension", severity: "Critical", time: "2m ago" },
  { id: "ALT-002", patient: "Jane Smith", condition: "Cardiac Arrhythmia", severity: "High", time: "15m ago" },
  { id: "ALT-003", patient: "Robert Brown", condition: "Metabolic Shift", severity: "Medium", time: "1h ago" },
  { id: "ALT-004", patient: "Sarah Wilson", condition: "Hematology Drop", severity: "High", time: "3h ago" }
];

const MOCK_LOGS = [
  { user: "Admin (Dr. Aris)", action: `Neural Model Re-train (${VERSION_CONFIG.version})`, time: "10:15 AM", status: "Completed" },
  { user: "System", action: "Automated Backup Protocol", time: "09:00 AM", status: "Success" },
  { user: "Admin (Dr. Aris)", action: "Exported Q3 Risk Report", time: "08:45 AM", status: "Success" },
  { user: "Dr. Miller", action: "Accessed Patient Data #8291", time: "07:30 AM", status: "Authorized" }
];

const MOCK_MODELS = [
  { name: "Diabetes Vector", accuracy: 98.4, status: "Active", lastTrained: "2026-04-15", color: "#0F9D8A" },
  { name: "Cardiac Neural", accuracy: 97.2, status: "Active", lastTrained: "2026-04-18", color: "#EF4444" },
  { name: "Hematology Core", accuracy: 99.1, status: "Active", lastTrained: "2026-04-10", color: "#6366F1" },
  { name: "Vascular Insight", accuracy: 96.5, status: "Idle", lastTrained: "2026-03-22", color: "#F59E0B" }
];

// --- Sub-Components ---

const AdminSidebar = () => {
  const { user, logout } = useAuth();
  const canManagePatients = ["admin", "hospital_admin"].includes((user?.role || "").toLowerCase());
  
  const menuSections = [
    {
      label: "Core",
      items: [
        { name: "Overview", icon: <Layout size={18} />, path: "/admin" },
        { name: "Patient Directory", icon: <Users size={18} />, path: "/admin/patients" },
        ...(canManagePatients ? [{ name: "Patient Registry", icon: <Users size={18} />, path: "/admin/registry" }] : []),
        ...(canManagePatients ? [{ name: "Encounter Queue", icon: <Calendar size={18} />, path: "/admin/encounters" }] : []),
      ]
    },
    {
      label: "AI System",
      items: [
        { name: "Model Monitoring", icon: <Cpu size={18} />, path: "/admin/models" },
        { name: "Risk Alerts", icon: <BellRing size={18} />, path: "/admin/alerts", badge: 4 },
        { name: "Data Pipeline", icon: <Database size={18} />, path: "/admin/pipeline" },
      ]
    },
    {
      label: "Admin Control",
      items: [
        { name: "Audit Logs", icon: <Terminal size={18} />, path: "/admin/logs" },
        { name: "Settings", icon: <Settings size={18} />, path: "/admin/settings" },
      ]
    }
  ];

  return (
    <aside className="admin-sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">
            <ShieldCheck size={20} />
          </div>
          <span className="sidebar-logo-text">Health Admin</span>
        </div>
      </div>
      
      <nav className="sidebar-nav custom-scrollbar">
        {menuSections.map((section, idx) => (
          <div key={idx} className="sidebar-section">
            <h4 className="sidebar-section-label">{section.label}</h4>
            {section.items.map((item, i) => (
              <NavLink 
                key={i} 
                to={item.path} 
                end={item.path === "/admin"}
                className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              >
                {item.icon}
                <span className="flex-1">{item.name}</span>
                {item.badge && (
                  <span className="px-1.5 py-0.5 bg-rose-500 text-white text-[10px] font-black rounded-full">
                    {item.badge}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="admin-user-profile">
          <div className="admin-avatar">
            {user?.full_name?.charAt(0) || "A"}
          </div>
          <div className="admin-user-info flex-1 overflow-hidden">
            <p className="truncate font-bold text-slate-800">{user?.full_name || "Administrator"}</p>
            <span className="truncate text-slate-400 text-[11px]">{user?.email || "admin@health.ai"}</span>
          </div>
          <button onClick={logout} className="p-1.5 hover:text-rose-500 transition-colors">
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </aside>
  );
};

const AdminOverview = ({ patients, metrics, loading, fetchData }) => {
  const riskCounts = useMemo(() => {
    let high = 0, moderate = 0, low = 0;
    (patients || []).forEach(p => {
      const r = (p.latest_risk_level || 'Low').toLowerCase();
      if (r.includes('high')) high++;
      else if (r.includes('mod') || r.includes('medium')) moderate++;
      else low++;
    });
    const total = (patients || []).length || 1;
    return {
      high, moderate, low, total,
      highPct: Math.round((high / total) * 100),
      modPct: Math.round((moderate / total) * 100),
      lowPct: Math.round((low / total) * 100)
    };
  }, [patients]);

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      <div className="kpi-grid">
        {metrics.map((m, i) => (
          <div key={i} className="admin-card kpi-card">
            <div className="flex justify-between items-start">
              <div className="kpi-icon-wrap" style={{ backgroundColor: `${m.color}15`, color: m.color }}>
                {m.icon}
              </div>
              <div className={`kpi-trend ${m.up ? 'trend-up' : 'trend-down'}`} style={{ color: m.up ? 'var(--admin-success)' : 'var(--admin-danger)' }}>
                {m.up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                {m.trend}
              </div>
            </div>
            <p className="kpi-label">{m.title}</p>
            <h2 className="kpi-value">{m.value}</h2>
            <div className="h-10 mt-2 w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%" debounce={50}>
                <AreaChart data={[{v: 10}, {v: 15}, {v: 12}, {v: 18}, {v: 16}, {v: 20}]}>
                  <Area type="monotone" dataKey="v" stroke={m.color} fill={m.color} fillOpacity={0.1} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 xl:col-span-8">
          <div className="admin-card">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-lg font-black">Clinical Telemetry Snapshot</h3>
              <div className="flex gap-2">
                <button onClick={fetchData} className="p-2 hover:bg-slate-50 rounded-lg transition-colors">
                  <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
                </button>
              </div>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Patient</th>
                    <th>Age</th>
                    <th>Risk Level</th>
                    <th>Last Scan</th>
                    <th>Status</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {patients.slice(0, 5).map((p, i) => (
                    <tr key={i}>
                      <td>
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 bg-slate-100 rounded-lg flex items-center justify-center font-bold text-xs text-slate-500">
                            {p.full_name?.charAt(0)}
                          </div>
                          <div>
                            <p className="m-0 text-sm font-bold">{p.full_name}</p>
                            <p className="m-0 text-[10px] text-slate-400">{p.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="text-sm font-bold text-slate-600">
                        {p.age || "—"}
                      </td>
                      <td>
                        <span className={`admin-badge ${p.latest_risk_level === 'High' ? 'badge-risk-high' : p.latest_risk_level === 'Moderate' ? 'badge-risk-mid' : 'badge-risk-low'}`}>
                          {p.latest_risk_level || 'Low'}
                        </span>
                      </td>
                      <td className="text-xs font-bold text-slate-500">
                        {p.history?.[0] ? new Date(p.history[0].created_at).toLocaleDateString() : 'Never'}
                      </td>
                      <td>
                        <div className="flex items-center gap-2 text-[11px] font-bold text-emerald-500">
                          <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" /> Live
                        </div>
                      </td>
                      <td className="text-right">
                        <button className="text-slate-400 hover:text-teal-500 transition-colors">
                          <ChevronRight size={18} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="col-span-12 xl:col-span-4">
          <div className="admin-card h-full">
            <h3 className="text-lg font-black mb-6">Risk Distribution</h3>
            <div className="h-[250px] w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%" debounce={50}>
                <PieChart>
                  <Pie
                    data={[
                      { name: 'High', value: riskCounts.high, color: '#EF4444' },
                      { name: 'Medium', value: riskCounts.moderate, color: '#F59E0B' },
                      { name: 'Low', value: riskCounts.low, color: '#10B981' }
                    ]}
                    cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value"
                  >
                    {[0,1,2].map((i) => <Cell key={i} fill={['#EF4444', '#F59E0B', '#10B981'][i]} />)}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="space-y-3 mt-4">
              <div className="flex justify-between items-center text-sm">
                <span className="flex items-center gap-2"><div className="w-2 h-2 bg-emerald-500 rounded-full" /> Low Risk</span>
                <span className="font-bold">{riskCounts.lowPct}% ({riskCounts.low})</span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span className="flex items-center gap-2"><div className="w-2 h-2 bg-amber-500 rounded-full" /> Moderate Risk</span>
                <span className="font-bold">{riskCounts.modPct}% ({riskCounts.moderate})</span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span className="flex items-center gap-2"><div className="w-2 h-2 bg-rose-500 rounded-full" /> High Risk</span>
                <span className="font-bold">{riskCounts.highPct}% ({riskCounts.high})</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

const PatientDirectory = ({ patients }) => {
  const [filter, setFilter] = useState("All");
  const [search, setSearch] = useState("");

  const filtered = patients.filter(p => {
    const matchesSearch = p.full_name?.toLowerCase().includes(search.toLowerCase()) || p.email?.toLowerCase().includes(search.toLowerCase());
    const matchesFilter = filter === "All" || p.latest_risk_level === filter;
    return matchesSearch && matchesFilter;
  });

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="admin-card">
        <div className="flex flex-col md:flex-row justify-between items-center gap-4 mb-6">
          <div className="relative w-full md:w-96">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input 
              type="text" 
              placeholder="Search by name or email..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 rounded-xl py-2.5 pl-10 pr-4 text-sm focus:outline-none focus:border-teal-500 transition-all"
            />
          </div>
          <div className="flex items-center gap-3 w-full md:w-auto">
            <Filter size={18} className="text-slate-400" />
            <select 
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="bg-white border border-slate-200 rounded-xl px-4 py-2 text-sm font-bold text-slate-700 outline-none focus:border-teal-500"
            >
              <option value="All">All Risk Levels</option>
              <option value="High">High Risk Only</option>
              <option value="Moderate">Moderate Risk</option>
              <option value="Low">Low Risk</option>
            </select>
          </div>
        </div>

        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Patient Profile</th>
                <th>Age</th>
                <th>Condition Context</th>
                <th>Risk Stratification</th>
                <th>Diagnostic History</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p, i) => (
                <tr key={i}>
                  <td>
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-slate-100 rounded-xl flex items-center justify-center font-bold text-slate-500">
                        {p.full_name?.charAt(0)}
                      </div>
                      <div>
                        <p className="m-0 text-sm font-bold text-slate-800">{p.full_name}</p>
                        <p className="m-0 text-[11px] text-slate-400">{p.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="text-sm font-bold text-slate-600">{p.age || "—"}</td>
                  <td>
                    <div className="flex gap-1 flex-wrap">
                      {p.has_diabetes && <span className="px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-[9px] font-black uppercase">Diabetes</span>}
                      {p.has_heart && <span className="px-2 py-0.5 bg-rose-50 text-rose-600 rounded text-[9px] font-black uppercase">Cardiac</span>}
                      {p.has_hypertension && <span className="px-2 py-0.5 bg-amber-50 text-amber-600 rounded text-[9px] font-black uppercase">Hypertension</span>}
                    </div>
                  </td>
                  <td>
                    <span className={`admin-badge ${p.latest_risk_level === 'High' ? 'badge-risk-high' : p.latest_risk_level === 'Moderate' ? 'badge-risk-mid' : 'badge-risk-low'}`}>
                      {p.latest_risk_level || 'Low'} Risk
                    </span>
                  </td>
                  <td className="text-xs font-bold text-slate-500">
                    {p.total_assessments} Total Screenings
                  </td>
                  <td className="text-right">
                    <button className="p-2 hover:bg-slate-100 rounded-lg text-slate-400 transition-colors">
                      <MoreVertical size={18} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="py-20 text-center text-slate-400">
              <Search size={48} className="mx-auto opacity-20 mb-4" />
              <p className="font-bold">No patient vectors found matching your criteria</p>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
};

const ModelMonitoring = () => {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/admin/models")
      .then(res => setModels(res.data.models || []))
      .catch(err => console.error("Failed to fetch models", err))
      .finally(() => setLoading(false));
  }, []);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {models.map((model, i) => (
          <div key={i} className="admin-card">
            <div className="flex justify-between items-start mb-6">
              <div>
                <h3 className="text-lg font-black text-slate-800">{model.name}</h3>
                <p className="text-xs text-slate-400 font-bold uppercase tracking-widest mt-1">Algorithm: {model.algorithm}</p>
              </div>
              <span className={`px-3 py-1 rounded-full text-[10px] font-black uppercase ${model.status === 'Active' ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' : 'bg-slate-50 text-slate-400 border border-slate-100'}`}>
                {model.status}
              </span>
            </div>
            
            <div className="space-y-6">
              <div>
                <div className="flex justify-between items-end mb-2">
                  <span className="text-xs font-black text-slate-400 uppercase">Inference Accuracy</span>
                  <span className="text-xl font-black text-slate-800">{model.accuracy}%</span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <motion.div 
                    initial={{ width: 0 }} 
                    animate={{ width: `${model.accuracy}%` }} 
                    className="h-full rounded-full" 
                    style={{ backgroundColor: model.color || '#0F9D8A' }}
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                  <span className="block text-[9px] font-black text-slate-400 uppercase mb-1">Precision</span>
                  <span className="text-xs font-bold text-slate-700">{model.precision}%</span>
                </div>
                <div className="p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                  <span className="block text-[9px] font-black text-slate-400 uppercase mb-1">Recall</span>
                  <span className="text-xs font-bold text-slate-700">{model.recall}%</span>
                </div>
                <div className="p-2.5 bg-slate-50 rounded-xl border border-slate-100">
                  <span className="block text-[9px] font-black text-slate-400 uppercase mb-1">AUC-ROC</span>
                  <span className="text-xs font-bold text-slate-700">{model.auc_roc}%</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="admin-card">
        <h3 className="text-lg font-black mb-6">Model Latency Tracking (ms)</h3>
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={[{t: '08:00', l: 42}, {t: '09:00', l: 38}, {t: '10:00', l: 45}, {t: '11:00', l: 40}, {t: '12:00', l: 41}, {t: '13:00', l: 36}]}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
              <XAxis dataKey="t" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94A3B8' }} />
              <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94A3B8' }} />
              <Tooltip />
              <Line type="monotone" dataKey="l" stroke="#0F9D8A" strokeWidth={3} dot={{ r: 4, fill: '#0F9D8A' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </motion.div>
  );
};

const RiskAlertsCenter = ({ patients = [] }) => {
  const alerts = useMemo(() => {
    const list = [];
    patients.forEach(p => {
      if (p.has_heart) list.push({ id: `ALT-${p.id}-H`, patient: p.full_name, condition: "High Risk Cardiac Vector", severity: "Critical", time: "Recent" });
      if (p.has_hypertension) list.push({ id: `ALT-${p.id}-HT`, patient: p.full_name, condition: "Hypertension Vector Elevation", severity: "High", time: "Recent" });
      if (p.has_diabetes) list.push({ id: `ALT-${p.id}-D`, patient: p.full_name, condition: "Elevated Glycemic Risk", severity: "Medium", time: "Recent" });
    });
    return list;
  }, [patients]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="admin-card">
        <div className="flex justify-between items-center mb-8">
          <h3 className="text-lg font-black">Active Clinical Alerts</h3>
          <span className="px-4 py-1.5 bg-rose-50 text-rose-600 rounded-full text-xs font-black uppercase tracking-widest">{alerts.length} Critical Pending</span>
        </div>
        
        <div className="space-y-4">
          {alerts.map((alert, i) => (
            <div key={i} className={`p-5 rounded-2xl border flex items-center gap-6 transition-all hover:translate-x-1 ${alert.severity === 'Critical' ? 'bg-rose-50/50 border-rose-100' : alert.severity === 'High' ? 'bg-amber-50/50 border-amber-100' : 'bg-slate-50 border-slate-100'}`}>
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${alert.severity === 'Critical' ? 'bg-rose-100 text-rose-600' : alert.severity === 'High' ? 'bg-amber-100 text-amber-600' : 'bg-slate-200 text-slate-500'}`}>
                <AlertTriangle size={24} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-1">
                  <h4 className="text-sm font-black text-slate-800">{alert.patient}</h4>
                  <span className={`px-2 py-0.5 rounded text-[9px] font-black uppercase ${alert.severity === 'Critical' ? 'bg-rose-600 text-white' : alert.severity === 'High' ? 'bg-amber-500 text-white' : 'bg-slate-400 text-white'}`}>
                    {alert.severity}
                  </span>
                </div>
                <p className="text-xs font-bold text-slate-500">{alert.condition} detected via AI Vector Analysis</p>
              </div>
              <div className="text-right">
                <p className="text-[10px] font-black text-slate-400 uppercase mb-2">{alert.time}</p>
                <button className={`px-4 py-1.5 rounded-lg text-[11px] font-black uppercase transition-all ${alert.severity === 'Critical' ? 'bg-rose-600 text-white hover:bg-rose-700' : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
                  Initiate Triage
                </button>
              </div>
            </div>
          ))}
          {alerts.length === 0 && (
            <div className="py-12 text-center text-slate-400 font-bold">
              <CheckCircle size={36} className="mx-auto text-emerald-400 mb-2" />
              <p>No high-risk patient alerts pending triage.</p>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
};

const DataPipeline = () => {
  const steps = [
    { name: "Clinical Intake", icon: <FileText size={20} />, status: "Active", throughput: "142 req/min" },
    { name: "Vectorization", icon: <Database size={20} />, status: "Active", throughput: "0.4ms lat" },
    { name: "Neural Inference", icon: <Cpu size={20} />, status: "Active", throughput: "98.4% conf" },
    { name: "Record Registry", icon: <Shield size={20} />, status: "Syncing", throughput: "Azure Cloud" }
  ];

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
      <div className="admin-card">
        <h3 className="text-lg font-black mb-10 text-center">System Data Architecture</h3>
        <div className="flex flex-col md:flex-row items-center justify-between gap-8 relative">
          <div className="absolute top-1/2 left-0 w-full h-0.5 bg-slate-100 -translate-y-1/2 hidden md:block" />
          {steps.map((step, i) => (
            <div key={i} className="relative z-10 flex flex-col items-center group">
              <div className={`w-16 h-16 rounded-2xl flex items-center justify-center mb-4 transition-all shadow-lg ${step.status === 'Active' ? 'bg-teal-500 text-white' : 'bg-indigo-500 text-white animate-pulse'}`}>
                {step.icon}
              </div>
              <h4 className="text-sm font-black text-slate-800 mb-1">{step.name}</h4>
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{step.throughput}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="admin-card">
          <h3 className="text-[13px] font-black uppercase tracking-widest text-slate-400 mb-6">System Load</h3>
          <div className="h-[200px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={[{v: 30}, {v: 45}, {v: 40}, {v: 70}, {v: 65}, {v: 85}]}>
                <Area type="monotone" dataKey="v" stroke="#6366F1" fill="#6366F1" fillOpacity={0.1} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="admin-card">
          <h3 className="text-[13px] font-black uppercase tracking-widest text-slate-400 mb-6">Storage Integrity</h3>
          <div className="space-y-4">
            <div className="flex justify-between items-center p-4 bg-slate-50 rounded-xl border border-slate-100">
              <div className="flex items-center gap-3">
                <Server size={18} className="text-slate-400" />
                <span className="text-sm font-bold">Clinical Records</span>
              </div>
              <span className="text-xs font-black text-teal-500">1.2 TB / 2.0 TB</span>
            </div>
            <div className="flex justify-between items-center p-4 bg-slate-50 rounded-xl border border-slate-100">
              <div className="flex items-center gap-3">
                <HardDrive size={18} className="text-slate-400" />
                <span className="text-sm font-bold">AI Model Weights</span>
              </div>
              <span className="text-xs font-black text-teal-500">450 GB / 1.0 TB</span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

const AuditLogs = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/admin/logs")
      .then(res => setLogs(res.data.logs || []))
      .catch(err => console.error("Failed to fetch logs", err))
      .finally(() => setLoading(false));
  }, []);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="admin-card">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-lg font-black">System Audit Trail</h3>
          <button className="flex items-center gap-2 px-4 py-2 bg-slate-50 hover:bg-slate-100 rounded-xl text-xs font-black uppercase transition-all">
            <Download size={14} /> Export Logs
          </button>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Operator</th>
                <th>Action Description</th>
                <th>Timestamp</th>
                <th>Integrity Status</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log, i) => (
                <tr key={i}>
                  <td>
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 bg-slate-800 rounded flex items-center justify-center text-[10px] font-black text-white">
                        {(log.user || 'A').charAt(0)}
                      </div>
                      <span className="text-sm font-bold text-slate-700">{log.user}</span>
                    </div>
                  </td>
                  <td className="text-sm font-bold text-slate-600">{log.action}</td>
                  <td className="text-xs font-bold text-slate-400">{log.time}</td>
                  <td>
                    <span className="text-[10px] font-black text-emerald-500 uppercase tracking-widest flex items-center gap-1.5">
                      <CheckCircle size={12} /> {log.status}
                    </span>
                  </td>
                </tr>
              ))}
              {logs.length === 0 && !loading && (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-slate-400 font-bold">No audit logs recorded yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </motion.div>
  );
};

const GlobalSettings = () => {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-3xl">
      <div className="admin-card">
        <h3 className="text-lg font-black mb-8">System Configuration</h3>
        <div className="space-y-8">
          <div className="flex items-center justify-between pb-6 border-b border-slate-100">
            <div>
              <h4 className="text-sm font-black text-slate-800">Critical AI Alerting</h4>
              <p className="text-xs text-slate-400 font-bold mt-1">Automatically notify medical supervisors on High-Risk detection</p>
            </div>
            <div className="w-12 h-6 bg-teal-500 rounded-full relative cursor-pointer">
              <div className="absolute right-1 top-1 w-4 h-4 bg-white rounded-full shadow-sm" />
            </div>
          </div>
          <div className="flex items-center justify-between pb-6 border-b border-slate-100">
            <div>
              <h4 className="text-sm font-black text-slate-800">Real-time Data Refresh</h4>
              <p className="text-xs text-slate-400 font-bold mt-1">Sync dashboard with inference engine every 60 seconds</p>
            </div>
            <div className="w-12 h-6 bg-slate-200 rounded-full relative cursor-pointer">
              <div className="absolute left-1 top-1 w-4 h-4 bg-white rounded-full shadow-sm" />
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <h4 className="text-sm font-black text-slate-800">Maintenance Mode</h4>
              <p className="text-xs text-slate-400 font-bold mt-1">Restrict diagnostic ingestion during system updates</p>
            </div>
            <div className="w-12 h-6 bg-slate-200 rounded-full relative cursor-pointer">
              <div className="absolute left-1 top-1 w-4 h-4 bg-white rounded-full shadow-sm" />
            </div>
          </div>
        </div>
        
        <div className="mt-12">
          <button className="bg-teal-500 hover:bg-teal-600 text-white font-black uppercase tracking-widest py-3 px-8 rounded-xl transition-all shadow-lg shadow-teal-500/20">
            Commit System Changes
          </button>
        </div>
      </div>
    </motion.div>
  );
};

// --- Main Layout Component ---

const AdminPage = () => {
  const [patients, setPatients] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const { showNotification } = useNotification();
  const { user } = useAuth();
  const canManagePatients = ["admin", "hospital_admin"].includes((user?.role || "").toLowerCase());
  const location = useLocation();

  const fetchData = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const response = await api.get("/reports/admin");
      if (!Array.isArray(response.data?.patients)) {
        throw new Error("The patient directory returned an invalid response.");
      }
      setPatients(response.data.patients);
      showNotification("Clinical Data Synchronized", "success");
    } catch (err) {
      setLoadError(err.message || "Unable to load the patient directory.");
      showNotification("Sync Failed", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const metrics = useMemo(() => {
    const highRisk = patients.filter(p => p.latest_risk_level === "High").length;
    const totalReports = patients.reduce((sum, p) => sum + (p.total_assessments || 0), 0);
    return [
      { title: "Patients", value: patients.length, trend: "+12%", up: true, icon: <Users size={18} />, color: "#0F9D8A" },
      { title: "High Risk", value: highRisk, trend: "-2%", up: false, icon: <AlertTriangle size={18} />, color: "#EF4444" },
      { title: "AI Reports", value: totalReports, trend: "+24%", up: true, icon: <FileText size={18} />, color: "#F59E0B" },
      { title: "Stability", value: "99.8%", trend: "Nominal", up: true, icon: <ShieldCheck size={18} />, color: "#10B981" }
    ];
  }, [patients]);

  const pageTitle = useMemo(() => {
    const path = location.pathname;
    if (path === "/admin") return "System Overview";
    if (path.includes("registry")) return "Patient Registry";
    if (path.includes("encounters")) return "Encounter Queue";
    if (path.includes("patients")) return "Patient Intelligence Directory";
    if (path.includes("models")) return "AI Model Monitoring";
    if (path.includes("alerts")) return "Risk Alerts Center";
    if (path.includes("pipeline")) return "Data Pipeline Architecture";
    if (path.includes("logs")) return "System Audit Logs";
    if (path.includes("settings")) return "Global Settings";
    return "Admin Control Center";
  }, [location]);

  return (
    <div className="admin-layout">
      <AdminSidebar />
      
      <main className="admin-main">
        <header className="command-bar">
          <div className="command-title">
            <h1>{pageTitle}</h1>
            <p>Clinical Intelligence Command Center v2.4</p>
          </div>
          
          <div className="flex items-center gap-6">
            <div className="hidden md:flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-100 rounded-full">
              <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
              <span className="text-[11px] font-black text-slate-500 uppercase tracking-widest">Live Engine</span>
            </div>
            
            <div className="relative cursor-pointer text-slate-400 hover:text-teal-600 transition-colors">
              <Bell size={20} />
              <span className="absolute -top-1 -right-1 w-4 h-4 bg-rose-500 text-white text-[9px] font-black flex items-center justify-center rounded-full border-2 border-white">
                4
              </span>
            </div>
          </div>
        </header>

        <div className="admin-content-wrap custom-scrollbar">
          {loadError && <div role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            Patient data could not be loaded: {loadError} <button type="button" onClick={fetchData} className="ml-2 font-bold underline">Retry</button>
          </div>}
          <Routes>
            <Route path="/" element={<AdminOverview patients={patients} metrics={metrics} loading={loading} fetchData={fetchData} />} />
            <Route path="/dashboard" element={<AdminOverview patients={patients} metrics={metrics} loading={loading} fetchData={fetchData} />} />
            <Route path="/patients" element={<PatientDirectory patients={patients} />} />
            <Route path="/registry" element={canManagePatients ? <PatientRegistry /> : <Navigate to="/admin" replace />} />
            <Route path="/encounters" element={canManagePatients ? <EncounterQueue /> : <Navigate to="/admin" replace />} />
            <Route path="/encounters/:encounterId" element={canManagePatients ? <EncounterDetail /> : <Navigate to="/admin" replace />} />
            <Route path="/models" element={<ModelMonitoring />} />
            <Route path="/alerts" element={<RiskAlertsCenter patients={patients} />} />
            <Route path="/pipeline" element={<DataPipeline />} />
            <Route path="/logs" element={<AuditLogs />} />
            <Route path="/settings" element={<GlobalSettings />} />
          </Routes>
        </div>
      </main>
    </div>
  );
};

class AdminPageErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error("Administrator page failed to render", error);
  }

  render() {
    if (this.state.failed) {
      return <div role="alert" className="min-h-screen bg-slate-50 p-8 text-slate-800">
        <h1 className="text-xl font-bold">The administrator page could not be displayed.</h1>
        <p className="mt-2 text-sm">Please retry. If the problem continues, contact support.</p>
        <button type="button" onClick={() => window.location.reload()} className="mt-4 rounded-lg bg-teal-700 px-4 py-2 text-sm font-bold text-white">Retry</button>
      </div>;
    }
    return this.props.children;
  }
}

export default function AdminPageWithErrorBoundary() {
  return <AdminPageErrorBoundary><AdminPage /></AdminPageErrorBoundary>;
}
