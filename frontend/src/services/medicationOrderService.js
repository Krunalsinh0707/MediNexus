import api from './api';

export const listMedicationOrders = async (params = {}) =>
  (await api.get('/medication-orders', { params })).data;

export const createMedicationOrder = async data =>
  (await api.post('/medication-orders', data)).data;

export const transitionMedicationOrder = async (id, data) =>
  (await api.post(`/medication-orders/${id}/transitions`, data)).data;
