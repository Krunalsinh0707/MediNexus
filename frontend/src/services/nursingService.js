import api from './api';

export const getNursingCensus = async (params = {}) => (await api.get('/nursing/census', { params })).data;
export const getNursingWorkspace = async id => (await api.get(`/nursing/admissions/${id}`)).data;
export const recordNursingObservation = async (id, body) => (await api.post(`/nursing/admissions/${id}/observations`, body)).data;
export const addNursingNote = async (id, body) => (await api.post(`/nursing/admissions/${id}/notes`, body)).data;
export const addNursingPlan = async (id, body) => (await api.post(`/nursing/admissions/${id}/plans`, body)).data;
export const transitionNursingPlan = async (id, planId, body) =>
  (await api.post(`/nursing/admissions/${id}/plans/${planId}/transitions`, body)).data;
export const addNursingTask = async (id, planId, body) =>
  (await api.post(`/nursing/admissions/${id}/plans/${planId}/tasks`, body)).data;
export const transitionNursingTask = async (id, taskId, body) =>
  (await api.post(`/nursing/admissions/${id}/tasks/${taskId}/transitions`, body)).data;
