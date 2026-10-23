import api from './api';

export const locations = async () => (await api.get('/inventory/locations')).data;
export const items = async (search, category) => (await api.get('/inventory/items', { params: { search, category } })).data;
export const item = async id => (await api.get(`/inventory/items/${id}`)).data;
export const createItem = async body => (await api.post('/inventory/items', body)).data;
export const batches = async location_id => (await api.get('/inventory/batches', { params: { location_id } })).data;
export const receive = async body => (await api.post('/inventory/receipts', body)).data;
export const move = async (id, body) => (await api.post(`/inventory/batches/${id}/movements`, body)).data;
export const stock = async location_id => (await api.get('/inventory/reports/stock', { params: { location_id } })).data;
export const movements = async location_id => (await api.get('/inventory/movements', { params: { location_id } })).data;
export const discrepancies = async location_id => (await api.get('/inventory/discrepancies', { params: { location_id } })).data;
export const reportCount = async (id, body) => (await api.post(`/inventory/batches/${id}/counts`, body)).data;
export const decideCount = async (id, body) => (await api.post(`/inventory/discrepancies/${id}/decision`, body)).data;
