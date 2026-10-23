export const clinicalWriteError = (error, action) => {
  const status = error?.response?.status;
  if (status === 401) return 'Your session has expired. Sign in again.';
  if (status === 403 || status === 404) {
    if (action === 'chat') return 'Only an assigned active clinician can update this consultation. Reload the conversation or contact its assigned clinician.';
    if (action === 'message') return 'Message not sent. An authorized patient, clinician, and active visit or confirmed appointment are required.';
    if (action === 'hide') return 'Only the patient can hide their own resolved consultation.';
    return 'Action denied. An active assigned clinician and authorized patient or review assignment are required.';
  }
  if (status === 409) {
    if (action === 'chat') return 'This consultation cannot make that transition now. Reload its current status before retrying.';
    if (action === 'hide') return 'Finish this consultation before hiding it. Its clinical history is retained.';
    if (action === 'review') return 'This report already has a review. Reload the queue before continuing.';
    return 'The clinical record changed. Reload it before retrying.';
  }
  if (status === 422) return 'Check the entered details and try again.';
  return 'The request could not be completed. Check your connection and try again.';
};
