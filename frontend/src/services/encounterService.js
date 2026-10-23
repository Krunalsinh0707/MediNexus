import api from './api';

export const listEncounters = async (params = {}) => (await api.get('/encounters', { params })).data;
export const getEncounter = async (id) => (await api.get(`/encounters/${id}`)).data;
export const createEncounter = async (data) => (await api.post('/encounters', data)).data;
export const assignEncounter = async (id, data) => (await api.put(`/encounters/${id}/assignment`, data)).data;
export const transitionEncounter = async (id, data) => (await api.post(`/encounters/${id}/transitions`, data)).data;
export const writeEncounterNote = async (id, data, addendum = false) =>
  (await api.post(`/encounters/${id}/${addendum ? 'addenda' : 'notes'}`, data)).data;
export const writeEncounterVitals = async (id, data) => (await api.post(`/encounters/${id}/vitals`, data)).data;
export const writeEncounterDiagnosis = async (id, data) => (await api.post(`/encounters/${id}/diagnoses`, data)).data;
export const getEncounterAllergies = async (id) => (await api.get(`/encounters/${id}/allergies`)).data;
export const writeEncounterAllergy = async (id, data) => (await api.post(`/encounters/${id}/allergies`, data)).data;
export const reviewEncounterAllergies = async (id, data) => (await api.post(`/encounters/${id}/allergy-review`, data)).data;
