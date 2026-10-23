import api from './api';

export const listWards = async () => (await api.get('/inpatient/wards')).data;
export const listRooms = async (params = {}) => (await api.get('/inpatient/rooms', { params })).data;
export const listBeds = async (params = {}) => (await api.get('/inpatient/beds', { params })).data;
export const getBedHistory = async (id) => (await api.get(`/inpatient/beds/${id}/history`)).data;
export const listAdmissions = async (params = {}) => (await api.get('/inpatient/admissions', { params })).data;
export const getAdmission = async (id) => (await api.get(`/inpatient/admissions/${id}`)).data;
export const requestAdmission = async (body) => (await api.post('/inpatient/admissions', body)).data;
export const decideAdmission = async (id, body) => (await api.post(`/inpatient/admissions/${id}/decisions`, body)).data;
export const transferAdmission = async (id, body) => (await api.post(`/inpatient/admissions/${id}/transfers`, body)).data;
export const dischargeAdmission = async (id, body) => (await api.post(`/inpatient/admissions/${id}/discharge`, body)).data;
export const planDischarge = async (id, body) => (await api.post(`/inpatient/admissions/${id}/discharge-plan`, body)).data;
export const setBedStatus = async (id, body) => (await api.post(`/inpatient/beds/${id}/status`, body)).data;
export const reserveBed = async (id, body) => (await api.post(`/inpatient/beds/${id}/reservations`, body)).data;
export const releaseBedReservation = async (id, body) => (await api.post(`/inpatient/beds/${id}/reservations/release`, body)).data;
