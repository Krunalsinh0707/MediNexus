export function medicationOrderCanSubmit(form, allergyContext, allergyAcknowledged) {
  const required = [
    form.medication_identifier, form.medication_display_name, form.dose, form.dose_unit,
    form.route, form.frequency, form.quantity, form.quantity_unit, form.start_date,
  ];
  const durationComplete = Boolean(form.duration_value) === Boolean(form.duration_unit);
  return Boolean(
    allergyContext && allergyAcknowledged && durationComplete &&
    required.every(value => String(value ?? '').trim()) &&
    Number(form.dose) > 0 && Number(form.quantity) > 0 &&
    (!form.duration_value || Number(form.duration_value) > 0)
  );
}

export function visibleMedicationOrders(items, loadedEncounterId, encounterId) {
  if (loadedEncounterId !== encounterId || !Array.isArray(items)) return [];
  return items.filter(item => item?.order?.encounter_id === encounterId);
}

export function medicationStatusMessage(status) {
  return {
    DRAFT: 'Draft prescription. It has not been signed.',
    SIGNED: 'Signed prescription. It has not been dispensed or administered.',
    CANCELLED: 'Cancelled prescription.',
  }[status] || 'Medication order status is unavailable.';
}
