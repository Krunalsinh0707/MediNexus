import api from './api';

export const listLaboratoryOrders = async (params = {}) =>
  (await api.get('/laboratory/orders', { params })).data;
export const getLaboratoryOrder = async id =>
  (await api.get(`/laboratory/orders/${id}`)).data;
export const getFinalLaboratoryResults = async id =>
  (await api.get(`/laboratory/orders/${id}/final-results`)).data;
export const transitionLaboratoryOrder = async (id, data) =>
  (await api.post(`/laboratory/orders/${id}/transitions`, data)).data;
export const createLaboratoryResult = async (id, data) =>
  (await api.post(`/laboratory/orders/${id}/results`, data)).data;
export const transitionLaboratoryResult = async (orderId, resultId, data) =>
  (await api.post(`/laboratory/orders/${orderId}/results/${resultId}/transitions`, data)).data;
