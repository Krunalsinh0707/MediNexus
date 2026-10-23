import { useState } from "react";
import { CalendarDays, Search, UserPlus } from "lucide-react";
import api from "../services/api";
import { parsePatientRegistryError } from "./patientRegistryErrors";

const emptyForm = {
  full_name: "",
  date_of_birth: "",
  email: "",
  mobile_no: "",
  blood_group: "",
};

const displayDate = (value) => (value ? String(value).slice(0, 10) : "—");

const PatientRegistry = () => {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formMessage, setFormMessage] = useState("");
  const [formError, setFormError] = useState("");
  const [possibleMatches, setPossibleMatches] = useState([]);

  const searchPatients = async (event) => {
    event?.preventDefault();
    if (!query.trim()) {
      setSearchError("Enter an MRN, name, email, or mobile number to search.");
      return;
    }
    setSearching(true);
    setSearchError("");
    setSearched(true);
    setItems([]);
    setTotal(0);
    try {
      const response = await api.post("/patients/search", { query: query.trim(), limit: 50, offset: 0 });
      setItems(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      setSearchError(parsePatientRegistryError(error).message);
      setItems([]);
      setTotal(0);
    } finally {
      setSearching(false);
    }
  };

  const loadMorePatients = async () => {
    setLoadingMore(true);
    setSearchError("");
    try {
      const response = await api.post("/patients/search", {
        query: query.trim(),
        limit: 50,
        offset: items.length,
      });
      setItems((current) => [...current, ...(response.data.items || [])]);
      setTotal(response.data.total || 0);
    } catch (error) {
      setSearchError(parsePatientRegistryError(error).message);
    } finally {
      setLoadingMore(false);
    }
  };

  const updateForm = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setFormError("");
    setFormMessage("");
    setPossibleMatches([]);
  };

  const registerPatient = async (confirmDemographicMatch = false) => {
    setSaving(true);
    setFormError("");
    setFormMessage("");
    try {
      const response = await api.post("/patients", {
        ...form,
        date_of_birth: form.date_of_birth || null,
        email: form.email.trim() || null,
        mobile_no: form.mobile_no.trim() || null,
        blood_group: form.blood_group || null,
        confirm_demographic_match: confirmDemographicMatch,
      });
      const patient = response.data;
      setForm(emptyForm);
      setPossibleMatches([]);
      setFormMessage(`Patient registered. MRN: ${patient.mrn}`);
      setQuery(patient.mrn);
      setItems([patient]);
      setTotal(1);
      setSearched(true);
    } catch (error) {
      const parsed = parsePatientRegistryError(error);
      setFormError(parsed.message);
      setPossibleMatches(parsed.type === "demographic-review" ? parsed.matches : []);
    } finally {
      setSaving(false);
    }
  };

  const submitRegistration = (event) => {
    event.preventDefault();
    registerPatient(false);
  };

  return (
    <section className="space-y-6 p-4 md:p-8" aria-labelledby="patient-registry-title">
      <header className="flex flex-col gap-2">
        <h2 id="patient-registry-title" className="text-2xl font-black text-slate-800">Patient Registry</h2>
        <p className="max-w-3xl text-sm text-slate-500">
          Search hospital patient records and register patients who do not need portal credentials. Every new patient receives a hospital MRN.
        </p>
      </header>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="patient-search-title">
          <h3 id="patient-search-title" className="mb-4 text-lg font-bold text-slate-800">Search patients</h3>
          <form onSubmit={searchPatients} className="flex flex-col gap-3 sm:flex-row">
            <label className="sr-only" htmlFor="patient-registry-search">Search by MRN, name, email, or mobile number</label>
            <input
              id="patient-registry-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="MRN, name, email, or mobile number"
              className="min-w-0 flex-1 rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
            />
            <button type="submit" disabled={searching} className="inline-flex items-center justify-center gap-2 rounded-xl bg-teal-700 px-5 py-3 text-sm font-bold text-white hover:bg-teal-800 disabled:opacity-60">
              <Search size={17} /> {searching ? "Searching…" : "Search"}
            </button>
          </form>
          {searchError && <p className="mt-3 text-sm text-rose-700" role="alert">{searchError}</p>}
          {searched && !searchError && <p className="mt-3 text-xs text-slate-500">{total} patient record{total === 1 ? "" : "s"} found.</p>}

          <div className="mt-5 overflow-x-auto">
            {items.length > 0 ? (
              <table className="w-full min-w-[680px] border-collapse text-left text-sm">
                <thead><tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-3">MRN</th><th className="px-3 py-3">Patient</th><th className="px-3 py-3">Date of birth</th><th className="px-3 py-3">Contact</th>
                </tr></thead>
                <tbody>{items.map((patient) => (
                  <tr key={patient.id} className="border-b border-slate-100 align-top last:border-0">
                    <td className="px-3 py-4 font-mono text-xs font-bold text-teal-800">{patient.mrn || "—"}</td>
                    <td className="px-3 py-4"><div className="font-semibold text-slate-800">{patient.full_name}</div><div className="mt-1 text-xs text-slate-500">{patient.blood_group || "Blood group not recorded"}</div></td>
                    <td className="px-3 py-4 text-slate-600">{displayDate(patient.date_of_birth)}</td>
                    <td className="px-3 py-4 text-xs text-slate-600"><div>{patient.email || "No email"}</div><div className="mt-1">{patient.mobile_no || "No mobile number"}</div></td>
                  </tr>
                ))}</tbody>
              </table>
            ) : searched && !searching && !searchError ? (
              <p className="rounded-xl bg-slate-50 p-5 text-sm text-slate-500">No patient records match this search.</p>
            ) : null}
            {items.length > 0 && items.length < total && (
              <button type="button" onClick={loadMorePatients} disabled={loadingMore} className="mt-4 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:border-teal-700 hover:text-teal-800 disabled:opacity-60">
                {loadingMore ? "Loading…" : `Load more (${items.length} of ${total})`}
              </button>
            )}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="patient-registration-title">
          <div className="mb-4 flex items-center gap-3">
            <div className="rounded-xl bg-teal-50 p-2 text-teal-700"><UserPlus size={20} /></div>
            <div><h3 id="patient-registration-title" className="text-lg font-bold text-slate-800">Register patient</h3><p className="text-xs text-slate-500">Portal access is not created.</p></div>
          </div>
          <form onSubmit={submitRegistration} className="space-y-4">
            <div>
              <label htmlFor="patient-full-name" className="mb-1 block text-xs font-bold text-slate-600">Full name *</label>
              <input id="patient-full-name" name="full_name" required minLength={2} maxLength={255} value={form.full_name} onChange={updateForm} className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-teal-600" />
            </div>
            <div>
              <label htmlFor="patient-dob" className="mb-1 block text-xs font-bold text-slate-600">Date of birth</label>
              <div className="relative"><CalendarDays size={16} className="absolute left-3 top-3 text-slate-400" /><input id="patient-dob" name="date_of_birth" type="date" value={form.date_of_birth} onChange={updateForm} className="w-full rounded-xl border border-slate-300 py-2.5 pl-9 pr-3 text-sm outline-none focus:border-teal-600" /></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><label htmlFor="patient-email" className="mb-1 block text-xs font-bold text-slate-600">Email (optional)</label><input id="patient-email" name="email" type="email" maxLength={255} value={form.email} onChange={updateForm} className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-teal-600" /></div>
              <div><label htmlFor="patient-mobile" className="mb-1 block text-xs font-bold text-slate-600">Mobile (optional)</label><input id="patient-mobile" name="mobile_no" type="tel" maxLength={20} value={form.mobile_no} onChange={updateForm} className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-teal-600" /></div>
            </div>
            <div>
              <label htmlFor="patient-blood-group" className="mb-1 block text-xs font-bold text-slate-600">Blood group (optional)</label>
              <select id="patient-blood-group" name="blood_group" value={form.blood_group} onChange={updateForm} className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-teal-600">
                <option value="">Not recorded</option>{["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].map((group) => <option key={group} value={group}>{group}</option>)}
              </select>
            </div>
            {formError && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700" role="alert">{formError}</p>}
            {formMessage && <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800" role="status">{formMessage}</p>}
            {possibleMatches.length > 0 && (
              <div className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4" role="group" aria-label="Possible duplicate patients">
                <p className="text-sm font-bold text-amber-950">Review possible matches. No record has been merged.</p>
                <ul className="space-y-2">{possibleMatches.map((patient) => <li key={patient.id} className="text-sm text-amber-900"><span className="font-semibold">{patient.full_name}</span> · {patient.mrn || "No MRN"} · DOB {displayDate(patient.date_of_birth)}</li>)}</ul>
                <button type="button" disabled={saving} onClick={() => registerPatient(true)} className="rounded-lg bg-amber-800 px-4 py-2 text-sm font-bold text-white hover:bg-amber-900 disabled:opacity-60">
                  {saving ? "Registering…" : "I reviewed these records; register a separate patient"}
                </button>
              </div>
            )}
            <button type="submit" disabled={saving} className="w-full rounded-xl bg-slate-900 px-4 py-3 text-sm font-bold text-white hover:bg-slate-800 disabled:opacity-60">
              {saving ? "Checking and registering…" : "Check duplicates and register"}
            </button>
          </form>
        </section>
      </div>
    </section>
  );
};

export default PatientRegistry;
