import api from './api';

export const listClinicalOrders = async (params = {}) =>
  (await api.get('/clinical-orders', { params })).data;

export const getClinicalOrder = async (id) =>
  (await api.get(`/clinical-orders/${id}`)).data;

export const createClinicalOrder = async (data) =>
  (await api.post('/clinical-orders', data)).data;

export const transitionClinicalOrder = async (id, data) =>
  (await api.post(`/clinical-orders/${id}/transitions`, data)).data;
