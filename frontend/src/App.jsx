import React, { useState, createContext, useContext, lazy, Suspense } from 'react';
import { motion } from 'framer-motion';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { NotificationProvider } from "./context/NotificationContext";
import NotificationContainer from "./components/Notifications/NotificationContainer";
import Sidebar from './components/Sidebar';
import ChatbotDrawer from './components/Chatbot/ChatbotDrawer';
import { ReportProvider } from './context/ReportContext';
import AnimatedLoader from './components/AnimatedLoader';
import './App.css';

// Lazy-loaded Page Routes for Performance Optimization
const Landing = lazy(() => import('./pages/Landing'));
const PatientLogin = lazy(() => import('./pages/patient/PatientLogin'));
const DoctorLogin = lazy(() => import('./pages/doctor/DoctorLogin'));
const AdminLogin = lazy(() => import('./pages/admin/AdminLogin'));
const Register = lazy(() => import('./pages/Register'));
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'));
const VerifyOTP = lazy(() => import('./pages/VerifyOTP'));
const ResetPassword = lazy(() => import('./pages/ResetPassword'));
const Profile = lazy(() => import('./pages/Profile'));
const AdminPage = lazy(() => import('./pages/AdminPage'));

const PatientDashboard = lazy(() => import('./pages/patient/PatientDashboard'));
const MyReports = lazy(() => import('./pages/patient/MyReports'));
const Appointments = lazy(() => import('./pages/patient/Appointments'));
const EmergencyPage = lazy(() => import('./pages/patient/EmergencyPage'));
const DoctorDashboard = lazy(() => import('./pages/doctor/DoctorDashboard'));
const DoctorReports = lazy(() => import('./pages/doctor/DoctorReports'));
const DoctorAppointments = lazy(() => import('./pages/doctor/DoctorAppointments'));
const DoctorPatientView = lazy(() => import('./pages/doctor/DoctorPatientView'));
const DepartmentsPage = lazy(() => import('./pages/departments/DepartmentsPage'));
const OwnReportFlow = lazy(() => import('./pages/patient/OwnReportFlow'));
const DoctorsPage = lazy(() => import('./pages/patient/DoctorsPage'));
const AnalyticsPage = lazy(() => import('./pages/patient/AnalyticsPage'));
const SettingsPage = lazy(() => import('./pages/patient/SettingsPage'));
const PatientChatPage = lazy(() => import('./pages/patient/PatientChatPage'));
const ClinicalChatConsole = lazy(() => import('./pages/doctor/ClinicalChatConsole'));
const DoctorEncounterEntry = lazy(() => import('./pages/doctor/DoctorEncounterEntry'));
const DoctorEncounterWorkspace = lazy(() => import('./pages/doctor/DoctorEncounterWorkspace'));
const MyVisits = lazy(() => import('./pages/patient/MyVisits'));
const PharmacyWorkspace = lazy(() => import('./pages/pharmacy/PharmacyWorkspace'));
const LaboratoryWorkspace = lazy(() => import('./pages/laboratory/LaboratoryWorkspace'));
const RadiologyWorkspace = lazy(() => import('./pages/radiology/RadiologyWorkspace'));
const InpatientWorkspace = lazy(() => import('./pages/InpatientWorkspace'));
const NursingWorkspace = lazy(() => import('./pages/NursingWorkspace'));
const BillingWorkspace = lazy(() => import('./pages/BillingWorkspace'));
const InsuranceWorkspace = lazy(() => import('./pages/InsuranceWorkspace'));
const InventoryWorkspace = lazy(() => import('./pages/InventoryWorkspace'));
const WorkforceWorkspace = lazy(() => import('./pages/WorkforceWorkspace'));

const LayoutContext = createContext();
export const useLayout = () => useContext(LayoutContext);

// ─── Portal Route Guards ─────────────────────────────────────────────────────

const PatientProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/patient/login" replace />;
  const role = (user.role || '').toLowerCase();
  if (role === 'doctor' || role === 'emergency_doctor') {
    return <Navigate to="/doctor/dashboard" replace />;
  }
  if (role === 'admin' || role === 'hospital_admin' || role === 'department_admin') {
    return <Navigate to="/admin" replace />;
  }
  return children;
};

const DoctorProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/doctor/login" replace />;
  const role = (user.role || '').toLowerCase();
  if (role === 'admin' || role === 'hospital_admin' || role === 'department_admin') {
    return <Navigate to="/admin" replace />;
  }
  if (role !== 'doctor' && role !== 'emergency_doctor') {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
};

const AdminProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/admin/login" replace />;
  const role = (user.role || '').toLowerCase();
  if (role === 'doctor' || role === 'emergency_doctor') {
    return <Navigate to="/doctor/dashboard" replace />;
  }
  if (role !== 'admin' && role !== 'hospital_admin' && role !== 'department_admin') {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
};

const DepartmentOperationsProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/admin/login" replace />;
  if ((user.role || '').toLowerCase() !== 'department_admin') {
    const role = (user.role || '').toLowerCase();
    return <Navigate to={role === 'doctor' || role === 'emergency_doctor' ? '/doctor/dashboard' : role === 'patient' || role === 'user' ? '/dashboard' : '/admin'} replace />;
  }
  return children;
};

const InpatientProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/admin/login" replace />;
  const role = (user.role || '').toLowerCase();
  if (!['doctor', 'emergency_doctor', 'admin', 'hospital_admin', 'department_admin'].includes(role)) {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
};

const NursingProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/admin/login" replace />;
  if ((user.role || '').toLowerCase() !== 'department_admin') return <Navigate to="/dashboard" replace />;
  return children;
};

const WorkforceProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/admin/login" replace />;
  if (!['admin', 'hospital_admin', 'department_admin', 'doctor', 'emergency_doctor'].includes((user.role || '').toLowerCase())) {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
};

const CommonProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) {
    const path = window.location.pathname;
    if (path.startsWith('/doctor')) return <Navigate to="/doctor/login" replace />;
    if (path.startsWith('/admin')) return <Navigate to="/admin/login" replace />;
    return <Navigate to="/patient/login" replace />;
  }
  return children;
};

