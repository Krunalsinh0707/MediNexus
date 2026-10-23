import { clinicalOrderError, clinicalOrderErrorIsRetryable } from './clinicalOrderUi.js';

export const pharmacyError = error => {
  const parsed = clinicalOrderError(error);
  if (error?.response?.status === 403) {
    return { ...parsed, message: 'An active assignment to the configured pharmacy department is required.' };
  }
  if (error?.response?.status === 503) {
    return { ...parsed, message: error?.response?.data?.detail || 'Pharmacy or inventory storage is unavailable.' };
  }
  return parsed;
};

export const pharmacyErrorIsRetryable = clinicalOrderErrorIsRetryable;

export const pharmacyActionLabel = action => ({
  ACCEPTED: 'Accept prescription',
  CLARIFICATION_REQUESTED: 'Request clarification',
  REJECTED: 'Reject prescription',
  IN_PROGRESS: 'Begin dispensing',
  PARTIALLY_DISPENSED: 'Record partial dispense',
  COMPLETED: 'Complete dispensing',
}[action] || action);

export const pharmacyTransitionPayload = (item, action, input = {}) => {
  const payload = { expected_version: item.version, status: action };
  if (action === 'CLARIFICATION_REQUESTED' || action === 'REJECTED') {
    payload.reason = input.reason?.trim() || '';
  }
  if (action === 'PARTIALLY_DISPENSED' || action === 'COMPLETED') {
    payload.quantity = Number(input.quantity);
    payload.quantity_unit = input.quantity_unit?.trim() || '';
    payload.stock_item_identifier = input.stock_item_identifier?.trim() || '';
  }
  return payload;
};

export const canSubmitPharmacyAction = (action, input = {}) => {
  if (action === 'CLARIFICATION_REQUESTED' || action === 'REJECTED') return Boolean(input.reason?.trim());
  if (action === 'PARTIALLY_DISPENSED' || action === 'COMPLETED') {
    return Number(input.quantity) > 0 && Boolean(input.quantity_unit?.trim()) && Boolean(input.stock_item_identifier?.trim());
  }
  return true;
};
