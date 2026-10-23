import api from './api';

export const getMyMedicalHistory = async (params = {}) =>
  (await api.get('/medical-history/me', { params })).data;

export const getPatientMedicalHistory = async (patientId, params = {}) =>
  (await api.get(`/medical-history/patients/${encodeURIComponent(patientId)}`, { params })).data;
