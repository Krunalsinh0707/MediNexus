export function inpatientError(error) {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (status === 503) return { message: 'Inpatient storage is not installed. Contact a system administrator.', retryable: false };
  if (status === 409) return { message: typeof detail === 'string' ? detail : 'This record changed. Reload and try again.', retryable: true };
  if (status === 403 || status === 404) return { message: 'You do not have access to this inpatient record or ward.', retryable: false };
  if (status === 422) return { message: typeof detail === 'string' ? detail : 'Check the required fields and try again.', retryable: false };
  return { message: 'Could not load or save inpatient information. Check your connection and retry.', retryable: true };
}

export const canAct = (admission, action) => Array.isArray(admission?.allowed_actions) && admission.allowed_actions.includes(action);
export const availableBed = (bed, wardId) => bed?.status === 'AVAILABLE' && Number(bed.ward_id) === Number(wardId);
