import { clinicalOrderError, clinicalOrderErrorIsRetryable } from './clinicalOrderUi.js';

export const laboratoryError = error => {
  const parsed = clinicalOrderError(error);
  if (error?.response?.status === 403) return { ...parsed, message: 'An active laboratory assignment with the required permission is needed.' };
  if (error?.response?.status === 503) return { ...parsed, message: error?.response?.data?.detail || 'Laboratory storage is unavailable.' };
  return parsed;
};
export const laboratoryErrorIsRetryable = clinicalOrderErrorIsRetryable;
export const laboratoryActionLabel = action => ({
  ACCEPTED:'Accept order', CLARIFICATION_REQUESTED:'Request clarification', REJECTED:'Reject order',
  COLLECTION_PENDING:'Prepare collection', COLLECTED:'Record collection', RECEIVED:'Accept specimen',
  SPECIMEN_REJECTED:'Reject specimen', PROCESSING:'Begin processing', VERIFIED:'Verify result', FINALIZED:'Finalize result',
  RESULT_REJECTED:'Result rejected',
}[action] || action);
export const laboratoryTransitionPayload = (item, action, input={}) => {
  const payload={expected_version:item.version,status:action};
  if (['CLARIFICATION_REQUESTED','REJECTED','SPECIMEN_REJECTED'].includes(action)) payload.reason=input.reason?.trim() || '';
  if (action==='SPECIMEN_REJECTED') payload.recollection_requested=Boolean(input.recollection_requested);
  if (action==='COLLECTED') {
    payload.specimen_identifier=input.specimen_identifier?.trim() || '';
    payload.specimen_type=input.specimen_type?.trim() || '';
  }
  return payload;
};
export const canSubmitLaboratoryAction = (action,input={}) => {
  if (['CLARIFICATION_REQUESTED','REJECTED','SPECIMEN_REJECTED'].includes(action)) return Boolean(input.reason?.trim());
  if (action==='COLLECTED') return Boolean(input.specimen_identifier?.trim() && input.specimen_type?.trim());
  return true;
};
export const laboratoryResultPayload = (item,input) => ({
  expected_workflow_version:item.version, specimen_id:Number(input.specimen_id),
  test_identifier:input.test_identifier.trim(), test_name:input.test_name.trim(),
  result_value:input.result_value.trim(), result_unit:input.result_unit.trim() || null,
  correction_reason:input.correction_reason.trim() || null,
});
