export const inventoryError = error => {
  const code = error?.response?.status;
  if (code === 503) return { message: 'Inventory storage is not installed. Stock operations are unavailable.', retryable: false };
  if (code === 403) return { message: 'You are not assigned to this storage location or action.', retryable: false };
  if (code === 409) return { message: error.response?.data?.detail || 'Stock changed. Reload and retry.', retryable: true };
  if (code === 422) return { message: 'Check the item, quantity, reason, dates and required references.', retryable: false };
  return { message: error?.response?.data?.detail || 'Could not load inventory. Check the connection and retry.', retryable: true };
};

export const canMove = (batch, form) => {
  if (!batch || !form?.movement_type || !form?.reason?.trim() || !form?.reference?.trim()) return false;
  if (!(Number(form.quantity) > 0)) return false;
  if (form.movement_type === 'TRANSFER' && !(Number(form.destination_location_id) > 0)) return false;
  if (form.movement_type === 'RETURN' && !(Number(form.related_movement_id) > 0)) return false;
  if (['RESERVE', 'RELEASE'].includes(form.movement_type) && (!form.workflow_type?.trim() || !form.workflow_reference?.trim())) return false;
  return true;
};

export const stockLabel = batch => {
  if (!batch) return 'Unknown';
  if (batch.status === 'QUARANTINED' || batch.status === 'RECALLED') return batch.status;
  if (!batch.expires_on) return 'Unknown expiry — unavailable';
  if (new Date(`${batch.expires_on}T00:00:00Z`) <= new Date()) return 'Expired — unavailable';
  return 'Eligible';
};
