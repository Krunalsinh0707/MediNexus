export const workforceError = error => {
  const status = error?.response?.status;
  if (status === 503) return { message: 'Workforce storage is not installed. Records and actions are unavailable.', retryable: false, unavailable: true };
  if (status === 403) return { message: 'You are not authorized for this staff record or action.', retryable: false };
  if (status === 404) return { message: 'This staff record or shift is unavailable.', retryable: true };
  if (status === 409) return { message: error.response?.data?.detail || 'The record changed. Reload before retrying.', retryable: true };
  if (status === 422) return { message: 'Check required fields, dates, assignment scope, and reason.', retryable: false };
  return { message: 'Could not reach the workforce service. Check the connection and retry.', retryable: true };
};

export const toOffsetISOString = localValue => localValue ? new Date(localValue).toISOString() : null;

export const canSubmitAssignment = form => !!(Number(form.user_id) > 0 && Number(form.department_id) > 0
  && form.source_module && form.assignment_role && form.reason?.trim().length >= 3
  && form.starts_at && (form.source_module !== 'WARD' || Number(form.ward_id) > 0)
  && (form.source_module !== 'INVENTORY' || Number(form.location_id) > 0));

export const canSubmitShift = form => !!(Number(form.user_id) > 0 && Number(form.department_id) > 0
  && form.title?.trim() && form.starts_at && form.ends_at
  && new Date(form.ends_at) > new Date(form.starts_at));
