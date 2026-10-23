import api from './api';

export const listPharmacyPrescriptions = async (params = {}) =>
  (await api.get('/pharmacy/prescriptions', { params })).data;

export const getPharmacyPrescription = async id =>
  (await api.get(`/pharmacy/prescriptions/${id}`)).data;

export const transitionPharmacyPrescription = async (id, data) =>
  (await api.post(`/pharmacy/prescriptions/${id}/transitions`, data)).data;