const DashboardLayout = ({ children }) => {
  const { user } = useAuth();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const toggleSidebar = () => setSidebarOpen(!sidebarOpen);

  const role = (user?.role || '').toLowerCase();
  const isPatient = !role || role === 'patient' || role === 'user';
  const isDedicatedChatPage = location.pathname.startsWith('/patient/chat') || location.pathname.startsWith('/doctor/clinical-chat');

  return (
    <LayoutContext.Provider value={{ toggleSidebar }}>
      <div className="flex h-screen w-full bg-[#F6F9FB] overflow-hidden relative">
        {/* Sidebar - Mobile overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-40 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Sidebar Container with its own independent scroll */}
        <aside className={`fixed inset-y-0 left-0 z-50 w-64 h-screen shrink-0 transform transition-transform duration-300 ease-in-out md:translate-x-0 md:static md:w-64 bg-white border-r border-slate-200 overflow-hidden ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
          <Sidebar onClose={() => setSidebarOpen(false)} />
        </aside>

        {/* Main Content Area with its own independent scroll */}
        <div className="flex-1 flex flex-col h-screen overflow-hidden relative min-w-0 bg-[#F6F9FB]">
          <main className="flex-1 overflow-y-auto overflow-x-hidden w-full bg-[#F6F9FB]">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3 }}
              className="w-full min-h-full flex flex-col bg-[#F6F9FB]"
            >
              {children}
            </motion.div>
          </main>
        </div>

        {/* Floating HealthBot Launcher (Patient Dashboard & Patient Pages) */}
        {isPatient && !isDedicatedChatPage && <ChatbotDrawer />}
      </div>
    </LayoutContext.Provider>
  );
};

function App() {
  return (
    <NotificationProvider>
      <NotificationContainer />
      <AuthProvider>
        <ReportProvider>
          <Suspense fallback={
            <div className="min-h-screen flex items-center justify-center bg-[#F7FAFC]">
              <AnimatedLoader size="lg" message="Loading MediNexus Platform..." />
            </div>
          }>
            <Routes>
              {/* Public Marketing & Gateway Routes */}
              <Route path="/" element={<Landing />} />
              <Route path="/patient/login" element={<PatientLogin />} />
              <Route path="/doctor/login" element={<DoctorLogin />} />
              <Route path="/admin/login" element={<AdminLogin />} />
              
              {/* Legacy /login Route Redirect */}
              <Route path="/login" element={<Navigate to="/patient/login" replace />} />

              <Route path="/register" element={<Register />} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route path="/verify-otp" element={<VerifyOTP />} />
              <Route path="/reset-password" element={<ResetPassword />} />

              {/* Patient Routes */}
              <Route path="/dashboard" element={<PatientProtectedRoute><DashboardLayout><PatientDashboard /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/reports" element={<PatientProtectedRoute><DashboardLayout><MyReports /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/my-reports" element={<PatientProtectedRoute><DashboardLayout><MyReports /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/own-report" element={<PatientProtectedRoute><DashboardLayout><OwnReportFlow /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/appointments" element={<PatientProtectedRoute><DashboardLayout><Appointments /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/my-visits" element={<PatientProtectedRoute><DashboardLayout><MyVisits /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/doctors" element={<PatientProtectedRoute><DashboardLayout><DoctorsPage /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/analytics" element={<PatientProtectedRoute><DashboardLayout><AnalyticsPage /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/history" element={<Navigate to="/my-reports" replace />} />
              <Route path="/report-history" element={<Navigate to="/my-reports" replace />} />
              <Route path="/patient/chat" element={<PatientProtectedRoute><DashboardLayout><PatientChatPage /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/chat" element={<Navigate to="/patient/chat" replace />} />

              {/* Doctor Routes */}
              <Route path="/doctor/dashboard" element={<DoctorProtectedRoute><DashboardLayout><DoctorDashboard /></DashboardLayout></DoctorProtectedRoute>} />
              <Route path="/doctor/appointments" element={<DoctorProtectedRoute><DashboardLayout><DoctorAppointments /></DashboardLayout></DoctorProtectedRoute>} />
              <Route path="/doctor/encounters/new" element={<DoctorProtectedRoute><DashboardLayout><DoctorEncounterEntry /></DashboardLayout></DoctorProtectedRoute>} />
              <Route path="/doctor/encounters/:encounterId" element={<DoctorProtectedRoute><DashboardLayout><DoctorEncounterWorkspace /></DashboardLayout></DoctorProtectedRoute>} />
              <Route path="/doctor/patients/:patientId" element={<DoctorProtectedRoute><DashboardLayout><DoctorPatientView /></DashboardLayout></DoctorProtectedRoute>} />
              <Route path="/doctor/reports" element={<DoctorProtectedRoute><DashboardLayout><DoctorReports /></DashboardLayout></DoctorProtectedRoute>} />
              <Route path="/doctor/clinical-chat" element={<DoctorProtectedRoute><DashboardLayout><ClinicalChatConsole /></DashboardLayout></DoctorProtectedRoute>} />

              {/* Department-scoped pharmacy operations */}
              <Route path="/pharmacy" element={<DepartmentOperationsProtectedRoute><DashboardLayout><PharmacyWorkspace /></DashboardLayout></DepartmentOperationsProtectedRoute>} />
              <Route path="/laboratory" element={<DepartmentOperationsProtectedRoute><DashboardLayout><LaboratoryWorkspace /></DashboardLayout></DepartmentOperationsProtectedRoute>} />
              <Route path="/radiology" element={<DepartmentOperationsProtectedRoute><DashboardLayout><RadiologyWorkspace /></DashboardLayout></DepartmentOperationsProtectedRoute>} />
              <Route path="/inpatient" element={<InpatientProtectedRoute><DashboardLayout><InpatientWorkspace /></DashboardLayout></InpatientProtectedRoute>} />
              <Route path="/nursing" element={<NursingProtectedRoute><DashboardLayout><NursingWorkspace /></DashboardLayout></NursingProtectedRoute>} />
              <Route path="/billing" element={<DepartmentOperationsProtectedRoute><DashboardLayout><BillingWorkspace /></DashboardLayout></DepartmentOperationsProtectedRoute>} />
              <Route path="/my-billing" element={<PatientProtectedRoute><DashboardLayout><BillingWorkspace patientView /></DashboardLayout></PatientProtectedRoute>} />
              <Route path="/insurance" element={<DepartmentOperationsProtectedRoute><DashboardLayout><InsuranceWorkspace /></DashboardLayout></DepartmentOperationsProtectedRoute>} />
              <Route path="/inventory" element={<DepartmentOperationsProtectedRoute><DashboardLayout><InventoryWorkspace /></DashboardLayout></DepartmentOperationsProtectedRoute>} />
              <Route path="/workforce" element={<WorkforceProtectedRoute><DashboardLayout><WorkforceWorkspace /></DashboardLayout></WorkforceProtectedRoute>} />
              <Route path="/my-insurance" element={<PatientProtectedRoute><DashboardLayout><InsuranceWorkspace patientView /></DashboardLayout></PatientProtectedRoute>} />

              {/* Shared Clinical & Account Services */}
              <Route path="/departments" element={<CommonProtectedRoute><DashboardLayout><DepartmentsPage /></DashboardLayout></CommonProtectedRoute>} />
              <Route path="/departments/:deptSlug" element={<CommonProtectedRoute><DashboardLayout><DepartmentsPage /></DashboardLayout></CommonProtectedRoute>} />
              <Route path="/emergency" element={<CommonProtectedRoute><DashboardLayout><EmergencyPage /></DashboardLayout></CommonProtectedRoute>} />
              <Route path="/profile" element={<CommonProtectedRoute><DashboardLayout><Profile /></DashboardLayout></CommonProtectedRoute>} />
              <Route path="/settings" element={<CommonProtectedRoute><DashboardLayout><SettingsPage /></DashboardLayout></CommonProtectedRoute>} />

              {/* Admin Routes */}
              <Route path="/admin/dashboard" element={<AdminProtectedRoute><AdminPage /></AdminProtectedRoute>} />
              <Route path="/admin/*" element={<AdminProtectedRoute><AdminPage /></AdminProtectedRoute>} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </ReportProvider>
      </AuthProvider>
    </NotificationProvider>
  );
}

export default App;
