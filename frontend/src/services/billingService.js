import api from './api';

const base = '/billing';
export const searchBillingPatients = q => api.get(`${base}/patients`, { params: { q } }).then(r => r.data);
export const getTariffs = department_id => api.get(`${base}/tariffs`, { params: { department_id } }).then(r => r.data);
export const getInvoices = params => api.get(`${base}/invoices`, { params }).then(r => r.data);
export const getInvoice = id => api.get(`${base}/invoices/${id}`).then(r => r.data);
export const getStatement = id => api.get(`${base}/patients/${id}/statement`).then(r => r.data);
export const createInvoice = body => api.post(`${base}/invoices`, body).then(r => r.data);
export const addCharge = (id, body) => api.post(`${base}/invoices/${id}/charges`, body).then(r => r.data);
export const issueInvoice = (id, body) => api.post(`${base}/invoices/${id}/issue`, body).then(r => r.data);
export const cancelInvoice = (id, body) => api.post(`${base}/invoices/${id}/cancel`, body).then(r => r.data);
export const requestAdjustment = (id, body) => api.post(`${base}/invoices/${id}/adjustments`, body).then(r => r.data);
export const decideAdjustment = (id, adjustmentId, body) => api.post(`${base}/invoices/${id}/adjustments/${adjustmentId}/decision`, body).then(r => r.data);
export const recordPayment = (id, body) => api.post(`${base}/invoices/${id}/payments`, body).then(r => r.data);
export const reversePayment = (id, paymentId, body) => api.post(`${base}/invoices/${id}/payments/${paymentId}/reverse`, body).then(r => r.data);
export const requestRefund = (id, body) => api.post(`${base}/invoices/${id}/refund-requests`, body).then(r => r.data);
