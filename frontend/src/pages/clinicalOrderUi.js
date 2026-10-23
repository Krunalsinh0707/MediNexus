export function clinicalOrderError(error) {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  if (status === 409) return { conflict: true, unavailable: false, message: typeof detail === 'string' ? detail : 'This order changed. Reload before trying again.' };
  if (status === 503) return { conflict: false, unavailable: true, message: typeof detail === 'string' ? detail : 'Clinical order storage is not installed yet.' };
  if (status === 401) return { conflict: false, unavailable: false, message: 'Your session has expired. Sign in again.' };
  if (status === 403 || status === 404) return { conflict: false, unavailable: false, message: 'This clinical order is unavailable to your account.' };
  if (status === 422) {
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg).join('; ') : 'Check the order details and try again.';
    return { conflict: false, unavailable: false, message };
  }
  return { conflict: false, unavailable: false, message: error?.response ? 'The order request failed. Try again.' : 'Network unavailable. Check your connection and retry.' };
}

export function clinicalOrderErrorIsRetryable(error) {
  const status = error?.response?.status;
  return status == null || status === 409 || status === 503 || status >= 500;
}

export function canCreateClinicalOrder(encounter, doctorId) {
  return Boolean(encounter && doctorId && encounter.doctor_id === doctorId && encounter.status === 'IN_PROGRESS');
}

export function orderActionLabel(status) {
  return {
    SIGNED: 'Sign order',
    ACCEPTED: 'Accept order',
    IN_PROGRESS: 'Start work',
    COMPLETED: 'Complete order',
    CANCELLED: 'Cancel order',
  }[status] || status;
}

export function ordersForEncounter(orders, loadedEncounterId, encounterId) {
  return loadedEncounterId === encounterId && Array.isArray(orders) ? orders : [];
}

export function releasedResultForEncounter(payload, order, encounter) {
  if (!payload || payload.order_id !== order.id || payload.patient_id !== encounter.patient_id ||
      payload.encounter_id !== encounter.id || order.encounter_id !== encounter.id ||
      order.patient_id !== encounter.patient_id || order.status === 'CANCELLED' || !order.signed_at) {
    throw new Error('The released result does not match this patient and visit. Reload the order.');
  }
  if (order.order_type === 'LAB') {
    if (!Array.isArray(payload.results)) throw new Error('The laboratory response is incomplete. Reload the order.');
    const pickLab = row => ({
      test_identifier: row.test_identifier, test_name: row.test_name, result_value: row.result_value,
      result_unit: row.result_unit, abnormality_flag: row.abnormality_flag,
      revision_number: row.revision_number, corrected: row.corrected, finalized_at: row.finalized_at,
    });
    return { kind: 'LAB', results: payload.results.map(pickLab),
      revisionHistory: Array.isArray(payload.revision_history) ? payload.revision_history.map(pickLab) : [] };
  }
  if (order.order_type === 'IMAGING') {
    const row = payload.report;
    const pickReport = item => ({ findings: item.findings, impression: item.impression,
      revision_number: item.revision_number, finalized_at: item.finalized_at });
    return { kind: 'IMAGING', report: row ? {
      findings: row.findings, impression: row.impression, revision_number: row.revision_number,
      amended: row.amended, finalized_at: row.finalized_at,
    } : null, revisionHistory: Array.isArray(payload.revision_history)
      ? payload.revision_history.map(pickReport) : [] };
  }
  throw new Error('This order type has no released diagnostic result.');
}
