import api from './api';
export const listRadiologyOrders=async(params={})=>(await api.get('/radiology/orders',{params})).data;
export const createImagingOrder=async data=>(await api.post('/radiology/orders',data)).data;
export const getRadiologyOrder=async id=>(await api.get(`/radiology/orders/${id}`)).data;
export const getReleasedRadiologyReport=async id=>(await api.get(`/radiology/orders/${id}/released-report`)).data;
export const transitionRadiologyOrder=async(id,data)=>(await api.post(`/radiology/orders/${id}/transitions`,data)).data;
export const createRadiologyReport=async(id,data)=>(await api.post(`/radiology/orders/${id}/reports`,data)).data;
export const transitionRadiologyReport=async(oid,rid,data)=>(await api.post(`/radiology/orders/${oid}/reports/${rid}/transitions`,data)).data;
