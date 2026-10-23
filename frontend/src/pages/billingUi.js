export function billingError(error) {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (status === 503) return { message: 'Billing storage or required configuration is unavailable. Contact a system administrator.', retryable: false };
  if (status === 403 || status === 404) return { message: 'You are not authorized to view or change this billing record.', retryable: false };
  if (status === 409) return { message: typeof detail === 'string' ? detail : 'Billing record changed. Reload before retrying.', retryable: true };
  if (status === 422) return { message: typeof detail === 'string' ? detail : 'Check the billing details and try again.', retryable: false };
  return { message: 'Billing request failed. Check the connection and retry.', retryable: true };
}

export const canEditDraft = invoice => Boolean(invoice?.status === 'DRAFT' && invoice?.allowed_actions?.includes('add_charge'));
export const canRecordPayment = invoice => Boolean(invoice?.allowed_actions?.includes('record_payment') && ['ISSUED', 'PARTIALLY_PAID', 'OVERDUE'].includes(invoice?.status) && Number(invoice?.outstanding) > 0);
export const manualPaymentLabel = payment => payment?.status === 'REVERSED' ? 'Reversed manual record' : 'Manually recorded (settlement unverified)';
