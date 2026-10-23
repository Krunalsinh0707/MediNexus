export function encounterError(error) {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (status === 409) return { conflict: true, message: typeof detail === 'string' ? detail : 'This visit changed. Reload before trying again.' };
  if (status === 401) return { conflict: false, message: 'Your session has expired. Sign in again.' };
  if (status === 403 || status === 404) return { conflict: false, message: 'This visit is unavailable to your account.' };
  if (status === 422) {
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg).join('; ') : 'Check the required fields and try again.';
    return { conflict: false, message };
  }
  return { conflict: false, message: error?.response ? 'The request failed. Try again.' : 'Network unavailable. Check your connection and try again.' };
}

export function newCreationKey() {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new Error('Secure check-in requires a browser with crypto.randomUUID support.');
  }
  return crypto.randomUUID();
}

export function latestRevisions(rows = []) {
  const corrected = new Set(rows.filter(row => row.previous_id != null).map(row => row.previous_id));
  return rows.filter(row => !corrected.has(row.id));
}

export function canEditEncounter(encounter, doctorId) {
  return Boolean(encounter && doctorId && encounter.doctor_id === doctorId && encounter.status === 'IN_PROGRESS');
}

export function patientSummaries(detail) {
  if (!detail || detail.status !== 'COMPLETED' || !Array.isArray(detail.summaries)) return [];
  return detail.summaries.filter(item => item.signed_at && typeof item.patient_summary === 'string');
}
