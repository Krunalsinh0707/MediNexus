import api from './api';

const root = '/insurance';
export const listPolicies = params => api.get(`${root}/policies`, { params }).then(r => r.data);
export const getPolicy = id => api.get(`${root}/policies/${id}`).then(r => r.data);
export const createPolicy = body => api.post(`${root}/policies`, body).then(r => r.data);
export const updatePolicy = (id, body) => api.put(`${root}/policies/${id}`, body).then(r => r.data);
export const recordEligibility = (id, body) => api.post(`${root}/policies/${id}/eligibility`, body).then(r => r.data);
export const releasePolicy = (id, body) => api.post(`${root}/policies/${id}/release`, body).then(r => r.data);
export const listClaims = params => api.get(`${root}/claims`, { params }).then(r => r.data);
export const getClaim = id => api.get(`${root}/claims/${id}`).then(r => r.data);
export const createClaim = body => api.post(`${root}/claims`, body).then(r => r.data);
export const transitionClaim = (id, body) => api.post(`${root}/claims/${id}/transitions`, body).then(r => r.data);
export const correctClaim = (id, body) => api.post(`${root}/claims/${id}/corrections`, body).then(r => r.data);
export const releaseClaim = (id, body) => api.post(`${root}/claims/${id}/release`, body).then(r => r.data);
export const reconcileRemittance = (id, body) => api.post(`${root}/claims/${id}/remittances`, body).then(r => r.data);
