export function insuranceError(error) {
  const code = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (code === 503) return { message: typeof detail === 'string' ? detail : 'Insurance storage or insurer integration is unavailable.', retryable: false };
  if (code === 403 || code === 404) return { message: 'You are not authorized to view or change this insurance record.', retryable: false };
  if (code === 409) return { message: typeof detail === 'string' ? detail : 'This insurance record changed. Reload before retrying.', retryable: true };
  if (code === 422) return { message: typeof detail === 'string' ? detail : 'Review the policy, claim lines, amounts, and evidence reference.', retryable: false };
  return { message: 'Insurance request failed. Check the connection and retry.', retryable: true };
}

export const can = (record, action) => Array.isArray(record?.allowed_actions) && record.allowed_actions.includes(action);
export const canTransition = (record, target) => Array.isArray(record?.allowed_transitions) && record.allowed_transitions.includes(target);
export const eligibilityLabel = record => record?.last_check_method === 'MANUAL_STAFF_ENTRY'
  ? 'Manual staff eligibility record; insurer integration unavailable' : 'Insurer integration unavailable; eligibility unverified';
export const remittanceLabel = record => record?.payment_status === 'MANUALLY_RECONCILED_UNVERIFIED'
  ? 'Manually reconciled against a billing payment; settlement unverified' : 'No insurer remittance recorded';
