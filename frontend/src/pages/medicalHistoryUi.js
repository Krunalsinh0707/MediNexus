export const provenanceLabel = (value) => ({
  signed_clinical_finding: 'Signed clinical finding',
  clinician_recorded_measurement: 'Clinician-recorded measurement',
  clinician_recorded_finding: 'Clinician-recorded finding',
  clinician_recorded_visit: 'Hospital visit record',
  clinician_recorded_report: 'Hospital report; review status shown separately',
  clinician_reviewed_report: 'Clinician-reviewed report',
  clinician_reviewed_information: 'Clinician-reviewed information',
  legacy_unverified: 'Legacy or unverified record',
  ai_generated_assessment: 'AI-generated assessment; not a confirmed diagnosis',
  client_submitted_unverified: 'Client-submitted legacy assessment; unverified, not a confirmed diagnosis',
})[value] || 'Source status unknown';

export const historyError = (error) => {
  const code = error?.response?.status;
  if (code === 401) return 'Your session has expired. Sign in again.';
  if (code === 403 || code === 404) return 'Medical history is unavailable to your account.';
  if (code === 422) return 'The history filter or page cursor is invalid. Clear the filters and retry.';
  return 'Medical history could not be loaded. Check your connection and try again.';
};

export const historyDateParams = (from, through) => {
  const params = {};
  if (from) params.after = `${from}T00:00:00Z`;
  if (through) {
    const end = new Date(`${through}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate() + 1);
    params.before = end.toISOString();
  }
  return params;
};
