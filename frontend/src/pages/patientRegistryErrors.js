export function parsePatientRegistryError(error) {
  const detail = error?.response?.data?.detail;
  if (detail?.code === "demographic_review_required" && Array.isArray(detail.matches)) {
    return {
      type: "demographic-review",
      message: detail.message || "Review possible matching patients before continuing.",
      matches: detail.matches,
    };
  }
  if (detail?.code === "duplicate_identifier") {
    return {
      type: "duplicate-identifier",
      message: detail.message || "This email or mobile number is already associated with a patient.",
      matches: [],
    };
  }
  return {
    type: "error",
    message: typeof detail === "string" ? detail : "Patient registration could not be completed.",
    matches: [],
  };
}
