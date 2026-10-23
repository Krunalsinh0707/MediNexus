export function nursingError(error) {
  const code = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (code === 503) return { message: 'Nursing storage or linked clinical data is unavailable. Contact a system administrator.', retryable: false };
  if (code === 403 || code === 404) return { message: 'You do not have an active nursing assignment for this record.', retryable: false };
  if (code === 409) return { message: typeof detail === 'string' ? detail : 'This record changed. Reload before retrying.', retryable: true };
  if (code === 422) return { message: typeof detail === 'string' ? detail : 'Check the supplied values and required fields.', retryable: false };
  return { message: 'Nursing information could not be loaded or saved. Check the connection and retry.', retryable: true };
}

export const allowed = (row, action) => Array.isArray(row?.allowed_actions) && row.allowed_actions.includes(action);
export const medicationState = order => ({
  prescription: order?.prescription_status || 'UNAVAILABLE',
  pharmacy: order?.pharmacy_status || 'UNAVAILABLE',
  administration: 'UNAVAILABLE',
});
export const measurementNames = [
  ['temperature_c', 'Temperature', '°C'], ['systolic_mmhg', 'Systolic BP', 'mmHg'],
  ['diastolic_mmhg', 'Diastolic BP', 'mmHg'], ['pulse_bpm', 'Pulse', 'beats/min'],
  ['respiratory_rate_per_min', 'Respiratory rate', 'breaths/min'],
  ['spo2_percent', 'SpO₂', '%'], ['height_cm', 'Height', 'cm'], ['weight_kg', 'Weight', 'kg'],
];
