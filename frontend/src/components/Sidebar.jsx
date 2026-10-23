import React from 'react';
import { NavLink, Link } from 'react-router-dom';
import { 
  LayoutDashboard, Activity, Heart, FileText, Clock, User, X, LogOut, 
  Cpu, ShieldCheck, Database, Brain, Layers,
  UserCheck, BarChart3, Calendar, Settings, AlertOctagon, Package,
  Building, Zap, Droplets, MessageSquare, Pill, BedDouble
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const Sidebar = ({ onClose }) => {
  const { user, logout } = useAuth();
  const role = user?.role || 'patient';
  const isDoctor = role === 'doctor' || role === 'emergency_doctor';
  const isAdmin = role === 'admin' || role === 'hospital_admin' || role === 'department_admin';
  const isDepartmentAdmin = role === 'department_admin';

  let sections = [];

  if (isDoctor) {
    sections = [
      {
        title: 'CLINICAL OVERVIEW',
        items: [
          { path: '/doctor/dashboard', name: 'Clinical Overview', icon: <LayoutDashboard size={18} /> },
        ]
      },
      {
        title: 'PATIENT CARE',
        items: [
          { path: '/doctor/clinical-chat', name: 'Clinical Chat Console', icon: <MessageSquare size={18} /> },
          { path: '/doctor/appointments', name: 'Consultations & Triage', icon: <Calendar size={18} /> },
          { path: '/workforce', name: 'My Shifts', icon: <Clock size={18} /> },
          { path: '/doctor/reports', name: 'Clinical Review Queue', icon: <ShieldCheck size={18} /> },
          { path: '/inpatient', name: 'Inpatient Care', icon: <BedDouble size={18} /> },
          { path: '/emergency', name: 'Emergency Queue', icon: <Activity size={18} /> },
          { path: '/departments', name: 'Hospital Departments', icon: <Building size={18} /> },
        ]
      },
      {
        title: 'ACCOUNT',
        items: [
          { path: '/profile', name: 'Profile', icon: <User size={18} /> },
          { path: '/settings', name: 'Settings', icon: <Settings size={18} /> },
        ]
      }
    ];
  } else if (isAdmin) {
    sections = [
      {
        title: 'ADMINISTRATION',
        items: [
          { path: '/admin/dashboard', name: 'Hospital Overview', icon: <LayoutDashboard size={18} /> },
          { path: '/admin', name: 'System Control', icon: <Database size={18} /> },
        ]
      },
      {
        title: 'HOSPITAL MANAGEMENT',
        items: [
          ...(isDepartmentAdmin ? [{ path: '/pharmacy', name: 'Pharmacy Queue', icon: <Pill size={18} /> }] : []),
          ...(isDepartmentAdmin ? [{ path: '/laboratory', name: 'Laboratory Queue', icon: <Droplets size={18} /> }] : []),
          ...(isDepartmentAdmin ? [{ path: '/radiology', name: 'Radiology Queue', icon: <Zap size={18} /> }] : []),
          { path: '/inpatient', name: 'Inpatient Operations', icon: <BedDouble size={18} /> },
          ...(isDepartmentAdmin ? [{ path: '/nursing', name: 'Nursing Station', icon: <Heart size={18} /> }] : []),
          ...(isDepartmentAdmin ? [{ path: '/billing', name: 'Billing', icon: <FileText size={18} /> }] : []),
          ...(isDepartmentAdmin ? [{ path: '/insurance', name: 'Insurance & Claims', icon: <ShieldCheck size={18} /> }] : []),
          ...(isDepartmentAdmin ? [{ path: '/inventory', name: 'Inventory', icon: <Package size={18} /> }] : []),
          { path: '/workforce', name: isDepartmentAdmin ? 'My Shifts' : 'Staff & Workforce', icon: <UserCheck size={18} /> },
          { path: '/departments', name: 'Departments', icon: <Database size={18} /> },
          { path: '/emergency', name: 'Emergency Queue', icon: <Activity size={18} /> },
          { path: '/admin/patients', name: 'Medical Records', icon: <FileText size={18} /> },
        ]
      },
      {
        title: 'ACCOUNT',
        items: [
          { path: '/profile', name: 'Profile', icon: <User size={18} /> },
          { path: '/settings', name: 'Settings', icon: <Settings size={18} /> },
        ]
      }
    ];
  } else {
    // Patient Portal Navigation — Matches Healthcare Design Reference
    sections = [
      {
        title: 'OVERVIEW',
        items: [
          { path: '/dashboard', name: 'Overview', icon: <LayoutDashboard size={18} /> },
          { path: '/analytics', name: 'My health', icon: <Activity size={18} /> },
          { path: '/reports', name: 'Medical reports', icon: <FileText size={18} /> },
          { path: '/appointments', name: 'Appointments', icon: <Calendar size={18} /> },
          { path: '/my-visits', name: 'Visit summaries', icon: <FileText size={18} /> },
          { path: '/my-billing', name: 'My billing', icon: <FileText size={18} /> },
          { path: '/my-insurance', name: 'My insurance', icon: <ShieldCheck size={18} /> },
          { path: '/doctors', name: 'Care team', icon: <UserCheck size={18} /> },
          { path: '/departments', name: 'Departments', icon: <Building size={18} /> },
        ]
      },
      {
        title: 'QUICK ACCESS',
        items: [
          { path: '/patient/chat', name: 'Clinical consultation', icon: <MessageSquare size={18} /> },
          { path: '/report-history', name: 'Report history', icon: <Clock size={18} /> },
        ]
      }
    ];
  }

  const NavSection = ({ title, items }) => (
    <div className="mb-5">
      <h3 className="px-4 mb-2 text-[10px] font-bold text-slate-400 uppercase tracking-widest">{title}</h3>
      <div className="space-y-1">
        {items.map((item, i) => (
          <NavLink
            key={item.name + item.path + i}
            to={item.path}
            onClick={onClose}
            className={({ isActive }) => 
              `flex items-center gap-3 px-3.5 py-2.5 rounded-xl transition-all font-medium text-[13px] ${
                isActive 
                  ? 'text-[#0D9488] bg-[#E8F5F3] font-semibold' 
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
              }`
            }
          >
            <span className="shrink-0">{item.icon}</span>
            <span className="truncate">{item.name}</span>
          </NavLink>
        ))}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-full bg-white border-r border-slate-200 select-none">
      {/* Hospital Platform Branding Header */}
      <div className="flex items-center gap-3 px-5 py-4.5 border-b border-slate-100 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-[#0D9488] text-white flex items-center justify-center font-bold shadow-xs shrink-0">
          <ShieldCheck size={18} />
        </div>
        <div className="overflow-hidden">
          <h2 className="text-sm font-bold text-slate-900 tracking-tight leading-tight">MediNexus</h2>
          <p className="text-[10px] font-medium text-slate-500 leading-tight">Clinical Intelligence</p>
        </div>
        <button className="md:hidden ml-auto p-1.5 text-slate-400 hover:bg-slate-50 rounded-lg" onClick={onClose} aria-label="Close menu">
          <X size={18} />
        </button>
      </div>

      {/* Navigation Sections */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto custom-scrollbar">
        {user ? (
          sections.map((sec, idx) => (
            <NavSection key={sec.title + idx} title={sec.title} items={sec.items} />
          ))
        ) : (
          <NavSection 
            title="PUBLIC ACCESS" 
            items={[{ path: '/ml-studio', name: 'Neural Studio', icon: <Cpu size={18} /> }]} 
          />
        )}

        {/* Security / Privacy Trust Card (for patient role) */}
        {!isDoctor && !isAdmin && (
          <div className="mt-4 mx-1 p-3.5 rounded-2xl bg-[#E8F5F3]/70 border border-[#D0ECE7] text-slate-700">
            <div className="flex items-start gap-2.5">
              <ShieldCheck size={16} className="text-[#0D9488] shrink-0 mt-0.5" />
              <div>
                <p className="text-[11px] font-bold text-slate-900 leading-snug">Your records are secure</p>
                <p className="text-[10px] text-slate-500 leading-relaxed mt-0.5">
                  Only you and your approved care team can access this information.
                </p>
              </div>
            </div>
          </div>
        )}
      </nav>

      {/* Patient Account & Sign Out Footer */}
      <div className="p-3 border-t border-slate-100 bg-slate-50/60 shrink-0">
        {user ? (
          <div className="flex items-center justify-between gap-2.5">
            <Link to="/profile" onClick={onClose} className="flex items-center gap-2.5 overflow-hidden hover:opacity-80 transition-opacity min-w-0">
              <div className="w-8 h-8 rounded-full bg-teal-100 text-teal-800 flex items-center justify-center font-bold text-xs shrink-0 border border-teal-200">
                {user.full_name ? user.full_name.charAt(0).toUpperCase() : 'P'}
              </div>
              <div className="overflow-hidden min-w-0">
                <p className="text-xs font-semibold text-slate-800 truncate">{user.full_name || 'Patient'}</p>
                <p className="text-[10px] text-slate-400 truncate capitalize">{user.role || 'Patient'}</p>
              </div>
            </Link>
            <button 
              onClick={logout} 
              className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors shrink-0"
              title="Sign Out"
            >
              <LogOut size={16} />
            </button>
          </div>
        ) : (
          <NavLink 
            to="/patient/login" 
            onClick={onClose} 
            className="flex w-full items-center justify-center gap-2 py-2 rounded-lg bg-slate-900 text-white font-semibold text-xs transition-colors"
          >
            Sign In
          </NavLink>
        )}
      </div>
    </div>
  );
};

export default Sidebar;

